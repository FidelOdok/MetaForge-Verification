"""Immutable input resources, bounded upload lifecycle and traceable external evidence."""

import hashlib
import time
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request

from metaforge_verification.artifacts import artifact_store
from metaforge_verification.auth import Principal
from metaforge_verification.contracts import (
    PhysicalEvidenceCreate,
    RenderCreate,
    RequirementSetCreate,
    ScenarioSuiteCreate,
    UploadCreate,
    VerificationRequest,
    WebhookEndpointCreate,
)
from metaforge_verification.engine import plan, references
from metaforge_verification.store import Conflict


def resource(store, caller, kind, resource_id=None, name=None, revision_id=None):
    row = store.get_resource(caller.tenant_id, kind, resource_id, name, revision_id)
    if row is None:
        raise HTTPException(404, "Resource not found")
    return row


def resolve(store, checks, body, caller):
    if isinstance(body, VerificationRequest):
        return body
    design = resource(store, caller, "twin", name=body.twin_id, revision_id=body.twin_revision_id)
    requirements = resource(store, caller, "requirements", body.requirements_revision_id)["data"]
    scenarios = resource(store, caller, "scenarios", body.scenario_suite_revision_id)["data"]
    if requirements["profile_id"] != body.profile_revision_id:
        raise HTTPException(409, "Requirement set and profile revisions differ")
    data = {
        **design["data"],
        "requirements": requirements["requirements"],
        "scenarios": scenarios["scenarios"],
        "profile_id": body.profile_revision_id,
        "baseline_id": body.baseline_id,
    }
    try:
        request = VerificationRequest.model_validate(data)
    except ValueError:
        raise HTTPException(422, "Registered resources have incompatible references") from None
    if not body.accept_gaps:
        resolved_plan = plan(request, checks)
        if (
            resolved_plan["missing_profile_rules"]
            or resolved_plan["missing_scenario_families"]
            or resolved_plan["conflicting_requirements"]
            or any(not c["available"] or c["missing_inputs"] for c in resolved_plan["checks"])
        ):
            raise HTTPException(409, {"code": "PLAN_GAPS", "plan": resolved_plan})
    return request


def add_routes(app, store, settings, principal, submit):
    Caller = Annotated[Principal, Depends(principal)]

    def require(caller, permission):
        if permission not in caller.permissions:
            raise HTTPException(403, f"{permission} permission required")

    def job(caller, job_id):
        row = store.get(caller.tenant_id, job_id)
        if row is None:
            raise HTTPException(404, "Verification not found")
        return row

    def artifact(caller, ref):
        try:
            data = artifact_store(settings, caller.tenant_id).read(ref.artifact_id)
            if hashlib.sha256(data).hexdigest() != ref.sha256:
                raise FileNotFoundError
        except FileNotFoundError:
            raise HTTPException(422, "Referenced artifact is missing or digest-invalid") from None

    def put(caller, kind, name, revision_id, data):
        try:
            return store.put_resource(
                caller.tenant_id, kind, name, revision_id, data, caller.actor_id
            )
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/v1/webhook-endpoints", status_code=201)
    def register_webhook(body: WebhookEndpointCreate, caller: Caller):
        require(caller, "review")
        try:
            return store.register_webhook_endpoint(caller.tenant_id, caller.actor_id)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/v1/webhook-endpoints")
    def list_webhooks(caller: Caller):
        row = store.get_webhook_endpoint(caller.tenant_id)
        return {
            "items": [row] if row else [],
            "policy": "Reviewer-managed approved destination; no signing secret returned.",
        }

    @app.post("/v1/webhook-endpoints/{endpoint_id}/disable")
    def disable_webhook(endpoint_id: str, caller: Caller):
        require(caller, "review")
        row = store.get_webhook_endpoint(caller.tenant_id)
        if row is None or row["id"] != endpoint_id:
            raise HTTPException(404, "Webhook endpoint not found")
        return store.disable_webhook_endpoint(caller.tenant_id, endpoint_id, caller.actor_id)

    @app.post("/v1/renders", status_code=202)
    def render(
        body: RenderCreate,
        caller: Caller,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ):
        require(caller, "submit")
        request = VerificationRequest(
            profile_id="artifact-render-v1",
            approval_ref="service:controlled-artifact-capture",
            twin={"twin_id": body.twin_id, "revision_id": body.revision_id},
            cad=body.cad,
            capture=body.source,
            requirements=[
                {
                    "id": "CAPTURE",
                    "description": "Four qualified source-bound views",
                    "rule_id": "visual.render_capture",
                    "required_fidelity": "F1",
                    "criterion": {
                        "operator": ">=",
                        "threshold": {"value": 4, "unit": "dimensionless"},
                    },
                }
            ],
        )
        for reference in references(request):
            artifact(caller, reference)
        return submit(request, caller, idempotency_key)

    @app.get("/v1/renders/{job_id}")
    def render_result(job_id: str, caller: Caller):
        row = job(caller, job_id)
        if row["request"]["profile_id"] != "artifact-render-v1":
            raise HTTPException(404, "Render job not found")
        result = {
            "verification_id": row["id"],
            "execution_state": row["state"],
            "error": row["error"],
            "capture": None,
        }
        if row["report"]:
            result["gate_decision"] = row["report"]["gate_decision"]
            for evidence in row["report"]["evidence"]:
                if evidence["method"] == "visual.render_capture":
                    result["capture"] = evidence["details"]
            result["findings"] = row["report"]["findings"]
        return result

    @app.post("/v1/requirement-sets", status_code=201)
    def register_requirements(body: RequirementSetCreate, caller: Caller):
        require(caller, "review")
        return put(
            caller, "requirements", body.name, body.revision_id, body.model_dump(mode="json")
        )

    @app.get("/v1/requirement-sets/{resource_id}")
    def get_requirements(resource_id: str, caller: Caller):
        return resource(store, caller, "requirements", resource_id)

    @app.post("/v1/scenario-suites", status_code=201)
    def register_scenarios(body: ScenarioSuiteCreate, caller: Caller):
        require(caller, "review")
        return put(caller, "scenarios", body.name, body.revision_id, body.model_dump(mode="json"))

    @app.get("/v1/scenario-suites/{resource_id}")
    def get_scenarios(resource_id: str, caller: Caller):
        return resource(store, caller, "scenarios", resource_id)

    @app.post("/v1/twins/{twin_id}/revisions", status_code=201)
    def register_revision(twin_id: str, body: VerificationRequest, caller: Caller):
        require(caller, "submit")
        if body.twin.twin_id != twin_id:
            raise HTTPException(422, "Twin path and manifest ID differ")
        for ref in references(body):
            artifact(caller, ref)
        return put(caller, "twin", twin_id, body.twin.revision_id, body.model_dump(mode="json"))

    @app.get("/v1/twins/{twin_id}/revisions/{revision_id}")
    def get_revision(twin_id: str, revision_id: str, caller: Caller):
        return resource(store, caller, "twin", name=twin_id, revision_id=revision_id)

    @app.get("/v1/verifications/{job_id}/findings")
    def findings(
        job_id: str,
        caller: Caller,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
    ):
        row = job(caller, job_id)
        if row["report"] is None:
            raise HTTPException(409, "Report not available")
        values = row["report"]["findings"]
        items = values[after : after + limit]
        return {"items": items, "next_cursor": after + len(items), "total": len(values)}

    @app.post("/v1/verifications/{job_id}/reverify", status_code=202)
    def reverify(
        job_id: str,
        body: VerificationRequest,
        caller: Caller,
        idempotency_key: Annotated[str, Header(min_length=1, max_length=200)],
    ):
        require(caller, "submit")
        job(caller, job_id)
        if body.previous_verification_id not in {None, job_id}:
            raise HTTPException(409, "Reverification lineage differs from path")
        return submit(
            body.model_copy(update={"previous_verification_id": job_id}), caller, idempotency_key
        )

    @app.post("/v1/artifact-uploads", status_code=201)
    def create_upload(body: UploadCreate, caller: Caller):
        require(caller, "submit")
        if body.size_bytes > settings.max_upload_bytes:
            raise HTTPException(413, "Artifact exceeds configured size limit")
        row = store.create_upload(caller.tenant_id, body)
        return {
            "upload_id": row["id"],
            "expires_at": row["expires"],
            "upload_url": f"/v1/artifact-uploads/{row['id']}/content",
            "finalize_url": f"/v1/artifacts/{row['id']}/finalize",
        }

    def upload_session(caller, upload_id):
        row = store.get_upload(caller.tenant_id, upload_id)
        if row is None:
            raise HTTPException(404, "Upload not found")
        if row["expires"] < time.time():
            raise HTTPException(409, "Upload expired")
        return row

    @app.put(
        "/v1/artifact-uploads/{upload_id}/content",
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def stage_upload(upload_id: str, request: Request, caller: Caller):
        require(caller, "submit")
        row = upload_session(caller, upload_id)
        data = await request.body()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != row["size_bytes"] or row["expected_sha256"] not in {None, digest}:
            raise HTTPException(422, "Upload size or expected digest differs")
        artifact_store(settings, caller.tenant_id).put(data)
        try:
            store.stage_upload(caller.tenant_id, upload_id, digest)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        return {"upload_id": upload_id, "state": "staged", "sha256": digest}

    @app.post("/v1/artifacts/{upload_id}/finalize")
    def finalize_upload(upload_id: str, caller: Caller):
        require(caller, "submit")
        row = upload_session(caller, upload_id)
        if row["state"] not in {"staged", "finalized"}:
            raise HTTPException(409, "Upload content has not been staged")
        try:
            data = artifact_store(settings, caller.tenant_id).read(row["actual_sha256"])
        except FileNotFoundError:
            raise HTTPException(422, "Staged artifact is unavailable") from None
        if (
            len(data) != row["size_bytes"]
            or hashlib.sha256(data).hexdigest() != row["actual_sha256"]
        ):
            raise HTTPException(422, "Staged artifact failed integrity validation")
        store.finalize_upload(caller.tenant_id, upload_id)
        return {
            "artifact_id": row["actual_sha256"],
            "sha256": row["actual_sha256"],
            "size_bytes": len(data),
            "state": "finalized",
        }

    @app.post("/v1/verifications/{job_id}/physical-evidence", status_code=201)
    def physical_evidence(job_id: str, body: PhysicalEvidenceCreate, caller: Caller):
        require(caller, "submit")
        job(caller, job_id)
        artifact(caller, body.artifact)
        payload = {
            **body.model_dump(mode="json"),
            "review_status": "unreviewed",
            "provenance": "externally_supplied",
            "fidelity_qualified": False,
        }
        return put(caller, "physical", job_id, str(uuid.uuid4()), payload)

    @app.get("/v1/physical-evidence/{resource_id}")
    def get_physical_evidence(resource_id: str, caller: Caller):
        return resource(store, caller, "physical", resource_id)
