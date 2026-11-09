"""Versioned public contracts; unknown fields and nonfinite values are rejected."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    NOT_ASSESSED = "not_assessed"


class Quantity(Contract):
    value: float
    unit: str = Field(min_length=1, max_length=50)

    @field_validator("unit")
    @classmethod
    def allowlisted_units(cls, value):
        if value not in {
            "W",
            "watt",
            "mW",
            "kW",
            "mm",
            "cm",
            "m",
            "degC",
            "kelvin",
            "K",
            "kelvin / watt",
            "K/W",
            "dimensionless",
            "percent",
            "V",
            "A",
            "mm^3",
            "ohm",
        }:
            raise ValueError("Unit is not supported by the v1 analytical profile")
        return value


class Fact(Contract):
    quantity: Quantity
    source_ref: str = Field(min_length=1, max_length=500)
    provenance: Literal["declared", "external_measurement"] = "declared"


class ArtifactRef(Contract):
    artifact_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Twin(Contract):
    twin_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    revision_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    facts: dict[str, Fact] = Field(default_factory=dict, max_length=100)
    artifacts: list[ArtifactRef] = Field(default_factory=list, max_length=20)


class Criterion(Contract):
    operator: Literal["<=", ">=", "=="]
    threshold: Quantity


class Requirement(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    description: str = Field(min_length=1, max_length=2000)
    rule_id: str = Field(min_length=1, max_length=100)
    required: bool = True
    required_fidelity: Literal["F0", "F1", "F2", "F3", "F4", "F5"] = "F2"
    criterion: Criterion


class DeviceModel(Contract):
    """Declared reference behavior, not compiled firmware or real network traffic."""

    model_version: Literal["lamp-behavior-1"] = "lamp-behavior-1"
    offline_policy: Literal["hold", "off"] = "hold"
    boot_output: float = Field(default=0, ge=0, le=100)
    sensor_fault_output: float = Field(default=0, ge=0, le=100)


class Step(Contract):
    event: Literal["on", "off", "dim", "disconnect", "reconnect", "power_cycle", "sensor_fault"]
    value: float | None = Field(default=None, ge=0, le=100)
    expected_output: float = Field(ge=0, le=100)
    expected_connected: bool

    @model_validator(mode="after")
    def validate_value(self):
        if (self.event == "dim") != (self.value is not None):
            raise ValueError("Only dim events must include value")
        return self


class Scenario(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    requirement_id: str = Field(min_length=1, max_length=100)
    steps: list[Step] = Field(min_length=1, max_length=100)
    family: Literal["normal", "fault", "recovery"] = "normal"

    @model_validator(mode="after")
    def meaningful_family(self):
        events = {s.event for s in self.steps}
        if self.family == "fault" and not events & {"sensor_fault", "power_cycle", "disconnect"}:
            raise ValueError("Fault scenario requires a fault stimulus")
        if self.family == "recovery" and not (
            {"disconnect", "reconnect"} <= events or "power_cycle" in events
        ):
            raise ValueError("Recovery scenario requires recovery stimuli")
        return self


class VisualComparison(Contract):
    reference: ArtifactRef
    candidate: ArtifactRef
    candidate_revision_id: str
    reference_context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approval_ref: str = Field(min_length=1, max_length=500)


class CADComponent(Contract):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    step: ArtifactRef
    translation_mm: tuple[float, float, float] = (0, 0, 0)
    rotation_deg: tuple[float, float, float] = (0, 0, 0)

    @field_validator("translation_mm", "rotation_deg")
    @classmethod
    def bounded_transform(cls, values):
        if any(abs(v) > 100_000 for v in values):
            raise ValueError("Transform exceeds supported envelope")
        return values


class CADAssembly(Contract):
    components: list[CADComponent] = Field(min_length=2, max_length=2)
    tolerance_mm: float = Field(default=0.001, gt=0, le=0.1)
    enclosure_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def unique_components(self):
        if len({c.id for c in self.components}) != len(self.components):
            raise ValueError("CAD component IDs must be unique")
        if self.enclosure_id is not None and self.enclosure_id not in {
            c.id for c in self.components
        }:
            raise ValueError("Enclosure ID must resolve to a component")
        return self


class CircuitElement(Contract):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
    kind: Literal["resistor", "voltage_source"]
    positive: str = Field(pattern=r"^(0|[a-z][a-z0-9_]{0,31})$")
    negative: str = Field(pattern=r"^(0|[a-z][a-z0-9_]{0,31})$")
    value: Quantity
    source_ref: str = Field(min_length=1, max_length=500)


class DCCircuit(Contract):
    model_version: Literal["resistive-dc-1"] = "resistive-dc-1"
    elements: list[CircuitElement] = Field(min_length=2, max_length=100)
    output_node: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")

    @model_validator(mode="after")
    def validate_circuit(self):
        if len({e.id.lower() for e in self.elements}) != len(self.elements):
            raise ValueError("Circuit element IDs must be unique ignoring case")
        nodes = {n for e in self.elements for n in (e.positive, e.negative)}
        if "0" not in nodes or self.output_node not in nodes:
            raise ValueError("Circuit requires ground and a connected output node")
        if not any(e.kind == "voltage_source" for e in self.elements):
            raise ValueError("Circuit requires an independent voltage source")
        return self


class ThermalBounds(Contract):
    ambient_max: Fact
    dissipation_max: Fact
    resistance_max: Fact


class VisualRegion(Contract):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    # Integer pixel coordinates [left, top, right, bottom] in the controlled capture.
    box: tuple[int, int, int, int]
    visible: bool
    component_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def valid_box(self):
        x0, y0, x1, y1 = self.box
        if not (0 <= x0 < x1 <= 4096 and 0 <= y0 < y1 <= 4096):
            raise ValueError("Invalid pixel region")
        return self


class VisualFeatures(Contract):
    regions: list[VisualRegion] = Field(min_length=1, max_length=20)
    background_rgb: tuple[int, int, int] = (255, 255, 255)
    background_tolerance: int = Field(default=20, ge=0, le=100)

    @model_validator(mode="after")
    def valid_colors(self):
        if any(c < 0 or c > 255 for c in self.background_rgb):
            raise ValueError("Invalid background color")
        if len({r.id for r in self.regions}) != len(self.regions):
            raise ValueError("Visual region IDs must be unique")
        return self


class CaptureInput(Contract):
    model: ArtifactRef | None = None
    from_cad: bool = False

    @model_validator(mode="after")
    def one_source(self):
        if (self.model is not None) == self.from_cad:
            raise ValueError("Capture requires exactly one GLB or CAD source")
        return self


class RenderReference(Contract):
    manifest: ArtifactRef
    images: dict[Literal["front", "side", "top", "iso"], ArtifactRef]

    @model_validator(mode="after")
    def complete_views(self):
        if set(self.images) != {"front", "side", "top", "iso"}:
            raise ValueError("Reference requires front, side, top and iso images")
        return self


class RenderCreate(Contract):
    twin_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    revision_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    source: CaptureInput
    cad: CADAssembly | None = None

    @model_validator(mode="after")
    def cad_source(self):
        if self.source.from_cad and self.cad is None:
            raise ValueError("CAD capture requires an assembly")
        return self


class VerificationRequest(Contract):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: Literal[
        "smart-lamp-analytical-v1",
        "smart-lamp-digital-v1",
        "smart-lamp-integrated-v1",
        "artifact-render-v1",
    ] = "smart-lamp-analytical-v1"
    approval_ref: str = Field(min_length=1, max_length=500)
    lifecycle_stage: Literal["concept", "EVT", "DVT", "PVT"] = "concept"
    twin: Twin
    requirements: list[Requirement] = Field(min_length=1, max_length=100)
    behavior_model: DeviceModel | None = None
    scenarios: list[Scenario] = Field(default_factory=list, max_length=20)
    visual: VisualComparison | None = None
    cad: CADAssembly | None = None
    circuit: DCCircuit | None = None
    thermal_bounds: ThermalBounds | None = None
    visual_features: VisualFeatures | None = None
    baseline_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    previous_verification_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    capture: CaptureInput | None = None
    render_reference: RenderReference | None = None

    @model_validator(mode="after")
    def unique_references(self):
        if self.capture and self.capture.from_cad and self.cad is None:
            raise ValueError("CAD capture requires an assembly")
        if self.profile_id == "artifact-render-v1" and (
            self.capture is None
            or len(self.requirements) != 1
            or self.requirements[0].rule_id != "visual.render_capture"
        ):
            raise ValueError("Artifact render profile permits only its capture obligation")
        ids = [r.id for r in self.requirements]
        if len(set(ids)) != len(ids):
            raise ValueError("Requirement IDs must be unique")
        if len({s.id for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario IDs must be unique")
        for scenario in self.scenarios:
            if scenario.requirement_id not in ids:
                raise ValueError("Scenario references unknown requirement")
        return self


class BaselineCreate(Contract):
    verification: VerificationRequest
    rationale: str = Field(min_length=1, max_length=2000)


class ReviewCreate(Contract):
    requirement_id: str = Field(min_length=1, max_length=100)
    decision: Literal["accepted", "rejected", "needs_evidence"]
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[ArtifactRef] = Field(default_factory=list, max_length=10)


class UploadCreate(Contract):
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class WebhookEndpointCreate(Contract):
    destination: Literal["default"] = "default"


class RequirementSetCreate(Contract):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    revision_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    profile_id: Literal[
        "smart-lamp-analytical-v1", "smart-lamp-digital-v1", "smart-lamp-integrated-v1"
    ]
    requirements: list[Requirement] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_requirements(self):
        if len({r.id for r in self.requirements}) != len(self.requirements):
            raise ValueError("Requirement IDs must be unique")
        return self


class ScenarioSuiteCreate(Contract):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    revision_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    scenarios: list[Scenario] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_scenarios(self):
        if len({s.id for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario IDs must be unique")
        return self


class VerificationByReference(Contract):
    twin_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    twin_revision_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    requirements_revision_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    scenario_suite_revision_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    profile_revision_id: Literal[
        "smart-lamp-analytical-v1", "smart-lamp-digital-v1", "smart-lamp-integrated-v1"
    ]
    baseline_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    accept_gaps: bool = False


class PhysicalEvidenceCreate(Contract):
    artifact: ArtifactRef
    configuration_ref: str = Field(min_length=1, max_length=500)
    origin: str = Field(min_length=1, max_length=500)
    captured_at: str = Field(min_length=1, max_length=100)
    instrument_id: str | None = Field(default=None, max_length=200)
    calibration_ref: str | None = Field(default=None, max_length=500)
    notes: str = Field(default="", max_length=2000)

    @field_validator("captured_at")
    @classmethod
    def aware_timestamp(cls, value):
        from datetime import datetime

        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError("Capture timestamp must include timezone")
        return value


def baseline_snapshot(request: VerificationRequest):
    visual = request.visual
    return {
        "profile_id": request.profile_id,
        "lifecycle_stage": request.lifecycle_stage,
        "requirements": [r.model_dump(mode="json") for r in request.requirements],
        "scenarios": [s.model_dump(mode="json") for s in request.scenarios],
        "thermal_bounds": request.thermal_bounds.model_dump(mode="json")
        if request.thermal_bounds
        else None,
        "visual_features": request.visual_features.model_dump(mode="json")
        if request.visual_features
        else None,
        "visual_reference": {
            "reference": visual.reference.model_dump(mode="json"),
            "context": visual.reference_context_sha256,
            "approval_ref": visual.approval_ref,
        }
        if visual
        else None,
        "render_reference": request.render_reference.model_dump(mode="json")
        if request.render_reference
        else None,
    }


def revision_snapshot(request: VerificationRequest):
    return {
        "twin": request.twin.model_dump(mode="json"),
        "cad": request.cad.model_dump(mode="json") if request.cad else None,
        "circuit": request.circuit.model_dump(mode="json") if request.circuit else None,
        "behavior_model": request.behavior_model.model_dump(mode="json")
        if request.behavior_model
        else None,
        "capture": request.capture.model_dump(mode="json") if request.capture else None,
        "visual_candidate": {
            "candidate": request.visual.candidate.model_dump(mode="json"),
            "context": request.visual.candidate_context_sha256,
            "revision": request.visual.candidate_revision_id,
        }
        if request.visual
        else None,
    }


class Evidence(Contract):
    evidence_id: str
    method: str
    fidelity: str
    input_fingerprint: str
    measurements: dict[str, Quantity] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)
    tool_version: str = "metaforge-verification/0.3.0"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Finding(Contract):
    requirement_id: str
    rule_id: str
    rule_version: str = "1.0.0"
    module: Literal["artifact", "domain", "system", "scenario"]
    outcome: Outcome
    reason: str
    achieved_fidelity: str | None = None
    measurement: Quantity | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    criterion: Criterion | None = None
    component_ids: list[str] = Field(default_factory=list)
    suggestion: str | None = None


class Report(Contract):
    schema_version: Literal["1.0"] = "1.0"
    verification_id: str
    profile_id: str
    twin_id: str
    revision_id: str
    input_fingerprint: str
    gate_decision: Literal["pass", "fail", "incomplete"]
    findings: list[Finding]
    evidence: list[Evidence]
    coverage: dict
    limitations: list[str]
    lifecycle_stage: str = "concept"
    approval: dict = Field(default_factory=dict)


def fingerprint(value: BaseModel | dict) -> str:
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
