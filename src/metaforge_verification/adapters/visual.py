"""Controlled PNG regression comparison. No semantic/aesthetic or CAD claims."""

import io

from PIL import Image, ImageChops, UnidentifiedImageError

from metaforge_verification.adapters.base import CheckResult, CheckUnavailable, InvalidEvidence
from metaforge_verification.contracts import Evidence, Quantity, fingerprint

MAX_PIXELS = 4_000_000


def load_png(data):
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "PNG" or im.width * im.height > MAX_PIXELS:
                raise InvalidEvidence("Expected PNG with no more than 4 million pixels")
            im.load()
            return im.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidEvidence("Invalid or excessive image") from exc


def controlled_images(request, artifacts):
    visual = request.visual
    if visual is None:
        raise CheckUnavailable("No controlled visual comparison supplied")
    if visual.candidate_revision_id != request.twin.revision_id:
        raise InvalidEvidence("Stale visual candidate: revision mismatch")
    if visual.reference_context_sha256 != visual.candidate_context_sha256:
        raise InvalidEvidence("Camera/render contexts differ; comparison is not qualified")
    images = [load_png(artifacts.read(a.artifact_id)) for a in (visual.reference, visual.candidate)]
    if images[0].size != images[1].size:
        raise InvalidEvidence("Image dimensions differ")
    return images


class PixelDifference:
    rule_id = "visual.pixel_difference"
    module = "artifact"
    fidelity = "F1"

    def run(self, request, artifacts):
        images = controlled_images(request, artifacts)
        visual = request.visual
        diff = ImageChops.difference(*images)
        # Count changes in any channel, including alpha; getbbox's default alpha-only
        # behavior must not discard RGB-only changes.
        mask = diff.getchannel(0)
        for channel in diff.split()[1:]:
            mask = ImageChops.lighter(mask, channel)
        changed = sum(count for value, count in enumerate(mask.histogram()) if value)
        value = Quantity(value=changed / (images[0].width * images[0].height), unit="dimensionless")
        fp = fingerprint(request)
        ev = Evidence(
            evidence_id=f"ev-visual-{fp[:16]}",
            method=self.rule_id,
            fidelity="F1",
            input_fingerprint=fp,
            measurements={"changed_pixel_fraction": value},
            source_refs=[
                visual.approval_ref,
                visual.reference.artifact_id,
                visual.candidate.artifact_id,
            ],
            assumptions=[
                "Controlled PNG comparison only; no semantic or engineering correctness.",
                "Capture identity is supplied and integrity-bound; not independently attested.",
            ],
            details={
                "changed_pixels": changed,
                "difference_bbox": mask.getbbox(),
                "render_context_sha256": visual.candidate_context_sha256,
            },
        )
        return CheckResult(value, ev)


class RegionSilhouette:
    """Worst regional foreground-mask mismatch. Regions/visibility require independent approval."""

    rule_id = "visual.region_silhouette"
    module = "artifact"
    fidelity = "F1"

    def run(self, request, artifacts):
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise CheckUnavailable("OpenCV visual extra is not installed") from exc
        if request.visual_features is None:
            raise CheckUnavailable("Approved visible-feature regions and background required")
        images = controlled_images(request, artifacts)
        arrays = [np.array(im.convert("RGB"), dtype=np.int16) for im in images]
        features = request.visual_features
        background = np.array(features.background_rgb, dtype=np.int16)
        masks = [
            (np.max(np.abs(a - background), axis=2) > features.background_tolerance).astype("uint8")
            for a in arrays
        ]
        if any(not bool(np.all(np.array(im)[:, :, 3] == 255)) for im in images):
            raise InvalidEvidence("Silhouette checks require opaque controlled PNG captures")
        regions = []
        for region in features.regions:
            if not region.visible:
                raise CheckUnavailable(f"Feature region is occluded/unqualified: {region.id}")
            x0, y0, x1, y1 = region.box
            if x1 > images[0].width or y1 > images[0].height:
                raise InvalidEvidence("Feature region is outside the capture frame")
            a, b = [m[y0:y1, x0:x1] for m in masks]
            reference_area = cv2.countNonZero(a)
            if reference_area < 4:
                raise InvalidEvidence(
                    f"Reference region lacks an observable foreground: {region.id}"
                )
            union = cv2.countNonZero(cv2.bitwise_or(a, b))
            difference = cv2.countNonZero(cv2.bitwise_xor(a, b))
            regions.append(
                {
                    "region_id": region.id,
                    "box": region.box,
                    "component_id": region.component_id,
                    "mismatch_fraction": difference / union,
                    "reference_foreground_pixels": reference_area,
                    "candidate_foreground_pixels": cv2.countNonZero(b),
                    "review_status": "automated_observation",
                }
            )
        value = Quantity(value=max(r["mismatch_fraction"] for r in regions), unit="dimensionless")
        fp = fingerprint(request)
        return CheckResult(
            value,
            Evidence(
                evidence_id=f"ev-region-{fp[:16]}",
                method=self.rule_id,
                fidelity=self.fidelity,
                input_fingerprint=fp,
                measurements={"worst_region_mismatch": value},
                source_refs=[
                    request.visual.approval_ref,
                    request.visual.reference.sha256,
                    request.visual.candidate.sha256,
                ],
                tool_version=f"opencv/{cv2.__version__}",
                details={"regions": regions},
                assumptions=[
                    "Foreground masks in independently approved visible regions.",
                    "No semantic, hidden-part, physical dimension or aesthetic claim.",
                    "Visibility/reference approval is asserted unless baseline-managed.",
                ],
            ),
        )
