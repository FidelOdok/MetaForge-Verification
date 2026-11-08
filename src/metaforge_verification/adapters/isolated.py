"""Bounded subprocess execution for bundled engineering tools (Linux/POSIX).

Process/resource isolation is not a network/filesystem security sandbox. Deploy the
worker with a read-only image, restricted mounts, no credentials and denied egress.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from metaforge_verification.adapters.base import CheckUnavailable, InvalidEvidence


def container_command(directory):
    executable = shutil.which("docker")
    image = os.getenv("VERIFICATION_ENGINE_IMAGE", "")
    if not executable or not re.fullmatch(
        r"(?:[A-Za-z0-9][A-Za-z0-9./:_-]*@)?sha256:[a-f0-9]{64}", image
    ):
        raise CheckUnavailable("Container executor requires Docker and a pinned image digest/ID")
    if os.getuid() == 0:
        raise CheckUnavailable("Container executor controller must run as a non-root user")
    name = "verification-engine-" + uuid.uuid4().hex
    command = [
        executable,
        "run",
        "--rm",
        "--pull",
        "never",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--cpus",
        "1",
        "--memory",
        "1g",
        "--memory-swap",
        "1g",
        "--pids-limit",
        "128",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=128m",
        "--mount",
        f"type=bind,src={directory},dst=/job",
        "--env",
        "HOME=/tmp",
        "--env",
        "OMP_NUM_THREADS=1",
        "--env",
        "OPENBLAS_NUM_THREADS=1",
        "--env",
        "SPICE_ASCIIRAWFILE=1",
        "--entrypoint",
        "python",
        image,
        "-m",
        "metaforge_verification.engineering_worker",
        "/job",
    ]
    return command, [executable, "rm", "--force", name]


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
        mode = os.getenv("VERIFICATION_ENGINE_EXECUTOR", "process")
        command = [sys.executable, "-m", "metaforge_verification.engineering_worker", directory]
        cleanup = None
        if mode == "docker":
            command, cleanup = container_command(directory)
            # These configure the trusted controller's daemon connection, not the job container.
            docker_host = os.getenv("VERIFICATION_DOCKER_HOST")
            if docker_host:
                if not docker_host.startswith("unix:///"):
                    raise CheckUnavailable(
                        "Dedicated Docker transport must use an absolute Unix socket"
                    )
                env["DOCKER_HOST"] = docker_host
        elif mode != "process":
            raise CheckUnavailable("Unknown engineering executor")
        with (root / "process.log").open("wb") as output:
            child = subprocess.Popen(
                command,
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
                if cleanup:
                    try:
                        subprocess.run(
                            cleanup,
                            env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=10,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        # Failed cleanup must not turn a timeout/cancel into accepted evidence.
                        raise InvalidEvidence(
                            "Container cleanup requires operator reconciliation"
                        ) from None
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
        result["executor"] = {
            "backend": mode,
            "image": os.getenv("VERIFICATION_ENGINE_IMAGE") if mode == "docker" else None,
            "filesystem_scope": "job-only bind + read-only image"
            if mode == "docker"
            else "worker host",
            "network": "denied",
        }
        return result
