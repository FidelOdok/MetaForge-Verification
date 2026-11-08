"""Reproducible 100-tenant HTTP smoke benchmark. Not a heavy-engine production load claim."""

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    tokens = {f"synthetic-tenant-token-{i:03}": f"organization-{i:03}" for i in range(100)}
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "VERIFICATION_AUTH_MODE": "tokens",
            "VERIFICATION_TOKENS": json.dumps(tokens),
            "VERIFICATION_REVIEW_TOKENS": "{}",
            "VERIFICATION_REQUIRE_APPROVED_BASELINE": "false",
            "VERIFICATION_DATABASE_URL": f"sqlite:///{directory}/jobs.db",
            "VERIFICATION_ARTIFACT_BACKEND": "local",
            "VERIFICATION_ARTIFACT_ROOT": f"{directory}/artifacts",
            "VERIFICATION_WEBHOOK_DESTINATIONS": "{}",
            "VERIFICATION_MAX_RUNNING_JOBS": "2",
            "VERIFICATION_MAX_RUNNING_PER_TENANT": "1",
        }
        base = f"http://127.0.0.1:{port}"
        processes = []

        def start(argv):
            child = subprocess.Popen(
                [sys.executable, *argv],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(child)

        def request(path, token=None, body=None):
            headers = {"Content-Type": "application/json", "Idempotency-Key": "same-tenant-key"}
            if token:
                headers["Authorization"] = "Bearer " + token
            req = urllib.request.Request(
                base + path, data=body, headers=headers, method="POST" if body else "GET"
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.load(response)

        try:
            start(
                [
                    "-m",
                    "uvicorn",
                    "metaforge_verification.api:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "error",
                ]
            )
            deadline = time.monotonic() + 20
            while True:
                try:
                    request("/health")
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("API startup failed") from None
                    time.sleep(0.1)
            for _ in range(2):
                start(["-m", "metaforge_verification", "worker"])
            payload = (Path(__file__).parents[1] / "examples/lamp.json").read_bytes()

            def submit(token):
                started = time.monotonic()
                row = request("/v1/verifications", token, payload)
                return {
                    "token": token,
                    "id": row["verification_id"],
                    "submit_seconds": time.monotonic() - started,
                    "started": started,
                }

            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=10) as pool:
                accepted = list(pool.map(submit, tokens))
            assert len({r["id"] for r in accepted}) == 100

            def finish(row):
                deadline = time.monotonic() + 90
                while True:
                    state = request(f"/v1/verifications/{row['id']}", row["token"])[
                        "execution_state"
                    ]
                    if state == "completed":
                        break
                    if state in {"failed", "canceled"} or time.monotonic() > deadline:
                        raise RuntimeError(f"Tenant job did not complete: {state}")
                    time.sleep(0.1)
                report = request(f"/v1/verifications/{row['id']}/report", row["token"])
                assert report["gate_decision"] == "fail"
                assert request("/v1/usage", row["token"])["accepted_reports"] == 1
                return time.monotonic() - row["started"]

            with ThreadPoolExecutor(max_workers=10) as pool:
                turnaround = list(pool.map(finish, accepted))
            denied = 0
            for index, row in enumerate(accepted):
                try:
                    request(f"/v1/verifications/{accepted[(index + 1) % 100]['id']}", row["token"])
                    raise AssertionError("Cross-tenant access was permitted")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 404
                    denied += 1
                    exc.close()

            def percentile(values, p):
                return round(sorted(values)[min(len(values) - 1, int((len(values) - 1) * p))], 6)

            result = {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "workload": {
                    "tenants": 100,
                    "jobs": 100,
                    "parallel_submitters": 10,
                    "worker_processes": 2,
                    "global_running_job_limit": 2,
                    "storage": "SQLite + local artifacts",
                    "transport": "HTTP loopback",
                    "checks": "analytical lamp; no CAD/circuit/render/GPU workload",
                },
                "environment": {
                    "python": platform.python_version(),
                    "os": platform.system(),
                    "visible_cpu_count": os.cpu_count(),
                },
                "results": {
                    "completed": 100,
                    "cross_tenant_reads_denied": denied,
                    "accepted_usage_records": 100,
                    "submit_p50_seconds": percentile([r["submit_seconds"] for r in accepted], 0.5),
                    "submit_p95_seconds": percentile([r["submit_seconds"] for r in accepted], 0.95),
                    "submit_p99_seconds": percentile([r["submit_seconds"] for r in accepted], 0.99),
                    "observed_completion_p95_seconds": percentile(turnaround, 0.95),
                    "total_elapsed_seconds": round(time.monotonic() - started, 6),
                },
                "limitations": [
                    "Synthetic smoke benchmark; no production capacity/SLA claim.",
                    "Completion timing includes polling/observation delay.",
                    "No heavy-engine, PostgreSQL, HA, S3 or restore qualification.",
                ],
            }
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
        finally:
            for child in reversed(processes):
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
