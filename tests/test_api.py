from copy import deepcopy

import pytest

from metaforge_verification.api import create_app
from metaforge_verification.config import Settings
from metaforge_verification.worker import run_once


def test_fail_closed_configuration():
    with pytest.raises(ValueError):
        create_app(Settings())


def test_authentication_required(client, payload):
    assert client.get("/health").status_code == 200
    assert client.get("/v1/capabilities").status_code == 401
    assert client.post("/v1/verifications", json=payload).status_code == 401


def test_persistent_async_report_and_idempotency(client, app, headers, payload, settings):
    first = client.post("/v1/verifications", json=payload, headers=headers)
    assert first.status_code == 202, first.text
    job_id = first.json()["verification_id"]
    assert first.json()["execution_state"] == "queued"
    second = client.post("/v1/verifications", json=payload, headers=headers)
    assert second.json()["verification_id"] == job_id
    assert client.get(f"/v1/verifications/{job_id}/report", headers=headers).status_code == 409
    run_once(app.state.store)
    assert (
        client.get(f"/v1/verifications/{job_id}/report", headers=headers).json()["gate_decision"]
        == "fail"
    )
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as restarted:
        report = restarted.get(f"/v1/verifications/{job_id}/report", headers=headers)
        assert report.status_code == 200
        assert restarted.get(
            f"/v1/verifications/{job_id}/report?format=markdown", headers=headers
        ).text.startswith("# Verification report")


def test_conflicts_do_not_mutate_revision(client, headers, payload):
    assert client.post("/v1/verifications", json=payload, headers=headers).status_code == 202
    changed = deepcopy(payload)
    changed["twin"]["facts"]["load_power"]["quantity"]["value"] = 6
    assert client.post("/v1/verifications", json=changed, headers=headers).status_code == 409
    assert (
        client.post(
            "/v1/verifications", json=changed, headers={**headers, "Idempotency-Key": "two"}
        ).status_code
        == 409
    )
    changed["twin"]["revision_id"] = "r2"
    assert (
        client.post(
            "/v1/verifications", json=changed, headers={**headers, "Idempotency-Key": "two"}
        ).status_code
        == 202
    )


def test_tenant_isolation_jobs_and_artifacts(client, headers, payload):
    job_id = client.post("/v1/verifications", json=payload, headers=headers).json()[
        "verification_id"
    ]
    b = {"Authorization": "Bearer tenant-b-long-random-token"}
    assert client.get(f"/v1/verifications/{job_id}", headers=b).status_code == 404
    assert client.post(f"/v1/verifications/{job_id}/cancel", headers=b).status_code == 404
    artifact = client.post("/v1/artifacts", headers=headers, content=b"private-model").json()
    path = f"/v1/artifacts/{artifact['artifact_id']}"
    assert client.get(path, headers=headers).content == b"private-model"
    assert client.get(path, headers=b).status_code == 404


def test_cancellation_prevents_execution(client, app, headers, payload):
    job_id = client.post("/v1/verifications", json=payload, headers=headers).json()[
        "verification_id"
    ]
    assert (
        client.post(f"/v1/verifications/{job_id}/cancel", headers=headers).json()["execution_state"]
        == "canceled"
    )
    assert run_once(app.state.store) is False


def test_strict_contracts(client, headers, payload):
    payload["tenant_id"] = "other-tenant"
    assert client.post("/v1/verifications", json=payload, headers=headers).status_code == 422


def test_upload_limit(client, settings, headers):
    settings.max_upload_bytes = 4
    assert client.post("/v1/artifacts", content=b"12345", headers=headers).status_code == 413


def test_openapi_has_no_metaforge_application_dependency(client):
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "MetaForge Verification"
    assert "/v1/verifications" in spec["paths"]


def test_pending_quota_is_enforced(client, settings, headers, payload):
    settings.max_pending_per_tenant = 1
    first = client.post("/v1/verifications", json=payload, headers=headers)
    assert first.status_code == 202
    assert (
        client.post(
            "/v1/verifications", json=payload, headers={**headers, "Idempotency-Key": "second"}
        ).status_code
        == 429
    )
    # Idempotent replay is not a new reservation.
    assert client.post("/v1/verifications", json=payload, headers=headers).status_code == 202


def test_unknown_units_and_duplicate_ids_are_rejected(client, headers, payload):
    payload["twin"]["facts"]["load_power"]["quantity"]["unit"] = "watt ** 999999999"
    assert client.post("/v1/verifications", json=payload, headers=headers).status_code == 422
    payload["twin"]["facts"]["load_power"]["quantity"]["unit"] = "W"
    payload["requirements"][1]["id"] = payload["requirements"][0]["id"]
    assert client.post("/v1/verifications", json=payload, headers=headers).status_code == 422
