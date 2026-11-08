"""Create a tiny GLB with one triangle; no customer geometry or remote resources."""

import json
import struct
import sys
from pathlib import Path

positions = struct.pack("<9f", -1, -1, 0, 1, -1, 0, 0, 1, 0)
doc = {
    "asset": {"version": "2.0"},
    "scene": 0,
    "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0}],
    "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
    "materials": [
        {
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.1, 0.5, 0.8, 1],
                "metallicFactor": 0,
                "roughnessFactor": 1,
            },
        }
    ],
    "buffers": [{"byteLength": len(positions)}],
    "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)}],
    "accessors": [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
            "min": [-1, -1, 0],
            "max": [1, 1, 0],
        }
    ],
}
raw = json.dumps(doc, separators=(",", ":")).encode()
raw += b" " * (-len(raw) % 4)
body = struct.pack("<II", len(raw), 0x4E4F534A) + raw
body += struct.pack("<II", len(positions), 0x004E4942) + positions
Path(sys.argv[1]).write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
