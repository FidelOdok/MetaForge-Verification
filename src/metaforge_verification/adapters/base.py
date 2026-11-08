"""Operator-installed extension seam. Customer requests never execute arbitrary code."""

from dataclasses import dataclass
from typing import Protocol

from metaforge_verification.contracts import Evidence, Quantity, VerificationRequest


class CheckUnavailable(Exception):
    """Required input or a qualified adapter is not available."""


class InvalidEvidence(Exception):
    """Inputs/results cannot support a sound conclusion."""


class ArtifactReader(Protocol):
    def read(self, artifact_id: str) -> bytes: ...


@dataclass
class CheckResult:
    value: Quantity
    evidence: Evidence


class Check(Protocol):
    rule_id: str
    module: str
    fidelity: str

    def run(self, request: VerificationRequest, artifacts: ArtifactReader) -> CheckResult: ...
