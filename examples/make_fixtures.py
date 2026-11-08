"""Synthetic engineering fixture; thresholds are illustrative project criteria."""

import json
from pathlib import Path


def lamp_request():
    def fact(value, unit):
        return {
            "quantity": {"value": value, "unit": unit},
            "source_ref": "fixture:independent-lamp-baseline-v1",
            "provenance": "declared",
        }

    def requirement(id, rule, operator, value, unit, fidelity="F2"):
        return {
            "id": id,
            "description": id,
            "rule_id": rule,
            "required": True,
            "required_fidelity": fidelity,
            "criterion": {"operator": operator, "threshold": {"value": value, "unit": unit}},
        }

    return {
        "schema_version": "1.0",
        "profile_id": "smart-lamp-analytical-v1",
        "approval_ref": "fixture:approved-lamp-requirements-v1",
        "twin": {
            "twin_id": "lamp",
            "revision_id": "r1",
            "artifacts": [],
            "facts": {
                "supply_power": fact(10, "W"),
                "load_power": fact(12, "W"),
                "ambient_temperature": fact(25, "degC"),
                "dissipated_power": fact(2, "W"),
                "thermal_resistance": fact(5, "kelvin / watt"),
                "cavity_x": fact(52, "mm"),
                "cavity_y": fact(32, "mm"),
                "cavity_z": fact(12, "mm"),
                "pcb_x": fact(50, "mm"),
                "pcb_y": fact(30, "mm"),
                "pcb_z": fact(10, "mm"),
            },
        },
        "requirements": [
            requirement("POWER", "device.power_budget", "<=", 0.8, "dimensionless"),
            requirement("THERMAL", "device.thermal_estimate", "<=", 45, "degC"),
            requirement("FIT", "geometry.declared_box_fit", ">=", 1, "mm"),
            requirement("BEHAVIOR", "scenario.device_behavior", "==", 0, "dimensionless"),
            requirement("VISUAL", "visual.pixel_difference", "<=", 0, "dimensionless", "F1"),
        ],
        "behavior_model": {
            "model_version": "lamp-behavior-1",
            "offline_policy": "hold",
            "boot_output": 0,
            "sensor_fault_output": 0,
        },
        "scenarios": [
            {
                "id": "operation-and-recovery",
                "requirement_id": "BEHAVIOR",
                "steps": [
                    {"event": "on", "expected_output": 100, "expected_connected": True},
                    {
                        "event": "dim",
                        "value": 40,
                        "expected_output": 40,
                        "expected_connected": True,
                    },
                    {"event": "disconnect", "expected_output": 40, "expected_connected": False},
                    {"event": "reconnect", "expected_output": 40, "expected_connected": True},
                    {"event": "sensor_fault", "expected_output": 0, "expected_connected": True},
                    {"event": "power_cycle", "expected_output": 0, "expected_connected": True},
                ],
            }
        ],
    }


if __name__ == "__main__":
    Path(__file__).with_name("lamp.json").write_text(json.dumps(lamp_request(), indent=2) + "\n")
