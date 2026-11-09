"""The `imagine-v1` profile: when a design's intent phase can be handed on.

Every predicate that decides pass or fail lives here. The handover rules keep
exact parity with the checklist MetaForge shipped before this service owned
them, so moving the decision changes no outcome. The Define-exit rules are
ported from the studio's Programme view, where they are stricter on purpose:
an assumption that is merely accepted passes the handover gate and fails the
Define exit.

Rules are small classes behind one protocol, like the lamp profile's checks.
Turning them into versioned rule data with a closed criterion union is the
next step (spec section 17); until then a rule's metadata and its predicate
sit together so they cannot drift.
"""

from __future__ import annotations

from typing import ClassVar

from metaforge_verification.profile.contracts import (
    ConceptRevision,
    Fix,
    Gate,
    Ref,
    Resolver,
    Severity,
    Status,
    ValidationFinding,
)

PROFILE_ID = "imagine-v1"
PROFILE_VERSION = "1.0.0"
RULE_VERSION = f"{PROFILE_ID}@{PROFILE_VERSION}"

#: A ledger row the handover holds back (the Define exit also accepts
#: ``unrepresentable`` as reviewed, as the Programme view counts it).
HANDOVER_OPEN_ROWS = (None, "", "unreviewed", "unrepresentable")
DEFINE_OPEN_ROWS = (None, "", "unreviewed")

NOT_SUPPLIED = "The client did not supply this; the service does not guess."


def _studio(rev: ConceptRevision, id_: str) -> Ref:
    return Ref(kind="studio", id=id_, revision=rev.number)


class Rule:
    check_id: ClassVar[str]
    gate: ClassVar[Gate]
    severity: ClassVar[Severity] = "blocking"
    resolver: ClassVar[Resolver] = "agent"

    def evaluate(self, rev: ConceptRevision) -> list[ValidationFinding]:
        raise NotImplementedError

    def finding(
        self,
        status: Status,
        target: Ref,
        message: str,
        *,
        suffix: str = "",
        evidence: list[Ref] | None = None,
        fix: Fix | None = None,
        severity: Severity | None = None,
        resolver: Resolver | None = None,
        accepted_by: list[str] | None = None,
    ) -> ValidationFinding:
        stem = "f_" + self.check_id.replace(".", "_")
        return ValidationFinding(
            id=f"{stem}_{suffix}" if suffix else stem,
            check_id=self.check_id,
            rule_version=RULE_VERSION,
            gate=self.gate,
            severity=severity or self.severity,
            status=status,
            target=target,
            message=message,
            evidence=evidence or [],
            resolver=resolver or self.resolver,
            fix=fix,
            accepted_by=accepted_by or [],
        )


# -- handover -----------------------------------------------------------------


class LedgerReviewed(Rule):
    check_id = "ledger.reviewed"
    gate = "handover"

    open_rows: ClassVar[tuple[str | None, ...]] = HANDOVER_OPEN_ROWS

    def evaluate(self, rev):
        rows = rev.ledger
        target = _studio(rev, "ledger")
        if not rows:
            return [self.finding(Status.FAIL, target, "No intent ledger.")]
        open_ = [r for r in rows if r.status in self.open_rows]
        if open_:
            return [
                self.finding(
                    Status.FAIL,
                    target,
                    f"{len(rows) - len(open_)} of {len(rows)} statements reviewed.",
                    evidence=[Ref(kind="ledger_row", id=r.id, revision=rev.number) for r in open_],
                    fix=Fix(
                        op="set",
                        pointer="/ledger",
                        needs="a review status for each open statement",
                    ),
                )
            ]
        return [self.finding(Status.PASS, target, f"All {len(rows)} statements reviewed.")]


class AssumptionsSettled(Rule):
    check_id = "assumptions.settled"
    gate = "handover"
    resolver = "person"

    def evaluate(self, rev):
        target = _studio(rev, "assumptions")
        asm = rev.assumptions
        if not asm:
            return [self.finding(Status.PASS, target, "No assumptions recorded.")]
        unconfirmed = [a for a in asm if a.state == "unconfirmed"]
        accepted = [a for a in asm if a.state == "accepted"]

        def refs(items):
            return [Ref(kind="assumption", id=a.id, revision=rev.number) for a in items]

        if unconfirmed:
            return [
                self.finding(
                    Status.FAIL,
                    target,
                    f"{len(unconfirmed)} of {len(asm)} assumptions still to confirm or accept.",
                    evidence=refs(unconfirmed),
                )
            ]
        if accepted:
            by = sorted({a.accepted_by for a in accepted if a.accepted_by})
            return [
                self.finding(
                    Status.ASSUMED,
                    target,
                    f"{len(accepted)} of {len(asm)} accepted as assumptions, not confirmed.",
                    evidence=refs(accepted),
                    severity="advisory",
                    accepted_by=by,
                )
            ]
        return [self.finding(Status.PASS, target, f"{len(asm)} confirmed.")]


class ScenariosConfirmed(Rule):
    check_id = "scenarios.confirmed"
    gate = "handover"
    resolver = "person"

    def evaluate(self, rev):
        target = _studio(rev, "scenarios")
        if not rev.scenarios:
            return [self.finding(Status.FAIL, target, "No scenario tests yet.")]
        inferred = [s for s in rev.scenarios if s.origin != "person" and not s.confirmed]
        if inferred:
            return [
                self.finding(
                    Status.FAIL,
                    target,
                    f"{len(inferred)} inferred scenarios not yet confirmed by a person.",
                    evidence=[Ref(kind="scenario", id=s.id, revision=rev.number) for s in inferred],
                )
            ]
        return [self.finding(Status.PASS, target, f"{len(rev.scenarios)} confirmed.")]


class RequirementsSourced(Rule):
    check_id = "requirements.sourced"
    gate = "handover"

    def evaluate(self, rev):
        target = _studio(rev, "requirements")
        reqs = rev.requirements
        if not reqs:
            return [self.finding(Status.FAIL, target, "No requirements yet.")]
        unsourced = [r for r in reqs if not (r.source or "").strip()]
        if unsourced:
            return [
                self.finding(
                    Status.FAIL,
                    target,
                    f"{len(unsourced)} of {len(reqs)} requirements have no source.",
                    evidence=[
                        Ref(kind="requirement", id=r.id, revision=rev.number) for r in unsourced
                    ],
                    fix=Fix(
                        op="set",
                        pointer="/requirements",
                        needs="a source for each requirement, from the person",
                    ),
                )
            ]
        defaulted = [r for r in reqs if r.verification_defaulted]
        if defaulted:
            return [
                self.finding(
                    Status.ASSUMED,
                    target,
                    f"{len(reqs)} sourced; {len(defaulted)} use the default verification method.",
                    evidence=[
                        Ref(kind="requirement", id=r.id, revision=rev.number) for r in defaulted
                    ],
                    severity="advisory",
                )
            ]
        return [self.finding(Status.PASS, target, f"{len(reqs)} with a source and a method.")]


def _chosen(rev: ConceptRevision):
    """The distinct parts the functions chose, in function order."""
    by_id = {p.id: p for p in rev.parts}
    seen, out = set(), []
    for fn in rev.functions:
        if fn.part_id and fn.part_id not in seen:
            seen.add(fn.part_id)
            out.append(by_id[fn.part_id])
    return out


class PartsChosen(Rule):
    check_id = "parts.chosen"
    gate = "handover"

    def evaluate(self, rev):
        if not rev.functions:
            return [self.finding(Status.FAIL, _studio(rev, "functions"), "No functions.")]
        out = []
        for fn in rev.functions:
            target = Ref(kind="function", id=fn.id, revision=rev.number)
            if fn.part_id is None:
                out.append(
                    self.finding(
                        Status.FAIL,
                        target,
                        f"No part is chosen for {fn.id}.",
                        suffix=fn.id,
                        fix=Fix(
                            op="add",
                            pointer="/parts",
                            needs=f"a candidate part for {fn.id}, read from its datasheet",
                        ),
                    )
                )
            else:
                out.append(
                    self.finding(Status.PASS, target, f"{fn.id} has a chosen part.", suffix=fn.id)
                )
        return out


class _PartRule(Rule):
    """A check on every chosen part. One finding per part, so a fix is addressable."""

    gate = "handover"

    def gap(self, part) -> str | None:
        raise NotImplementedError

    needs: ClassVar[str]
    field: ClassVar[str]

    def evaluate(self, rev):
        out = []
        index = {p.id: i for i, p in enumerate(rev.parts)}
        for part in _chosen(rev):
            target = Ref(kind="part", id=part.id, revision=rev.number)
            gap = self.gap(part)
            if gap is None:
                out.append(
                    self.finding(Status.PASS, target, f"{part.id} is complete.", suffix=part.id)
                )
            else:
                out.append(
                    self.finding(
                        Status.FAIL,
                        target,
                        f"{part.id} lacks {gap}.",
                        suffix=part.id,
                        evidence=[target],
                        fix=Fix(
                            op="set",
                            pointer=f"/parts/{index[part.id]}/{self.field}",
                            needs=self.needs,
                        ),
                    )
                )
        return out


class PartsSource(_PartRule):
    check_id = "parts.source"
    needs = "a source the agent has read, and the date it was read"
    field = "source"

    def gap(self, part):
        missing = []
        if not (part.source or "").strip():
            missing.append("source")
        if not (part.retrieved or "").strip():
            missing.append("date")
        return " and ".join(missing) or None


class PartsInterfaces(_PartRule):
    check_id = "parts.interfaces"
    needs = "the interfaces the datasheet lists"
    field = "interface_count"

    def gap(self, part):
        return None if part.interface_count > 0 else "interfaces"


class PartsEnvelope(_PartRule):
    check_id = "parts.envelope"
    needs = "an envelope read from a drawing, with its source"
    field = "has_envelope"

    def gap(self, part):
        return None if part.has_envelope else "a 3D envelope"


class ProcessContext(Rule):
    check_id = "process.context"
    gate = "handover"

    def evaluate(self, rev):
        target = Ref(kind="process", id="manufacturing", revision=rev.number)
        ctx = rev.process
        missing = [
            name
            for name, value in (
                ("process", ctx.process),
                ("material", ctx.material),
                ("quantity", ctx.quantity),
            )
            if value in (None, "")
        ]
        if missing:
            return [
                self.finding(
                    Status.FAIL,
                    target,
                    "No " + ", ".join(missing) + ".",
                    fix=Fix(
                        op="set",
                        pointer="/process",
                        needs="process, material and quantity as the person stated them",
                    ),
                )
            ]
        return [self.finding(Status.PASS, target, "Manufacturing context recorded.")]


class ConceptMesh(Rule):
    check_id = "concept.mesh"
    gate = "handover"
    #: Only a step outside the revision makes one.
    resolver = "external"

    def evaluate(self, rev):
        target = _studio(rev, "concept_mesh")
        if rev.concept_mesh:
            return [self.finding(Status.PASS, target, "An illustrative concept mesh exists.")]
        return [self.finding(Status.FAIL, target, "No concept mesh for the project.")]


class InterfacesDescribed(Rule):
    check_id = "interfaces.described"
    gate = "handover"

    def evaluate(self, rev):
        target = _studio(rev, "interfaces")
        if rev.interface_count > 0:
            return [self.finding(Status.PASS, target, f"{rev.interface_count} described.")]
        return [
            self.finding(
                Status.FAIL,
                target,
                "No interfaces described.",
                fix=Fix(op="add", pointer="/interface_count", needs="the interfaces described"),
            )
        ]


class ScreeningStored(Rule):
    check_id = "screening.stored"
    gate = "handover"
    # Only the studio's browser engine produces a screening result today, so no
    # agent can clear this. It becomes ``agent`` when the screening rules run
    # here (spec section 18).
    resolver = "person"

    def evaluate(self, rev):
        target = _studio(rev, "screening")
        if rev.screening_stored:
            return [self.finding(Status.PASS, target, "A V2 screening result is stored.")]
        return [self.finding(Status.FAIL, target, "No V2 screening result is stored.")]


# -- define exit (advisory for handover) -------------------------------------


class _Define(Rule):
    gate = "define_exit"
    severity = "advisory"


class DefineLedgerReviewed(_Define, LedgerReviewed):
    check_id = "define.ledger_reviewed"
    open_rows = DEFINE_OPEN_ROWS


class DefineAssumptionsConfirmed(_Define):
    """Stricter than the handover: accepting an assumption does not confirm it."""

    check_id = "define.assumptions_confirmed"
    resolver = "person"

    def evaluate(self, rev):
        target = _studio(rev, "assumptions")
        asm = rev.assumptions
        if not asm:
            return [self.finding(Status.PASS, target, "None recorded.")]
        pending = [a for a in asm if a.state != "confirmed"]
        if pending:
            return [
                self.finding(
                    Status.FAIL,
                    target,
                    f"{len(asm) - len(pending)} of {len(asm)} confirmed; "
                    "accepting an assumption does not confirm it.",
                    evidence=[
                        Ref(kind="assumption", id=a.id, revision=rev.number) for a in pending
                    ],
                    accepted_by=sorted({a.accepted_by for a in pending if a.accepted_by}),
                )
            ]
        return [self.finding(Status.PASS, target, f"{len(asm)} of {len(asm)} confirmed.")]


class DefineMarketsChosen(_Define):
    check_id = "define.markets_chosen"

    def evaluate(self, rev):
        target = _studio(rev, "markets")
        if rev.markets:
            return [self.finding(Status.PASS, target, f"{len(rev.markets)} chosen.")]
        return [
            self.finding(
                Status.FAIL,
                target,
                "No market chosen.",
                fix=Fix(op="add", pointer="/markets", needs="at least one market, from the person"),
            )
        ]


class _DefineSupplied(_Define):
    """A check that rests on the client's own readiness answer."""

    attr: ClassVar[str]
    fail_text: ClassVar[str]
    ok_text: ClassVar[str]

    def evaluate(self, rev):
        target = _studio(rev, "requirements")
        answers = [getattr(r, self.attr) for r in rev.requirements]
        if not rev.requirements or any(a is None for a in answers):
            return [self.finding(Status.NOT_ASSESSED, target, NOT_SUPPLIED)]
        short = [r for r in rev.requirements if not getattr(r, self.attr)]
        if short:
            return [
                self.finding(
                    Status.FAIL,
                    target,
                    f"{len(short)} of {len(rev.requirements)} requirements {self.fail_text}.",
                    evidence=[Ref(kind="requirement", id=r.id, revision=rev.number) for r in short],
                )
            ]
        return [self.finding(Status.PASS, target, f"Every requirement {self.ok_text}.")]


class DefineRequirementValues(_DefineSupplied):
    check_id = "define.requirement_values"
    attr = "has_value"
    fail_text = "have no value"
    ok_text = "has a value"


class DefineRequirementTests(_DefineSupplied):
    check_id = "define.requirement_tests"
    attr = "has_test"
    fail_text = "have no planned test"
    ok_text = "has a planned test"


class _Form(Rule):
    """Advisory findings about an authored form. They never block: they make visible what the
    profile did not assess, and they apply only when the client says the form is authored."""

    gate: ClassVar[Gate] = "handover"
    severity: ClassVar[Severity] = "advisory"

    @staticmethod
    def authored(rev: ConceptRevision):
        return rev.form if rev.form is not None and rev.form.kind == "authored" else None


class FormEnclosureChecks(_Form):
    check_id = "form.enclosure_checks"

    def evaluate(self, rev):
        if self.authored(rev) is None:
            return []
        return [
            self.finding(
                Status.NOT_ASSESSED,
                _studio(rev, "form"),
                "The form is authored, so the checks that need an enclosure (wall thickness, "
                "draft, fit of the electronics, moulding and cost) were not assessed.",
            )
        ]


class FormConfidenceMix(_Form):
    check_id = "form.confidence_mix"

    def evaluate(self, rev):
        form = self.authored(rev)
        if form is None or any(p.kind != "component" for p in form.parts):
            return []
        return [
            self.finding(
                Status.FAIL,
                _studio(rev, "form"),
                "Every part of the form is a bought component, so nothing in it shapes this "
                "product's own form and the scene does not read as a finished design.",
                fix=Fix(
                    op="add",
                    pointer="/form/parts",
                    needs="a part whose geometry is generated or declared for this product",
                ),
            )
        ]


RULES: tuple[Rule, ...] = (
    LedgerReviewed(),
    AssumptionsSettled(),
    ScenariosConfirmed(),
    RequirementsSourced(),
    PartsChosen(),
    PartsSource(),
    PartsInterfaces(),
    PartsEnvelope(),
    ProcessContext(),
    ConceptMesh(),
    InterfacesDescribed(),
    ScreeningStored(),
    DefineLedgerReviewed(),
    DefineAssumptionsConfirmed(),
    DefineMarketsChosen(),
    DefineRequirementValues(),
    DefineRequirementTests(),
    FormEnclosureChecks(),
    FormConfidenceMix(),
)

LIMITATIONS = [
    "Declared design facts only: nothing here is measured, simulated or certified.",
    "Nothing is reported above V2 (captured, consistent, screened).",
    "Config validity is supplied by the client until those rules move into this service.",
    "Whether a requirement has a value or a planned test is the client's answer; "
    "when it is not supplied the check reads not_assessed.",
    "A part's source is checked for presence, not that it was read or says what is claimed.",
    "A form the client calls authored is not assessed against enclosure checks; the profile "
    "says so and does not guess.",
]
