import hashlib
import hmac
import io

from metaforge_verification.artifacts import S3ArtifactStore
from metaforge_verification.contracts import VerificationRequest
from metaforge_verification.store import Store
from metaforge_verification.webhooks import deliver_once


def test_webhook_signature_deduplication_and_retry(settings, payload):
    settings.webhook_destinations = {
        "a": {"url": "https://example.test/verification", "secret": "s" * 32}
    }
    store = Store(settings)
    request = VerificationRequest.model_validate(payload)
    store.submit("a", "same", request)
    store.submit("a", "same", request)
    seen = []

    def sender(url, body, headers):
        expected = hmac.new(
            b"s" * 32, headers["X-Verification-Timestamp"].encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        assert headers["X-Verification-Signature"] == "sha256=" + expected
        seen.append(headers["X-Verification-Event-ID"])
        return 204

    assert deliver_once(store, sender)
    assert not deliver_once(store, sender)
    assert len(seen) == 1
    store.submit("a", "another", request)
    assert deliver_once(store, lambda *args: 503)
    assert not deliver_once(store, sender)  # Backoff prevents immediate retry.
    from sqlalchemy import update

    from metaforge_verification.store import webhook_deliveries

    with store.engine.begin() as conn:
        conn.execute(
            update(webhook_deliveries)
            .where(webhook_deliveries.c.state == "pending")
            .values(next_attempt=0)
        )
    assert deliver_once(store, sender)
    assert len(seen) == 2


def test_s3_hash_namespace_and_integrity():
    class Client:
        objects = {}

        def put_object(self, **kwargs):
            self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"].read()

        def get_object(self, **kwargs):
            return {"Body": io.BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

    client = Client()
    a, b = S3ArtifactStore("bucket", "a", client), S3ArtifactStore("bucket", "b", client)
    digest = a.put(b"private fixture")
    assert a.read(digest) == b"private fixture"
    assert a.key(digest) != b.key(digest)
    client.objects[("bucket", a.key(digest))] = b"corrupted"
    import pytest

    with pytest.raises(FileNotFoundError):
        a.read(digest)


def test_check_parallelism_preserves_report_order(payload, tmp_path):
    import threading

    from metaforge_verification.adapters.base import CheckResult
    from metaforge_verification.contracts import Evidence, Quantity
    from metaforge_verification.engine import evaluate
    from metaforge_verification.store import LocalArtifactStore

    barrier = threading.Barrier(2)

    class Check:
        module, fidelity = "domain", "F2"

        def __init__(self, rule_id):
            self.rule_id = rule_id

        def run(self, request, artifacts):
            barrier.wait(timeout=3)
            return CheckResult(
                Quantity(value=0, unit="dimensionless"),
                Evidence(
                    evidence_id=self.rule_id,
                    method=self.rule_id,
                    fidelity="F2",
                    input_fingerprint="x",
                ),
            )

    from test_engineering import requirement

    payload["requirements"] = [requirement("first"), requirement("second")]
    payload["scenarios"] = []
    report = evaluate(
        "parallel",
        VerificationRequest.model_validate(payload),
        LocalArtifactStore(tmp_path, "a"),
        checks={r: Check(r) for r in ("first", "second")},
    )
    assert [f.requirement_id for f in report.findings[1:3]] == ["first", "second"]
    assert all(f.outcome == "pass" for f in report.findings[1:3])


def test_registered_webhook_authority_and_disable(settings, payload, headers):
    from fastapi.testclient import TestClient

    from metaforge_verification.api import create_app

    settings.review_tokens = {"reviewer-long-random-token": "a"}
    settings.webhook_destinations = {
        "a": {"url": "https://approved.example.test/events", "secret": "s" * 32}
    }
    app = create_app(settings)
    reviewer = {"Authorization": "Bearer reviewer-long-random-token"}
    with TestClient(app) as client:
        assert client.post("/v1/webhook-endpoints", json={}, headers=headers).status_code == 403
        assert (
            client.post(
                "/v1/webhook-endpoints", json={"url": "http://127.0.0.1"}, headers=reviewer
            ).status_code
            == 422
        )
        registered = client.post("/v1/webhook-endpoints", json={}, headers=reviewer)
        assert registered.status_code == 201
        assert "s" * 32 not in registered.text
        endpoint = registered.json()
        assert (
            client.post("/v1/webhook-endpoints", json={}, headers=reviewer).json()["id"]
            == endpoint["id"]
        )
        other = {"Authorization": "Bearer tenant-b-long-random-token"}
        assert client.get("/v1/webhook-endpoints", headers=other).json()["items"] == []
        client.post("/v1/verifications", json=payload, headers=headers)
        disabled = client.post(f"/v1/webhook-endpoints/{endpoint['id']}/disable", headers=reviewer)
        assert disabled.json()["enabled"] is False
        calls = []
        while deliver_once(app.state.store, lambda *args: calls.append(args) or 204):
            pass
        assert calls == []


def test_shared_cad_waiters_do_not_starve_ready_circuit(monkeypatch, payload, tmp_path):
    import threading
    from collections import Counter

    from test_engineering import dc_payload, requirement

    import metaforge_verification.adapters.isolated as isolated
    from metaforge_verification.engine import evaluate
    from metaforge_verification.store import LocalArtifactStore

    barrier = threading.Barrier(2)
    calls, lock = [], threading.Lock()

    def native(task, blobs=None, timeout=45, cancelled=None):
        with lock:
            calls.append(task["engine"])
        barrier.wait(timeout=3)
        if task["engine"] == "cad":
            return {"invalid_solids": 0, "tool_version": "fixture-native-1"}
        return {"output_voltage_v": 6, "tool_version": "fixture-native-1"}

    monkeypatch.setattr(isolated, "engineering_task", native)
    dc_payload(payload)
    reader = LocalArtifactStore(tmp_path, "a")
    digest = reader.put(b"dispatch fixture; never parsed by a native engine")
    ref = {"artifact_id": digest, "sha256": digest}
    payload["cad"] = {"components": [{"id": "a", "step": ref}, {"id": "b", "step": ref}]}
    payload["requirements"] = [
        {**requirement("geometry.step_validity"), "id": f"CAD{i}"} for i in range(4)
    ] + [requirement("electrical.dc_output_voltage", 7, "V", "<=", "F3")]
    report = evaluate("dispatch", VerificationRequest.model_validate(payload), reader)
    assert all(f.outcome == "pass" for f in report.findings[1:6])
    assert Counter(calls) == Counter({"cad": 1, "circuit": 1})
