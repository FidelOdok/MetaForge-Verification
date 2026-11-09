import json
import struct

import pytest
from fastapi.testclient import TestClient

from metaforge_verification.api import create_app
from metaforge_verification.contracts import VerificationRequest
from metaforge_verification.engine import evaluate
from metaforge_verification.render_worker import qualify_glb
from metaforge_verification.store import LocalArtifactStore


def glb(document):
    encoded = json.dumps(document).encode()
    encoded += b" " * ((-len(encoded)) % 4)
    return struct.pack("<5I", 0x46546C67, 2, 20 + len(encoded), len(encoded), 0x4E4F534A) + encoded


def test_renderer_rejects_external_resources_and_malformed_length():
    with pytest.raises(ValueError, match="embedded"):
        qualify_glb(glb({"buffers": [{"uri": "https://outside.invalid/model.bin"}]}))
    with pytest.raises(ValueError, match="header"):
        qualify_glb(glb({}) + b"extra")


def test_render_job_permissions_and_approval_boundary(settings, headers, payload):
    settings.require_approved_baseline = True
    settings.review_tokens = {"reviewer-long-random-token": "a"}
    with TestClient(create_app(settings)) as client:
        data = glb({"asset": {"version": "2.0"}})
        uploaded = client.post("/v1/artifacts", content=data, headers=headers).json()
        source = {"model": {"artifact_id": uploaded["artifact_id"], "sha256": uploaded["sha256"]}}
        request = {"twin_id": "render-test", "revision_id": "r1", "source": source}
        response = client.post("/v1/renders", json=request, headers=headers)
        assert response.status_code == 202, response.text
        job_id = response.json()["verification_id"]
        assert client.get(f"/v1/renders/{job_id}", headers=headers).json()["capture"] is None
        other = {"Authorization": "Bearer tenant-b-long-random-token"}
        assert client.get(f"/v1/renders/{job_id}", headers=other).status_code == 404
        assert (
            client.post(
                "/v1/renders",
                json=request,
                headers={**headers, "Authorization": "Bearer reviewer-long-random-token"},
            ).status_code
            == 403
        )
        # Artifact generation cannot bypass baseline approval for engineering checks.
        payload["profile_id"] = "artifact-render-v1"
        payload["capture"] = source
        assert client.post("/v1/verifications", json=payload, headers=headers).status_code == 422


def test_step_preview_preserves_named_components_and_transforms(tmp_path):
    pytest.importorskip("OCP")
    from test_engineering import box_step

    from metaforge_verification.adapters.isolated import engineering_task
    from metaforge_verification.contracts import CADAssembly

    artifact = box_step(tmp_path, "part.step", (10, 10, 10))
    source = CADAssembly.model_validate(
        {
            "components": [
                {"id": "case", "step": artifact},
                {"id": "pcb", "step": artifact, "translation_mm": [12, 0, 0]},
            ]
        }
    )
    reader = LocalArtifactStore(tmp_path, "a")
    result = engineering_task(
        {"engine": "cad", "assembly": source.model_dump(mode="json"), "export_glb": True},
        [reader.read(artifact["artifact_id"])] * 2,
    )
    data = result["_glb_bytes"]
    qualify_glb(data)
    length = struct.unpack_from("<I", data, 12)[0]
    model = json.loads(data[20 : 20 + length])
    assert [node["name"] for node in model["nodes"]] == ["case", "pcb"]
    assert model["accessors"][2]["min"] == pytest.approx([0.012, 0, 0])
    assert model["accessors"][2]["max"] == pytest.approx([0.022, 0.01, 0.01])
    assert result["tessellation"]["triangles"] == 24


def test_integrated_gate_requires_scenario_families(payload, tmp_path):
    payload["profile_id"] = "smart-lamp-integrated-v1"
    report = evaluate(
        "family", VerificationRequest.model_validate(payload), LocalArtifactStore(tmp_path, "a")
    )
    assert report.coverage["missing_scenario_families"] == ["fault", "recovery"]
    assert report.gate_decision != "pass"


def test_semantically_empty_fault_scenario_is_rejected(payload):
    payload["scenarios"][0]["family"] = "fault"
    payload["scenarios"][0]["steps"] = [
        {"event": "on", "expected_output": 100, "expected_connected": True}
    ]
    with pytest.raises(ValueError, match="fault stimulus"):
        VerificationRequest.model_validate(payload)
