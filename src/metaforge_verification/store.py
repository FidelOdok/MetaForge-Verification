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

from metaforge_verification.contracts import fingerprint

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

    def submit(self, tenant, key, request):
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
                        raise Conflict("Idempotency key already used for a different request")
                    conn.commit()
                    return dict(old), False
                revfp = fingerprint(request.twin)
                rev_where = and_(
                    revisions.c.tenant == tenant,
                    revisions.c.twin_id == request.twin.twin_id,
                    revisions.c.revision_id == request.twin.revision_id,
                )
                revision = conn.execute(select(revisions).where(rev_where)).mappings().first()
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
                conn.commit()
                return row, True
        except IntegrityError as exc:
            raise Conflict(
                "Concurrent submission conflict; retry with the same idempotency key"
            ) from exc

    def claim(self, job_id=None):
        now = time.time()
        with self.engine.begin() as conn:
            conn.execute(
                update(jobs)
                .where(
                    jobs.c.state == "running",
                    jobs.c.lease_until < now,
                    jobs.c.attempt >= self.settings.max_attempts,
                )
                .values(state="failed", error="Worker attempt limit exhausted", lease_token=None)
            )
            ready = and_(
                or_(
                    jobs.c.state == "queued",
                    and_(jobs.c.state == "running", jobs.c.lease_until < now),
                ),
                jobs.c.attempt < self.settings.max_attempts,
            )
            query = select(jobs).where(ready)
            if job_id is not None:
                query = query.where(jobs.c.id == job_id)
            row = conn.execute(query.order_by(jobs.c.created).limit(1)).mappings().first()
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

    def finish(self, row, report=None, error=None):
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
            return result.rowcount == 1

    def cancel(self, tenant, job_id):
        with self.engine.begin() as conn:
            conn.execute(
                update(jobs)
                .where(
                    jobs.c.id == job_id,
                    jobs.c.tenant == tenant,
                    jobs.c.state.in_(["queued", "running"]),
                )
                .values(state="canceled", lease_token=None)
            )
        return self.get(tenant, job_id)


class LocalArtifactStore:
    """Content-addressed immutable bytes, tenant scoped; no user paths or remote URLs."""

    def __init__(self, root, tenant):
        self.root = Path(root) / hashlib.sha256(tenant.encode()).hexdigest()

    def _path(self, artifact_id):
        if len(artifact_id) != 64 or any(c not in "0123456789abcdef" for c in artifact_id):
            raise FileNotFoundError("Invalid artifact ID")
        return self.root / artifact_id

    def put(self, data):
        import os
        import tempfile

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
        return self._path(artifact_id).read_bytes()
