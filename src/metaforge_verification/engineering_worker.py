"""Private process entry point. Typed jobs only; never execute uploaded code/netlists."""

import json
import math
import os
import resource
import shutil
import subprocess
import sys
from pathlib import Path


def cad(task, root):
    from OCP import __version__
    from OCP.Bnd import Bnd_Box
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepGProp import BRepGProp
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    def volume(shape):
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        return abs(props.Mass())

    shapes, components = [], []
    for index, component in enumerate(task["assembly"]["components"]):
        reader = STEPControl_Reader()
        if reader.ReadFile(str(root / f"input-{index}.step")) != IFSelect_RetDone:
            raise ValueError("STEP parse failed")
        # Normalize source STEP units to millimetres before transfer.
        reader.SetSystemLengthUnit(1.0)
        if reader.NbRootsForTransfer() > 100:
            raise ValueError("STEP root count exceeds supported envelope")
        if not reader.TransferRoots():
            raise ValueError("STEP contains no transferable geometry")
        shape = reader.OneShape()
        count = 0
        solids = TopExp_Explorer(shape, TopAbs_SOLID)
        while solids.More():
            count += 1
            solids.Next()
            if count > 1:
                raise ValueError("Each CAD component must contain exactly one solid")
        if count != 1:
            raise ValueError("CAD component contains no solid")
        faces = TopExp_Explorer(shape, TopAbs_FACE)
        face_count = 0
        while faces.More():
            face_count += 1
            if face_count > 10_000:
                raise ValueError("CAD face count exceeds supported envelope")
            faces.Next()
        valid = BRepCheck_Analyzer(shape).IsValid()
        transform = gp_Trsf()
        # Active rotations Rx, then Ry, then Rz, then translation in assembly coordinates.
        for axis, angle in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), component["rotation_deg"]):
            rotation = gp_Trsf()
            rotation.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis)), math.radians(angle))
            transform = rotation.Multiplied(transform)
        translation = gp_Trsf()
        translation.SetTranslation(gp_Vec(*component["translation_mm"]))
        shape = BRepBuilderAPI_Transform(shape, translation.Multiplied(transform), True).Shape()
        bounds = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, bounds, False, False)
        bbox = bounds.Get()
        if any(not math.isfinite(v) or abs(v) > 100_000 for v in bbox):
            raise ValueError("CAD extent exceeds supported millimetre envelope")
        components.append(
            {
                "component_id": component["id"],
                "valid": valid,
                "faces": face_count,
                "volume_mm3": volume(shape),
                "bbox_mm": bbox,
            }
        )
        shapes.append(shape)
    result = {"tool_version": f"cadquery-ocp/{__version__}", "components": components}
    if not all(c["valid"] and c["volume_mm3"] > 0 for c in components):
        result["invalid_solids"] = sum(not c["valid"] or c["volume_mm3"] <= 0 for c in components)
        return result
    result["invalid_solids"] = 0
    common = BRepAlgoAPI_Common(*shapes)
    common.Build()
    if not common.IsDone() or not BRepCheck_Analyzer(common.Shape()).IsValid():
        raise ValueError("CAD intersection failed numerical/topology qualification")
    result["intersection_volume_mm3"] = volume(common.Shape())
    distance = BRepExtrema_DistShapeShape(*shapes)
    distance.Perform()
    if not distance.IsDone() or distance.NbSolution() < 1:
        raise ValueError("CAD distance solver failed")
    result["distance_mm"] = distance.Value()
    a, b = distance.PointOnShape1(1), distance.PointOnShape2(1)
    result["closest_points_mm"] = [(a.X(), a.Y(), a.Z()), (b.X(), b.Y(), b.Z())]
    if task.get("export_glb"):
        from metaforge_verification.meshing import export_glb

        result["tessellation"] = export_glb(shapes, components, root / "derived.glb")
    return result


def circuit(task, root):
    executable = os.getenv("VERIFICATION_NGSPICE_EXECUTABLE") or shutil.which("ngspice")
    if not executable:
        return {"unavailable": "ngspice executable is not installed"}
    from metaforge_verification.adapters.analytical import convert
    from metaforge_verification.contracts import DCCircuit

    model = DCCircuit.model_validate(task["circuit"])
    lines = ["MetaForge bounded resistive DC model"]
    for index, element in enumerate(model.elements):
        unit, prefix = ("ohm", "R") if element.kind == "resistor" else ("V", "V")
        value = convert(element.value, unit)
        if (
            (prefix == "R" and not 1e-3 <= value <= 1e9)
            or (prefix == "V" and abs(value) > 60)
            or element.positive == element.negative
        ):
            raise ValueError("Circuit element outside supported low-voltage DC envelope")
        lines.append(f"{prefix}{index} {element.positive} {element.negative} {value:.17g}")
    lines += [".save all", ".op", ".end"]
    netlist = "\n".join(lines) + "\n"
    (root / "model.cir").write_text(netlist)
    with (root / "ngspice.log").open("wb") as log:
        run = subprocess.run(
            [executable, "-n", "-b", "-r", "result.raw", "model.cir"],
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
    log = (root / "ngspice.log").read_text(errors="replace").lower()
    if run.returncode or any(
        s in log
        for s in (
            "singular matrix",
            "failed",
            "fatal",
            "timestep too small",
            "warning:",
            "error:",
        )
    ):
        raise ValueError("Circuit solution failed convergence/quality checks")
    raw = (root / "result.raw").read_text()
    header, data = raw.split("Values:\n", 1)
    if "No. Points: 1" not in header:
        raise ValueError("Unexpected operating-point result dimensions")
    variable_lines = header.split("Variables:\n", 1)[1].strip().splitlines()
    names = [line.split()[1].lower() for line in variable_lines]
    tokens = data.split()
    if len(tokens) != len(names) + 1 or tokens[0] != "0":
        raise ValueError("Unexpected operating-point result format")
    vectors = dict(zip(names, map(float, tokens[1:])))
    if not all(math.isfinite(v) for v in vectors.values()):
        raise ValueError("Nonfinite operating point")

    def node(name):
        if name == "0":
            return 0.0
        if f"v({name})" in vectors:
            return vectors[f"v({name})"]
        return vectors[name]

    voltage, loss, source_power = node(model.output_node), 0.0, 0.0
    currents = {}
    for index, element in enumerate(model.elements):
        drop = node(element.positive) - node(element.negative)
        if element.kind == "resistor":
            current = drop / convert(element.value, "ohm")
            loss += drop * current
        else:
            expected = convert(element.value, "V")
            if abs(drop - expected) > max(1e-8, abs(expected) * 1e-7):
                raise ValueError("Voltage source constraint residual exceeds tolerance")
            current = vectors[f"i(v{index})"]
            source_power += drop * current
        for name, sign in ((element.positive, 1), (element.negative, -1)):
            if name != "0":
                currents[name] = currents.get(name, 0) + sign * current
    if max(map(abs, currents.values()), default=0) > 1e-8 or abs(loss + source_power) > max(
        1e-8, loss * 1e-7
    ):
        raise ValueError("Circuit violates KCL or power-balance residual tolerance")
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5)
    version_line = next(
        (s.strip("* ") for s in version.stdout.splitlines() if "ngspice-" in s),
        "ngspice/version-unavailable",
    )
    import hashlib

    return {
        "output_voltage_v": voltage,
        "resistor_dissipation_w": loss,
        "source_power_w": source_power,
        "max_kcl_residual_a": max(map(abs, currents.values()), default=0),
        "power_balance_residual_w": abs(loss + source_power),
        "tool_version": version_line,
        "netlist_sha256": hashlib.sha256(netlist.encode()).hexdigest(),
        "generated_netlist": netlist,
        "raw_result": raw,
    }


def main():
    # Native parser/solver limits apply before importing OCP or parsing supplied files.
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    root = Path(sys.argv[1])
    try:
        task = json.loads((root / "task.json").read_text())
        if task["engine"] == "render":
            # Chromium reserves a large virtual address space. Container/cgroup
            # memory limits bound physical use; local process mode is opt-in.
            resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**4, 16 * 1024**4))
            resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
        else:
            resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
            resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
            from metaforge_verification.process_security import deny_network

            deny_network()
        output_limit = (12 if task.get("export_glb") else 2) * 1024**2
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
        if task["engine"] == "cad":
            result = cad(task, root)
        elif task["engine"] == "circuit":
            result = circuit(task, root)
        elif task["engine"] == "render":
            from metaforge_verification.render_worker import render

            result = render(task, root)
        else:
            raise ValueError("Unsupported bundled engine")
    except ImportError:
        result = {"unavailable": "Optional engineering engine dependency is not installed"}
    except Exception as exc:
        # Only known static ValueError diagnostics may be shown to a customer.
        result = {
            "error": str(exc)
            if type(exc) is ValueError
            else "Engineering adapter failed qualification"
        }
    (root / "result.json").write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
