"""Server-generated, source-bound four-view capture and rendered visual regression."""

import json

from PIL import ImageChops

from metaforge_verification.adapters.base import CheckResult, CheckUnavailable, InvalidEvidence
from metaforge_verification.adapters.isolated import engineering_task
from metaforge_verification.adapters.visual import load_png
from metaforge_verification.contracts import Evidence, Quantity, fingerprint

VIEWS = ("front", "side", "top", "iso")


def ref(digest):
    return {"artifact_id": digest, "sha256": digest}


def capture(request, artifacts):
    if request.capture is None:
        raise CheckUnavailable("A controlled capture source is required")
    if not hasattr(artifacts, "put"):
        raise CheckUnavailable("Capture requires a writable tenant-scoped artifact store")
    execute = getattr(artifacts, "engineering", engineering_task)
    derivation = None
    if request.capture.from_cad:
        if request.cad is None:
            raise CheckUnavailable("CAD source assembly is missing")
        derived = execute(
            {"engine": "cad", "assembly": request.cad.model_dump(mode="json"), "export_glb": True},
            [artifacts.read(c.step.artifact_id) for c in request.cad.components],
        )
        if derived.get("invalid_solids") or "_glb_bytes" not in derived:
            raise InvalidEvidence("Unqualified CAD cannot generate an accepted preview")
        data = derived["_glb_bytes"]
        derivation = {
            "source": request.cad.model_dump(mode="json"),
            "tool_version": derived["tool_version"],
            "tessellation": derived["tessellation"],
        }
    else:
        data = artifacts.read(request.capture.model.artifact_id)
    model_digest = artifacts.put(data)
    rendered = execute({"engine": "render", "revision_id": request.twin.revision_id}, [data])
    manifest = rendered["manifest"]
    if manifest["revision_id"] != request.twin.revision_id:
        raise InvalidEvidence("Stale generated capture")
    images = {}
    for view in VIEWS:
        png = rendered["_render_pngs"][view]
        image = load_png(png)
        if image.size != (512, 512):
            raise InvalidEvidence("Generated capture resolution is not qualified")
        # A blank frame cannot prove a complete view set. Alpha cannot hide RGB content.
        white = image.copy()
        white.paste((255, 255, 255, 255), (0, 0, 512, 512))
        diff = ImageChops.difference(image.convert("RGB"), white.convert("RGB"))
        if diff.getbbox() is None:
            raise InvalidEvidence(f"Generated view is empty: {view}")
        images[view] = ref(artifacts.put(png))
    # Preserve the original renderer manifest, then add separately hashed service lineage.
    manifest_digest = artifacts.put(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    )
    return {
        "manifest": ref(manifest_digest),
        "images": images,
        "source_model": ref(model_digest),
        "context_sha256": manifest["context_sha256"],
        "revision_id": request.twin.revision_id,
        "settings": manifest["settings"],
        "bounds": manifest["bounds"],
        "derivation": derivation,
        "tool_version": rendered["tool_version"],
        "executor": rendered["executor"],
    }


class RenderCapture:
    rule_id = "visual.render_capture"
    module = "artifact"
    fidelity = "F1"

    def run(self, request, artifacts):
        result = capture(request, artifacts)
        value = Quantity(value=4, unit="dimensionless")
        fp = fingerprint(request)
        return CheckResult(
            value,
            Evidence(
                evidence_id=f"ev-capture-{fp[:16]}",
                method=self.rule_id,
                fidelity=self.fidelity,
                input_fingerprint=fp,
                measurements={"qualified_views": value},
                source_refs=[result["source_model"]["sha256"]],
                tool_version=result["tool_version"],
                details=result,
                assumptions=[
                    "Four nonempty, service-generated views of this source revision.",
                    "Capture success does not establish engineering or aesthetic conformity.",
                    "CAD-derived previews retain transforms/component IDs and tessellation limits.",
                ],
            ),
        )


class RenderRegression:
    rule_id = "visual.render_regression"
    module = "artifact"
    fidelity = "F1"

    def run(self, request, artifacts):
        baseline = request.render_reference
        if baseline is None:
            raise CheckUnavailable("An approved four-view render reference is required")
        result = capture(request, artifacts)
        try:
            raw = artifacts.read(baseline.manifest.artifact_id)
            if len(raw) > 64_000:
                raise InvalidEvidence("Reference capture manifest is excessive")
            manifest = json.loads(raw)
            if (
                manifest["schema_version"] != "1.0"
                or manifest["context_sha256"] != result["context_sha256"]
                or manifest["settings"] != result["settings"]
            ):
                raise InvalidEvidence("Reference and candidate rendering contexts differ")
            refs = {r["view"]: r for r in manifest["views"]}
            if len(manifest["views"]) != 4 or set(refs) != set(VIEWS):
                raise InvalidEvidence("Reference view set is incomplete")
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidEvidence("Malformed reference capture manifest") from exc
        differences = []
        for view in VIEWS:
            expected = baseline.images[view]
            if expected.sha256 != refs[view]["sha256"]:
                raise InvalidEvidence("Reference manifest/image identity mismatch")
            a = load_png(artifacts.read(expected.artifact_id))
            b = load_png(artifacts.read(result["images"][view]["artifact_id"]))
            if a.size != b.size:
                raise InvalidEvidence("Reference/candidate dimensions differ")
            diff = ImageChops.difference(a, b)
            mask = diff.getchannel(0)
            for channel in diff.split()[1:]:
                mask = ImageChops.lighter(mask, channel)
            changed = sum(n for pixel, n in enumerate(mask.histogram()) if pixel)
            differences.append(
                {
                    "view": view,
                    "changed_fraction": changed / (a.width * a.height),
                    "difference_bbox": mask.getbbox(),
                    "reference": expected.model_dump(mode="json"),
                    "candidate": result["images"][view],
                }
            )
        value = Quantity(
            value=max(d["changed_fraction"] for d in differences), unit="dimensionless"
        )
        fp = fingerprint(request)
        return CheckResult(
            value,
            Evidence(
                evidence_id=f"ev-render-regression-{fp[:16]}",
                method=self.rule_id,
                fidelity=self.fidelity,
                input_fingerprint=fp,
                measurements={"worst_view_changed_fraction": value},
                source_refs=[baseline.manifest.sha256, result["source_model"]["sha256"]],
                tool_version=result["tool_version"],
                details={"capture": result, "differences": differences},
                assumptions=[
                    "Controlled rendering and approved references; no semantic/aesthetic judgment.",
                    "Framing normalizes scale; authoritative dimensions require CAD checks.",
                ],
            ),
        )
