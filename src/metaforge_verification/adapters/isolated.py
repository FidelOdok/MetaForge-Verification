"""Bounded subprocess execution for bundled engineering tools (Linux/POSIX).

Process/resource isolation is not a network/filesystem security sandbox. Deploy the
worker with a read-only image, restricted mounts, no credentials and denied egress.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from metaforge_verification.adapters.base import CheckUnavailable, InvalidEvidence


def engineering_task(task, blobs=None, timeout=45, cancelled=None):
    if sys.platform != "linux":
        raise CheckUnavailable("Engineering subprocess adapter requires Linux resource limits")
    with tempfile.TemporaryDirectory(prefix="verification-engine-") as directory:
        root = Path(directory)
        for index, data in enumerate(blobs or []):
            if len(data) > 10 * 1024 * 1024:
                raise InvalidEvidence("Engineering artifact exceeds 10 MiB")
            (root / f"input-{index}.step").write_bytes(data)
        (root / "task.json").write_text(json.dumps(task, allow_nan=False))
        # Explicit child environment: customer tokens/cloud credentials are not inherited.
        env = {
            "PATH": os.defpath,
            "HOME": directory,
            "LANG": "C.UTF-8",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "SPICE_ASCIIRAWFILE": "1",
            "PYTHONPATH": os.pathsep.join(p for p in sys.path if p and Path(p).is_absolute()),
        }
        executable = os.getenv("VERIFICATION_NGSPICE_EXECUTABLE")
        if executable:
            if not Path(executable).is_absolute():
                raise CheckUnavailable("Configured ngspice executable must be an absolute path")
            env["VERIFICATION_NGSPICE_EXECUTABLE"] = executable
        with (root / "process.log").open("wb") as output:
            child = subprocess.Popen(
                [sys.executable, "-m", "metaforge_verification.engineering_worker", directory],
                cwd=directory,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout
            try:
                while child.poll() is None:
                    if cancelled and cancelled():
                        raise CheckUnavailable("Engineering execution canceled or lease lost")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise InvalidEvidence("Engineering process exceeded wall-time limit")
                    try:
                        child.wait(timeout=min(0.25, remaining))
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                # Kill any descendants left by a tool, including after a successful child exit.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
        path = root / "result.json"
        if child.returncode or not path.exists() or path.stat().st_size > 256_000:
            raise InvalidEvidence("Engineering process failed or exceeded resource limits")
        try:
            result = json.loads(path.read_text())
        except (ValueError, OSError) as exc:
            raise InvalidEvidence("Engineering process produced invalid output") from exc
        if result.get("unavailable"):
            raise CheckUnavailable(result["unavailable"])
        if result.get("error"):
            raise InvalidEvidence(result["error"])
        return result
