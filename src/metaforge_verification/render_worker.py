"""Controlled renderer entry point. Never navigate to a customer URL."""

import json
import os
import shutil
import struct
import subprocess
from pathlib import Path


def qualify_glb(data):
    if not 20 <= len(data) <= 10 * 1024**2:
        raise ValueError("GLB size outside the supported envelope")
    magic, version, length, chunk_size, chunk_type = struct.unpack_from("<5I", data)
    if magic != 0x46546C67 or version != 2 or length != len(data) or chunk_type != 0x4E4F534A:
        raise ValueError("Invalid GLB header or declared length")
    if chunk_size > len(data) - 20:
        raise ValueError("Invalid GLB JSON chunk length")
    document = json.loads(data[20 : 20 + chunk_size])
    if (
        len(document.get("nodes", [])) > 10_000
        or len(document.get("meshes", [])) > 1000
        or document.get("extensionsRequired")
    ):
        raise ValueError("GLB exceeds supported scene/extension limits")
    if any("uri" in b for b in document.get("buffers", [])) or any(
        "uri" in image for image in document.get("images", [])
    ):
        raise ValueError("Only embedded GLB buffers/images are supported")
    if any(accessor.get("count", 0) > 1_200_000 for accessor in document.get("accessors", [])):
        raise ValueError("GLB accessor exceeds supported element count")


def render(task, root):
    qualify_glb((root / "input-0.glb").read_bytes())
    candidates = [
        Path("/opt/verification/render"),
        Path(__file__).resolve().parents[2] / "visual-capture",
    ]
    configured = os.getenv("VERIFICATION_RENDER_ROOT")
    capture_root = (
        Path(configured) if configured else next((p for p in candidates if p.exists()), None)
    )
    node = os.getenv("VERIFICATION_NODE_EXECUTABLE") or shutil.which("node")
    if not node or capture_root is None or not (capture_root / "capture.mjs").is_file():
        return {"unavailable": "Controlled renderer/Node runtime is not installed"}
    if configured and not capture_root.is_absolute():
        raise ValueError("Configured render root must be an absolute operator path")
    if not (capture_root / "node_modules/playwright").is_dir():
        return {"unavailable": "Run npm ci in the controlled renderer package"}
    with (root / "render.log").open("wb") as log:
        run = subprocess.run(
            [
                node,
                "--max-old-space-size=256",
                str(capture_root / "capture.mjs"),
                str(root / "input-0.glb"),
                str(root / "capture"),
                task["revision_id"],
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=40,
        )
    if run.returncode:
        raise ValueError("Controlled capture failed; inspect the installed renderer/browser")
    path = root / "capture/manifest.json"
    if not path.is_file() or path.stat().st_size > 64_000:
        raise ValueError("Capture manifest is absent or excessive")
    manifest = json.loads(path.read_text())
    if manifest.get("revision_id") != task["revision_id"]:
        raise ValueError("Renderer returned a stale revision")
    return {
        "manifest": manifest,
        "tool_version": "playwright/"
        + manifest["settings"]["playwright"]
        + ";chromium/"
        + manifest["settings"]["browser"]
        + ";three/"
        + manifest["settings"]["three"],
    }
