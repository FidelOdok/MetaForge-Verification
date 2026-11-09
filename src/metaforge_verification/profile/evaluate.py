"""Evaluate the `imagine-v1` profile: findings, gate decisions, verdict, level.

A pure function of the request and the rule version: the same input gives the
same report byte for byte. No clock, no storage, no network. That is what lets
it answer synchronously, and what makes a replay reproduce a report.
"""

from __future__ import annotations

from metaforge_verification.contracts import fingerprint
from metaforge_verification.profile.contracts import (
    UNRESOLVED,
    ConceptRevision,
    Gate,
    GateResult,
    Level,
    Ref,
    Status,
    ValidationFinding,
    ValidationReport,
    ValidationRequest,
    Verdict,
)
from metaforge_verification.profile.rules import (
    LIMITATIONS,
    PROFILE_ID,
    PROFILE_VERSION,
    RULE_VERSION,
    RULES,
)

ALL_GATES: tuple[Gate, ...] = ("config_valid", "handover", "define_exit")

#: Gates whose every finding decides the gate. Elsewhere only blocking ones do:
#: the Define exit is advisory for handover but still a gate in its own right.
COUNT_ALL = {"define_exit"}


class UnknownRefs(ValueError):
    """A scope ref names nothing in the revision."""

    def __init__(self, bad: list[Ref]) -> None:
        super().__init__("A scope ref names nothing in this revision.")
        self.bad = bad


def known_refs(rev: ConceptRevision) -> set[tuple[str, str]]:
    refs = {
        ("studio", name)
        for name in (
            "config",
            "ledger",
            "assumptions",
            "scenarios",
            "requirements",
            "functions",
            "markets",
            "concept_mesh",
            "interfaces",
            "screening",
        )
    }
    refs.add(("process", "manufacturing"))
    for kind, items in (
        ("ledger_row", rev.ledger),
        ("assumption", rev.assumptions),
        ("scenario", rev.scenarios),
        ("requirement", rev.requirements),
        ("function", rev.functions),
        ("part", rev.parts),
    ):
        refs.update((kind, i.id) for i in items)
    return refs


def is_unresolved_blocker(f: ValidationFinding) -> bool:
    return f.severity == "blocking" and f.status in UNRESOLVED


def compute_verdict(findings: list[ValidationFinding]) -> Verdict:
    """Who acts next. First match wins, so the agent is never handed a blocker it cannot clear."""
    blockers = [f for f in findings if is_unresolved_blocker(f)]
    if any(f.gate == "config_valid" and f.status == Status.FAIL for f in blockers):
        return "invalid"
    for resolver, verdict in (
        ("agent", "needs_agent"),
        ("external", "blocked_external"),
        ("person", "needs_person"),
    ):
        if any(f.resolver == resolver for f in blockers):
            return verdict  # type: ignore[return-value]
    return "ready_for_handover"


def gate_results(findings: list[ValidationFinding], gates: list[Gate]) -> list[GateResult]:
    out = []
    for gate in gates:
        mine = [f for f in findings if f.gate == gate]
        counted = mine if gate in COUNT_ALL else [f for f in mine if f.severity == "blocking"]
        if any(f.status == Status.FAIL for f in counted):
            decision = "fail"
        elif any(f.status in UNRESOLVED for f in counted):
            decision = "incomplete"
        else:
            decision = "pass"
        out.append(
            GateResult(
                gate=gate,
                rule_version=RULE_VERSION,
                decision=decision,
                blocking=sum(1 for f in mine if is_unresolved_blocker(f)),
                assumed=sum(1 for f in mine if f.status == Status.ASSUMED),
                advisory=sum(
                    1
                    for f in mine
                    if f.severity == "advisory" and f.status not in (Status.PASS, Status.ASSUMED)
                ),
            )
        )
    return out


def level_for(findings: list[ValidationFinding]) -> Level:
    """V0 captured, V1 consistent, V2 screened. The ceiling is V2, whatever is submitted."""
    if any(f.gate == "config_valid" and is_unresolved_blocker(f) for f in findings):
        return "V0"
    stored = [f for f in findings if f.check_id == "screening.stored"]
    if stored and all(f.status == Status.PASS for f in stored):
        return "V2"
    return "V1"


def _scoped(findings: list[ValidationFinding], scope: list[Ref]) -> list[ValidationFinding]:
    wanted = {(r.kind, r.id) for r in scope}
    return [
        f
        for f in findings
        if (f.target.kind, f.target.id) in wanted
        or any((e.kind, e.id) in wanted for e in f.evidence)
    ]


def config_not_supplied(rev: ConceptRevision) -> ValidationFinding:
    """No client said the config is valid, so the service does not assume it is."""
    return ValidationFinding(
        id="f_config_not_supplied",
        check_id="config.not_supplied",
        rule_version=RULE_VERSION,
        gate="config_valid",
        severity="blocking",
        status=Status.NOT_ASSESSED,
        target=Ref(kind="studio", id="config", revision=rev.number),
        message="No config_valid result was supplied; the config is not assumed valid.",
        resolver="external",
    )


def validate(request: ValidationRequest) -> ValidationReport:
    rev = request.revision
    # The client owns config_valid. Without a supplied result the gate is left
    # out of a default report: the service evaluated nothing, so it says nothing.
    wanted = request.gates or [g for g in ALL_GATES if g != "config_valid" or request.supplied]
    gates = [g for g in ALL_GATES if g in wanted]
    if request.scope:
        known = known_refs(rev)
        bad = [r for r in request.scope if (r.kind, r.id) not in known]
        if bad:
            raise UnknownRefs(bad)

    findings: list[ValidationFinding] = [f for f in request.supplied if f.gate in gates]
    if "config_valid" in gates:
        said_valid = any(f.status == Status.PASS for f in findings)
        said_invalid = any(is_unresolved_blocker(f) for f in findings)
        if not said_valid and not said_invalid:
            findings.append(config_not_supplied(rev))
    for rule in RULES:
        if rule.gate in gates:
            findings.extend(rule.evaluate(rev))
    if request.scope:
        findings = _scoped(findings, request.scope)

    return ValidationReport(
        profile_id=PROFILE_ID,
        profile_version=PROFILE_VERSION,
        twin_id=rev.twin_id,
        revision_id=rev.revision_id,
        revision_number=rev.number,
        input_fingerprint=fingerprint(
            {
                "revision": rev.model_dump(mode="json"),
                "supplied": [f.model_dump(mode="json") for f in request.supplied],
            }
        ),
        level=level_for(findings),
        gates=gate_results(findings, gates),
        findings=findings,
        debt=[f for f in findings if f.status == Status.ASSUMED],
        verdict=compute_verdict(findings),
        limitations=LIMITATIONS,
    )
