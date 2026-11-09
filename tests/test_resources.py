import hashlib

from fastapi.testclient import TestClient

from metaforge_verification.api import create_app
from metaforge_verification.worker import run_once


def test_bounded_upload_stage_finalize_and_tenant_access(client, headers):
    data = b"verified fixture bytes"
    digest = hashlib.sha256(data).hexdigest()
    session = client.post(
        "/v1/artifact-uploads", headers=headers, json={"size_bytes": len(data), "sha256": digest}
    ).json()
    assert client.post(session["finalize_url"], headers=headers).status_code == 409
    assert (
        client.put(session["upload_url"], content=data + b"x", headers=headers).status_code == 422
    )
    assert client.put(session["upload_url"], content=data, headers=headers).status_code == 200
    assert client.put(session["upload_url"], content=data, headers=headers).status_code == 200
    assert client.post(session["finalize_url"], headers=headers).json()["artifact_id"] == digest
    assert client.post(session["finalize_url"], headers=headers).status_code == 200
    assert client.get(f"/v1/artifacts/{digest}", headers=headers).content == data
    other = {"Authorization": "Bearer tenant-b-long-random-token"}
    assert client.post(session["finalize_url"], headers=other).status_code == 404


def test_registered_immutable_resources_resolve_to_async_job(settings, payload, headers):
    settings.review_tokens = {"reviewer-long-random-token": "a"}
    reviewer = {"Authorization": "Bearer reviewer-long-random-token"}
    app = create_app(settings)
    with TestClient(app) as client:
        requirements = {
            "name": "lamp",
            "revision_id": "v1",
            "profile_id": payload["profile_id"],
            "requirements": payload["requirements"],
        }
        assert (
            client.post("/v1/requirement-sets", json=requirements, headers=headers).status_code
            == 403
        )
        req = client.post("/v1/requirement-sets", json=requirements, headers=reviewer).json()
        requirements["requirements"][0]["description"] = "changed"
        assert (
            client.post("/v1/requirement-sets", json=requirements, headers=reviewer).status_code
            == 409
        )
        suite = client.post(
            "/v1/scenario-suites",
            headers=reviewer,
            json={"name": "lamp", "revision_id": "v1", "scenarios": payload["scenarios"]},
        ).json()
        twin_id = payload["twin"]["twin_id"]
        assert (
            client.post(f"/v1/twins/{twin_id}/revisions", headers=headers, json=payload).status_code
            == 201
        )
        ref = {
            "twin_id": twin_id,
            "twin_revision_id": "r1",
            "requirements_revision_id": req["id"],
            "scenario_suite_revision_id": suite["id"],
            "profile_revision_id": payload["profile_id"],
        }
        assert client.post("/v1/verifications", json=ref, headers=headers).status_code == 409
        plan = client.post("/v1/verification-plans", json=ref, headers=headers).json()
        assert next(c for c in plan["checks"] if c["rule_id"] == "visual.pixel_difference")[
            "missing_inputs"
        ] == ["visual"]
        ref["accept_gaps"] = True
        response = client.post("/v1/verifications", json=ref, headers=headers)
        assert response.status_code == 202, response.text
        job_id = response.json()["verification_id"]
        run_once(app.state.store, job_id)
        findings = client.get(
            f"/v1/verifications/{job_id}/findings", headers=headers, params={"limit": 2}
        ).json()
        assert len(findings["items"]) == 2 and findings["next_cursor"] == 2
        other = {"Authorization": "Bearer tenant-b-long-random-token"}
        assert client.get(f"/v1/requirement-sets/{req['id']}", headers=other).status_code == 404


def test_reverify_links_revision_and_records_physical_upload(client, app, payload, headers):
    job = client.post("/v1/verifications", json=payload, headers=headers).json()["verification_id"]
    assert (
        client.post(
            f"/v1/verifications/{job}/reverify",
            json=payload,
            headers={**headers, "Idempotency-Key": "two"},
        ).status_code
        == 409
    )
    payload["twin"]["revision_id"] = "r2"
    response = client.post(
        f"/v1/verifications/{job}/reverify",
        json=payload,
        headers={**headers, "Idempotency-Key": "two"},
    )
    assert response.status_code == 202
    new = response.json()["verification_id"]
    assert app.state.store.get("a", new)["request"]["previous_verification_id"] == job
    artifact = client.post("/v1/artifacts", content=b"external bench log", headers=headers).json()
    record = client.post(
        f"/v1/verifications/{new}/physical-evidence",
        headers=headers,
        json={
            "artifact": {"artifact_id": artifact["artifact_id"], "sha256": artifact["sha256"]},
            "configuration_ref": "lamp-r2-serial001",
            "origin": "bench:operator",
            "captured_at": "2026-11-08T14:00:00+00:00",
        },
    )
    assert record.status_code == 201, record.text
    assert record.json()["data"]["fidelity_qualified"] is False
    assert record.json()["data"]["review_status"] == "unreviewed"
