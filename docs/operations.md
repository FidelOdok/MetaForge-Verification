# Operation and qualification

## Configuration

| Variable | Meaning / default |
| --- | --- |
| VERIFICATION_AUTH_MODE | tokens by default; explicit local only for loopback development |
| VERIFICATION_TOKENS | JSON map of submitter tokens to tenant IDs |
| VERIFICATION_REVIEW_TOKENS | Disjoint JSON map of reviewer tokens to tenant IDs |
| VERIFICATION_REQUIRE_APPROVED_BASELINE | true requires service-managed baseline IDs |
| VERIFICATION_DATABASE_URL | SQLite locally; PostgreSQL for coordinated workers |
| VERIFICATION_ARTIFACT_BACKEND | local or s3 |
| VERIFICATION_ARTIFACT_ROOT | Shared tenant-scoped local root |
| VERIFICATION_S3_BUCKET | Private bucket for s3 backend |
| VERIFICATION_S3_ENDPOINT_URL | Optional operator-controlled compatible endpoint |
| VERIFICATION_S3_REGION | us-east-1 unless configured |
| VERIFICATION_MAX_RUNNING_JOBS | 2 shared running-job slots by default |
| VERIFICATION_MAX_RUNNING_PER_TENANT | 1 by default |
| VERIFICATION_NGSPICE_EXECUTABLE | Optional absolute operator-configured binary path |
| VERIFICATION_WORKER_ENGINES | Optional comma-separated ocp,ngspice,opencv declaration for separate worker images |
| VERIFICATION_WEBHOOK_DESTINATIONS | JSON map tenant → HTTPS url and secret |

The native check executor permits four check threads per job. Shared CAD/circuit
futures reduce duplicate solves; distinct jobs still need deployment-wide CPU/memory
capacity. Default running-job limits are conservative development settings, not the
specification's qualified ten-task engineering pool. Do not increase limits without
measuring aggregate memory, task mix and queue delay.

The API can run without native packages. For separate engineering images, configure
`VERIFICATION_WORKER_ENGINES=ocp,ngspice,opencv` only when those workers are actually
installed and enabled. Otherwise planning detects tools in its local runtime. An
operator declaration is not a live worker heartbeat or qualification certificate;
missing dependencies at execution still produce a visible gap.

Native subprocesses deny network calls but still see the worker filesystem. Keep
host secrets/designs from other tenants outside their mounts. Production per-job
filesystem/container isolation and credential scoping remain release blockers.

## Events, webhooks and usage

Configure destinations on API and worker processes using the same secret source:

```json
{"organization-a":{"url":"https://customer.example/verification-events","secret":"replace-with-at-least-32-random-characters"}}
```

No real secret belongs in this repository. Destinations are operator-managed; there
is no customer URL registration endpoint yet. Run `metaforge-verification webhooks`
as a separate dispatcher. It sends JSON events with:

- `X-Verification-Event-ID`: stable event identity; deduplicate it.
- `X-Verification-Timestamp`: Unix seconds for the delivery attempt.
- `X-Verification-Signature`: `sha256=` followed by HMAC-SHA256 over
  `timestamp + "." + exact_request_body` using the shared secret.

Verify signatures with constant-time comparison, enforce a timestamp tolerance and
record event IDs transactionally at the receiver. Delivery is at least once; retries
reuse event identity. Redirects are rejected. Eight unsuccessful attempts produce a
`dead_letter` record; inspect/reconcile these through operator SQL procedures until a
retry-management interface is qualified. Changing destination configuration affects
pending deliveries and requires operator change control.

Events are an outbox tied to authoritative state. The usage ledger records one
accepted report and accepted-attempt wall time; it does not charge money, account for
all retry infrastructure spend or claim measured CPU utilization. Canceled and failed
attempts do not create billable completions. Retention/deletion/expiry enforcement and
complete access audit are not delivered.

## Upgrade from 0.1

Stop new admission, drain/stop workers, back up SQL and artifact storage together,
then deploy matching API/worker versions. Version 0.2 adds SQL tables and fields only
inside JSON contracts; table creation happens at startup. Legacy idempotency replays
normalize their stored request before comparison. Legacy design fingerprints are
upgraded only when the recorded complete design matches the new submission.

This is not an Alembic migration/replay-qualified rolling-upgrade system. Existing
accepted reports keep their original evidence; deploys do not rewrite history. Test
migration and restore on a copy before touching pilot data. No production RPO/RTO or
SLA is established by this implementation.

## Qualification status

Executed locally: Python and native numerical/security fixtures, an actual
ngspice-42 divider and electrical/thermal path, OCP STEP collision/correction,
OpenCV masks, real HTTP API/separate-worker smoke and browser workbench checks.

The environment cannot run Docker here. PostgreSQL and matched Playwright-browser
qualification run in GitHub CI; do not infer a pass until the corresponding run
completes. Live S3 policies/credentials, Temporal failover/replay, signed engineering
images, representative 100-organization load, restoration drills and actual pilot
hardware models remain separate acceptance work.

Optional adapter dependencies do not certify a tool for every input. The release
support matrix must remain bounded to executed fixtures and reviewed product models.
