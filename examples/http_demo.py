"""Exercise the public HTTP service end to end. No direct database/worker access."""

import argparse
import copy
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from integrated_fixture import build


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8086")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    agent = os.getenv("VERIFICATION_DEMO_AGENT_TOKEN", "local-testing-agent-token")
    reviewer = os.getenv("VERIFICATION_DEMO_REVIEWER_TOKEN", "local-testing-reviewer-token")
    base = args.base_url.rstrip("/")
    prefix = "test-" + uuid.uuid4().hex[:12]

    def call(path, method="GET", body=None, token=agent, key=None, raw=False):
        headers = {"Authorization": "Bearer " + token}
        if body is not None:
            headers["Content-Type"] = "application/octet-stream" if raw else "application/json"
        if key:
            headers["Idempotency-Key"] = prefix + ":" + key
        req = urllib.request.Request(
            base + path,
            data=body if raw else json.dumps(body).encode() if body is not None else None,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            details = exc.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {details}") from None

    def upload(data):
        result = call("/v1/artifacts", "POST", data, raw=True)
        assert result["sha256"] == hashlib.sha256(data).hexdigest()
        return {"artifact_id": result["artifact_id"], "sha256": result["sha256"]}

    def wait(job_id):
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            row = call(f"/v1/verifications/{job_id}")
            if row["execution_state"] == "completed":
                return call(f"/v1/verifications/{job_id}/report")
            if row["execution_state"] in {"failed", "canceled"}:
                raise RuntimeError(f"Job execution failed: {row['error']}")
            time.sleep(0.2)
        raise RuntimeError("Verification deadline exceeded")

    with tempfile.TemporaryDirectory() as directory:
        payload = build(upload, directory, prefix)
        reference_job = call(
            "/v1/renders",
            "POST",
            {
                "twin_id": prefix + "-reference",
                "revision_id": "approved",
                "source": {"from_cad": True},
                "cad": payload["cad"],
            },
            key="render",
        )
        reference_report = wait(reference_job["verification_id"])
        if reference_report["gate_decision"] != "pass":
            raise RuntimeError(
                "Reference render did not qualify: " + json.dumps(reference_report["findings"])
            )
        capture = call(f"/v1/renders/{reference_job['verification_id']}")["capture"]
        payload["render_reference"] = {"manifest": capture["manifest"], "images": capture["images"]}
        baseline = call(
            "/v1/baselines",
            "POST",
            {
                "verification": payload,
                "rationale": "Synthetic fixture: independent geometry, DC and thermal criteria.",
            },
            token=reviewer,
        )
        payload["baseline_id"] = baseline["id"]
        first = copy.deepcopy(payload)
        first["twin"]["revision_id"] = "r1"
        first["cad"]["components"][1]["translation_mm"] = [20, 5, 4]
        accepted = call("/v1/verifications", "POST", first, key="r1")
        assert (
            call("/v1/verifications", "POST", first, key="r1")["verification_id"]
            == accepted["verification_id"]
        )
        failed = wait(accepted["verification_id"])
        assert failed["gate_decision"] == "fail", failed
        assert (
            next(f for f in failed["findings"] if f["requirement_id"] == "CAD_INTERFERENCE")[
                "outcome"
            ]
            == "fail"
        )
        assert (
            next(f for f in failed["findings"] if f["requirement_id"] == "RENDER_REGRESSION")[
                "outcome"
            ]
            == "fail"
        )
        fixed = copy.deepcopy(payload)
        fixed["twin"]["revision_id"] = "r2"
        second = call(
            f"/v1/verifications/{accepted['verification_id']}/reverify", "POST", fixed, key="r2"
        )
        passed = wait(second["verification_id"])
        assert passed["gate_decision"] == "pass", passed
        comparison = call(
            f"/v1/verifications/{second['verification_id']}/comparison?against={accepted['verification_id']}"
        )
        summary = {
            "base_url": base,
            "reference_job": reference_job["verification_id"],
            "failed_job": accepted["verification_id"],
            "corrected_job": second["verification_id"],
            "first_gate": failed["gate_decision"],
            "corrected_gate": passed["gate_decision"],
            "required_checks": passed["coverage"]["required_total"],
            "scenario_families": sorted(
                {s["family"] for s in passed["coverage"]["scenario_matrix"]}
            ),
            "review_url": base + "/review?job=" + second["verification_id"],
            "comparison": comparison,
            "corrected_request": fixed,
            "scope": "Synthetic digital workflow; not full-product or physical qualification.",
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, indent=2) + "\n")
        print(
            json.dumps(
                {k: v for k, v in summary.items() if k not in {"corrected_request", "comparison"}},
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
