# Verification architecture

Any client submits a digital twin to the independent API. The public core owns
planning, criteria evaluation, evidence and execution semantics. It does not edit
CAD, schematics, firmware, approved requirements or manufacturing instructions.

## Intelligence and acceptance

The execution engine is Python. Pydantic validates contracts; the profile registry
selects mandatory obligations; Pint checks units; deterministic criteria evaluate
measurements. An optional external LLM may propose requirements or explain findings,
but cannot approve its own criteria, overwrite a baseline or serve as a physical oracle.

The four modules remain artifact, domain, system and scenario. They share one report
and coverage model. Fidelity labels describe the method: STEP/static visual F1,
analytical thermal F2, native DC simulation F3. No F5 physical adapter is qualified.

## Execution and dependencies

HTTP submission durably writes an immutable request and queued job. SQL polling or
Temporal claims jobs with renewable leases and fencing tokens. Only the owning,
unexpired attempt can commit a report and its usage record. Cancellation revokes
ownership; native subprocesses also observe cancellation/lease loss and are terminated.
Trusted arbitrary plugin code is not forcibly preempted.

The scheduler serializes claims, enforces global/per-tenant running-job ceilings and
prioritizes the least-recently-dispatched eligible tenant. Independent checks use a
four-thread bounded executor. CAD and circuit tasks have shared in-flight futures so
multiple criteria do not rerun the same native solve. Circuit-to-thermal evaluation
waits for accepted electrical loss evidence and retains its source result.

This is not yet a durable per-check DAG, separate resource-class scheduler or an
aggregate vCPU/memory/spend reservation system. Running-job limits must be sized
against the declared native-process envelope and actual deployment resources.

## Native-engine boundary

STEP blobs and typed resistor/source models enter a fresh temporary workspace.
The child receives explicit runtime paths and no inherited customer/cloud credentials.
Before native import/execution it enables Linux seccomp network denial and resource
limits: 30 CPU seconds, 3 GiB virtual address space, 2 MiB per output file and 128 open
files. The parent enforces a 45-second wall limit and kills the process group on
cancellation, timeout or cleanup. ngspice also has a 20-second subprocess deadline.

These controls do not provide filesystem isolation from the host. Deploy native
workers non-root with restricted mounts, a read-only image, no service credentials,
container/cgroup aggregate limits and a qualified image digest. The API image does
not need CAD libraries. Do not treat a parser process as a complete security sandbox.

## Engineering support

- STEP: source units normalized to mm, two single-solid components, rigid Rx/Ry/Rz
  transforms followed by translation, validity, exact-solid common volume, closest
  points, conservative clearance and optional bounding-envelope containment.
- Circuit: ideal independent DC voltage sources up to 60 V, resistors from 1 mOhm to
  1 GOhm, one operating point; warnings, nonconvergence, source-constraint residuals,
  KCL and power-balance failures block acceptance. Generated netlist and raw output
  are retained in evidence with actual tool version.
- Thermal: sourced nominal and conservative-upper-bound single-node steady state;
  circuit-derived heating is a separately named system check.
- Behavior: declared lamp state-machine events and independent expected outputs;
  not compiled firmware, timing, protocol traffic or hardware execution.
- Visual: controlled PNG differences and OpenCV foreground masks within approved
  visible regions. Occlusion, blank references, incompatible contexts and stale
  revisions cannot produce a supported feature pass. These are not semantic identity,
  dimension, material or aesthetic measurements.

The standalone Playwright/Three.js capture CLI generates four views and a manifest.
Automatic service scheduling of that CLI and CAD-to-preview semantic correspondence
remain open. No render is silently represented as authoritative B-rep measurement.

## Authority and immutable inputs

Submitter tokens and reviewer tokens are distinct. An external identity extension can
provide equivalent principals. Managed baselines freeze required criteria, scenario
expectations, thermal bounds and visual references. Only reviewers create/revoke them;
submissions cannot change their snapshot. Baselines are checked at admission and
worker startup. Revocation blocks new work; existing accepted reports remain historical
records. Revocation during a running solve is not a retroactive report rewrite.

Revision fingerprints include CAD, circuit, behavior model and visual candidate as
well as the twin manifest. Requirements and scenario suites have independent immutable
resource revisions. Comparison computes conservative invalidation and finding changes;
measurements are currently recomputed across jobs, not reused from a cross-revision cache.

Reviews are append-only and tied to the report fingerprint. They cannot override a
failed engineering measurement. Uploaded physical evidence is timestamped external
material with review/calibration metadata; upload is not instrument qualification.

## Storage and events

SQLite is for development; PostgreSQL is the shared SQL authority. Local artifact
paths are tenant-hashed/content-addressed. The optional S3 implementation uses the
same tenant hash and digest namespace, bounded reads and hash verification. Credentials
come from the operator runtime. Tenant-controlled fetch URLs and storage paths are
never accepted as artifact references.

State transitions, approvals, resources and reviews produce append-only cursor events.
Configured webhook destinations get transactional delivery intents; retries have fenced
leases, HMAC signatures and bounded attempts. Consumers deduplicate event IDs. Usage
records share the report acceptance transaction, so a late/replayed attempt cannot
create a second completion. This is metering, not a full billing/spend platform.

## Release boundaries

Both named profiles are concept/digital evidence profiles. EVT/DVT/PVT obligations,
production capacity, deployment recovery, actual pilot design fixtures and broader
adapters need independent qualification. See implementation-status.md and operations.md.
