# Readiness profiles

A readiness profile answers "is this phase done, and if not, what is left and who
clears it". It is the second kind of profile in this core. The lamp profile
(`smart-lamp-analytical-v1`, schema 1.0) runs numeric checks against scalar
thresholds as an asynchronous, persisted job. A readiness profile (schema 2.0) judges
declared facts, answers synchronously, and routes the work.

The first readiness profile is `imagine-v1`: whether a design's intent phase can be
handed on to engineering.

## Endpoint

`POST /v1/validations` takes a `ValidationRequest` and returns a `ValidationReport`.

It is a dry run. It is pure and read-only: nothing is stored, no job is queued, no
idempotency key is needed, and the same request gives the same report byte for byte.
It does not hand anything over, accept an assumption or confirm a scenario. Those stay
a person's decisions in the client.

`GET /v1/capabilities` lists it under `validation_profiles`, with the gates the service
owns and the gates a client still supplies.

## The request

| Field | Meaning |
| --- | --- |
| `revision` | A `ConceptRevision`: declared facts about the design's intent, parts and context. Immutable input. |
| `supplied` | Findings from a gate the client still owns (`config_valid`). Folded into the verdict unchanged. A client may not supply a finding for a gate the service owns. To say a config is valid, supply a `pass` finding; the service never infers it. |
| `scope` | Refs to re-check. A ref that names nothing in the revision is a 422 with `bad_refs`. |
| `gates` | Which gates to run. Default: all. |

`ConceptRevision` is neutral on purpose. It carries a ledger, assumptions, scenarios,
requirements, the part chosen for each function, the manufacturing context, markets,
and a few flags. It does not carry any client's config format, so any engineering
client can submit one. A client maps its own state to it.

A client's own readiness answers (`has_value`, `has_test` on a requirement) are
optional. When one is not supplied the check reads `not_assessed`. The service does not
guess.

### The form

A revision may carry `form`, the shape of the product as the client declares it:

| Field | Meaning |
| --- | --- |
| `kind` | `enclosure` (the client's single template) or `authored` (a form built from parts that carry geometry code). |
| `parts` | For an authored form, each part's `id`, its `kind` (`generated`, `primitive` or `component`, which says how far to trust it as geometry) and whether it is the `body`. The code stays with the client. |

The field is optional and additive. A revision without it, or with an `enclosure` form,
produces the report it always did. The client sends it only for an authored form.

## The report

Each `ValidationFinding` has:

- `check_id`, `gate`, `severity` (`blocking` or `advisory`) and `rule_version`.
- `status`: `pass`, `fail`, `assumed`, `inconclusive` or `not_assessed`.
- `target`, a `Ref` (`kind`, `id`, `revision`) saying what it is about.
- `resolver`: who can clear it. `agent` edits the design, `person` is a decision only a
  person can make, `external` needs something outside the revision.
- `fix`, an optional structured hint: an `op`, a JSON `pointer` into the submitted
  revision, and what is `needs`ed. A fix has no value field. It names what is needed and
  where from, never the value.
- `accepted_by`: who accepted an assumption, so an agent's acceptance is never shown as
  a person's confirmation.

Messages are generated from ids and counts, never copied from submitted text, and ids
are restricted to a safe character set. A client must still treat finding text as data.

### Status

`assumed` means satisfied by an accepted assumption, not a confirmation. It is debt:
listed in `debt`, never folded into `pass`, and it does not block. `inconclusive` means
the check ran and the evidence is weak. `not_assessed` means there was no input.

### Gates and verdict

Each gate has a decision of `pass`, `fail` or `incomplete`. A failure dominates;
otherwise any unresolved required finding makes it `incomplete`.

The verdict says who acts next. First match wins:

1. `invalid`: the client supplied a blocking `config_valid` failure.
2. `needs_agent`: a blocking finding the agent can clear.
3. `blocked_external`: a blocking finding that needs something outside.
4. `needs_person`: a blocking finding only a person can clear.
5. `ready_for_handover`: nothing blocking is unresolved.

A gate decision and a verdict are different answers. A gate can read `incomplete` while
the verdict reads `needs_person`.

### Level

`level` is `V0` (captured), `V1` (consistent) or `V2` (screened). It never exceeds V2,
whatever is submitted. It is `V0` while a blocking `config_valid` finding is
unresolved (including one that was never supplied), `V2` once a screening result is
stored, and `V1` otherwise.

## The `imagine-v1` rules

Gate `handover` (blocking). These match the nine-item checklist MetaForge used before
this service owned the decision, so moving it changes no outcome.

| check_id | Blocks when | Resolver |
| --- | --- | --- |
| `ledger.reviewed` | no ledger, or a row is unset, `unreviewed` or `unrepresentable` | agent |
| `assumptions.settled` | an assumption is neither confirmed nor accepted | person |
| `scenarios.confirmed` | none, or an inferred one is not confirmed | person |
| `requirements.sourced` | none, or one has no source | agent |
| `parts.chosen` | a function has no chosen part | agent |
| `parts.source` | a chosen part lacks a source or the date it was read | agent |
| `parts.interfaces` | a chosen part lists no interfaces | agent |
| `parts.envelope` | a chosen part has no 3D envelope | agent |
| `process.context` | process, material or quantity is missing | agent |
| `concept.mesh` | no concept mesh exists | external |
| `interfaces.described` | no interfaces are described | agent |
| `screening.stored` | no V2 screening result is stored | person |

Part checks are one finding per part per check, so a fix is addressable. A part chosen
for two functions is checked once.

`assumptions.settled` and `requirements.sourced` report `assumed` (advisory) when every
assumption is accepted but not all confirmed, or every requirement is sourced but one
uses the default verification method.

Gate `define_exit` (advisory for handover, but a gate in its own right). Ported from the
programme view, where it is stricter on purpose.

| check_id | Meaning |
| --- | --- |
| `define.ledger_reviewed` | every ledger row reviewed (here `unrepresentable` counts as reviewed) |
| `define.assumptions_confirmed` | every assumption confirmed; accepting one does not confirm it |
| `define.markets_chosen` | at least one market |
| `define.requirement_values` | every requirement has a value (client's answer) |
| `define.requirement_tests` | every requirement has a planned test (client's answer) |

The form rules apply only when the client says the form is `authored`. Both are advisory,
so they cannot change a verdict, a gate or a level:

| check_id | Meaning |
| --- | --- |
| `form.enclosure_checks` | the form is authored, so the checks that need an enclosure (wall, draft, fit, moulding, cost) were not assessed; reads `not_assessed`, never `pass` |
| `form.confidence_mix` | every part is a bought component, so nothing shapes the product's own form; fails with a fix that names what is needed and no value |
| `form.measured` | the client did not measure the form, so balance, overhang and overlapping components were not assessed; reads `not_assessed`, with a fix that names a look at the revision, never `pass` |
| `form.balance` | the angle the form tips over at, from the client's estimate of its centre of mass against its flat base: `pass` from 15 degrees, `fail` below that (a screening threshold, stated in the finding) or when the centre of mass is outside the base; `not_assessed` for a form with no flat base |
| `form.component_overlap` | one `fail` per pair of component boxes that overlap, with the volume, or a single `pass` when none do |

The measurements come from the client's own drawn triangles with uniform density and are estimates: the
service judges balance and overlap, as advisory findings that cannot change a verdict, and does not judge
overhang, because its limit depends on a process and an orientation the profile does not have. Wall
thickness is not measured.

The difference between the two gates is deliberate. A studio can pass the handover with
every assumption merely accepted and still fail the Define exit. The report now says so.

## What this does not do

- It checks that a source is present, not that it was read or says what is claimed. A
  template value such as `<order code>` still counts as present. Detecting that is a
  separate claim check.
- `screening.stored` has resolver `person` because only a client's own engine produces a
  screening result today. It becomes `agent` once the screening rules run here.
- The config rules are not here yet. A client supplies `config_valid` findings, and the
  service never marks that gate `pass` by itself. A default report leaves the gate out when
  nothing was supplied, because the service evaluated nothing. Asking for it explicitly with
  nothing supplied, or supplying only warnings, gives the gate `incomplete` and a blocking
  `config.not_supplied` finding (`not_assessed`, resolver `external`), so the verdict reads
  `blocked_external` and not `invalid`: an unchecked config is not a known-bad one.
- Rules are code behind one protocol. Versioned rule data with a closed criterion union
  is the next step.
- Nothing here is measured, simulated or certified, and nothing is above V2.
