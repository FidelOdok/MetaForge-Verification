import io
import shutil

import pytest
from PIL import Image, ImageDraw

from metaforge_verification.contracts import VerificationRequest
from metaforge_verification.engine import evaluate
from metaforge_verification.store import LocalArtifactStore


def requirement(rule, value=0, unit="dimensionless", operator="<=", fidelity="F1"):
    return dict(
        id=rule.replace(".", "_"),
        description=rule,
        rule_id=rule,
        criterion={"operator": operator, "threshold": {"value": value, "unit": unit}},
        required_fidelity=fidelity,
    )


def run(payload, root):
    return evaluate(
        "test", VerificationRequest.model_validate(payload), LocalArtifactStore(root, "a")
    )


def box_step(tmp_path, name, size):
    pytest.importorskip("OCP")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    writer = STEPControl_Writer()
    writer.Transfer(BRepPrimAPI_MakeBox(*size).Shape(), STEPControl_AsIs)
    path = tmp_path / name
    writer.Write(str(path))
    store = LocalArtifactStore(tmp_path, "a")
    digest = store.put(path.read_bytes())
    return {"artifact_id": digest, "sha256": digest}


@pytest.mark.parametrize("offset,clearance,intersection", [(12, 1.999, 0), (10, 0, 0), (9, 0, 100)])
def test_real_step_distance_and_collision(payload, tmp_path, offset, clearance, intersection):
    artifact = box_step(tmp_path, "box.step", (10, 10, 10))
    payload["cad"] = {
        "components": [
            {"id": "base", "step": artifact},
            {"id": "pcb", "step": artifact, "translation_mm": [offset, 0, 0]},
        ]
    }
    payload["scenarios"] = []
    payload["requirements"] = [
        requirement("geometry.step_validity"),
        requirement("geometry.step_interference", unit="mm^3"),
        requirement("geometry.step_clearance", 1, "mm", ">="),
    ]
    report = run(payload, tmp_path)
    by_rule = {f.rule_id: f for f in report.findings if not f.requirement_id.startswith("profile:")}
    assert by_rule["geometry.step_validity"].outcome == "pass"
    assert by_rule["geometry.step_interference"].measurement.value == pytest.approx(intersection)
    finding = by_rule["geometry.step_clearance"]
    if intersection:
        assert finding.outcome == "inconclusive"
    else:
        assert finding.measurement.value == pytest.approx(clearance)
    ev = next(e for e in report.evidence if e.method == "geometry.step_validity")
    assert ev.details["components"][0]["volume_mm3"] == pytest.approx(1000)
    assert ev.tool_version.startswith("cadquery-ocp/")


def dc_payload(payload):
    payload["scenarios"] = []
    payload["requirements"] = [
        requirement("electrical.dc_output_voltage", 6.001, "V", "<=", "F3"),
        {**requirement("electrical.dc_output_voltage", 5.999, "V", ">=", "F3"), "id": "lower"},
    ]
    payload["circuit"] = {
        "output_node": "out",
        "elements": [
            {
                "id": "supply",
                "kind": "voltage_source",
                "positive": "supply",
                "negative": "0",
                "value": {"value": 12, "unit": "V"},
                "source_ref": "fixture:12V",
            },
            {
                "id": "upper",
                "kind": "resistor",
                "positive": "supply",
                "negative": "out",
                "value": {"value": 1000, "unit": "ohm"},
                "source_ref": "fixture:1kohm",
            },
            {
                "id": "lower",
                "kind": "resistor",
                "positive": "out",
                "negative": "0",
                "value": {"value": 1000, "unit": "ohm"},
                "source_ref": "fixture:1kohm",
            },
        ],
    }


def test_real_ngspice_divider(payload, tmp_path):
    import os

    if not shutil.which("ngspice") and not os.getenv("VERIFICATION_NGSPICE_EXECUTABLE"):
        pytest.skip("ngspice not installed")
    dc_payload(payload)
    report = run(payload, tmp_path)
    for f in report.findings:
        if f.rule_id == "electrical.dc_output_voltage":
            assert f.outcome == "pass", f.reason
            assert f.measurement.value == pytest.approx(6, abs=1e-9)


def test_spice_injection_is_not_a_model(payload):
    dc_payload(payload)
    payload["circuit"]["elements"][0]["positive"] = "out\n.control\nshell id"
    with pytest.raises(ValueError):
        VerificationRequest.model_validate(payload)


def test_real_circuit_loss_to_thermal_dependency(payload, tmp_path):
    import os

    if not shutil.which("ngspice") and not os.getenv("VERIFICATION_NGSPICE_EXECUTABLE"):
        pytest.skip("ngspice not installed")
    dc_payload(payload)
    payload["requirements"] += [
        requirement("electrical.resistor_dissipation", 0.073, "W", "<=", "F3"),
        requirement("system.circuit_thermal_temperature", 26, "degC", "<=", "F2"),
    ]
    report = run(payload, tmp_path)
    loss = next(f for f in report.findings if f.rule_id == "electrical.resistor_dissipation")
    thermal = next(f for f in report.findings if f.rule_id == "system.circuit_thermal_temperature")
    assert loss.outcome == "pass" and loss.measurement.value == pytest.approx(0.072)
    assert thermal.outcome == "pass" and thermal.measurement.value == pytest.approx(25.36)
    evidence = next(e for e in report.evidence if e.method == "system.circuit_thermal_temperature")
    assert evidence.details["source_evidence"]["details"]["power_balance_residual_w"] < 1e-8


def test_native_cancel_and_deadline_are_hard_process_limits():
    from metaforge_verification.adapters.base import CheckUnavailable, InvalidEvidence
    from metaforge_verification.adapters.isolated import engineering_task

    with pytest.raises(CheckUnavailable, match="canceled"):
        engineering_task({"engine": "cad", "assembly": {}}, cancelled=lambda: True)
    with pytest.raises(InvalidEvidence, match="wall-time"):
        engineering_task({"engine": "cad", "assembly": {}}, timeout=0.001)


def test_malformed_step_cannot_pass(payload, tmp_path):
    store = LocalArtifactStore(tmp_path, "a")
    digest = store.put(b"not a STEP model")
    ref = {"artifact_id": digest, "sha256": digest}
    payload["cad"] = {"components": [{"id": "a", "step": ref}, {"id": "b", "step": ref}]}
    payload["requirements"].append(requirement("geometry.step_validity"))
    result = run(payload, tmp_path)
    finding = next(f for f in result.findings if f.rule_id == "geometry.step_validity")
    assert finding.outcome in {"inconclusive", "not_assessed"}


def test_contradictory_criteria_block_execution(payload, tmp_path):
    dc_payload(payload)
    payload["requirements"][1]["criterion"]["threshold"]["value"] = 7
    report = run(payload, tmp_path)
    assert all(
        f.outcome == "inconclusive"
        for f in report.findings
        if f.rule_id == "electrical.dc_output_voltage"
    )


def test_thermal_upper_bound_crossing(payload, tmp_path):
    payload["requirements"].append(requirement("device.thermal_worst_case", 45, "degC", "<=", "F2"))

    def fact(value, unit):
        return {"quantity": {"value": value, "unit": unit}, "source_ref": "approved:upper-bound"}

    payload["thermal_bounds"] = {
        "ambient_max": fact(35, "degC"),
        "dissipation_max": fact(3, "W"),
        "resistance_max": fact(5, "K/W"),
    }
    report = run(payload, tmp_path)
    finding = next(f for f in report.findings if f.rule_id == "device.thermal_worst_case")
    assert finding.measurement.value == 50 and finding.outcome == "fail"


@pytest.mark.parametrize(
    "missing,visible,outcome",
    [(False, True, "pass"), (True, True, "fail"), (False, False, "not_assessed")],
)
def test_visual_feature_region(payload, tmp_path, missing, visible, outcome):
    pytest.importorskip("cv2")
    store, refs = LocalArtifactStore(tmp_path, "a"), []
    for candidate in (False, True):
        image = Image.new("RGB", (40, 40), "white")
        if not candidate or not missing:
            ImageDraw.Draw(image).rectangle((10, 10, 19, 19), fill="black")
        data = io.BytesIO()
        image.save(data, format="PNG")
        digest = store.put(data.getvalue())
        refs.append({"artifact_id": digest, "sha256": digest})
    payload["visual"] = {
        "reference": refs[0],
        "candidate": refs[1],
        "candidate_revision_id": "r1",
        "reference_context_sha256": "a" * 64,
        "candidate_context_sha256": "a" * 64,
        "approval_ref": "review:button",
    }
    payload["visual_features"] = {
        "regions": [{"id": "button", "box": [5, 5, 25, 25], "visible": visible}]
    }
    payload["requirements"].append(requirement("visual.region_silhouette"))
    report = run(payload, tmp_path)
    finding = next(f for f in report.findings if f.rule_id == "visual.region_silhouette")
    assert finding.outcome == outcome
