# Initial implementation verification

Date: 8 November 2026. This records local checks, not deployed service qualification.

| Check | Observed outcome |
| --- | --- |
| Python tests | 30 passed: API/auth, tenant scoping, immutable revisions, idempotency/concurrency, cancellation/fencing, analytical units/results, scenarios, visual integrity and Temporal sandbox preparation |
| JavaScript tests | 2 passed: capture asset allowlist and byte hashing |
| Lint/format | Ruff checks and formatting passed |
| OpenAPI | Generated schema consistency check passed |
| Real process smoke | HTTP API accepted a persistent job; separate worker completed it and report was retrieved |
| Lamp revision demonstration | Known over-budget revision failed; corrected analytical revision passed all five profile obligations with limitations retained |
| Browser capture | Four GLB views captured; PNG hashes checked; front image contained visible geometry |
| Capture environment | Playwright 1.58.2, Three.js 0.172.0, Chromium 153.0.8010.0 via explicit operator executable path, software rendering |
| Python distribution | Source distribution and wheel built |

The standard Playwright browser download returned invalid/truncated archives in this
execution environment. Browser execution was checked with a separately supplied Chromium
binary; its version is recorded in capture context. CI installs Playwright's matching
browser and must qualify that environment independently. No cross-version pixel-equivalence
claim is made. Local controlled-render images are test intermediates, not shipped baselines.

The Temporal workflow prepared successfully in the SDK sandbox. A live Temporal server,
workflow replay/failover and worker deployment versioning were not exercised. PostgreSQL
coverage is configured as a CI job, but no live PostgreSQL server or Docker daemon was
available locally. The container configuration was not built/run here; GitHub CI is
configured to build it. Frozen dependencies were installed for the local Python checks.
A Starlette TestClient/httpx deprecation warning remains upstream; the tests passed.

This implementation is an initial open-core vertical slice. It is not the complete
smart-device MVP from the broader product specification, a production 100-customer
qualification, a live MetaForge integration, physical validation or certification.
API currently accepts a captured PNG comparison; the separate capture CLI is explicitly
invoked by an operator/integration rather than automatically scheduled by the API.
