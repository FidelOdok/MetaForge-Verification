# Test the integrated Verification API

The test package runs an authenticated API, a separate durable worker, OpenCASCADE,
ngspice, OpenCV and controlled Playwright/Chromium rendering. It includes a real HTTP
correction loop and a browser review page. It is a local digital-workflow test package;
it does not complete the full product's firmware, physical, manufacturing or hosting
qualification requirements.

## Docker: recommended, including on Windows

Use Docker with Linux containers. Until the implementation PR is merged, check out
`feat/engineering-validation-engines` after cloning the repository.

```bash
git switch feat/engineering-validation-engines
docker compose -f compose.testing.yaml up --build --wait
docker compose -f compose.testing.yaml run --rm demo
```

Open:

- API / Swagger: http://127.0.0.1:8086/docs
- Evidence workbench: http://127.0.0.1:8086/review

The demo prints failed/corrected verification IDs and a review link. Paste either ID
into the workbench to inspect findings, numerical criteria, source-bound previews,
red difference regions, sources, assumptions and scenario coverage.

These public credentials are deliberately restricted to the loopback test setup:

| Role | Bearer token |
| --- | --- |
| Submitter / design agent | local-testing-agent-token |
| Reviewer / baseline approval | local-testing-reviewer-token |

Tokens are entered into Swagger's Authorization header or the workbench token field.
The workbench keeps tokens in page memory and does not put them in URLs/storage.
This Compose file publishes only loopback ingress, uses an internal test network and
retains test data in named volumes. Use distinct operator-managed credentials and
qualified isolation before any external deployment.

Stop services while keeping test data:

```bash
docker compose -f compose.testing.yaml down
```

Reset this test stack, deleting its test database, artifacts and saved demo results:

```bash
docker compose -f compose.testing.yaml down --volumes
```

## What the demo actually executes

1. Generate independent synthetic STEP fixtures: an open enclosure and PCB solid.
2. Upload their actual bytes through the API; verify server-computed digests.
3. Submit an asynchronous `/v1/renders` job for the known reference assembly.
4. The worker validates/transforms STEP, tessellates it into a named-component GLB,
   converts millimetres to glTF metres, and generates four nonempty controlled views.
5. Approve fixed numerical/scenario/reference criteria using the separate reviewer token.
6. Submit a displaced PCB revision. CAD detects interference/envelope violations;
   automatic rendering also detects differences from the approved four-view reference.
7. Run the 12 V resistive divider, source/KCL/power-balance quality checks, circuit loss,
   sequential loss-to-thermal calculation and conservative thermal-bound check.
8. Run mandatory normal, fault and recovery behavior-model families.
9. Correct the PCB placement, create a new revision and reverify against unchanged criteria.
10. Read a passing **named digital-profile** report, events, usage and revision comparison.

The reference is generated independently from the deliberately defective candidate.
The correct 6 V divider result and thermal thresholds are fixed fixture expectations.
The demo never modifies approved criteria to obtain its corrected pass. The geometry,
electronics and scenarios are numerical fixtures, not a qualified commercial lamp.

## API routes for rendering

`POST /v1/renders` accepts an `Idempotency-Key` and one source:

- `source.model`: an uploaded self-contained GLB artifact reference; or
- `source.from_cad: true` plus a two-component `cad` assembly.

The request also includes `twin_id` and `revision_id`. It returns the same asynchronous
job/status contract as verification. `GET /v1/renders/{verification_id}` exposes the
capture when ready: manifest, front/side/top/iso PNG artifact references, actual tool
versions, rendering context, component/source lineage and tessellation settings.
Retrieve PNG/GLB artifacts through authenticated `GET /v1/artifacts/{artifact_id}`.

Asset-capture jobs use `artifact-render-v1`, a distinct immutable capture namespace.
They do not require an engineering approval baseline and cannot establish engineering
or lifecycle readiness. Engineering jobs still require reviewer approval in this setup.

For automatic comparison during engineering verification, use
`profile_id: smart-lamp-integrated-v1`, `capture: {"from_cad": true}` and an approved
`render_reference` containing the reference manifest and four PNG references. Missing
normal/fault/recovery families make this profile incomplete. The older analytical and
digital profiles remain available with their published boundaries.

## Test your own two-part design

Start with the generated HTTP demo and inspect its requests in `examples/http_demo.py`
and `examples/integrated_fixture.py`. The same API accepts your artifacts and approved
criteria. For a saved request/example, run the demo client against the running stack:

```bash
python examples/http_demo.py --base-url http://127.0.0.1:8086 --output data/testing/latest.json
```

The client needs Python 3.12 and the engineering dependencies to generate its STEP
fixtures; the containerized demo already has them. The saved JSON includes
`corrected_request`, which shows exact artifact/baseline/scenario references. Use new
twin/revision IDs for design changes and new idempotency keys for new submissions.
Approve changed criteria/references separately with the reviewer credential.

Current CAD support is two single-solid STEP components, with explicit transforms
and a mapped enclosure ID. Geometry and typed circuit models must remain within the
published support envelope. External GLB resource URIs and required extensions are
rejected. All four generated views must contain observable model pixels. Uploaded
meshes do not become authoritative CAD; use STEP for dimension/fit conclusions.

## Native Linux development

Install Python 3.12+, Node 22, ngspice and libseccomp2. Then:

```bash
pip install -r requirements-engineering.lock
pip install --no-deps -e .
cd visual-capture
npm ci --ignore-scripts
npx playwright install --with-deps chromium
cd ..
python scripts/run_test_stack.py
```

In another terminal:

```bash
python examples/http_demo.py
```

The helper binds only 127.0.0.1, uses explicit test credentials, persists under
`data/testing`, and opts into local process rendering. `VERIFICATION_CHROMIUM_EXECUTABLE`
and `VERIFICATION_NGSPICE_EXECUTABLE` accept qualified absolute operator paths when
needed. `PLAYWRIGHT_BROWSERS_PATH` selects an explicit installed browser cache.

For an automated run that starts and stops its own API/worker processes:

```bash
python scripts/smoke_integrated.py --ui
```

This performs actual HTTP and browser interactions. CI additionally builds and runs
the Docker Compose package. The process-mode helper is a development convenience;
production filesystem isolation uses the pinned per-task executor or another qualified
execution backend. Firmware/HIL, calibrated inspection, general DFM, semantic VLM
review, commercial billing and production qualification remain outside this test package.
