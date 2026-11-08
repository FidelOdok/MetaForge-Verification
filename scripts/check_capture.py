"""Capture smoke check: all expected assets exist and hashes/PNG signatures match."""

import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text())
assert {v["view"] for v in manifest["views"]} == {"front", "side", "top", "iso"}
assert manifest["revision_id"] == "r1"
for view in manifest["views"]:
    raw = (root / view["file"]).read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert hashlib.sha256(raw).hexdigest() == view["sha256"]
print("Four controlled GLB views captured; PNG hashes verified.")
