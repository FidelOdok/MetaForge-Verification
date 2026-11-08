"""Run an HTTP-contract demonstration against a real temporary persistent store."""

import io
import json
import tempfile
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient
from make_fixtures import lamp_request
from PIL import Image

from metaforge_verification.api import create_app
from metaforge_verification.config import Settings
from metaforge_verification.worker import run_once

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    app = create_app(
        Settings(
            database_url=f"sqlite:///{root / 'jobs.db'}",
            artifact_root=root / "artifacts",
            auth_mode="local",
        )
    )
    with TestClient(app) as client:
        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), "white").save(buffer, format="PNG")
        artifact = client.post("/v1/artifacts", content=buffer.getvalue()).json()
        ref = {k: artifact[k] for k in ("artifact_id", "sha256")}
        context = "0" * 64
        first = lamp_request()
        first["visual"] = {
            "reference": ref,
            "candidate": ref,
            "candidate_revision_id": "r1",
            "reference_context_sha256": context,
            "candidate_context_sha256": context,
            "approval_ref": "fixture:approved-capture-context",
        }
        second = deepcopy(first)
        second["twin"]["revision_id"] = "r2"
        second["twin"]["facts"]["load_power"]["quantity"]["value"] = 6
        second["visual"]["candidate_revision_id"] = "r2"
        summary = []
        for revision in (first, second):
            submitted = client.post(
                "/v1/verifications",
                json=revision,
                headers={"Idempotency-Key": revision["twin"]["revision_id"]},
            )
            submitted.raise_for_status()
            job_id = submitted.json()["verification_id"]
            run_once(app.state.store)
            report = client.get(f"/v1/verifications/{job_id}/report").json()
            summary.append(
                {
                    "revision": report["revision_id"],
                    "gate": report["gate_decision"],
                    "coverage": report["coverage"],
                    "limitations": report["limitations"],
                }
            )
        assert [r["gate"] for r in summary] == ["fail", "pass"]
        print(json.dumps(summary, indent=2))
