# Executed verification results — 0.3.0 candidate

9 November 2026. These results qualify the stated synthetic cases only.

| Check | Observed result |
| --- | --- |
| Python suite with engineering extras | 66 passed |
| Ruff lint / formatting | Passed |
| Actual HTTP API + separate worker | Durable submission → report passed |
| Analytical correction demonstration | Failing revision → corrected profile pass |
| Native digital correction demonstration | Actual STEP collision → corrected placement; 14 approved requirements evaluated |
| Native CAD | OCP 7.8.1.1; solid volume, separation, contact and intersection fixtures |
| Circuit | ngspice-42; 12 V / equal-resistor divider → 6 V and 0.072 W |
| Circuit → thermal | 25 °C + 0.072 W × 5 K/W → 25.36 °C |
| Visual | OpenCV 4.11.0; missing-region, occluded-region, RGB-only change and stale-context fixtures |
| Native resource/security | Seccomp socket denial, hard deadline/cancel and malformed STEP fixtures passed |
| Governance | Agent approval denied; changed baseline criteria rejected; revocation, scoped reviews and immutable model tests passed |
| Usage/outbox | Duplicate acceptance yields one ledger record; signed delivery and retry/backoff fixtures passed |
| Review workbench | Real Chromium 153.0.8010.0 report/review interaction passed; engineering failure retained |
| 100-tenant HTTP smoke | 100 completions; 100 denied cross-tenant reads; 100 accepted usage records |
| Integrated HTTP service | STEP → named-component GLB → four-view capture → approval → failing revision → corrected 13-requirement pass |
| Integrated review | Four authenticated previews, difference annotations and CAD failures displayed in Chromium |
| Scenario gate | Normal/fault/recovery required for the integrated profile; missing families block completion |
| Package | Wheel and source distribution built; workbench assets included |

The [100-tenant result](qualification/100-tenant-smoke.json) contains workload,
environment and measured latency. It is lightweight loopback/SQLite traffic with two
workers, not a heavy-engine, distributed or production benchmark. Completion timing
includes observation delay. Do not generalize its numbers to a hosting SLA.

The environment's Playwright browser download returned truncated ZIPs. Local UI
qualification used a registry-distributed Chromium 153 binary with its actual version
recorded. GitHub CI installs Playwright's matching browser and must pass independently.
No baseline equivalence between those browser versions is asserted.

S3 unit tests exercise namespace/digest logic; live bucket policy/network/credentials
are not qualified. PostgreSQL, container build and matched-browser suites run in CI;
check their actual run results before promotion. Docker is unavailable locally.
Temporal sandbox preparation passes; live workflow failover/replay is not qualified.

The complete 109-requirement draft remains unfinished: see implementation-status.md.
In particular, actual pilot electrical models, KiCad, general manufacturing rules,
compiled firmware/HIL, calibrated physical evidence, semantic visual review and
production isolation/recovery require further implementation and independent approval.
There is no physical validation, certification or manufacturing-release claim.
