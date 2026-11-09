"""Start the full local stack, exercise its HTTP API, then stop every child."""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        ready, output = Path(directory) / "ready.json", Path(directory) / "result.json"
        stack = subprocess.Popen(
            [
                sys.executable,
                str(root / "scripts/run_test_stack.py"),
                "--port",
                str(port),
                "--data",
                str(Path(directory) / "data"),
                "--ready-file",
                str(ready),
            ],
            cwd=root,
            env=os.environ,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            while not ready.exists():
                if stack.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Integrated stack failed to start")
                time.sleep(0.1)
            base = json.loads(ready.read_text())["base_url"]
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "examples/http_demo.py"),
                    "--base-url",
                    base,
                    "--output",
                    str(output),
                ],
                cwd=root,
                timeout=240,
            )
            if result.returncode:
                raise SystemExit(result.returncode)
            summary = json.loads(output.read_text())
            assert summary["first_gate"] == "fail" and summary["corrected_gate"] == "pass"
            assert summary["scenario_families"] == ["fault", "normal", "recovery"]
            if args.ui:
                import shutil

                node = os.getenv("VERIFICATION_NODE_EXECUTABLE") or shutil.which("node")
                subprocess.run(
                    [node, str(root / "visual-capture/integrated-review.test.mjs"), str(output)],
                    cwd=root,
                    check=True,
                    timeout=60,
                )
            print("Integrated HTTP: CAD → rendering → approval → failure → correction: PASS")
        finally:
            import signal

            os.killpg(stack.pid, signal.SIGINT)
            try:
                stack.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(stack.pid, signal.SIGKILL)
                stack.wait()


if __name__ == "__main__":
    main()
