"""Executable declared lamp behavior with independent, submitted expectations."""

from metaforge_verification.adapters.base import CheckResult, CheckUnavailable
from metaforge_verification.contracts import Evidence, Quantity, fingerprint


class BehaviorScenarios:
    rule_id = "scenario.device_behavior"
    module = "scenario"
    fidelity = "F2"

    def run(self, request, artifacts):
        model = request.behavior_model
        if model is None or not request.scenarios:
            raise CheckUnavailable("A behavior model and at least one linked scenario are required")
        scenarios = [
            s
            for s in request.scenarios
            if any(
                r.id == s.requirement_id and r.rule_id == self.rule_id for r in request.requirements
            )
        ]
        if not scenarios:
            raise CheckUnavailable("No scenario maps to a behavior requirement")
        failures, traces = 0, []
        for scenario in scenarios:
            output, connected = model.boot_output, True
            for index, step in enumerate(scenario.steps):
                match step.event:
                    case "on":
                        output = 100
                    case "off":
                        output = 0
                    case "dim":
                        output = step.value
                    case "disconnect":
                        connected = False
                        if model.offline_policy == "off":
                            output = 0
                    case "reconnect":
                        connected = True
                    case "power_cycle":
                        output, connected = model.boot_output, True
                    case "sensor_fault":
                        output = model.sensor_fault_output
                passed = output == step.expected_output and connected == step.expected_connected
                failures += not passed
                traces.append(
                    {
                        "scenario_id": scenario.id,
                        "step": index,
                        "output": output,
                        "connected": connected,
                        "matches": passed,
                    }
                )
        fp = fingerprint(request)
        ev = Evidence(
            evidence_id=f"ev-behavior-{fp[:16]}",
            method=self.rule_id,
            fidelity="F2",
            input_fingerprint=fp,
            source_refs=[request.approval_ref],
            assumptions=[
                "Declared behavior model only; not compiled firmware, network or hardware.",
                "Events are discrete logical inputs; no physical timing is inferred.",
            ],
            details={"traces": traces, "model_version": model.model_version},
        )
        return CheckResult(Quantity(value=failures, unit="dimensionless"), ev)
