"""Bounded B-rep tessellation to an embedded GLB; source solids remain authoritative."""

import json
import struct


def export_glb(shapes, components, path):
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    binary, views, accessors, meshes, nodes = bytearray(), [], [], [], []
    triangle_total = 0
    for index, shape in enumerate(shapes):
        mesher = BRepMesh_IncrementalMesh(shape, 0.1, False, 0.3, False)
        if not mesher.IsDone():
            raise ValueError("CAD tessellation failed")
        vertices, triangles = [], []
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = TopoDS.Face_s(explorer.Current())
            location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face, location)
            if triangulation is None:
                raise ValueError("CAD face has no triangulation")
            offset = len(vertices) // 3
            if offset + triangulation.NbNodes() > 200_000:
                raise ValueError("CAD preview vertex limit exceeded")
            for n in range(1, triangulation.NbNodes() + 1):
                point = triangulation.Node(n).Transformed(location.Transformation())
                # glTF 2.0 uses metres; authoritative STEP transfer is normalized to mm.
                vertices.extend((point.X() / 1000, point.Y() / 1000, point.Z() / 1000))
            for n in range(1, triangulation.NbTriangles() + 1):
                a, b, c = triangulation.Triangle(n).Get()
                if face.Orientation() == TopAbs_REVERSED:
                    b, c = c, b
                triangles.extend((offset + a - 1, offset + b - 1, offset + c - 1))
            triangle_total += triangulation.NbTriangles()
            if triangle_total > 400_000:
                raise ValueError("CAD preview triangle limit exceeded")
            explorer.Next()
        if not triangles:
            raise ValueError("CAD preview has no triangles")

        def append(data, target):
            offset = len(binary)
            binary.extend(data)
            while len(binary) % 4:
                binary.append(0)
            views.append(
                {"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target}
            )
            return len(views) - 1

        packed_positions = struct.pack(f"<{len(vertices)}f", *vertices)
        vertices = struct.unpack(f"<{len(vertices)}f", packed_positions)
        position = append(packed_positions, 34962)
        indices = append(struct.pack(f"<{len(triangles)}I", *triangles), 34963)
        accessors.extend(
            [
                {
                    "bufferView": position,
                    "componentType": 5126,
                    "count": len(vertices) // 3,
                    "type": "VEC3",
                    "min": [min(vertices[a::3]) for a in range(3)],
                    "max": [max(vertices[a::3]) for a in range(3)],
                },
                {
                    "bufferView": indices,
                    "componentType": 5125,
                    "count": len(triangles),
                    "type": "SCALAR",
                },
            ]
        )
        meshes.append(
            {
                "name": components[index]["component_id"],
                "primitives": [
                    {
                        "attributes": {"POSITION": 2 * index},
                        "indices": 2 * index + 1,
                        "material": index % 2,
                    }
                ],
            }
        )
        nodes.append({"name": components[index]["component_id"], "mesh": index})
    document = {
        "asset": {"version": "2.0", "generator": "metaforge-ocp-tessellation-v1"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
        "materials": [
            {
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.65, 0.72, 0.78, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 0.8,
                },
            },
            {
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.05, 0.5, 0.25, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 0.8,
                },
            },
        ],
    }
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" " * ((-len(encoded)) % 4)
    length = 12 + 8 + len(encoded) + 8 + len(binary)
    if length > 10 * 1024**2:
        raise ValueError("Derived GLB exceeds 10 MiB")
    path.write_bytes(
        struct.pack("<III", 0x46546C67, 2, length)
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )
    return {
        "linear_deflection_mm": 0.1,
        "angular_deflection_rad": 0.3,
        "triangles": triangle_total,
        "component_ids": [c["component_id"] for c in components],
        "source_unit": "mm",
        "preview_unit": "m",
        "scale_to_metres": 0.001,
        "limitations": ["Tessellated preview; use B-rep for dimensions."],
    }
