"""Local test service with separate API/worker processes and explicit synthetic credentials."""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8086)
    parser.add_argument("--data", type=Path, default=Path("data/testing"))
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args()
    missing = [name for name in ("OCP", "cv2") if importlib.util.find_spec(name) is None]
    ngspice = os.getenv("VERIFICATION_NGSPICE_EXECUTABLE") or shutil.which("ngspice")
    node = os.getenv("VERIFICATION_NODE_EXECUTABLE") or shutil.which("node")
    render_root = Path(
        os.getenv("VERIFICATION_RENDER_ROOT", Path(__file__).parents[1] / "visual-capture")
    ).resolve()
    if not ngspice:
        missing.append("ngspice")
    if not node or not (render_root / "node_modules/playwright").is_dir():
        missing.append("Node/controlled Playwright package")
    if missing:
        raise SystemExit("Missing test tools: " + ", ".join(missing) + ". See docs/testing.md.")
    root = args.data.resolve()
    root.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "VERIFICATION_AUTH_MODE": "tokens",
        "VERIFICATION_TOKENS": json.dumps({"local-testing-agent-token": "testing"}),
        "VERIFICATION_REVIEW_TOKENS": json.dumps({"local-testing-reviewer-token": "testing"}),
        "VERIFICATION_REQUIRE_APPROVED_BASELINE": "true",
        "VERIFICATION_WEBHOOK_DESTINATIONS": "{}",
        "VERIFICATION_ARTIFACT_BACKEND": "local",
        "VERIFICATION_DATABASE_URL": f"sqlite:///{root / 'jobs.db'}",
        "VERIFICATION_ARTIFACT_ROOT": str(root / "artifacts"),
        "VERIFICATION_ENGINE_EXECUTOR": "process",
        "VERIFICATION_RENDER_ALLOW_PROCESS": "true",
        "VERIFICATION_RENDER_ROOT": str(render_root),
        "VERIFICATION_NODE_EXECUTABLE": str(node),
        "VERIFICATION_NGSPICE_EXECUTABLE": str(ngspice),
        "VERIFICATION_WORKER_ENGINES": "ocp,ngspice,opencv,renderer",
    }
    children = []
    if not env.get("PLAYWRIGHT_BROWSERS_PATH") and not env.get("VERIFICATION_CHROMIUM_EXECUTABLE"):
        cache_root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(cache_root / "ms-playwright")
    try:
        commands = [
            [
                sys.executable,
                "-m",
                "uvicorn",
                "metaforge_verification.api:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--log-level",
                "warning",
            ],
            [sys.executable, "-m", "metaforge_verification", "worker"],
        ]
        # Initialize API/schema first, avoiding simultaneous initial table creation.
        children.append(subprocess.Popen(commands[0], env=env))
        base = f"http://127.0.0.1:{args.port}"
        deadline = time.monotonic() + 20
        while True:
            if children[0].poll() is not None:
                raise RuntimeError("API process exited")
            try:
                with urllib.request.urlopen(base + "/health", timeout=1):
                    break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("API startup timed out") from None
                time.sleep(0.1)
        children.append(subprocess.Popen(commands[1], env=env))
        ready = {
            "base_url": base,
            "docs": base + "/docs",
            "review": base + "/review",
            "mode": "local synthetic testing",
            "data": str(root),
        }
        if args.ready_file:
            args.ready_file.write_text(json.dumps(ready))
        print(json.dumps(ready, indent=2), flush=True)
        print("Run: python examples/http_demo.py --base-url " + base, flush=True)
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A test-stack process exited")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
