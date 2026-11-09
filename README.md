# MetaForge Verification

Independent, Apache-2.0 verification core for generated smart-device revisions.
MetaForge is a client, not a required runtime dependency. Hosted account management,
billing and provisioning belong in cloud extensions, not this package.

## Implemented first slice

- Versioned strict request/result contracts and a discoverable analytical lamp profile.
- Immutable twin revisions and input fingerprints.
- Persistent asynchronous jobs with SQLite locally or PostgreSQL, idempotency,
  bounded admission, cancellation and fenced/renewable execution leases.
- Sourced, unit-aware power budgets and single-node steady-state thermal estimates.
- Centered declared-box enclosure-fit calculation, explicitly **not CAD measurement**.
- Executable lamp behavior scenarios, explicitly **not compiled firmware tests**.
- Controlled PNG comparison with revision/context/digest checks and difference regions.
- Optional standalone Playwright/Chromium/Three.js capture worker producing four GLB views.
- Artifact integrity, requirement coverage, pass/fail/inconclusive/not-assessed outcomes,
  and JSON/Markdown evidence reports.
- Token-to-tenant isolation for API, submissions and local artifact paths; fail-closed
  startup unless local single-tenant mode is explicitly selected.
- Trusted check-plugin and authentication extension seams.
- Optional Temporal workflow/dispatcher using the same fenced execution path.
- Readiness profiles (`imagine-v1`): a synchronous, pure `POST /v1/validations` whose
  findings say who can clear them (agent, person or external), with a computed verdict
  and a V2 level ceiling. See `docs/readiness-profiles.md`.

This is a runnable foundation, not the complete smart-device MVP or a qualified
100-customer production deployment. No physical/certification claims are made.
OCP/KiCad/ngspice execution, semantic visual review, calibrated physical inspection,
VLM calls, S3 backend, webhooks, billing and incremental evidence reuse remain follow-up
work. Unsupported requested rules remain explicit gaps. Consult `docs/architecture.md`.

## Quick start

Python 3.12+:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
export VERIFICATION_AUTH_MODE=local  # explicit single tenant; bind only to loopback
metaforge-verification api
```

In another terminal with the same working directory/environment:

```bash
metaforge-verification worker
```

Run the self-contained lamp demonstration (it creates its own temporary database):

```bash
python examples/demo.py
```

Or submit a request:

```bash
curl -X POST http://127.0.0.1:8000/v1/verifications \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: lamp-r1' \
  --data-binary @examples/lamp.json
```

Without uploaded visual assets, that example honestly yields a visual coverage gap.
The demo uploads controlled images and demonstrates failing and corrected revisions.
OpenAPI is served at `/openapi.json`; interactive docs at `/docs`.

## Identity and persistence

Default auth mode is `tokens`, which refuses startup without configured keys:

```bash
export VERIFICATION_AUTH_MODE=tokens
export VERIFICATION_TOKENS='{"replace-with-a-long-random-token":"organization-a"}'
```

Tokens are operator bootstrap configuration, not a production organization/role system.
Do not commit them. An external cloud identity adapter may inject an `Authenticator`
into `create_app`; the core never imports Supabase or a cloud package. The caller
cannot select a tenant using a request field/header.

`VERIFICATION_DATABASE_URL` defaults to `sqlite:///./data/verification.db`.
PostgreSQL uses `postgresql+psycopg://...` after `pip install -e '.[postgres]'`.
`VERIFICATION_ARTIFACT_ROOT` defaults to `./data/artifacts`. Local workers must share
that artifact path. It is not a distributed object store. Jobs and uploaded bytes
survive API restarts; running API in-memory background tasks is deliberately avoided.

`docker compose up --build` runs the local PostgreSQL/API/worker stack with loopback
API ingress and a clearly local-only database password. Do not expose it unchanged.

## Trusted rules and evidence

`approval_ref` identifies the externally approved requirement baseline; this core
records the assertion, it does not independently verify a human approval signature.
Measurements/sources in submissions are externally supplied facts and remain labeled
as such. Missing sources, incompatible units and insufficient fidelity cannot pass.
The analytical profile requires power, thermal, declared-box fit, behavior and visual
obligations; omitting a mandatory rule does not produce a complete profile pass.

Plugins register on `metaforge.verification.checks` and implement `adapters/base.py`.
Enable installed plugins with `VERIFICATION_LOAD_PLUGINS=true`. They are trusted
operator code, not user-supplied scripts or a sandbox. Run heavy/untrusted parsers in
separate qualified workers before claiming their support. A plugin cannot override
a built-in rule ID.

## Temporal option

```bash
pip install -e '.[temporal,postgres]'
export VERIFICATION_TEMPORAL_ADDRESS=localhost:7233
metaforge-verification temporal-worker
# separate process, same DB and artifact storage:
metaforge-verification temporal-dispatch
```

Use this pair **instead of** the SQL polling worker. SQL submissions form the durable
dispatch outbox; workflow IDs deduplicate start attempts. Temporal is an optional
runtime, not a dependency on MetaForge's application. See the architecture document
for execution limits and unqualified deployment behavior.

## Development

```bash
ruff check .
ruff format --check .
pytest -q
metaforge-verification openapi > /tmp/openapi.json
python -m build
```

The GitHub workflows run deterministic CI and package/container builds. Publishing
images and deploying production are deliberately separate. There are no configured
cloud accounts, secrets, production deployment or live performance claims.

## Open core boundary

Public: API, schemas, rules/evidence engine, local runner, basic profile, fixtures,
qualified adapter interfaces and basic visual validation.

Cloud extension: tenant provisioning and role administration, subscriptions/billing,
managed scheduling/storage, enterprise policies and support. Use extension protocols;
never add `if cloud_provider == ...` branches to core verification logic.

License: Apache-2.0, matching the MetaForge open-core repository. This initial code is
new; it does not vendor MetaForge's gateway or adapters. External tool/data licenses
must be reviewed before adding distributions or proprietary components.

## Controlled browser capture

```bash
cd visual-capture
npm ci --ignore-scripts
npx playwright install --with-deps chromium
node capture.mjs /absolute/path/model.glb ./output r1
```

The capture worker owns its Three.js viewer; it does not open a customer session or
fetch arbitrary URLs. It serves only bundled assets and the supplied GLB on loopback,
blocks other origins and waits for explicit render readiness. It writes front/side/top/iso
PNGs plus revision/model/context hashes. Upload selected PNGs through `/v1/artifacts`,
then link the returned digests and capture context in the visual comparison contract.
This CLI-to-API bridge is explicit; capture is not automatically scheduled by the API yet.
Mesh framing is automatic, so compare precise scale/placement with CAD evidence.

Lockfiles: `requirements.lock` (runtime), `requirements-dev.lock` (qualification),
and `visual-capture/package-lock.json`. CI uses the frozen dependency sets.

An operator may set `VERIFICATION_CHROMIUM_EXECUTABLE` to a qualified Chromium binary.
Its actual version is recorded in capture context; do not compare baselines across
unqualified environment changes.
