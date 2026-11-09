"""Independent synthetic geometry/circuit/scenario fixtures for service integration testing."""

from pathlib import Path

from make_fixtures import lamp_request


def build(upload, directory, twin_id):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    def step(shape, name):
        path = Path(directory) / name
        writer = STEPControl_Writer()
        writer.Transfer(shape, STEPControl_AsIs)
        writer.Write(str(path))
        return upload(path.read_bytes())

    case = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeBox(60, 40, 16).Shape(),
        BRepPrimAPI_MakeBox(gp_Pnt(2, 2, 2), 56, 36, 20).Shape(),
    ).Shape()
    case_ref = step(case, "enclosure.step")
    pcb_ref = step(BRepPrimAPI_MakeBox(50, 30, 2).Shape(), "pcb.step")
    payload = lamp_request()
    payload["profile_id"] = "smart-lamp-integrated-v1"
    payload["twin"]["twin_id"] = twin_id
    payload["twin"]["facts"]["load_power"]["quantity"]["value"] = 6
    payload["requirements"] = [
        r for r in payload["requirements"] if r["id"] not in {"FIT", "VISUAL"}
    ]

    def require(id, rule, value, unit="dimensionless", op="<=", fidelity="F1"):
        payload["requirements"].append(
            {
                "id": id,
                "description": id,
                "rule_id": rule,
                "required_fidelity": fidelity,
                "criterion": {"operator": op, "threshold": {"value": value, "unit": unit}},
            }
        )

    require("CAD_VALID", "geometry.step_validity", 0)
    require("CAD_INTERFERENCE", "geometry.step_interference", 0, "mm^3")
    require("CAD_CLEARANCE", "geometry.step_clearance", 1.5, "mm", ">=")
    require("CAD_ENVELOPE", "geometry.step_envelope_containment", 1, "mm", ">=")
    require("VOLTAGE_MIN", "electrical.dc_output_voltage", 5.999, "V", ">=", "F3")
    require("VOLTAGE_MAX", "electrical.dc_output_voltage", 6.001, "V", "<=", "F3")
    require("CIRCUIT_LOSS", "electrical.resistor_dissipation", 0.073, "W", "<=", "F3")
    require("COUPLED_THERMAL", "system.circuit_thermal_temperature", 26, "degC", "<=", "F2")
    require("THERMAL_BOUND", "device.thermal_worst_case", 45, "degC", "<=", "F2")
    require("RENDER_REGRESSION", "visual.render_regression", 0)
    payload["cad"] = {
        "enclosure_id": "case",
        "components": [
            {"id": "case", "step": case_ref},
            {"id": "pcb", "step": pcb_ref, "translation_mm": [5, 5, 4]},
        ],
    }
    payload["capture"] = {"from_cad": True}
    payload["circuit"] = {
        "output_node": "out",
        "elements": [
            {
                "id": "supply",
                "kind": "voltage_source",
                "positive": "supply",
                "negative": "0",
                "value": {"value": 12, "unit": "V"},
                "source_ref": "fixture:12V",
            },
            {
                "id": "upper",
                "kind": "resistor",
                "positive": "supply",
                "negative": "out",
                "value": {"value": 1000, "unit": "ohm"},
                "source_ref": "fixture:1kohm",
            },
            {
                "id": "lower",
                "kind": "resistor",
                "positive": "out",
                "negative": "0",
                "value": {"value": 1000, "unit": "ohm"},
                "source_ref": "fixture:1kohm",
            },
        ],
    }

    def fact(value, unit):
        return {"quantity": {"value": value, "unit": unit}, "source_ref": "fixture:reviewed-bound"}

    payload["thermal_bounds"] = {
        "ambient_max": fact(30, "degC"),
        "dissipation_max": fact(2, "W"),
        "resistance_max": fact(6, "K/W"),
    }

    def event(name, output, connected=True, **extra):
        return {"event": name, "expected_output": output, "expected_connected": connected, **extra}

    payload["scenarios"] = [
        {
            "id": "normal",
            "family": "normal",
            "requirement_id": "BEHAVIOR",
            "steps": [event("on", 100), event("dim", 40, value=40), event("off", 0)],
        },
        {
            "id": "fault",
            "family": "fault",
            "requirement_id": "BEHAVIOR",
            "steps": [event("on", 100), event("sensor_fault", 0)],
        },
        {
            "id": "recovery",
            "family": "recovery",
            "requirement_id": "BEHAVIOR",
            "steps": [
                event("dim", 40, value=40),
                event("disconnect", 40, False),
                event("reconnect", 40),
                event("power_cycle", 0),
            ],
        },
    ]
    return payload
