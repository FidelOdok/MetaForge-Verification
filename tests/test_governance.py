import copy

from fastapi.testclient import TestClient

from metaforge_verification.api import create_app
from metaforge_verification.contracts import VerificationRequest
from metaforge_verification.store import Store
from metaforge_verification.worker import run_once

REVIEW = {"Authorization": "Bearer reviewer-long-random-token"}


def baseline_client(settings):
    settings.review_tokens = {"reviewer-long-random-token": "a"}
    settings.require_approved_baseline = True
    return TestClient(create_app(settings))


def test_agents_cannot_approve_or_change_criteria(settings, headers, payload):
    with baseline_client(settings) as client:
        body = {"verification": payload, "rationale": "Reviewed independent fixture"}
        assert client.post("/v1/baselines", json=body, headers=headers).status_code == 403
        assert client.post("/v1/verifications", json=payload, headers=headers).status_code == 409
        baseline = client.post("/v1/baselines", json=body, headers=REVIEW).json()
        payload["baseline_id"] = baseline["id"]
        response = client.post("/v1/verifications", json=payload, headers=headers)
        assert response.status_code == 202
        payload["requirements"][0]["criterion"]["threshold"]["value"] = 100
        changed = {**headers, "Idempotency-Key": "changed"}
        assert client.post("/v1/verifications", json=payload, headers=changed).status_code == 409
        assert (
            client.get(
                f"/v1/baselines/{baseline['id']}",
                headers={"Authorization": "Bearer tenant-b-long-random-token"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/v1/verifications",
                json=payload,
                headers={**REVIEW, "Idempotency-Key": "reviewer-submit"},
            ).status_code
            == 403
        )


def test_revocation_blocks_new_jobs_but_preserves_replay(settings, headers, payload):
    with baseline_client(settings) as client:
        baseline = client.post(
            "/v1/baselines", json={"verification": payload, "rationale": "Reviewed"}, headers=REVIEW
        ).json()
        payload["baseline_id"] = baseline["id"]
        first = client.post("/v1/verifications", json=payload, headers=headers)
        client.post(f"/v1/baselines/{baseline['id']}/revoke", headers=REVIEW)
        assert (
            client.post("/v1/verifications", json=payload, headers=headers).json() == first.json()
        )
        assert (
            client.post(
                "/v1/verifications", json=payload, headers={**headers, "Idempotency-Key": "new"}
            ).status_code
            == 409
        )


def test_events_usage_and_review_are_tenant_scoped(settings, payload, headers):
    settings.review_tokens = {"reviewer-long-random-token": "a"}
    app = create_app(settings)
    with TestClient(app) as client:
        result = client.post("/v1/verifications", json=payload, headers=headers).json()
        job_id = result["verification_id"]
        assert run_once(app.state.store, job_id)
        assert not run_once(app.state.store, job_id)
        usage = client.get("/v1/usage", headers=headers).json()
        assert usage["accepted_reports"] == 1
        other = {"Authorization": "Bearer tenant-b-long-random-token"}
        assert client.get("/v1/usage", headers=other).json()["accepted_reports"] == 0
        assert client.get(f"/v1/verifications/{job_id}/events", headers=other).status_code == 404
        data = client.get(f"/v1/verifications/{job_id}/events", headers=headers).json()
        assert [e["kind"] for e in data["items"]] == [
            "verification.queued",
            "verification.running",
            "verification.completed",
        ]
        assert (
            client.get("/v1/events", params={"after": data["next_cursor"]}, headers=headers).json()[
                "items"
            ]
            == []
        )
        review = {"requirement_id": "POWER", "decision": "accepted", "rationale": "Review only"}
        url = f"/v1/verifications/{job_id}/reviews"
        assert client.post(url, json=review, headers=headers).status_code == 403
        assert client.post(url, json=review, headers=REVIEW).status_code == 201
        report = client.get(f"/v1/verifications/{job_id}/report", headers=headers).json()
        assert report["gate_decision"] == "fail"  # Review does not rewrite a failing result.
        assert len(client.get(url, headers=headers).json()["items"]) == 1


def test_revision_freezes_actual_model_not_only_twin(settings, payload):
    import pytest

    from metaforge_verification.store import Conflict

    store = Store(settings)
    request = VerificationRequest.model_validate(payload)
    store.submit("a", "one", request)
    changed = copy.deepcopy(payload)
    changed["behavior_model"]["offline_policy"] = "off"
    with pytest.raises(Conflict, match="immutable"):
        store.submit("a", "two", VerificationRequest.model_validate(changed))


def test_fair_queue_and_global_limit(settings, payload):
    settings.max_running_jobs = 2
    settings.max_running_per_tenant = 1
    store = Store(settings)
    request = VerificationRequest.model_validate(payload)
    a1, _ = store.submit("a", "a1", request)
    store.submit("a", "a2", request)
    b1, _ = store.submit("b", "b1", request)
    first, second = store.claim(), store.claim()
    assert {first["id"], second["id"]} == {a1["id"], b1["id"]}
    assert store.claim() is None
    store.cancel("a", a1["id"])
    assert store.claim()["tenant"] == "a"


def test_revision_comparison_reports_regression_and_resolved(settings, payload, headers):
    app = create_app(settings)
    with TestClient(app) as client:
        first = client.post("/v1/verifications", json=payload, headers=headers).json()[
            "verification_id"
        ]
        run_once(app.state.store, first)
        payload["twin"]["revision_id"] = "r2"
        payload["twin"]["facts"]["load_power"]["quantity"]["value"] = 6
        second = client.post(
            "/v1/verifications", json=payload, headers={**headers, "Idempotency-Key": "two"}
        ).json()["verification_id"]
        run_once(app.state.store, second)
        result = client.get(
            f"/v1/verifications/{second}/comparison", params={"against": first}, headers=headers
        ).json()
        assert (
            next(f for f in result["findings"] if f["requirement_id"] == "POWER")["change"]
            == "resolved"
        )
        assert "POWER" in result["invalidated_requirements"]
        assert "THERMAL" not in result["invalidated_requirements"]


def test_network_denial_is_inherited():
    import subprocess
    import sys

    code = """
from metaforge_verification.process_security import deny_network
import socket
deny_network()
try:
    socket.socket()
except PermissionError:
    print("denied")
else:
    raise SystemExit("network unexpectedly permitted")
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == "denied", result.stderr


def test_revocation_before_execution_blocks_report_and_usage(settings, payload, headers):
    with baseline_client(settings) as client:
        baseline = client.post(
            "/v1/baselines",
            headers=REVIEW,
            json={"verification": payload, "rationale": "Approved synthetic fixture"},
        ).json()
        payload["baseline_id"] = baseline["id"]
        job = client.post("/v1/verifications", json=payload, headers=headers).json()[
            "verification_id"
        ]
        client.post(f"/v1/baselines/{baseline['id']}/revoke", headers=REVIEW)
        assert run_once(client.app.state.store, job)
        assert (
            client.get(f"/v1/verifications/{job}", headers=headers).json()["execution_state"]
            == "failed"
        )
        assert client.get("/v1/usage", headers=headers).json()["accepted_reports"] == 0


def test_digital_model_cannot_close_physical_stage(payload, tmp_path):
    from test_engine import add_images, run

    payload["twin"]["facts"]["load_power"]["quantity"]["value"] = 6
    add_images(payload, tmp_path)
    payload["lifecycle_stage"] = "DVT"
    result = run(payload, tmp_path)
    assert result.gate_decision == "incomplete"
    assert (
        next(f for f in result.findings if f.rule_id == "gate.lifecycle").outcome == "not_assessed"
    )
