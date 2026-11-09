# MetaForge Verification

**Evidence-backed verification for hardware revisions.**

Submit a digital twin, approved requirements and scenarios. Get an asynchronous,
traceable report showing what passed, what failed and which evidence is missing.
Use it from MetaForge, another design agent, an engineering application or CI.

The open core owns verification contracts, execution, engineering checks, evidence
and review. It runs independently of MetaForge and cloud account/billing services.

## Run the integrated test service

```bash
git switch feat/engineering-validation-engines
docker compose -f compose.testing.yaml up --build --wait
docker compose -f compose.testing.yaml run --rm demo
```

Open **http://127.0.0.1:8086/docs** or **http://127.0.0.1:8086/review**.
The demo prints verification IDs and a review link. Use the local fixture submitter
token `local-testing-agent-token`; the separate reviewer token is
`local-testing-reviewer-token`. These are public test credentials for loopback use.

The worker now runs STEP → GLB → four-view capture itself. The HTTP demo detects a
seeded geometry/visual defect, runs circuit/thermal and normal/fault/recovery checks,
and verifies a correction against unchanged approved criteria.
[Testing instructions and your-own-design workflow](docs/testing.md).

## What runs today

| Engine | Supported checks |
| --- | --- |
| Python rules engine + Pint | Requirement criteria, sourced quantities, power budgets, thermal estimates and conservative bounds |
| OpenCASCADE through OCP | STEP solid validity, rigid assembly transforms, interference volume, clearance and envelope containment |
| ngspice | Bounded resistive DC operating points, loss, KCL/power-balance qualification and sequential circuit-to-thermal evaluation |
| OpenCV + Pillow | Controlled PNG regression and foreground mismatch in approved visible regions |
| Playwright + Chromium + Three.js | Async four-view GLB/STEP capture with source/settings/browser hashes |
| SQL worker / optional Temporal | Durable jobs, idempotency, renewable leases and fenced acceptance |

Independent checks run concurrently. Native CAD/circuit work runs in separate Linux
processes with CPU, memory, file, wall-time and network restrictions. An optional
per-task Docker executor adds a pinned read-only image and job-only filesystem mount. Shared solver
results are deduplicated within a job.

Reviewer and design-agent credentials are separate. Approved baselines freeze criteria,
scenario expectations and visual references. An agent cannot weaken that baseline to
make a revision pass. Reviews remain separate from engineering measurements.

## Start locally

Python 3.12+:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
export VERIFICATION_AUTH_MODE=local
metaforge-verification api
```

In another terminal with the same environment and working directory:

```bash
metaforge-verification worker
```

Open `/docs` for the API and `/review` for the evidence workbench. Local mode is an
explicit single-tenant development mode; keep the API on loopback.

Run the analytical demonstration:

```bash
python examples/demo.py
```

For native engineering on Linux, install `ngspice` and `libseccomp2` using your OS
package manager, then:

```bash
pip install -r requirements-engineering.lock
pip install --no-deps -e .
python examples/digital_demo.py
```

The digital demonstration creates STEP enclosure/PCB fixtures, detects a seeded
collision, corrects the PCB placement and verifies the next revision against the
same reviewer-approved baseline. It also runs a 12 V divider, thermal bounds,
behavior scenarios and a controlled image-region comparison. These are synthetic
qualification fixtures, not a complete manufactured lamp design.

## API workflow

1. Upload artifacts directly with `POST /v1/artifacts`, or use the bounded
   `/v1/artifact-uploads` → content → finalize lifecycle.
2. Register immutable twin revisions, requirement sets and scenario suites.
3. Use `POST /v1/verification-plans` to inspect executable checks, input gaps and limits.
4. Approve an immutable `/v1/baselines` snapshot with reviewer credentials.
5. Submit `POST /v1/verifications` with an `Idempotency-Key`. Read status, cursor events,
   paginated findings, coverage and JSON/Markdown reports.
6. Submit a new revision through `/reverify`, inspect `/comparison`, and retain reviews
   and externally supplied physical evidence separately.

Embedded requests remain supported for existing clients. Reference-based submissions
require explicit `accept_gaps: true` when the resolved plan has missing evidence.
Use `VERIFICATION_REQUIRE_APPROVED_BASELINE=true` to require service-managed approval.

See [the published OpenAPI](docs/openapi.json), [architecture](docs/architecture.md)
and [implementation status against the draft](docs/implementation-status.md).

## Identity and storage

The default auth mode fails closed without configured tokens:

```bash
export VERIFICATION_AUTH_MODE=tokens
export VERIFICATION_TOKENS='{"replace-with-a-long-random-agent-token":"organization-a"}'
export VERIFICATION_REVIEW_TOKENS='{"replace-with-a-different-reviewer-token":"organization-a"}'
export VERIFICATION_REQUIRE_APPROVED_BASELINE=true
```

These are bootstrap credentials. Keep real values out of source control. A cloud
identity adapter can inject the public `Authenticator` protocol; the core does not
import Supabase or a proprietary package. Tokens determine tenant identity.

SQLite and tenant-scoped local artifacts are the development defaults. PostgreSQL
and S3-compatible storage are available through configuration:

```bash
pip install -e '.[postgres,s3]'
export VERIFICATION_DATABASE_URL='postgresql+psycopg://...'
export VERIFICATION_ARTIFACT_BACKEND=s3
export VERIFICATION_S3_BUCKET='your-private-bucket'
# Optional operator-controlled compatible endpoint:
# export VERIFICATION_S3_ENDPOINT_URL='https://...'
```

Use workload credentials and private bucket policies in a deployment. Local artifact
storage requires a shared volume across workers. `compose.yaml` is a local
PostgreSQL/API/worker stack. `Dockerfile.engineering` supplies native engineering
packages; qualify the built image digest before promotion.

## Operations and extensions

- Cursor events and webhook deliveries use a transactional SQL outbox. Destinations
  are operator-approved per tenant; reviewers register/disable them through the API.
  Deliveries are signed, retried and deduplicated.
- `GET /v1/usage` reports accepted completions and accepted-attempt wall time. No
  charging or production pricing policy is configured.
- The scheduler enforces global/per-tenant running-job ceilings and dispatches the
  least recently served eligible tenant. These are job ceilings, not aggregate
  distributed CPU/memory reservations.
- Optional Temporal uses the same immutable submissions and fenced worker. Run
  `temporal-worker` plus `temporal-dispatch` instead of the SQL polling worker.
- Trusted adapters register on `metaforge.verification.checks`. Enable reviewed
  installed plugins with `VERIFICATION_LOAD_PLUGINS=true`. Uploaded scripts and
  arbitrary customer netlists are not executed.

[Deployment and migration notes](docs/operations.md) explain configuration, limits,
webhook verification, cancellation and remaining qualification work.

## Development

```bash
pip install -r requirements-dev.lock
pip install --no-deps -e .
ruff check .
ruff format --check .
pytest -q
python scripts/export_openapi.py --check
python scripts/smoke_http.py
python -m build
```

For controlled capture:

```bash
cd visual-capture
npm ci --ignore-scripts
npx playwright install --with-deps chromium
node capture.mjs /absolute/path/model.glb ./output r1
```

CI runs SQLite/PostgreSQL suites, native-engine fixtures, the digital correction loop,
controlled rendering, browser workbench checks and package/container builds.

## Release scope

Version 0.3 expands the executable open core. The **full drafted product remains
unfinished**; the [109-requirement register](docs/implementation-status.md) records
implemented, partial and open obligations.

Current exclusions include qualified KiCad ERC/DRC, semiconductor/transient circuit
models, general wall-thickness/DFM, compiled firmware/HIL, calibrated physical
inspection, semantic VLM review, cross-revision evidence
cache reuse and production qualification for 100 organizations. EVT/DVT/PVT requests
retain an explicit evidence gap. A named digital-profile pass is not certification
or manufacturing approval.

## Open core

Apache-2.0. Public: contracts, rules, adapters, evidence, local execution, review and
provider-neutral interfaces. Cloud extensions: account provisioning, subscriptions,
commercial policies and managed operations. The private cloud repository remains
outside this package. External engine/model licenses require their own review.
