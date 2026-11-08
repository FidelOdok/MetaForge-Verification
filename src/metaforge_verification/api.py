"""Independent API. Heavy checks execute in separate workers, never FastAPI background tasks."""

import json
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from metaforge_verification import __version__
from metaforge_verification.artifacts import artifact_store
from metaforge_verification.auth import Principal, TokenAuthenticator
from metaforge_verification.config import Settings
from metaforge_verification.contracts import (
    BaselineCreate,
    Report,
    ReviewCreate,
    VerificationByReference,
    VerificationRequest,
)
from metaforge_verification.engine import LIMITATIONS, PROFILES, plan, registry
from metaforge_verification.store import Conflict, QuotaExceeded, Store


def markdown(report):
    def clean(s):
        return str(s).replace("\n", " ").replace("|", "\\|").replace("<", "&lt;")

    lines = [
        "# Verification report",
        "",
        f"Gate: **{report.gate_decision}**",
        f"Revision: `{report.twin_id}/{report.revision_id}`",
        "",
        "| Requirement | Outcome | Reason |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| {clean(f.requirement_id)} | {f.outcome} | {clean(f.reason)} |" for f in report.findings
    ]
    lines += ["", "## Limitations", ""] + [f"- {s}" for s in report.limitations]
    return "\n".join(lines) + "\n"


def create_app(settings=None, authenticator=None):
    settings = (settings or Settings.from_env()).validate()
    store = Store(settings)
    checks = registry(settings.load_plugins)
    auth = authenticator or TokenAuthenticator(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        store.engine.dispose()

    app = FastAPI(title="MetaForge Verification", version=__version__, lifespan=lifespan)
    app.state.store = store

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        codes = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
            422: "INVALID_INPUT",
            429: "QUOTA_EXCEEDED",
        }
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "detail": exc.detail,
                "code": codes.get(exc.status_code, "REQUEST_ERROR"),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        response = await request_validation_exception_handler(request, exc)
        data = json.loads(response.body)
        return JSONResponse(
            status_code=422,
            content={
                **data,
                "code": "INVALID_INPUT",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.get("/review", include_in_schema=False)
    def review_page():
        from importlib.resources import files

        return Response(
            files("metaforge_verification").joinpath("web/review.html").read_text(),
            media_type="text/html",
            headers={
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; "
                "form-action 'none'; base-uri 'none'; frame-ancestors 'none'",
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.get("/review/assets/{name}", include_in_schema=False)
    def review_asset(name: str):
        from importlib.resources import files

        types = {"review.css": "text/css", "review.js": "text/javascript"}
        if name not in types:
            raise HTTPException(404, "Asset not found")
        return Response(
            files("metaforge_verification").joinpath(f"web/{name}").read_text(),
            media_type=types[name],
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.middleware("http")
    async def bounded_request(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        # Includes chunked bodies; do not trust Content-Length. Bound bytes before
        # Pydantic parsing or upload buffering.
        if request.method in {"POST", "PUT", "PATCH"}:
            upload_path = request.url.path == "/v1/artifacts" or (
                request.url.path.startswith("/v1/artifact-uploads/")
                and request.url.path.endswith("/content")
            )
            limit = settings.max_upload_bytes if upload_path else 1_000_000
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "code": "PAYLOAD_TOO_LARGE",
                            "detail": "Request exceeds configured byte limit",
                            "request_id": request.state.request_id,
                        },
                        headers={"X-Request-ID": request.state.request_id},
                    )
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    def principal(authorization: Annotated[str | None, Header()] = None):
        result = auth.authenticate(authorization)
        if result is None:
            raise HTTPException(
                401, "Bearer authentication required", headers={"WWW-Authenticate": "Bearer"}
            )
        if "read" not in result.permissions:
            raise HTTPException(403, "read permission required")
        return result

    Caller = Annotated[Principal, Depends(principal)]

    def require(caller, permission):
        if permission not in caller.permissions:
            raise HTTPException(403, f"{permission} permission required")

    def find_job(caller, job_id):
        row = store.get(caller.tenant_id, job_id)
        if row is None:
            raise HTTPException(404, "Verification not found")
        return row

    def public_job(row):
        return {
            "verification_id": row["id"],
            "execution_state": row["state"],
            "input_fingerprint": row["fingerprint"],
            "attempt": row["attempt"],
            "error": row["error"],
            "links": {
                "status": f"/v1/verifications/{row['id']}",
                "report": f"/v1/verifications/{row['id']}/report",
            },
        }

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__, "auth_mode": settings.auth_mode}

    @app.get("/v1/capabilities")
    def capabilities(caller: Caller):
        return {
            "schema_version": "1.0",
            "profiles": sorted(PROFILES),
            "checks": [
                {"rule_id": c.rule_id, "module": c.module, "fidelity": c.fidelity}
                for c in checks.values()
            ],
            "limitations": LIMITATIONS,
        }

    @app.post("/v1/artifacts", status_code=201)
    async def upload(request: Request, caller: Caller):
        if not caller.permissions & {"submit", "review"}:
            raise HTTPException(403, "Upload permission required")
        data = await request.body()
        if not data:
            raise HTTPException(422, "Empty artifact")
        digest = artifact_store(settings, caller.tenant_id).put(data)
        return {"artifact_id": digest, "sha256": digest, "size_bytes": len(data)}

    @app.get("/v1/artifacts/{artifact_id}")
    def download(artifact_id: str, caller: Caller):
        try:
            data = artifact_store(settings, caller.tenant_id).read(artifact_id)
        except FileNotFoundError:
            raise HTTPException(404, "Artifact not found") from None
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.post("/v1/verification-plans")
    def verification_plan(body: VerificationRequest | VerificationByReference, caller: Caller):
        from metaforge_verification.resource_api import resolve

        if isinstance(body, VerificationByReference):
            body = body.model_copy(update={"accept_gaps": True})
        return plan(resolve(store, checks, body, caller), checks)

    @app.post("/v1/verifications", status_code=202)
    def submit(
        body: VerificationRequest | VerificationByReference,
        caller: Caller,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ):
        require(caller, "submit")
        from metaforge_verification.resource_api import resolve

        body = resolve(store, checks, body, caller)
        try:
            row, _ = store.submit(caller.tenant_id, idempotency_key, body, actor=caller.actor_id)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except QuotaExceeded as exc:
            raise HTTPException(429, str(exc)) from None
        return public_job(row)

    @app.get("/v1/verifications/{job_id}")
    def status(job_id: str, caller: Caller):
        return public_job(find_job(caller, job_id))

    @app.post("/v1/verifications/{job_id}/cancel")
    def cancel(job_id: str, caller: Caller):
        require(caller, "submit")
        find_job(caller, job_id)
        return public_job(store.cancel(caller.tenant_id, job_id))

    @app.get("/v1/verifications/{job_id}/report")
    def report(job_id: str, caller: Caller, format: str = "json"):
        row = find_job(caller, job_id)
        if row["report"] is None:
            raise HTTPException(409, f"Report not available: {row['state']}")
        result = Report.model_validate(row["report"])
        if format == "markdown":
            return PlainTextResponse(markdown(result), media_type="text/markdown")
        if format != "json":
            raise HTTPException(422, "format must be json or markdown")
        return result

    @app.get("/v1/verifications/{job_id}/coverage")
    def coverage(job_id: str, caller: Caller):
        row = find_job(caller, job_id)
        if row["report"] is None:
            raise HTTPException(409, "Report not available")
        return row["report"]["coverage"]

    @app.post("/v1/baselines", status_code=201)
    def approve_baseline(body: BaselineCreate, caller: Caller):
        require(caller, "review")
        # Approved references must exist under the reviewing tenant, with matching bytes.
        import hashlib

        from metaforge_verification.engine import references

        artifacts = artifact_store(settings, caller.tenant_id)
        for ref in references(body.verification):
            try:
                if hashlib.sha256(artifacts.read(ref.artifact_id)).hexdigest() != ref.sha256:
                    raise FileNotFoundError
            except FileNotFoundError:
                raise HTTPException(422, "Baseline artifact is missing or digest-invalid") from None
        return store.create_baseline(
            caller.tenant_id, caller.actor_id, body.verification, body.rationale
        )

    @app.get("/v1/baselines/{baseline_id}")
    def get_baseline(baseline_id: str, caller: Caller):
        result = store.get_baseline(caller.tenant_id, baseline_id)
        if result is None:
            raise HTTPException(404, "Baseline not found")
        return result

    @app.post("/v1/baselines/{baseline_id}/revoke")
    def revoke_baseline(baseline_id: str, caller: Caller):
        require(caller, "review")
        get_baseline(baseline_id, caller)
        return store.revoke_baseline(caller.tenant_id, baseline_id, caller.actor_id)

    @app.get("/v1/events")
    def event_stream(
        caller: Caller,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
    ):
        items = store.list_events(caller.tenant_id, after=after, limit=limit)
        return {"items": items, "next_cursor": items[-1]["cursor"] if items else after}

    @app.get("/v1/verifications/{job_id}/events")
    def job_events(
        job_id: str,
        caller: Caller,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
    ):
        find_job(caller, job_id)
        items = store.list_events(caller.tenant_id, after=after, limit=limit, job_id=job_id)
        return {"items": items, "next_cursor": items[-1]["cursor"] if items else after}

    @app.get("/v1/usage")
    def tenant_usage(caller: Caller):
        return store.list_usage(caller.tenant_id)

    @app.post("/v1/verifications/{job_id}/reviews", status_code=201)
    def review(job_id: str, body: ReviewCreate, caller: Caller):
        require(caller, "review")
        find_job(caller, job_id)
        import hashlib

        for ref in body.evidence_refs:
            try:
                data = artifact_store(settings, caller.tenant_id).read(ref.artifact_id)
                if hashlib.sha256(data).hexdigest() != ref.sha256:
                    raise FileNotFoundError
            except FileNotFoundError:
                raise HTTPException(422, "Review evidence is missing or digest-invalid") from None
        try:
            return store.add_review(caller.tenant_id, job_id, caller.actor_id, body)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/v1/verifications/{job_id}/reviews")
    def get_reviews(job_id: str, caller: Caller):
        find_job(caller, job_id)
        return {
            "items": store.list_reviews(caller.tenant_id, job_id),
            "policy": "Append-only reviews preserve the original engineering gate.",
        }

    @app.get("/v1/verifications/{job_id}/comparison")
    def compare(job_id: str, against: str, caller: Caller):
        from metaforge_verification.comparison import compare_jobs

        try:
            return compare_jobs(find_job(caller, against), find_job(caller, job_id))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    from metaforge_verification.resource_api import add_routes

    add_routes(app, store, settings, principal, submit)
    return app
