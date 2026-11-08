"""Independent API. Heavy checks execute in separate workers, never FastAPI background tasks."""

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from metaforge_verification import __version__
from metaforge_verification.auth import Principal, TokenAuthenticator
from metaforge_verification.config import Settings
from metaforge_verification.contracts import Report, VerificationRequest
from metaforge_verification.engine import LIMITATIONS, plan, registry
from metaforge_verification.store import Conflict, LocalArtifactStore, QuotaExceeded, Store


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

    @app.middleware("http")
    async def bounded_request(request: Request, call_next):
        # Includes chunked bodies; do not trust Content-Length. Bound bytes before
        # Pydantic parsing or upload buffering.
        if request.method in {"POST", "PUT", "PATCH"}:
            limit = settings.max_upload_bytes if request.url.path == "/v1/artifacts" else 1_000_000
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return Response(status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        return await call_next(request)

    def principal(authorization: Annotated[str | None, Header()] = None):
        result = auth.authenticate(authorization)
        if result is None:
            raise HTTPException(
                401, "Bearer authentication required", headers={"WWW-Authenticate": "Bearer"}
            )
        return result

    Caller = Annotated[Principal, Depends(principal)]

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
            "profiles": ["smart-lamp-analytical-v1"],
            "checks": [
                {"rule_id": c.rule_id, "module": c.module, "fidelity": c.fidelity}
                for c in checks.values()
            ],
            "limitations": LIMITATIONS,
        }

    @app.post("/v1/artifacts", status_code=201)
    async def upload(request: Request, caller: Caller):
        data = await request.body()
        if not data:
            raise HTTPException(422, "Empty artifact")
        digest = LocalArtifactStore(settings.artifact_root, caller.tenant_id).put(data)
        return {"artifact_id": digest, "sha256": digest, "size_bytes": len(data)}

    @app.get("/v1/artifacts/{artifact_id}")
    def download(artifact_id: str, caller: Caller):
        try:
            data = LocalArtifactStore(settings.artifact_root, caller.tenant_id).read(artifact_id)
        except FileNotFoundError:
            raise HTTPException(404, "Artifact not found") from None
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.post("/v1/verification-plans")
    def verification_plan(body: VerificationRequest, caller: Caller):
        return plan(body, checks)

    @app.post("/v1/verifications", status_code=202)
    def submit(
        body: VerificationRequest,
        caller: Caller,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ):
        try:
            row, _ = store.submit(caller.tenant_id, idempotency_key, body)
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

    return app
