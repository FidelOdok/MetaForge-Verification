"""HTTP-level synthetic digital fixture: seeded STEP collision -> corrected revision.

Requires .[engineering] and ngspice. These shapes/circuits are independent numerical
fixtures, not a qualified lamp electrical/thermal/manufacturing design.
"""

import io
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from make_fixtures import lamp_request
from PIL import Image, ImageDraw

from metaforge_verification.api import create_app
from metaforge_verification.config import Settings
from metaforge_verification.worker import run_once


def main():
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        settings = Settings(
            database_url=f"sqlite:///{root / 'jobs.db'}",
            artifact_root=root / "artifacts",
            tokens={"demo-submitter-long-token": "demo"},
            review_tokens={"demo-reviewer-long-token": "demo"},
            require_approved_baseline=True,
        )
        app = create_app(settings)
        headers = {"Authorization": "Bearer demo-submitter-long-token", "Idempotency-Key": "r1"}
        reviewer = {"Authorization": "Bearer demo-reviewer-long-token"}
        with TestClient(app) as client:

            def upload(data):
                result = client.post("/v1/artifacts", content=data, headers=headers).json()
                return {"artifact_id": result["artifact_id"], "sha256": result["sha256"]}

            def step(shape, filename):
                path = root / filename
                writer = STEPControl_Writer()
                writer.Transfer(shape, STEPControl_AsIs)
                writer.Write(str(path))
                return upload(path.read_bytes())

            enclosure = BRepAlgoAPI_Cut(
                BRepPrimAPI_MakeBox(60, 40, 16).Shape(),
                BRepPrimAPI_MakeBox(gp_Pnt(2, 2, 2), 56, 36, 20).Shape(),
            ).Shape()
            refs = [
                step(enclosure, "case.step"),
                step(BRepPrimAPI_MakeBox(50, 30, 2).Shape(), "pcb.step"),
            ]
            image = Image.new("RGB", (40, 40), "white")
            ImageDraw.Draw(image).rectangle((10, 10, 19, 19), fill="black")
            data = io.BytesIO()
            image.save(data, format="PNG")
            png = upload(data.getvalue())
            payload = lamp_request()
            payload["profile_id"] = "smart-lamp-digital-v1"
            payload["twin"]["facts"]["load_power"]["quantity"]["value"] = 6
            payload["requirements"] = [r for r in payload["requirements"] if r["id"] != "FIT"]

            def require(id, rule, value, unit="dimensionless", operator="<=", fidelity="F1"):
                payload["requirements"].append(
                    {
                        "id": id,
                        "description": id,
                        "rule_id": rule,
                        "required_fidelity": fidelity,
                        "criterion": {
                            "operator": operator,
                            "threshold": {"value": value, "unit": unit},
                        },
                    }
                )

            require("CAD_VALID", "geometry.step_validity", 0)
            require("CAD_INTERFERENCE", "geometry.step_interference", 0, "mm^3")
            require("CAD_CLEARANCE", "geometry.step_clearance", 1.5, "mm", ">=")
            require("CAD_ENVELOPE", "geometry.step_envelope_containment", 1, "mm", ">=")
            require("CIRCUIT_MIN", "electrical.dc_output_voltage", 5.999, "V", ">=", "F3")
            require("CIRCUIT_MAX", "electrical.dc_output_voltage", 6.001, "V", "<=", "F3")
            require("CIRCUIT_LOSS", "electrical.resistor_dissipation", 0.073, "W", "<=", "F3")
            require("COUPLED_THERMAL", "system.circuit_thermal_temperature", 26, "degC", "<=", "F2")
            require("THERMAL_BOUND", "device.thermal_worst_case", 45, "degC", "<=", "F2")
            require("VISIBLE_REGION", "visual.region_silhouette", 0)
            payload["cad"] = {
                "enclosure_id": "case",
                "components": [
                    {"id": "case", "step": refs[0]},
                    {"id": "pcb", "step": refs[1], "translation_mm": [20, 5, 4]},
                ],
            }
            payload["circuit"] = {
                "output_node": "out",
                "elements": [
                    {
                        "id": "supply",
                        "kind": "voltage_source",
                        "positive": "supply",
                        "negative": "0",
                        "value": {"value": 12, "unit": "V"},
                        "source_ref": "fixture:source",
                    },
                    {
                        "id": "r1",
                        "kind": "resistor",
                        "positive": "supply",
                        "negative": "out",
                        "value": {"value": 1000, "unit": "ohm"},
                        "source_ref": "fixture:resistor",
                    },
                    {
                        "id": "r2",
                        "kind": "resistor",
                        "positive": "out",
                        "negative": "0",
                        "value": {"value": 1000, "unit": "ohm"},
                        "source_ref": "fixture:resistor",
                    },
                ],
            }

            def fact(value, unit):
                return {
                    "quantity": {"value": value, "unit": unit},
                    "source_ref": "review:upper-bound",
                }

            payload["thermal_bounds"] = {
                "ambient_max": fact(30, "degC"),
                "dissipation_max": fact(2, "W"),
                "resistance_max": fact(6, "K/W"),
            }
            payload["visual"] = {
                "reference": png,
                "candidate": png,
                "candidate_revision_id": "r1",
                "reference_context_sha256": "a" * 64,
                "candidate_context_sha256": "a" * 64,
                "approval_ref": "review:visible-region",
            }
            payload["visual_features"] = {
                "regions": [
                    {
                        "id": "button",
                        "box": [5, 5, 25, 25],
                        "visible": True,
                        "component_id": "button",
                    }
                ]
            }
            approved = client.post(
                "/v1/baselines",
                json={
                    "verification": payload,
                    "rationale": "Independent synthetic numerical fixture thresholds",
                },
                headers=reviewer,
            )
            assert approved.status_code == 201, approved.text
            payload["baseline_id"] = approved.json()["id"]
            reports = []
            for revision, position in (("r1", [20, 5, 4]), ("r2", [5, 5, 4])):
                payload["twin"]["revision_id"] = revision
                payload["visual"]["candidate_revision_id"] = revision
                payload["cad"]["components"][1]["translation_mm"] = position
                response = client.post(
                    "/v1/verifications",
                    json=payload,
                    headers={**headers, "Idempotency-Key": revision},
                )
                assert response.status_code == 202, response.text
                job = response.json()["verification_id"]
                run_once(app.state.store, job)
                result = client.get(f"/v1/verifications/{job}/report", headers=headers)
                assert result.status_code == 200, result.text
                reports.append(result.json())
            assert reports[0]["gate_decision"] == "fail", reports[0]
            assert reports[1]["gate_decision"] == "pass", reports[1]
            comparison = client.get(
                f"/v1/verifications/{reports[1]['verification_id']}/comparison",
                params={"against": reports[0]["verification_id"]},
                headers=headers,
            ).json()
            assert any(f["change"] == "resolved" for f in comparison["findings"])
            print(
                json.dumps(
                    {
                        "first_gate": reports[0]["gate_decision"],
                        "corrected_gate": reports[1]["gate_decision"],
                        "approved_requirements": reports[1]["coverage"]["required_total"],
                        "usage": client.get("/v1/usage", headers=headers).json(),
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
