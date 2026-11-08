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


class PixelDifference:
    rule_id = "visual.pixel_difference"
    module = "artifact"
    fidelity = "F1"

    def run(self, request, artifacts):
        visual = request.visual
        if visual is None:
            raise CheckUnavailable("No controlled visual comparison supplied")
        if visual.candidate_revision_id != request.twin.revision_id:
            raise InvalidEvidence("Stale visual candidate: revision mismatch")
        if visual.reference_context_sha256 != visual.candidate_context_sha256:
            raise InvalidEvidence("Camera/render contexts differ; comparison is not qualified")
        images = [
            load_png(artifacts.read(a.artifact_id)) for a in (visual.reference, visual.candidate)
        ]
        if images[0].size != images[1].size:
            raise InvalidEvidence("Image dimensions differ")
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
