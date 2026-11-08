"""Deterministic planning, qualification and requirement/gate evaluation."""

import hashlib
from importlib.metadata import entry_points

from metaforge_verification.adapters.analytical import (
    EnclosureFit,
    PowerBudget,
    ThermalEstimate,
    convert,
)
from metaforge_verification.adapters.base import CheckUnavailable, InvalidEvidence
from metaforge_verification.adapters.behavior import BehaviorScenarios
from metaforge_verification.adapters.visual import PixelDifference
from metaforge_verification.contracts import Finding, Outcome, Report, fingerprint

MANDATORY = {
    "device.power_budget",
    "device.thermal_estimate",
    "geometry.declared_box_fit",
    "scenario.device_behavior",
    "visual.pixel_difference",
}
LIMITATIONS = [
    "Analytical lamp profile only. No product certification or manufacturing approval.",
    "Declared boxes/component values are not independently measured CAD/circuit data.",
    "Behavior-model tests do not validate compiled firmware or physical/network behavior.",
    "PNG comparison does not validate visible-feature semantics or subjective aesthetics.",
    "OCP/KiCad/ngspice execution needs separately qualified adapters; not bundled here.",
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
    return refs


def plan(request, checks=None):
    checks = checks if checks is not None else registry()
    return {
        "profile_id": request.profile_id,
        "input_fingerprint": fingerprint(request),
        "checks": [
            {
                "requirement_id": r.id,
                "rule_id": r.rule_id,
                "available": r.rule_id in checks,
                "achievable_fidelity": getattr(checks.get(r.rule_id), "fidelity", None),
            }
            for r in request.requirements
        ],
        "missing_profile_rules": sorted(
            MANDATORY - {r.rule_id for r in request.requirements if r.required}
        ),
        "limitations": LIMITATIONS,
    }


def evaluate(job_id, request, artifacts, checks=None):
    checks = checks if checks is not None else registry()
    fp = fingerprint(request)
    evidence_list, findings = [], []
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
    for requirement in request.requirements:
        check = checks.get(requirement.rule_id)
        finding = Finding(
            requirement_id=requirement.id,
            rule_id=requirement.rule_id,
            module=check.module if check else "domain",
            outcome=Outcome.NOT_ASSESSED,
            reason="No qualified adapter installed",
        )
        if not integrity_ok:
            finding.reason = "Blocked by artifact integrity failure"
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
                evidence_list.append(result.evidence)
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
        findings.append(finding)
    missing = plan(request, checks)["missing_profile_rules"]
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
    )
