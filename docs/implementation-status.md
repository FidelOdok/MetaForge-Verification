# Implementation status against the drafted verification API

Baseline: architecture/product specification v2.3, 8 November 2026. This register describes code and executed synthetic fixtures, not product certification or production qualification. The full drafted product is **not complete**. A status here never overrides the published support envelope.

Implemented means the named bounded capability has code and a corresponding test/demo. Partial means a material acceptance obligation remains. Open means no delivered implementation of that obligation. Full-product integrations need their own representative models, fixtures and deployment qualification.

| Requirement | Status | Evidence / remaining acceptance |
| --- | --- | --- |
| FR-IN-001 | Partial | Partial manifests, missing-input plans, and STEP support; KiCad intake remains. |
| FR-IN-002 | Partial | Artifact hashes and immutable design/resources implemented; broader component semantics remain. |
| FR-IN-003 | Partial | Process limits/network denial and optional pinned per-job Docker isolation; production qualification remains. |
| FR-IN-004 | Partial | Original hashes and generated SPICE netlist/raw output retained; general conversion lineage remains. |
| FR-IN-005 | Open | Not delivered; retain as an explicit release obligation. |
| FR-IN-006 | Partial | Units, duplicate IDs and conflicting numeric constraints checked; general semantic conflicts remain. |
| FR-IN-007 | Partial | Source references preserved; independent component-data review connectors remain. |
| FR-IN-008 | Open | Not delivered; retain as an explicit release obligation. |
| FR-PL-001 | Partial | Profiles/inputs/capabilities resolved; general DAG/risk policy remains. |
| FR-PL-002 | Implemented | Deterministic engine; no LLM dependency in acceptance/execution. |
| FR-PL-003 | Partial | Named profiles, rule versions, timestamps and actual native tool versions; image qualification remains. |
| FR-PL-004 | Partial | Separate reviewer tokens and immutable baseline snapshots; controlled waivers remain. |
| FR-PL-005 | Partial | Bounded job admission/process limits; transactional monetary reservations remain. |
| FR-MOD-001 | Partial | STEP units/transforms and typed circuit values; schematic/CAD/preview mapping qualification remains. |
| FR-MOD-002 | Partial | Sourced thermal inputs/bounds; broader simulation setup qualification remains. |
| FR-MOD-003 | Partial | Frozen reviewer-approved criteria/scenarios/references; independent product fixture approval remains. |
| FR-MOD-004 | Open | Not delivered; retain as an explicit release obligation. |
| FR-GEO-001 | Partial | OCP STEP validity, one-solid envelope and transforms; actual pilot assemblies remain to qualify. |
| FR-GEO-002 | Partial | Exact-solid interference/distance and closest-point locations; broader assemblies/tolerance analysis remain. |
| FR-GEO-003 | Open | Not delivered; retain as an explicit release obligation. |
| FR-GEO-004 | Open | Not delivered; retain as an explicit release obligation. |
| FR-ELEC-001 | Open | Not delivered; retain as an explicit release obligation. |
| FR-ELEC-002 | Partial | Power budgets; interface/datasheet qualification remains. |
| FR-ELEC-003 | Implemented | Bounded ideal resistive DC operating point; test_engineering.py and digital_demo.py. |
| FR-ELEC-004 | Open | Not delivered; retain as an explicit release obligation. |
| FR-THERM-001 | Implemented | Reference analytical temperature checks; test_engine.py. |
| FR-THERM-002 | Implemented | Conservative upper bounds; test_engineering.py. |
| FR-THERM-003 | Open | Not delivered; retain as an explicit release obligation. |
| FR-BEH-001 | Implemented | Deterministic lamp state model; test_engine.py. |
| FR-BEH-002 | Implemented | Model-only evidence labels retained in reports. |
| FR-FW-001 | Open | Not delivered; retain as an explicit release obligation. |
| FR-FW-002 | Open | Not delivered; retain as an explicit release obligation. |
| FR-SCN-001 | Partial | Integrated profile enforces three scenario families and thermal bounds; broader product fixtures remain. |
| FR-SCN-002 | Partial | Requirement/scenario/family matrix and mandatory-family gaps; broader configuration products remain. |
| FR-SCN-003 | Partial | Missing models block checks; broader model mapping qualification remains. |
| FR-SCN-004 | Open | Not delivered; retain as an explicit release obligation. |
| FR-SCN-005 | Open | Not delivered; retain as an explicit release obligation. |
| FR-SYS-001 | Open | Not delivered; retain as an explicit release obligation. |
| FR-SYS-002 | Partial | Explicit circuit-loss-to-thermal dependency and source evidence; other domain mappings remain. |
| FR-SYS-003 | Open | Not delivered; retain as an explicit release obligation. |
| FR-UNC-001 | Partial | Conservative thermal upper bounds and geometric tolerance; general source-quality/tolerance policy remains. |
| FR-UNC-002 | Open | Not delivered; retain as an explicit release obligation. |
| FR-PHY-001 | Partial | Timestamped external-evidence registration and review records; instrument/calibration qualification remains. |
| FR-PHY-002 | Open | Not delivered; retain as an explicit release obligation. |
| FR-MFG-001 | Open | Not delivered; retain as an explicit release obligation. |
| FR-GATE-001 | Implemented | Named concept profiles; EVT/DVT/PVT requests retain an evidence gap. |
| FR-GATE-002 | Open | Not delivered; retain as an explicit release obligation. |
| FR-REV-001 | Partial | Dependency invalidation comparison; complete domain dependency graph remains. |
| FR-REV-002 | Partial | Within-job native result deduplication; cross-revision measurement cache reuse remains. |
| FR-REV-003 | Implemented | Structured criteria/measurements/evidence; immutable design snapshots. |
| FR-REV-004 | Implemented | Comparison classifies resolved, persistent, regression, removed and unassessed findings. |
| FR-EV-001 | Partial | Input hashes, tool/rule versions and native output retained; image digest/scenario qualification remains. |
| FR-EV-002 | Implemented | Persistent execution state separated from report gate. |
| FR-EV-003 | Implemented | Four distinct outcomes; native failures never pass. |
| FR-EV-004 | Partial | JSON/Markdown, coverage and review UI; retention/expiry semantics remain. |
| FR-UI-001 | Partial | Review workbench shows causes, measurements, assumptions and locations as evidence JSON; richer annotation views remain. |
| FR-UI-002 | Open | Not delivered; retain as an explicit release obligation. |
| FR-API-001 | Implemented | Versioned OpenAPI, async submission, capabilities, status, cancellation and reports. |
| FR-API-002 | Partial | Idempotency, cursor events, signed retries and reviewer-managed approved endpoint registration/disable; broader self-service destinations remain. |
| FR-EX-001 | Partial | SQL jobs, event outbox, fencing and optional Temporal; durable per-check DAG remains. |
| FR-EX-002 | Partial | Independent checks overlap and circuit/thermal uses a shared dependency barrier; durable multi-stage DAG remains. |
| FR-EX-003 | Partial | Global/tenant job ceilings and native resource limits; aggregate CPU/memory/spend reservations remain. |
| FR-TEN-001 | Partial | Tenant isolation and 100 SQL namespaces; membership and representative hosted load qualification remain. |
| FR-TEN-002 | Partial | Least-recently-dispatched tenant fairness and running ceilings; separate resource-class queues remain. |
| FR-BILL-001 | Partial | Deduplicated accepted reports and accepted-attempt wall time; no charging or full spend ledger. |
| FR-OPS-001 | Partial | Append-only execution/approval/review events; complete access audit/retention/delete remains. |
| FR-EXT-001 | Open | Not delivered; retain as an explicit release obligation. |
| NFR-001 | Partial | Tenant-scoped jobs/resources/reviews/S3 prefixes/events; hosted adversarial qualification remains. |
| NFR-002 | Partial | Separate worker; real HTTP smoke; 100-tenant latency benchmark remains. |
| NFR-003 | Open | Not delivered; retain as an explicit release obligation. |
| NFR-004 | Partial | Idempotency, late-result fencing and ledger deduplication tested; deployment fault drills remain. |
| NFR-005 | Partial | Native numerical fixtures and actual solver versions; full supported-profile corpus remains. |
| NFR-006 | Open | Not delivered; retain as an explicit release obligation. |
| NFR-007 | Partial | Native limits, seccomp egress denial and per-job Docker boundary; deployed adversarial qualification remains. |
| NFR-008 | Partial | Frozen Python/Node dependencies; signed/pinned engineering image promotion remains. |
| NFR-009 | Partial | No inherited customer credentials in native process; broad operational redaction audit remains. |
| NFR-010 | Partial | Job/attempt events and native failure reasons; full metrics/traces/dashboard remain. |
| NFR-011 | Partial | Admission 429 and running ceilings; deployed exhaustion/aggregate-budget benchmark remains. |
| NFR-012 | Partial | Legacy idempotency normalization and additive tables; deployment migration/replay policy remains. |
| NFR-013 | Partial | Workbench preserves gaps/fidelity; integrated simplified view remains. |
| NFR-014 | Open | Not delivered; retain as an explicit release obligation. |
| FR-VIS-001 | Partial | Async service capture binds source/revision/settings/assets; broader origin/physical attestation remains. |
| FR-VIS-002 | Partial | Managed baselines freeze references independently of candidates; external authority qualification remains. |
| FR-VIS-003 | Partial | Automatic source-bound four-view capture with nonempty frames; semantic feature visibility qualification remains. |
| FR-VIS-004 | Partial | Measured pixel/mask results separate from human reviews; no VLM/aesthetic assertions. |
| FR-VIS-005 | Partial | Approved-region foreground mismatch with region/component details; representative defect benchmark remains. |
| FR-VIS-006 | Partial | Visual findings cannot override CAD failures; general CAD/render semantic mapping remains. |
| FR-VIS-007 | Open | Not delivered; retain as an explicit release obligation. |
| FR-VIS-008 | Partial | Controlled context identity and stale-render rejection; broader registration and lighting normalization remain. |
| FR-VIS-009 | Open | Not delivered; retain as an explicit release obligation. |
| FR-VIS-010 | Open | Not delivered; retain as an explicit release obligation. |
| FR-VIS-011 | Partial | Authenticated previews and rendered-difference overlays; broader semantic annotations remain. |
| FR-SEC-001 | Open | Not delivered; retain as an explicit release obligation. |
| FR-VIS-012 | Partial | Reviewer-managed references/regions; authority classes and intent decomposition remain. |
| FR-VIS-013 | Partial | Approved-region mask conformity only; semantic checklist/shape interpretation remains. |
| FR-VIS-014 | Partial | Revision finding comparison and changed-criteria disclosure; authorized feature-change workflow remains. |
| FR-VIS-015 | Partial | Service tessellation preserves source STEP hashes, transforms, component names and mm-to-m conversion; broader format mapping remains. |
| FR-VIS-016 | Partial | Independent append-only reviewer decisions; subjective mandatory review-policy gating remains. |
| FR-VIS-017 | Partial | Criteria, regions, component IDs, evidence method and review labels; richer source-view mapping remains. |
| FR-CICD-001 | Open | Not delivered; retain as an explicit release obligation. |
| FR-CICD-002 | Open | Not delivered; retain as an explicit release obligation. |
| FR-CICD-003 | Open | Not delivered; retain as an explicit release obligation. |
| FR-CICD-004 | Open | Not delivered; retain as an explicit release obligation. |
| FR-CICD-005 | Open | Not delivered; retain as an explicit release obligation. |
| FR-CICD-006 | Open | Not delivered; retain as an explicit release obligation. |
| FR-CICD-007 | Open | Not delivered; retain as an explicit release obligation. |
| FR-CICD-008 | Open | Not delivered; retain as an explicit release obligation. |
| FR-CICD-009 | Open | Not delivered; retain as an explicit release obligation. |
| FR-CICD-010 | Open | Not delivered; retain as an explicit release obligation. |
