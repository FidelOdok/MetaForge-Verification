"""Typed boundaries for native engineering tools; no uploaded scripts or commands."""

from metaforge_verification.adapters.base import CheckResult, CheckUnavailable, InvalidEvidence
from metaforge_verification.adapters.isolated import engineering_task
from metaforge_verification.contracts import Evidence, Quantity, fingerprint


class CADCheck:
    module = "domain"
    fidelity = "F1"
    metric = "invalid_solids"
    unit = "dimensionless"

    def run(self, request, artifacts):
        if request.cad is None:
            raise CheckUnavailable("Two STEP components with assembly transforms are required")
        assembly = request.cad.model_dump(mode="json")
        execute = getattr(artifacts, "engineering", engineering_task)
        result = execute(
            {"engine": "cad", "assembly": assembly},
            [artifacts.read(c.step.artifact_id) for c in request.cad.components],
        )
        if self.metric != "invalid_solids" and result["invalid_solids"]:
            raise InvalidEvidence("Invalid solids block authoritative CAD measurements")
        value = result.get(self.metric)
        if value is None:
            raise InvalidEvidence("CAD solver did not produce the required measurement")
        if self.metric == "distance_mm":
            if result["intersection_volume_mm3"] > request.cad.tolerance_mm**3:
                raise InvalidEvidence("Intersecting solids: inspect CAD interference finding")
            # Publish a conservative lower bound under the declared geometric tolerance.
            value = max(0, value - request.cad.tolerance_mm)
        measurement = Quantity(value=value, unit=self.unit)
        fp = fingerprint(request)
        return CheckResult(
            measurement,
            Evidence(
                evidence_id=f"ev-{self.rule_id}-{fp[:16]}",
                method=self.rule_id,
                fidelity=self.fidelity,
                input_fingerprint=fp,
                measurements={self.metric: measurement},
                source_refs=[c.step.sha256 for c in request.cad.components],
                tool_version=result["tool_version"],
                details=result,
                assumptions=[
                    "STEP units: mm. Apply Rx/Ry/Rz rotations, then assembly translation.",
                    f"Tolerance: {request.cad.tolerance_mm} mm; two single solids.",
                    "Distance/intersection only; no wall, DFM or material qualification.",
                    "Separation alone proves neither containment nor component identity.",
                ],
            ),
        )


class CADValidity(CADCheck):
    rule_id = "geometry.step_validity"


class CADInterference(CADCheck):
    rule_id = "geometry.step_interference"
    metric = "intersection_volume_mm3"
    unit = "mm^3"


class CADClearance(CADCheck):
    rule_id = "geometry.step_clearance"
    metric = "distance_mm"
    unit = "mm"


class CADEnvelopeContainment(CADCheck):
    rule_id = "geometry.step_envelope_containment"
    metric = "envelope_margin_mm"
    unit = "mm"

    def run(self, request, artifacts):
        if request.cad is None or request.cad.enclosure_id is None:
            raise CheckUnavailable("A mapped enclosure component ID is required")
        result = CADValidity().run(request, artifacts)
        if result.value.value:
            raise InvalidEvidence("Invalid solids block containment measurements")
        components = result.evidence.details["components"]
        outer = next(
            c["bbox_mm"] for c in components if c["component_id"] == request.cad.enclosure_id
        )
        inner = next(
            c["bbox_mm"] for c in components if c["component_id"] != request.cad.enclosure_id
        )
        margin = min(min(inner[a] - outer[a], outer[a + 3] - inner[a + 3]) for a in range(3))
        value = Quantity(value=margin - request.cad.tolerance_mm, unit="mm")
        ev = result.evidence.model_copy(
            update={
                "evidence_id": f"ev-{self.rule_id}-{fingerprint(request)[:16]}",
                "method": self.rule_id,
                "measurements": {"envelope_margin_mm": value},
                "assumptions": result.evidence.assumptions
                + [
                    "Envelope containment only; also require interference/clearance checks.",
                    "Concave openings and assembly insertion paths are not qualified.",
                ],
            }
        )
        return CheckResult(value, ev)


class DCOperatingPoint:
    rule_id = "electrical.dc_output_voltage"
    module = "domain"
    fidelity = "F3"
    metric = "output_voltage_v"
    unit = "V"

    def run(self, request, artifacts):
        if request.circuit is None:
            raise CheckUnavailable("A sourced resistive DC circuit model is required")
        execute = getattr(artifacts, "engineering", engineering_task)
        result = execute(
            {
                "engine": "circuit",
                "circuit": request.circuit.model_dump(mode="json"),
            }
        )
        measurement = Quantity(value=result[self.metric], unit=self.unit)
        fp = fingerprint(request)
        return CheckResult(
            measurement,
            Evidence(
                evidence_id=f"ev-{self.rule_id}-{fp[:16]}",
                method=self.rule_id,
                fidelity=self.fidelity,
                input_fingerprint=fp,
                measurements={self.metric: measurement},
                source_refs=[e.source_ref for e in request.circuit.elements],
                tool_version=result["tool_version"],
                details=result,
                assumptions=[
                    "Ideal DC sources up to 60 V; resistors from 1 mOhm to 1 GOhm.",
                    "No semiconductor, LED driver, transient, parasitic or firmware model.",
                    "Caller-supplied model; mapping to the schematic is unqualified.",
                    "Warnings, singular matrices and nonconvergence block acceptance.",
                ],
            ),
        )


class CircuitDissipation(DCOperatingPoint):
    rule_id = "electrical.resistor_dissipation"
    metric = "resistor_dissipation_w"
    unit = "W"


class CircuitThermal:
    rule_id = "system.circuit_thermal_temperature"
    module = "system"
    fidelity = "F2"

    def run(self, request, artifacts):
        from metaforge_verification.adapters.analytical import fact

        # This is an explicit dependency barrier: no thermal result before accepted DC evidence.
        electrical = CircuitDissipation().run(request, artifacts)
        ambient = fact(request, "ambient_temperature", "degC")
        resistance = fact(request, "thermal_resistance", "K/W")
        if ambient < -273.15 or resistance < 0:
            raise InvalidEvidence("Invalid thermal boundary conditions")
        value = Quantity(value=ambient + electrical.value.value * resistance, unit="degC")
        fp = fingerprint(request)
        return CheckResult(
            value,
            Evidence(
                evidence_id=f"ev-{self.rule_id}-{fp[:16]}",
                method=self.rule_id,
                fidelity=self.fidelity,
                input_fingerprint=fp,
                measurements={"estimated_temperature": value, "circuit_loss": electrical.value},
                source_refs=electrical.evidence.source_refs
                + [
                    request.twin.facts["ambient_temperature"].source_ref,
                    request.twin.facts["thermal_resistance"].source_ref,
                ],
                details={
                    "source_evidence": electrical.evidence.model_dump(mode="json"),
                    "dependency": "electrical.resistor_dissipation",
                },
                assumptions=[
                    "All modeled resistor loss heats one steady-state thermal node.",
                    "No unmodeled LED/driver loss, spatial or time-dependent coupling.",
                ],
            ),
        )
