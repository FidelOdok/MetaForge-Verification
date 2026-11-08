"""SQL-backed immutable submissions, duplicate-safe acceptance and leased execution."""

import hashlib
import time
import uuid
from pathlib import Path

from sqlalchemy import (
    JSON,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    and_,
    create_engine,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from metaforge_verification.contracts import baseline_snapshot, fingerprint, revision_snapshot

metadata = MetaData()
jobs = Table(
    "verification_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant", String(200), nullable=False),
    Column("idempotency_key", String(200), nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("request", JSON, nullable=False),
    Column("state", String(20), nullable=False),
    Column("report", JSON),
    Column("error", String(200)),
    Column("created", Float, nullable=False),
    Column("lease_until", Float, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("lease_token", String(36)),
    UniqueConstraint("tenant", "idempotency_key"),
)
revisions = Table(
    "verification_revisions",
    metadata,
    Column("tenant", String(200), primary_key=True),
    Column("twin_id", String(100), primary_key=True),
    Column("revision_id", String(100), primary_key=True),
    Column("fingerprint", String(64), nullable=False),
)
baselines = Table(
    "verification_baselines",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant", String(200), nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("reviewer", String(100), nullable=False),
    Column("rationale", String(2000), nullable=False),
    Column("created", Float, nullable=False),
    Column("revoked", Float),
)
events = Table(
    "verification_events",
    metadata,
    Column("cursor", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(200), nullable=False),
    Column("job_id", String(36)),
    Column("kind", String(100), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("created", Float, nullable=False),
    Column("details", JSON, nullable=False),
)
reviews = Table(
    "verification_reviews",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant", String(200), nullable=False),
    Column("job_id", String(36), nullable=False),
    Column("report_fingerprint", String(64), nullable=False),
    Column("reviewer", String(100), nullable=False),
    Column("created", Float, nullable=False),
    Column("decision", JSON, nullable=False),
)
usage = Table(
    "verification_usage",
    metadata,
    Column("job_id", String(36), primary_key=True),
    Column("tenant", String(200), nullable=False),
    Column("created", Float, nullable=False),
    Column("accepted_reports", Integer, nullable=False),
    Column("compute_seconds", Float, nullable=False),
)
dispatch_history = Table(
    "verification_dispatch_history",
    metadata,
    Column("tenant", String(200), primary_key=True),
    Column("last_dispatch", Float, nullable=False),
)
webhook_deliveries = Table(
    "verification_webhook_deliveries",
    metadata,
    Column("event_cursor", Integer, primary_key=True),
    Column("tenant", String(200), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("state", String(20), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("next_attempt", Float, nullable=False),
    Column("lease_until", Float, nullable=False),
    Column("lease_token", String(36)),
    Column("last_status", Integer),
)
resources = Table(
    "verification_resources",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant", String(200), nullable=False),
    Column("kind", String(50), nullable=False),
    Column("name", String(100), nullable=False),
    Column("revision_id", String(100), nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("data", JSON, nullable=False),
    Column("created", Float, nullable=False),
    UniqueConstraint("tenant", "kind", "name", "revision_id"),
)
uploads = Table(
    "verification_uploads",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("tenant", String(200), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("expected_sha256", String(64)),
    Column("actual_sha256", String(64)),
    Column("state", String(20), nullable=False),
    Column("expires", Float, nullable=False),
)


class Conflict(Exception):
    pass


class QuotaExceeded(Exception):
    pass


class Store:
    def __init__(self, settings):
        self.settings = settings
        if settings.database_url.startswith("sqlite:///"):
            path = settings.database_url.removeprefix("sqlite:///")
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(settings.database_url)
        metadata.create_all(self.engine)

    def get(self, tenant, job_id):
        with self.engine.connect() as conn:
            row = (
                conn.execute(select(jobs).where(jobs.c.id == job_id, jobs.c.tenant == tenant))
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def get_internal(self, job_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
            return dict(row) if row else None

    def put_resource(self, tenant, kind, name, revision_id, data, actor):
        fp = fingerprint(data)
        row = dict(
            id=str(uuid.uuid4()),
            tenant=tenant,
            kind=kind,
            name=name,
            revision_id=revision_id,
            fingerprint=fp,
            data=data,
            created=time.time(),
        )
        try:
            with self.engine.begin() as conn:
                if kind == "twin":
                    from metaforge_verification.contracts import VerificationRequest

                    request = VerificationRequest.model_validate(data)
                    revfp = fingerprint(revision_snapshot(request))
                    where = and_(
                        revisions.c.tenant == tenant,
                        revisions.c.twin_id == name,
                        revisions.c.revision_id == revision_id,
                    )
                    old_revision = conn.execute(select(revisions).where(where)).mappings().first()
                    if old_revision and old_revision["fingerprint"] != revfp:
                        raise Conflict("Twin revision conflicts with an existing immutable design")
                    if not old_revision:
                        conn.execute(
                            insert(revisions).values(
                                tenant=tenant,
                                twin_id=name,
                                revision_id=revision_id,
                                fingerprint=revfp,
                            )
                        )
                conn.execute(insert(resources).values(**row))
                self.event(
                    conn,
                    tenant,
                    "resource.registered",
                    actor=actor,
                    resource_id=row["id"],
                    resource_kind=kind,
                    fingerprint=fp,
                )
            return row
        except IntegrityError:
            with self.engine.connect() as conn:
                old = (
                    conn.execute(
                        select(resources).where(
                            resources.c.tenant == tenant,
                            resources.c.kind == kind,
                            resources.c.name == name,
                            resources.c.revision_id == revision_id,
                        )
                    )
                    .mappings()
                    .first()
                )
                if old and old["fingerprint"] == fp:
                    return dict(old)
            raise Conflict("Resource revision is immutable; use a new revision ID") from None

    def get_resource(self, tenant, kind, resource_id=None, name=None, revision_id=None):
        query = select(resources).where(resources.c.tenant == tenant, resources.c.kind == kind)
        query = (
            query.where(resources.c.id == resource_id)
            if resource_id
            else query.where(resources.c.name == name, resources.c.revision_id == revision_id)
        )
        with self.engine.connect() as conn:
            row = conn.execute(query).mappings().first()
            return dict(row) if row else None

    def create_upload(self, tenant, body):
        row = dict(
            id=str(uuid.uuid4()),
            tenant=tenant,
            size_bytes=body.size_bytes,
            expected_sha256=body.sha256,
            actual_sha256=None,
            state="pending",
            expires=time.time() + 86400,
        )
        with self.engine.begin() as conn:
            conn.execute(insert(uploads).values(**row))
        return row

    def get_upload(self, tenant, upload_id):
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(uploads).where(uploads.c.tenant == tenant, uploads.c.id == upload_id)
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def stage_upload(self, tenant, upload_id, digest):
        with self.engine.begin() as conn:
            changed = conn.execute(
                update(uploads)
                .where(
                    uploads.c.tenant == tenant,
                    uploads.c.id == upload_id,
                    uploads.c.state == "pending",
                    uploads.c.expires >= time.time(),
                )
                .values(state="staged", actual_sha256=digest)
            )
            if not changed.rowcount:
                row = (
                    conn.execute(
                        select(uploads).where(uploads.c.tenant == tenant, uploads.c.id == upload_id)
                    )
                    .mappings()
                    .first()
                )
                if not row or row["actual_sha256"] != digest or row["expires"] < time.time():
                    raise Conflict("Upload is expired, absent or already contains different bytes")

    def finalize_upload(self, tenant, upload_id):
        with self.engine.begin() as conn:
            changed = conn.execute(
                update(uploads)
                .where(
                    uploads.c.tenant == tenant,
                    uploads.c.id == upload_id,
                    uploads.c.state == "staged",
                    uploads.c.expires >= time.time(),
                )
                .values(state="finalized")
            )
            if changed.rowcount:
                self.event(conn, tenant, "artifact.finalized", actor="caller", upload_id=upload_id)
        return self.get_upload(tenant, upload_id)

    def event(self, conn, tenant, kind, job_id=None, actor="worker", **details):
        created = time.time()
        inserted = conn.execute(
            insert(events).values(
                tenant=tenant,
                job_id=job_id,
                kind=kind,
                actor=actor,
                created=created,
                details=details,
            )
        )
        if tenant in self.settings.webhook_destinations:
            cursor = inserted.inserted_primary_key[0]
            conn.execute(
                insert(webhook_deliveries).values(
                    event_cursor=cursor,
                    tenant=tenant,
                    payload={
                        "event_id": str(cursor),
                        "type": kind,
                        "job_id": job_id,
                        "created": created,
                        "details": details,
                    },
                    state="pending",
                    attempt=0,
                    next_attempt=created,
                    lease_until=0,
                    lease_token=None,
                    last_status=None,
                )
            )

    def claim_webhook(self):
        now = time.time()
        with self.engine.begin() as conn:
            ready = and_(
                webhook_deliveries.c.state.in_(["pending", "delivering"]),
                webhook_deliveries.c.lease_until < now,
                webhook_deliveries.c.next_attempt <= now,
            )
            row = (
                conn.execute(
                    select(webhook_deliveries)
                    .where(ready)
                    .order_by(webhook_deliveries.c.event_cursor)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            token = str(uuid.uuid4())
            changed = conn.execute(
                update(webhook_deliveries)
                .where(
                    ready,
                    webhook_deliveries.c.event_cursor == row["event_cursor"],
                    webhook_deliveries.c.attempt == row["attempt"],
                )
                .values(
                    state="delivering",
                    attempt=row["attempt"] + 1,
                    lease_until=now + 60,
                    lease_token=token,
                )
            )
            return (
                {**dict(row), "attempt": row["attempt"] + 1, "lease_token": token}
                if changed.rowcount
                else None
            )

    def finish_webhook(self, row, status):
        success = status is not None and 200 <= status < 300
        with self.engine.begin() as conn:
            result = conn.execute(
                update(webhook_deliveries)
                .where(
                    webhook_deliveries.c.event_cursor == row["event_cursor"],
                    webhook_deliveries.c.lease_token == row["lease_token"],
                    webhook_deliveries.c.lease_until >= time.time(),
                )
                .values(
                    state="delivered"
                    if success
                    else "dead_letter"
                    if row["attempt"] >= 8
                    else "pending",
                    next_attempt=time.time() + min(3600, 2 ** row["attempt"]),
                    lease_token=None,
                    lease_until=0,
                    last_status=status,
                )
            )
            return result.rowcount == 1

    def create_baseline(self, tenant, actor, request, rationale):
        snapshot = baseline_snapshot(request)
        row = dict(
            id=str(uuid.uuid4()),
            tenant=tenant,
            fingerprint=fingerprint(snapshot),
            snapshot=snapshot,
            reviewer=actor,
            rationale=rationale,
            created=time.time(),
            revoked=None,
        )
        with self.engine.begin() as conn:
            conn.execute(insert(baselines).values(**row))
            self.event(
                conn,
                tenant,
                "baseline.approved",
                actor=actor,
                baseline_id=row["id"],
                fingerprint=row["fingerprint"],
            )
        return row

    def get_baseline(self, tenant, baseline_id):
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(baselines).where(
                        baselines.c.tenant == tenant, baselines.c.id == baseline_id
                    )
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def revoke_baseline(self, tenant, baseline_id, actor):
        with self.engine.begin() as conn:
            result = conn.execute(
                update(baselines)
                .where(
                    baselines.c.tenant == tenant,
                    baselines.c.id == baseline_id,
                    baselines.c.revoked.is_(None),
                )
                .values(revoked=time.time())
            )
            if result.rowcount:
                self.event(conn, tenant, "baseline.revoked", actor=actor, baseline_id=baseline_id)
        return self.get_baseline(tenant, baseline_id)

    def list_events(self, tenant, after=0, limit=100, job_id=None):
        with self.engine.connect() as conn:
            query = select(events).where(events.c.tenant == tenant, events.c.cursor > after)
            if job_id:
                query = query.where(events.c.job_id == job_id)
            return [
                dict(r)
                for r in conn.execute(query.order_by(events.c.cursor).limit(limit)).mappings()
            ]

    def list_usage(self, tenant):
        from sqlalchemy import func

        with self.engine.connect() as conn:
            row = conn.execute(
                select(
                    func.coalesce(func.sum(usage.c.accepted_reports), 0),
                    func.coalesce(func.sum(usage.c.compute_seconds), 0),
                ).where(usage.c.tenant == tenant)
            ).one()
        return {
            "accepted_reports": row[0],
            "accepted_attempt_compute_seconds": row[1],
            "policy": "One report per accepted completion; no charges configured. "
            "Canceled/failed attempts and retries are not billed. "
            "Compute seconds describe accepted attempts, not all infrastructure spend.",
        }

    def add_review(self, tenant, job_id, actor, decision):
        with self.engine.begin() as conn:
            job = (
                conn.execute(select(jobs).where(jobs.c.tenant == tenant, jobs.c.id == job_id))
                .mappings()
                .first()
            )
            if not job or job["report"] is None:
                raise Conflict("A completed report is required for review")
            if decision.requirement_id not in {
                f["requirement_id"] for f in job["report"]["findings"]
            }:
                raise Conflict("Review references an unknown finding")
            row = dict(
                id=str(uuid.uuid4()),
                tenant=tenant,
                job_id=job_id,
                reviewer=actor,
                created=time.time(),
                report_fingerprint=fingerprint(job["report"]),
                decision=decision.model_dump(mode="json"),
            )
            conn.execute(insert(reviews).values(**row))
            self.event(conn, tenant, "review.recorded", job_id, actor=actor, review_id=row["id"])
        return row

    def list_reviews(self, tenant, job_id):
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(reviews)
                    .where(reviews.c.tenant == tenant, reviews.c.job_id == job_id)
                    .order_by(reviews.c.created)
                ).mappings()
            ]

    def submit(self, tenant, key, request, actor="external"):
        fp = fingerprint(request)
        # PostgreSQL advisory locks serialize admission for one tenant; SQLite's
        # immediate transaction provides the corresponding local single-writer lock.
        from sqlalchemy import text

        try:
            with self.engine.connect() as conn:
                if self.engine.dialect.name == "sqlite":
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    lock = int.from_bytes(
                        hashlib.sha256(tenant.encode()).digest()[:8], "big", signed=True
                    )
                    conn.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})
                old = (
                    conn.execute(
                        select(jobs).where(jobs.c.tenant == tenant, jobs.c.idempotency_key == key)
                    )
                    .mappings()
                    .first()
                )
                if old:
                    if old["fingerprint"] != fp:
                        from metaforge_verification.contracts import VerificationRequest

                        if fingerprint(VerificationRequest.model_validate(old["request"])) != fp:
                            raise Conflict("Idempotency key already used for a different request")
                    conn.commit()
                    return dict(old), False
                if request.previous_verification_id:
                    previous = (
                        conn.execute(
                            select(jobs).where(
                                jobs.c.tenant == tenant,
                                jobs.c.id == request.previous_verification_id,
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if (
                        not previous
                        or previous["request"]["twin"]["twin_id"] != request.twin.twin_id
                        or previous["request"]["twin"]["revision_id"] == request.twin.revision_id
                    ):
                        raise Conflict(
                            "Reverification requires an accessible prior job and new twin revision"
                        )
                if request.baseline_id:
                    baseline = (
                        conn.execute(
                            select(baselines)
                            .where(
                                baselines.c.tenant == tenant, baselines.c.id == request.baseline_id
                            )
                            .with_for_update()
                        )
                        .mappings()
                        .first()
                    )
                    if not baseline or baseline["revoked"] is not None:
                        raise Conflict("Approved baseline is absent or revoked")
                    if baseline["fingerprint"] != fingerprint(baseline_snapshot(request)):
                        raise Conflict(
                            "Requirements, scenarios or references differ from approved baseline"
                        )
                elif self.settings.require_approved_baseline:
                    raise Conflict("An approved baseline is required for submission")
                revfp = fingerprint(revision_snapshot(request))
                rev_where = and_(
                    revisions.c.tenant == tenant,
                    revisions.c.twin_id == request.twin.twin_id,
                    revisions.c.revision_id == request.twin.revision_id,
                )
                revision = conn.execute(select(revisions).where(rev_where)).mappings().first()
                if revision and revision["fingerprint"] == fingerprint(request.twin):
                    # Upgrade a legacy v0.1 revision only if its complete recorded design matches.
                    candidates = conn.execute(
                        select(jobs.c.request).where(jobs.c.tenant == tenant)
                    ).scalars()
                    from metaforge_verification.contracts import VerificationRequest

                    for candidate in candidates:
                        prior = VerificationRequest.model_validate(candidate)
                        if (prior.twin.twin_id, prior.twin.revision_id) == (
                            request.twin.twin_id,
                            request.twin.revision_id,
                        ) and fingerprint(revision_snapshot(prior)) == revfp:
                            conn.execute(
                                update(revisions).where(rev_where).values(fingerprint=revfp)
                            )
                            revision = {"fingerprint": revfp}
                            break
                if revision and revision["fingerprint"] != revfp:
                    raise Conflict("Twin revision is immutable; use a new revision ID")
                active = conn.execute(
                    select(jobs.c.id).where(
                        jobs.c.tenant == tenant, jobs.c.state.in_(["queued", "running"])
                    )
                ).all()
                if len(active) >= self.settings.max_pending_per_tenant:
                    raise QuotaExceeded("Tenant pending-job limit reached")
                if not revision:
                    conn.execute(
                        insert(revisions).values(
                            tenant=tenant,
                            twin_id=request.twin.twin_id,
                            revision_id=request.twin.revision_id,
                            fingerprint=revfp,
                        )
                    )
                row = dict(
                    id=str(uuid.uuid4()),
                    tenant=tenant,
                    idempotency_key=key,
                    fingerprint=fp,
                    request=request.model_dump(mode="json"),
                    state="queued",
                    created=time.time(),
                    lease_until=0,
                    attempt=0,
                    lease_token=None,
                    report=None,
                    error=None,
                )
                conn.execute(insert(jobs).values(**row))
                self.event(
                    conn,
                    tenant,
                    "verification.queued",
                    row["id"],
                    actor=actor,
                    input_fingerprint=fp,
                    baseline_id=request.baseline_id,
                )
                conn.commit()
                return row, True
        except IntegrityError as exc:
            raise Conflict(
                "Concurrent submission conflict; retry with the same idempotency key"
            ) from exc

    def claim(self, job_id=None):
        now = time.time()
        with self.engine.begin() as conn:
            from sqlalchemy import func, text

            if self.engine.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.execute(text("SELECT pg_advisory_xact_lock(732821063)"))
            exhausted = conn.execute(
                select(jobs.c.id, jobs.c.tenant).where(
                    jobs.c.state == "running",
                    jobs.c.lease_until < now,
                    jobs.c.attempt >= self.settings.max_attempts,
                )
            ).all()
            conn.execute(
                update(jobs)
                .where(
                    jobs.c.state == "running",
                    jobs.c.lease_until < now,
                    jobs.c.attempt >= self.settings.max_attempts,
                )
                .values(state="failed", error="Worker attempt limit exhausted", lease_token=None)
            )
            for exhausted_id, tenant in exhausted:
                self.event(
                    conn,
                    tenant,
                    "verification.failed",
                    exhausted_id,
                    reason="Worker attempt limit exhausted",
                )
            ready = and_(
                or_(
                    jobs.c.state == "queued",
                    and_(jobs.c.state == "running", jobs.c.lease_until < now),
                ),
                jobs.c.attempt < self.settings.max_attempts,
            )
            active = (
                conn.execute(
                    select(jobs.c.tenant).where(
                        jobs.c.state == "running", jobs.c.lease_until >= now
                    )
                )
                .scalars()
                .all()
            )
            if len(active) >= self.settings.max_running_jobs:
                return None
            full_tenants = {
                tenant
                for tenant in active
                if active.count(tenant) >= self.settings.max_running_per_tenant
            }
            query = (
                select(jobs)
                .outerjoin(dispatch_history, dispatch_history.c.tenant == jobs.c.tenant)
                .where(ready)
            )
            if full_tenants:
                query = query.where(jobs.c.tenant.not_in(full_tenants))
            if job_id is not None:
                query = query.where(jobs.c.id == job_id)
            row = (
                conn.execute(
                    query.order_by(
                        func.coalesce(dispatch_history.c.last_dispatch, 0), jobs.c.created
                    ).limit(1)
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            token = str(uuid.uuid4())
            result = conn.execute(
                update(jobs)
                .where(jobs.c.id == row["id"], ready, jobs.c.attempt == row["attempt"])
                .values(
                    state="running",
                    lease_token=token,
                    lease_until=now + self.settings.lease_seconds,
                    attempt=row["attempt"] + 1,
                )
            )
            if result.rowcount != 1:
                return None
            changed = conn.execute(
                update(dispatch_history)
                .where(dispatch_history.c.tenant == row["tenant"])
                .values(last_dispatch=now)
            )
            if not changed.rowcount:
                conn.execute(
                    insert(dispatch_history).values(tenant=row["tenant"], last_dispatch=now)
                )
            self.event(
                conn, row["tenant"], "verification.running", row["id"], attempt=row["attempt"] + 1
            )
            return {
                **dict(row),
                "state": "running",
                "lease_token": token,
                "attempt": row["attempt"] + 1,
            }

    def heartbeat(self, row):
        with self.engine.begin() as conn:
            result = conn.execute(
                update(jobs)
                .where(
                    jobs.c.id == row["id"],
                    jobs.c.state == "running",
                    jobs.c.lease_token == row["lease_token"],
                )
                .values(lease_until=time.time() + self.settings.lease_seconds)
            )
            return result.rowcount == 1

    def finish(self, row, report=None, error=None, compute_seconds=0):
        with self.engine.begin() as conn:
            result = conn.execute(
                update(jobs)
                .where(
                    jobs.c.id == row["id"],
                    jobs.c.state == "running",
                    jobs.c.lease_token == row["lease_token"],
                    jobs.c.lease_until >= time.time(),
                )
                .values(
                    state="failed" if error else "completed",
                    report=report,
                    error=error,
                    lease_token=None,
                )
            )
            if result.rowcount == 1:
                self.event(
                    conn,
                    row["tenant"],
                    "verification.failed" if error else "verification.completed",
                    row["id"],
                    attempt=row["attempt"],
                )
                if not error:
                    conn.execute(
                        insert(usage).values(
                            job_id=row["id"],
                            tenant=row["tenant"],
                            created=time.time(),
                            accepted_reports=1,
                            compute_seconds=max(0, compute_seconds),
                        )
                    )
            return result.rowcount == 1

    def cancel(self, tenant, job_id):
        with self.engine.begin() as conn:
            result = conn.execute(
                update(jobs)
                .where(
                    jobs.c.id == job_id,
                    jobs.c.tenant == tenant,
                    jobs.c.state.in_(["queued", "running"]),
                )
                .values(state="canceled", lease_token=None)
            )
            if result.rowcount:
                self.event(conn, tenant, "verification.canceled", job_id, actor="caller")
        return self.get(tenant, job_id)


class LocalArtifactStore:
    """Content-addressed immutable bytes, tenant scoped; no user paths or remote URLs."""

    def __init__(self, root, tenant, max_bytes=10 * 1024**2):
        self.root = Path(root) / hashlib.sha256(tenant.encode()).hexdigest()
        self.max_bytes = max_bytes

    def _path(self, artifact_id):
        if len(artifact_id) != 64 or any(c not in "0123456789abcdef" for c in artifact_id):
            raise FileNotFoundError("Invalid artifact ID")
        return self.root / artifact_id

    def put(self, data):
        import os
        import tempfile

        if len(data) > self.max_bytes:
            raise ValueError("Artifact exceeds configured byte limit")
        digest = hashlib.sha256(data).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(name, self._path(digest))
        finally:
            Path(name).unlink(missing_ok=True)
        return digest

    def read(self, artifact_id):
        with self._path(artifact_id).open("rb") as handle:
            data = handle.read(self.max_bytes + 1)
        if len(data) > self.max_bytes or hashlib.sha256(data).hexdigest() != artifact_id:
            raise FileNotFoundError("Artifact integrity or size violation")
        return data
