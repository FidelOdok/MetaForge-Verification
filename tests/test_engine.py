import io

import pytest
from PIL import Image

from metaforge_verification.contracts import VerificationRequest
from metaforge_verification.engine import evaluate
from metaforge_verification.store import LocalArtifactStore


def run(payload, tmp_path):
    return evaluate(
        "test", VerificationRequest.model_validate(payload), LocalArtifactStore(tmp_path, "a")
    )


def test_power_failure_and_coverage_gap(payload, tmp_path):
    report = run(payload, tmp_path)
    power = next(f for f in report.findings if f.requirement_id == "POWER")
    assert power.measurement.value == 1.2 and power.outcome == "fail"
    assert report.gate_decision == "fail"
    assert (
        next(f for f in report.findings if f.requirement_id == "VISUAL").outcome == "not_assessed"
    )


def test_unit_conversion_and_thermal_reference(payload, tmp_path):
    payload["twin"]["facts"]["load_power"]["quantity"] = {"value": 6000, "unit": "mW"}
    report = run(payload, tmp_path)
    assert next(f for f in report.findings if f.requirement_id == "POWER").measurement.value == 0.6
    assert next(f for f in report.findings if f.requirement_id == "THERMAL").measurement.value == 35
    assert report.gate_decision == "incomplete"  # visual evidence missing


@pytest.mark.parametrize("case", ["missing", "units", "physical"])
def test_missing_invalid_and_insufficient_fidelity(payload, tmp_path, case):
    if case == "missing":
        del payload["twin"]["facts"]["supply_power"]
        expected = "not_assessed"
    elif case == "units":
        payload["twin"]["facts"]["supply_power"]["quantity"]["unit"] = "mm"
        expected = "inconclusive"
    else:
        payload["requirements"][0]["required_fidelity"] = "F5"
        expected = "inconclusive"
    assert (
        next(f for f in run(payload, tmp_path).findings if f.requirement_id == "POWER").outcome
        == expected
    )


def test_profile_cannot_be_passed_by_omitting_checks(payload, tmp_path):
    payload["requirements"] = [payload["requirements"][0]]
    payload["twin"]["facts"]["load_power"]["quantity"]["value"] = 5
    payload["scenarios"] = []
    report = run(payload, tmp_path)
    assert report.gate_decision == "incomplete"
    assert len(report.coverage["missing_profile_rules"]) == 4


def test_behavior_mismatch_is_reported(payload, tmp_path):
    payload["behavior_model"]["offline_policy"] = "off"
    report = run(payload, tmp_path)
    finding = next(f for f in report.findings if f.requirement_id == "BEHAVIOR")
    assert finding.outcome == "fail"
    assert finding.measurement.value == 2  # disconnect and reconnect expectations violated


def test_scenarios_do_not_count_as_other_requirements(payload, tmp_path):
    payload["scenarios"][0]["requirement_id"] = "POWER"
    report = run(payload, tmp_path)
    assert (
        next(f for f in report.findings if f.requirement_id == "BEHAVIOR").outcome == "not_assessed"
    )


def add_images(payload, tmp_path, changed=False):
    store = LocalArtifactStore(tmp_path, "a")
    ids = []
    for i in range(2):
        image = Image.new("RGB", (10, 10), "white")
        if changed and i:
            image.putpixel((2, 3), (0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        digest = store.put(buffer.getvalue())
        ids.append({"artifact_id": digest, "sha256": digest})
    payload["visual"] = {
        "reference": ids[0],
        "candidate": ids[1],
        "candidate_revision_id": "r1",
        "reference_context_sha256": "a" * 64,
        "candidate_context_sha256": "a" * 64,
        "approval_ref": "fixture:approved",
    }


def test_rgb_difference_is_not_lost_by_alpha(payload, tmp_path):
    add_images(payload, tmp_path, changed=True)
    report = run(payload, tmp_path)
    finding = next(f for f in report.findings if f.requirement_id == "VISUAL")
    assert finding.outcome == "fail" and finding.measurement.value == 0.01
    ev = next(e for e in report.evidence if e.method == "visual.pixel_difference")
    assert ev.details["difference_bbox"] == (2, 3, 3, 4)


@pytest.mark.parametrize("case", ["stale", "context", "hash"])
def test_invalid_visual_evidence_cannot_pass(payload, tmp_path, case):
    add_images(payload, tmp_path)
    if case == "stale":
        payload["visual"]["candidate_revision_id"] = "r0"
    elif case == "context":
        payload["visual"]["candidate_context_sha256"] = "b" * 64
    else:
        payload["visual"]["candidate"]["sha256"] = "0" * 64
    report = run(payload, tmp_path)
    finding = next(f for f in report.findings if f.requirement_id == "VISUAL")
    assert finding.outcome != "pass"


def test_complete_named_profile_pass_preserves_limits(payload, tmp_path):
    payload["twin"]["facts"]["load_power"]["quantity"]["value"] = 6
    add_images(payload, tmp_path)
    report = run(payload, tmp_path)
    assert report.gate_decision == "pass"
    assert report.coverage["required_passed"] == 5
    assert any("do not validate compiled firmware" in s for s in report.limitations)
