"""Deterministic planning, qualification and requirement/gate evaluation."""

import hashlib
import importlib.util
import logging
import os
import shutil
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from importlib.metadata import entry_points

from metaforge_verification.adapters.analytical import (
    EnclosureFit,
    PowerBudget,
    ThermalEstimate,
    ThermalWorstCase,
    convert,
)
from metaforge_verification.adapters.base import CheckUnavailable, InvalidEvidence
from metaforge_verification.adapters.behavior import BehaviorScenarios
from metaforge_verification.adapters.engineering import (
    CADClearance,
    CADEnvelopeContainment,
    CADInterference,
    CADValidity,
    CircuitDissipation,
    CircuitThermal,
    DCOperatingPoint,
)
from metaforge_verification.adapters.visual import PixelDifference, RegionSilhouette
from metaforge_verification.contracts import Finding, Outcome, Report, fingerprint

MANDATORY = {
    "device.power_budget",
    "device.thermal_estimate",
    "geometry.declared_box_fit",
    "scenario.device_behavior",
    "visual.pixel_difference",
}
PROFILES = {
    "smart-lamp-analytical-v1": MANDATORY,
    "smart-lamp-digital-v1": (MANDATORY - {"geometry.declared_box_fit"})
    | {
        "geometry.step_validity",
        "geometry.step_interference",
        "geometry.step_clearance",
        "geometry.step_envelope_containment",
        "electrical.dc_output_voltage",
        "device.thermal_worst_case",
        "visual.region_silhouette",
    },
}
LIMITATIONS = [
    "Named lamp profiles only; no certification or manufacturing approval.",
    "Declared boxes/component values are not independently measured CAD/circuit data.",
    "Behavior-model tests do not validate compiled firmware or physical/network behavior.",
    "PNG comparison does not validate visible-feature semantics or subjective aesthetics.",
    "STEP distance/intersection does not establish global wall thickness or identity.",
    "Ideal resistive DC only; KiCad, semiconductor and firmware support is separate.",
    "100-tenant production operation and cloud identity are not qualified by this release.",
]


def registry(load_plugins=False):
    checks = {
        c.rule_id: c
        for c in (
            PowerBudget(),
            ThermalEstimate(),
            EnclosureFit(),
            BehaviorScenarios(),
            PixelDifference(),
            CADValidity(),
            CADInterference(),
            CADClearance(),
            CADEnvelopeContainment(),
            DCOperatingPoint(),
            CircuitDissipation(),
            CircuitThermal(),
            ThermalWorstCase(),
            RegionSilhouette(),
        )
    }
    if load_plugins:
        for ep in entry_points(group="metaforge.verification.checks"):
            check = ep.load()()
            if check.rule_id in checks:
                raise ValueError(f"Plugin cannot override built-in rule: {check.rule_id}")
            checks[check.rule_id] = check
    return checks


def references(request):
    refs = list(request.twin.artifacts)
    if request.visual:
        refs.extend([request.visual.reference, request.visual.candidate])
    if request.cad:
        refs.extend(c.step for c in request.cad.components)
    return refs


class EvaluationArtifacts:
    """One evaluation's immutable artifact reader and shared in-flight engineering results."""

    def __init__(self, reader, cancelled=None):
        self.reader, self.lock, self.results = reader, threading.Lock(), {}
        self.cancelled = cancelled

    def read(self, artifact_id):
        return self.reader.read(artifact_id)

    def engineering(self, task, blobs=None):
        from metaforge_verification.adapters.isolated import engineering_task

        key = fingerprint(
            {"task": task, "blobs": [hashlib.sha256(b).hexdigest() for b in blobs or []]}
        )
        with self.lock:
            first = key not in self.results
            if first:
                self.results[key] = Future()
            future = self.results[key]
        if first:
            try:
                future.set_result(engineering_task(task, blobs, cancelled=self.cancelled))
            except Exception as exc:
                future.set_exception(exc)
        return future.result()


def criterion_conflicts(request):
    """Find incompatible required numeric constraints on the same measurement."""
    groups, conflicts = {}, set()
    for requirement in request.requirements:
        if requirement.required and requirement.rule_id != "scenario.device_behavior":
            groups.setdefault(requirement.rule_id, []).append(requirement)
    for rules in groups.values():
        lo, hi = float("-inf"), float("inf")
        unit = rules[0].criterion.threshold.unit
        try:
            for r in rules:
                value = convert(r.criterion.threshold, unit)
                if r.criterion.operator in {">=", "=="}:
                    lo = max(lo, value)
                if r.criterion.operator in {"<=", "=="}:
                    hi = min(hi, value)
        except InvalidEvidence:
            conflicts.update(r.id for r in rules)
        if lo > hi:
            conflicts.update(r.id for r in rules)
    return conflicts


def readiness(request, rule):
    configured = os.getenv("VERIFICATION_WORKER_ENGINES")

    def enabled(name, local):
        return local if configured is None else name in configured.split(",")

    required_facts = {
        "device.power_budget": ["supply_power", "load_power"],
        "device.thermal_estimate": [
            "ambient_temperature",
            "dissipated_power",
            "thermal_resistance",
        ],
        "system.circuit_thermal_temperature": ["ambient_temperature", "thermal_resistance"],
        "geometry.declared_box_fit": [
            f"{k}_{a}" for k in ("cavity", "pcb") for a in ("x", "y", "z")
        ],
    }
    missing = [
        f"twin.facts.{name}"
        for name in required_facts.get(rule, [])
        if name not in request.twin.facts
    ]
    available = True
    if rule.startswith("geometry.step_"):
        available = enabled("ocp", importlib.util.find_spec("OCP") is not None)
        if request.cad is None:
            missing.append("cad")
    if rule.startswith("electrical.") or rule == "system.circuit_thermal_temperature":
        executable = os.getenv("VERIFICATION_NGSPICE_EXECUTABLE") or shutil.which("ngspice")
        available = enabled(
            "ngspice",
            bool(executable and os.path.isfile(executable) and os.access(executable, os.X_OK)),
        )
        if request.circuit is None:
            missing.append("circuit")
    if rule == "scenario.device_behavior":
        if request.behavior_model is None:
            missing.append("behavior_model")
        if not request.scenarios:
            missing.append("scenarios")
    if rule == "device.thermal_worst_case" and request.thermal_bounds is None:
        missing.append("thermal_bounds")
    if rule.startswith("visual.") and request.visual is None:
        missing.append("visual")
    if rule == "visual.region_silhouette":
        available = enabled("opencv", importlib.util.find_spec("cv2") is not None)
        if request.visual_features is None:
            missing.append("visual_features")
    return available, missing


def plan(request, checks=None):
    checks = checks if checks is not None else registry()
    return {
        "profile_id": request.profile_id,
        "input_fingerprint": fingerprint(request),
        "checks": [
            {
                "requirement_id": r.id,
                "rule_id": r.rule_id,
                "available": r.rule_id in checks and readiness(request, r.rule_id)[0],
                "missing_inputs": readiness(request, r.rule_id)[1],
                "achievable_fidelity": getattr(checks.get(r.rule_id), "fidelity", None),
            }
            for r in request.requirements
        ],
        "missing_profile_rules": sorted(
            PROFILES[request.profile_id] - {r.rule_id for r in request.requirements if r.required}
        ),
        "conflicting_requirements": sorted(criterion_conflicts(request)),
        "execution": {
            "max_parallel_checks": 4,
            "native_wall_seconds": 45,
            "native_memory_mib": 3072,
            "native_cpu_seconds": 30,
            "scope": "per process; deployment must enforce aggregate limits",
        },
        "limitations": LIMITATIONS,
    }


def evaluate(job_id, request, artifacts, checks=None, cancelled=None):
    checks = checks if checks is not None else registry()
    fp = fingerprint(request)
    evidence_list, findings = [], []
    artifacts = EvaluationArtifacts(artifacts, cancelled)
    conflicts = criterion_conflicts(request)
    integrity_ok = True
    for ref in references(request):
        try:
            raw = artifacts.read(ref.artifact_id)
            if hashlib.sha256(raw).hexdigest() != ref.sha256:
                raise InvalidEvidence("Artifact digest mismatch")
        except (FileNotFoundError, InvalidEvidence):
            integrity_ok = False
    findings.append(
        Finding(
            requirement_id="artifact-integrity",
            rule_id="artifact.integrity",
            module="artifact",
            outcome=Outcome.PASS if integrity_ok else Outcome.FAIL,
            reason="All supplied artifact digests match"
            if integrity_ok
            else "A referenced artifact is missing or has a mismatched digest",
            achieved_fidelity="F0",
        )
    )

    def assess(requirement):
        result_evidence = None
        check = checks.get(requirement.rule_id)
        finding = Finding(
            requirement_id=requirement.id,
            rule_id=requirement.rule_id,
            module=check.module if check else "domain",
            outcome=Outcome.NOT_ASSESSED,
            reason="No qualified adapter installed",
            criterion=requirement.criterion,
            component_ids=[c.id for c in request.cad.components]
            if request.cad and requirement.rule_id.startswith("geometry.step_")
            else [],
        )
        if not integrity_ok:
            finding.reason = "Blocked by artifact integrity failure"
        elif cancelled and cancelled():
            finding.reason = "Execution canceled or lease lost"
        elif requirement.id in conflicts:
            finding.outcome = Outcome.INCONCLUSIVE
            finding.reason = "Conflicting required criteria or incompatible criterion units"
        elif check is not None:
            try:
                check_request = request
                if requirement.rule_id == "scenario.device_behavior":
                    check_request = request.model_copy(
                        update={
                            "scenarios": [
                                s for s in request.scenarios if s.requirement_id == requirement.id
                            ]
                        }
                    )
                result = check.run(check_request, artifacts)
                result_evidence = result.evidence
                finding.evidence_ids = [result.evidence.evidence_id]
                finding.achieved_fidelity = check.fidelity
                finding.measurement = result.value
                measured = convert(result.value, requirement.criterion.threshold.unit)
                threshold = requirement.criterion.threshold.value
                op = requirement.criterion.operator
                passed = {
                    "<=": measured <= threshold,
                    ">=": measured >= threshold,
                    "==": measured == threshold,
                }[op]
                if int(check.fidelity[1:]) < int(requirement.required_fidelity[1:]):
                    finding.outcome = Outcome.INCONCLUSIVE
                    finding.reason = "Evidence fidelity does not satisfy this requirement"
                else:
                    finding.outcome = Outcome.PASS if passed else Outcome.FAIL
                    finding.reason = "Criterion satisfied" if passed else "Criterion violated"
            except CheckUnavailable as exc:
                finding.reason = str(exc)
            except InvalidEvidence as exc:
                finding.outcome, finding.reason = Outcome.INCONCLUSIVE, str(exc)
            except Exception:
                logging.getLogger(__name__).exception("Check execution failed: %s", check.rule_id)
                finding.outcome = Outcome.INCONCLUSIVE
                finding.reason = "Check execution failed; no accepted measurement"
        if finding.outcome == Outcome.FAIL:
            finding.suggestion = (
                "Revise the design against the measured violation; preserve approved criteria."
            )
        return finding, result_evidence

    # All current checks are independent or resolve an explicit shared solver future.
    # Results retain request order regardless of completion order.
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="verification-check") as executor:
        results = list(executor.map(assess, request.requirements))
    for finding, ev in results:
        findings.append(finding)
        if ev is not None:
            evidence_list.append(ev)
    missing = plan(request, checks)["missing_profile_rules"]
    if request.lifecycle_stage != "concept":
        findings.append(
            Finding(
                requirement_id="lifecycle-evidence",
                rule_id="gate.lifecycle",
                module="system",
                outcome=Outcome.NOT_ASSESSED,
                reason="EVT/DVT/PVT gates require qualified physical/process obligations",
            )
        )
    for rule_id in missing:
        findings.append(
            Finding(
                requirement_id=f"profile:{rule_id}",
                rule_id=rule_id,
                module="system",
                outcome=Outcome.NOT_ASSESSED,
                reason="Mandatory profile rule has no required requirement",
            )
        )
    required_ids = {r.id for r in request.requirements if r.required}
    blocking = [
        f
        for f in findings
        if f.requirement_id in required_ids
        or f.requirement_id == "artifact-integrity"
        or f.requirement_id == "lifecycle-evidence"
        or f.requirement_id.startswith("profile:")
    ]
    gate = "pass"
    if any(f.outcome == Outcome.FAIL for f in blocking):
        gate = "fail"
    elif any(f.outcome != Outcome.PASS for f in blocking):
        gate = "incomplete"
    # Explicit required obligations only; optional failures remain in findings.
    by_id = {f.requirement_id: f for f in findings}
    coverage = {
        "required_total": len(required_ids),
        "required_passed": sum(by_id[i].outcome == Outcome.PASS for i in required_ids),
        "required_assessed": sum(
            by_id[i].outcome in (Outcome.PASS, Outcome.FAIL) for i in required_ids
        ),
        "missing_profile_rules": missing,
        "scenario_total": len(request.scenarios),
    }
    return Report(
        verification_id=job_id,
        profile_id=request.profile_id,
        twin_id=request.twin.twin_id,
        revision_id=request.twin.revision_id,
        input_fingerprint=fp,
        gate_decision=gate,
        findings=findings,
        evidence=list({e.evidence_id: e for e in evidence_list}.values()),
        coverage=coverage,
        limitations=LIMITATIONS,
        lifecycle_stage=request.lifecycle_stage,
        approval={"status": "externally_asserted", "reference": request.approval_ref},
    )
