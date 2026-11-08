"""Exercise actual API and worker processes against a temporary durable database."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "VERIFICATION_AUTH_MODE": "local",
            "VERIFICATION_DATABASE_URL": f"sqlite:///{directory}/jobs.db",
            "VERIFICATION_ARTIFACT_ROOT": f"{directory}/artifacts",
        }
        base = f"http://127.0.0.1:{port}"
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "metaforge_verification.api:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        worker = None
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    with urllib.request.urlopen(base + "/health", timeout=1) as response:
                        assert json.load(response)["auth_mode"] == "local"
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("API did not start") from None
                    time.sleep(0.1)
            worker = subprocess.Popen(
                [sys.executable, "-m", "metaforge_verification", "worker"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            fixture = Path(__file__).resolve().parents[1] / "examples" / "lamp.json"
            req = urllib.request.Request(
                base + "/v1/verifications",
                data=fixture.read_bytes(),
                headers={"Content-Type": "application/json", "Idempotency-Key": "live-smoke"},
                method="POST",
            )
            with urllib.request.urlopen(req) as response:
                assert response.status == 202
                job_id = json.load(response)["verification_id"]
            deadline = time.monotonic() + 15
            while True:
                with urllib.request.urlopen(base + f"/v1/verifications/{job_id}") as response:
                    status = json.load(response)["execution_state"]
                if status == "completed":
                    break
                if status in {"failed", "canceled"} or time.monotonic() > deadline:
                    raise RuntimeError(f"Job did not complete: {status}")
                time.sleep(0.1)
            with urllib.request.urlopen(base + f"/v1/verifications/{job_id}/report") as response:
                report = json.load(response)
            assert report["gate_decision"] == "fail"
            print("Real HTTP API -> durable submission -> separate worker -> evidence report: PASS")
        finally:
            for process in (worker, api):
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
