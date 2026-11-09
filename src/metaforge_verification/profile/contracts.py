"""Contracts of profile validation (schema 2.0): findings that say who clears them.

The lamp profile's 1.0 contracts (`metaforge_verification.contracts`) are
requirement-centric: a numeric check against a scalar threshold. A readiness
profile asks different questions (is this reviewed, sourced, chosen) and its
answer has to route work, so these contracts add what 1.0 lacks: a `Ref` that
addresses what a finding is about, a `resolver` that says who can clear it, a
`fix` that names what is needed and never a value, an `assumed` status that is
debt rather than a pass, and a computed verdict.

`ValidationFinding`, `ValidationReport`, `Ref`, `Resolver`, `Status` and `Verdict` are a contract
shared with clients. Change them only additively, and bump `schema_version`
when a field changes meaning.

The submitted `ConceptRevision` is deliberately neutral: it carries declared
facts about a design's intent, parts and context, not any one client's config
format. A `Fix.pointer` is a JSON pointer into the *submitted revision*; the
client maps it to its own document.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from metaforge_verification.contracts import Contract

ID = r"^[A-Za-z0-9_.:-]{1,100}$"

RefKind = Literal[
    "studio",
    "part",
    "ledger_row",
    "requirement",
    "assumption",
    "scenario",
    "function",
    "interface",
    "process",
]
Gate = Literal["config_valid", "handover", "define_exit"]
#: The gates this service evaluates. ``config_valid`` is supplied by the client
#: until the config rules move here; the service never marks it ``pass``.
OWNED_GATES: tuple[Gate, ...] = ("handover", "define_exit")
Severity = Literal["blocking", "advisory"]
Resolver = Literal["agent", "person", "external"]
Verdict = Literal[
    "invalid", "needs_agent", "blocked_external", "needs_person", "ready_for_handover"
]
Level = Literal["V0", "V1", "V2"]


class Status(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    #: Satisfied by an accepted assumption, not a confirmation. Debt: listed,
    #: never folded into ``pass``.
    ASSUMED = "assumed"
    #: The check ran and cannot settle it (weak evidence).
    INCONCLUSIVE = "inconclusive"
    #: The check could not run (no input).
    NOT_ASSESSED = "not_assessed"


#: Unresolved: a blocking finding in one of these states holds the verdict.
UNRESOLVED = (Status.FAIL, Status.INCONCLUSIVE, Status.NOT_ASSESSED)


class Ref(Contract):
    """A stable address for what a finding is about."""

    kind: RefKind
    id: str = Field(pattern=ID)
    #: The revision number the id was read from.
    revision: int | None = Field(default=None, ge=0)


class Fix(Contract):
    """A structured hint. It names what is needed and where from, never a value."""

    op: Literal["set", "add", "remove"]
    pointer: str = Field(max_length=300)
    needs: str = Field(max_length=300)


class ValidationFinding(Contract):
    id: str = Field(pattern=ID)
    check_id: str = Field(pattern=ID)
    rule_version: str = Field(max_length=50)
    gate: Gate
    severity: Severity
    status: Status
    target: Ref
    #: Generated from ids and counts, never copied from submitted free text,
    #: so a client cannot smuggle instructions through a finding.
    message: str = Field(max_length=500)
    evidence: list[Ref] = Field(default_factory=list, max_length=200)
    resolver: Resolver
    fix: Fix | None = None
    #: Who accepted an assumption, for a delegated acceptance. An agent's
    #: acceptance is never shown as a person's confirmation.
    accepted_by: list[str] = Field(default_factory=list, max_length=50)


class GateResult(Contract):
    gate: Gate
    rule_version: str
    decision: Literal["pass", "fail", "incomplete"]
    blocking: int = 0
    assumed: int = 0
    advisory: int = 0


class ValidationReport(Contract):
    schema_version: Literal["2.0"] = "2.0"
    profile_id: str
    profile_version: str
    twin_id: str
    revision_id: str
    revision_number: int | None = None
    input_fingerprint: str
    #: V0 captured, V1 consistent, V2 screened. Never above V2.
    level: Level
    gates: list[GateResult]
    findings: list[ValidationFinding]
    debt: list[ValidationFinding]
    verdict: Verdict
    limitations: list[str]


# -- the submitted revision --------------------------------------------------


class LedgerRow(Contract):
    id: str = Field(pattern=ID)
    #: As the client records it (for example ``unreviewed``); ``None`` is unset.
    status: str | None = Field(default=None, max_length=50)


class Assumption(Contract):
    id: str = Field(pattern=ID)
    state: Literal["unconfirmed", "accepted", "confirmed"]
    accepted_by: str | None = Field(default=None, max_length=200)


class ScenarioItem(Contract):
    id: str = Field(pattern=ID)
    origin: Literal["person", "inferred"]
    confirmed: bool = False
    confirmed_by: str | None = Field(default=None, max_length=200)


class RequirementItem(Contract):
    id: str = Field(pattern=ID)
    source: str | None = Field(default=None, max_length=500)
    #: The verification method is the catalogue's default, not a stated one.
    verification_defaulted: bool = False
    #: The client's own readiness answers. ``None`` means not supplied, which
    #: the service reports as not assessed rather than guessing.
    has_value: bool | None = None
    has_test: bool | None = None


class Function(Contract):
    id: str = Field(pattern=ID)
    #: The part chosen for this function, or ``None``.
    part_id: str | None = Field(default=None, pattern=ID)


class Part(Contract):
    id: str = Field(pattern=ID)
    source: str | None = Field(default=None, max_length=500)
    retrieved: str | None = Field(default=None, max_length=50)
    interface_count: int = Field(default=0, ge=0)
    has_envelope: bool = False


FormKind = Literal["enclosure", "authored"]
PartKind = Literal["generated", "primitive", "component"]


class FormPart(Contract):
    """One part of an authored form. Its code stays with the client; only what the profile
    reads is sent: what it is called and how much it can be trusted as geometry."""

    id: str = Field(pattern=ID)
    #: ``generated`` geometry the agent wrote, a declared ``primitive``, or a bought ``component``.
    kind: PartKind
    #: The part the engine would place the electronics inside.
    body: bool = False


class FormFacts(Contract):
    """The shape of the product, as the client declares it.

    ``enclosure`` is the engine's one template. ``authored`` is a form whose parts carry
    geometry code the client runs in a sandbox. Optional on the revision: a client that does
    not send it, or sends ``enclosure``, gets the report it always got.
    """

    kind: FormKind
    parts: list[FormPart] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def coherent(self):
        ids = [p.id for p in self.parts]
        if len(set(ids)) != len(ids):
            raise ValueError("form part ids must be unique")
        if sum(1 for p in self.parts if p.body) > 1:
            raise ValueError("at most one form part may be the body")
        if self.kind == "authored" and not self.parts:
            raise ValueError("an authored form needs at least one part")
        return self


class ProcessContext(Contract):
    process: str | None = Field(default=None, max_length=100)
    material: str | None = Field(default=None, max_length=100)
    quantity: int | None = Field(default=None, ge=0)


class ConceptRevision(Contract):
    """Declared facts about a design's intent, parts and context. Immutable input."""

    twin_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    revision_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    number: int | None = Field(default=None, ge=0)
    ledger: list[LedgerRow] = Field(default_factory=list, max_length=500)
    assumptions: list[Assumption] = Field(default_factory=list, max_length=200)
    scenarios: list[ScenarioItem] = Field(default_factory=list, max_length=200)
    requirements: list[RequirementItem] = Field(default_factory=list, max_length=500)
    functions: list[Function] = Field(default_factory=list, max_length=200)
    parts: list[Part] = Field(default_factory=list, max_length=500)
    process: ProcessContext = Field(default_factory=ProcessContext)
    markets: list[str] = Field(default_factory=list, max_length=50)
    #: Interfaces described, as the client counts them.
    interface_count: int = Field(default=0, ge=0)
    screening_stored: bool = False
    concept_mesh: bool = False
    #: The product's form, when it is not the engine's enclosure template. ``None`` means the
    #: client did not say, and no form finding is made.
    form: FormFacts | None = None

    @model_validator(mode="after")
    def consistent_references(self):
        for name in ("ledger", "assumptions", "scenarios", "requirements", "functions", "parts"):
            ids = [x.id for x in getattr(self, name)]
            if len(set(ids)) != len(ids):
                raise ValueError(f"{name} ids must be unique")
        parts = {p.id for p in self.parts}
        for fn in self.functions:
            if fn.part_id is not None and fn.part_id not in parts:
                raise ValueError(f"function {fn.id} names an unknown part")
        return self


class ValidationRequest(Contract):
    schema_version: Literal["2.0"] = "2.0"
    profile_id: Literal["imagine-v1"] = "imagine-v1"
    revision: ConceptRevision
    #: Findings from a gate the client still owns (``config_valid``). The
    #: service folds them into the verdict unchanged and never marks one pass.
    supplied: list[ValidationFinding] = Field(default_factory=list, max_length=500)
    #: Re-check only what these refs address.
    scope: list[Ref] | None = Field(default=None, max_length=200)
    gates: list[Gate] | None = None

    @model_validator(mode="after")
    def supplied_only_for_client_gates(self):
        for f in self.supplied:
            if f.gate in OWNED_GATES:
                raise ValueError(f"supplied findings may not claim the {f.gate} gate")
        return self
