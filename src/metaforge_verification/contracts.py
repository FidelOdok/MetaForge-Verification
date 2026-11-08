"""Versioned public contracts; unknown fields and nonfinite values are rejected."""

from __future__ import annotations

import hashlib
import json
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


class VisualComparison(Contract):
    reference: ArtifactRef
    candidate: ArtifactRef
    candidate_revision_id: str
    reference_context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approval_ref: str = Field(min_length=1, max_length=500)


class VerificationRequest(Contract):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: Literal["smart-lamp-analytical-v1"] = "smart-lamp-analytical-v1"
    approval_ref: str = Field(min_length=1, max_length=500)
    twin: Twin
    requirements: list[Requirement] = Field(min_length=1, max_length=100)
    behavior_model: DeviceModel | None = None
    scenarios: list[Scenario] = Field(default_factory=list, max_length=20)
    visual: VisualComparison | None = None

    @model_validator(mode="after")
    def unique_references(self):
        ids = [r.id for r in self.requirements]
        if len(set(ids)) != len(ids):
            raise ValueError("Requirement IDs must be unique")
        if len({s.id for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario IDs must be unique")
        for scenario in self.scenarios:
            if scenario.requirement_id not in ids:
                raise ValueError("Scenario references unknown requirement")
        return self


class Evidence(Contract):
    evidence_id: str
    method: str
    fidelity: str
    input_fingerprint: str
    measurements: dict[str, Quantity] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)
    tool_version: str = "metaforge-verification/0.1.0"


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


def fingerprint(value: BaseModel | dict) -> str:
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
