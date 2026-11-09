# Architecture and boundaries

## Dependencies

MetaForge (or any client) -> versioned Verification HTTP API -> public core.
A cloud extension depends on public contracts and injects identity/storage/execution
implementations. Public core must never import MetaForge, MetaForge-Cloud or a cloud
extension. Keep third-party engineering engines behind versioned checks.

## Implemented execution

Submission commits an immutable request and queued job in one transaction. A separate
worker atomically claims the job with a renewable lease and fencing token. Reports
commit only if the attempt still owns an unexpired lease. Cancellation invalidates
that ownership, preventing late result acceptance. It does not forcibly terminate
arbitrary plugin code; built-ins are bounded and production adapters require process
isolation and hard limits. The SQL runner is a development executor, not an elastic
sandbox or a fair 100-tenant scheduler.

Tenant admission is serialized through PostgreSQL transaction advisory locks or
SQLite immediate transactions. Idempotency is tenant-scoped; revision identity is
immutable per tenant/twin/revision. Input fingerprint includes requirements, approval
reference, model, scenarios and visual comparison. New criteria can evaluate an
unchanged twin but cannot mutate its artifact/fact revision.

Temporal dispatcher starts deterministic workflow IDs from the SQL outbox. The workflow
runs a fenced evaluation activity; activity retries respect terminal job states and
lease ownership. The current workflow has a five-minute per-activity limit; its built-in
checks are small. Do not install long-running plugins without an isolated execution
backend and qualified cancellation/timeouts. Workflow replay, worker deployment
versioning and live failover still require deployment qualification. Initialization
currently creates tables; a production schema migration policy is follow-up work.

## Evidence semantics

Artifact hashes are checked against actual tenant-local bytes. Analytical results are
computed from submitted sourced values, not measured from hardware. Box fit assumes
centered axis alignment and ignores obstacles/tolerances. Thermal uses T=ambient+P*R
at steady state. Behavior is a declared discrete model with submitted independent
expectations, not firmware execution. Visual comparison counts all differing RGBA
pixels under matching supplied capture-context hashes; it does not establish reference
pose authenticity, semantics, finish or aesthetic quality.

Missing input -> not_assessed. Invalid units/quality or insufficient fidelity ->
inconclusive. Numeric violation -> fail. Required failure dominates gate; otherwise
missing required evidence -> incomplete. Optional failures remain visible. A pass
belongs only to this named analytical profile and its submitted criteria.

## Readiness profiles

`POST /v1/validations` evaluates a readiness profile (`docs/readiness-profiles.md`)
over a submitted revision. It is synchronous and pure: no job, no storage, no clock, so
the same input gives the same report. It shares the contract base and fingerprinting
with the lamp profile but has its own schema (2.0) in `metaforge_verification.profile`,
so the lamp contracts and their published OpenAPI schemas are unchanged. The core
judges declared facts submitted in a neutral `ConceptRevision`; it never reads a
client's own config format.

## Adapter reuse plan

MetaForge already has a standalone render.model_views tool (Playwright/Chromium/Three.js),
CAD/EDA adapter images and Temporal. Reuse qualified deployments through explicit
versioned protocols; do not copy the gateway into this repo. The standalone PNG adapter accepts qualified captures from that render tool. The optional
`visual-capture` package also provides a small independent controlled GLB renderer;
neither capture path is implicitly called by the initial verification worker.

Next slices:
1. Qualify an operator-configured client for existing MCP adapters, including pinned
   image/tool versions, deadlines and typed outputs. No customer-supplied fetch URLs.
2. Add authoritative CAD checks and KiCad/ngspice evidence; keep declared-box checks
   separately named.
3. Add a controlled render worker and visual-feature criteria, with reference authority,
   visibility, annotations and optional VLM evaluation.
4. Add S3-compatible artifact storage, job-scoped credentials, external identity/roles,
   outbox webhooks, fair resource scheduling and usage ledger.
5. Qualify compiled firmware, coupled simulation and physical evidence separately.

No billing, evidence cache reuse or physical/certification readiness is implemented.

## Provider portability

SQLite/PostgreSQL, Python containers and the check/auth protocols are provider-neutral.
S3-compatible storage and isolated worker launch are explicit extension work. Local
Compose proves no AWS dependency, but not production portability/HA. Build one qualified
production backend first. Keep GHCR/GitHub CI reusable; avoid replacing Temporal with
SQS merely to adopt a provider stack.
