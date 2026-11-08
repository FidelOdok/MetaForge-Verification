"""Analytical checks on declared, sourced facts. These do not inspect CAD/circuit files."""

import pint

from metaforge_verification.adapters.base import CheckResult, CheckUnavailable, InvalidEvidence
from metaforge_verification.contracts import Evidence, Quantity, VerificationRequest, fingerprint

UNITS = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)


def convert(quantity: Quantity, unit: str) -> float:
    try:
        value = float(UNITS.Quantity(quantity.value, quantity.unit).to(unit).magnitude)
    except (pint.errors.PintError, ValueError, TypeError, OverflowError) as exc:
        raise InvalidEvidence(f"Incompatible or invalid units: {quantity.unit} -> {unit}") from exc
    import math

    if not math.isfinite(value):
        raise InvalidEvidence("Nonfinite converted quantity")
    return value


def fact(request: VerificationRequest, name: str, unit: str) -> float:
    if name not in request.twin.facts:
        raise CheckUnavailable(f"Missing sourced fact: {name}")
    return convert(request.twin.facts[name].quantity, unit)


def evidence(request, method, measurements, names, assumptions):
    fp = fingerprint(request)
    return Evidence(
        evidence_id=f"ev-{method}-{fp[:16]}",
        method=method,
        fidelity="F2",
        input_fingerprint=fp,
        measurements=measurements,
        source_refs=[request.twin.facts[n].source_ref for n in names],
        assumptions=assumptions,
        details={"input_provenance": {n: request.twin.facts[n].provenance for n in names}},
    )


class PowerBudget:
    rule_id = "device.power_budget"
    module = "domain"
    fidelity = "F2"

    def run(self, request, artifacts):
        supply = fact(request, "supply_power", "watt")
        load = fact(request, "load_power", "watt")
        if supply <= 0 or load < 0:
            raise InvalidEvidence("Supply must be positive and load nonnegative")
        value = Quantity(value=load / supply, unit="dimensionless")
        ev = evidence(
            request,
            self.rule_id,
            {
                "supply": Quantity(value=supply, unit="W"),
                "load": Quantity(value=load, unit="W"),
                "utilization": value,
            },
            ["supply_power", "load_power"],
            ["Declared power values; no transient, circuit or physical supply validation."],
        )
        return CheckResult(value, ev)


class ThermalEstimate:
    rule_id = "device.thermal_estimate"
    module = "domain"
    fidelity = "F2"

    def run(self, request, artifacts):
        ambient = fact(request, "ambient_temperature", "degC")
        loss = fact(request, "dissipated_power", "watt")
        resistance = fact(request, "thermal_resistance", "kelvin / watt")
        if loss < 0 or resistance < 0 or ambient < -273.15:
            raise InvalidEvidence("Invalid thermal operating parameters")
        value = Quantity(value=ambient + loss * resistance, unit="degC")
        ev = evidence(
            request,
            self.rule_id,
            {"estimated_temperature": value},
            ["ambient_temperature", "dissipated_power", "thermal_resistance"],
            [
                "Single-node steady-state estimate with declared effective thermal resistance.",
                "No spatial/transient thermal analysis or physical protection validation.",
            ],
        )
        return CheckResult(value, ev)


class EnclosureFit:
    rule_id = "geometry.declared_box_fit"
    module = "domain"
    fidelity = "F2"

    def run(self, request, artifacts):
        names = [f"{kind}_{axis}" for kind in ("cavity", "pcb") for axis in ("x", "y", "z")]
        values = {n: fact(request, n, "mm") for n in names}
        if any(v <= 0 for v in values.values()):
            raise InvalidEvidence("All declared box dimensions must be positive")
        clearance = min((values[f"cavity_{a}"] - values[f"pcb_{a}"]) / 2 for a in ("x", "y", "z"))
        value = Quantity(value=clearance, unit="mm")
        ev = evidence(
            request,
            self.rule_id,
            {"minimum_centered_clearance": value},
            names,
            [
                "Centered, axis-aligned declared bounding boxes; not a CAD measurement.",
                "Ignores internal obstacles, mounting features and manufacturing tolerances.",
            ],
        )
        return CheckResult(value, ev)
