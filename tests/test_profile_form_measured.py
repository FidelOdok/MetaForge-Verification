"""What a client measured from an authored form, and the advisory findings it earns (C10c).

The client sends measurements of the drawn triangles, as estimates: how far the form tips
before it falls over, and which component boxes overlap. The profile judges balance and
overlap, says plainly when nothing was measured, and never lets any of it move a verdict:
the numbers are screening, not a verification.
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_profile import only, request, revision
from test_profile_form import LAMP_FORM, form_findings

from metaforge_verification.profile import evaluate
from metaforge_verification.profile.contracts import ValidationRequest
from metaforge_verification.profile.rules import LIMITATIONS

STABLE = {
    "overhang_share": 0.12,
    "has_flat_base": True,
    "tip_angle_deg": 31.0,
    "margin_mm": 22.0,
    "overlaps": [],
}


def form_with(**over):
    form = deepcopy(LAMP_FORM)
    form["measured"] = {**STABLE, **over}
    return form


def report(form):
    rev = revision()
    rev["form"] = form
    return evaluate.validate(request(rev))


def by_check(rep, check_id):
    return [f for f in rep.findings if f.check_id == check_id]


# -- nothing measured -------------------------------------------------------------------


def test_an_authored_form_nobody_measured_says_so_and_names_what_to_do():
    f = only(report(LAMP_FORM), "form.measured")
    assert f.status == "not_assessed" and f.severity == "advisory" and f.gate == "handover"
    assert "not measured" in f.message
    assert f.fix is not None and "look" in f.fix.needs
    assert by_check(report(LAMP_FORM), "form.balance") == []
    assert by_check(report(LAMP_FORM), "form.component_overlap") == []


def test_unmeasured_never_reads_as_a_pass():
    assert all(f.status != "pass" for f in by_check(report(LAMP_FORM), "form.measured"))


# -- balance -----------------------------------------------------------------------------


def test_a_form_that_tips_late_passes_with_the_numbers():
    f = only(report(form_with()), "form.balance")
    assert f.status == "pass" and f.severity == "advisory"
    assert "31" in f.message and "22" in f.message and "uniform density" in f.message
    assert by_check(report(form_with()), "form.measured") == []


def test_a_form_that_tips_early_fails_advisory_with_a_fix_that_names_no_value():
    f = only(report(form_with(tip_angle_deg=10.0, margin_mm=4.0)), "form.balance")
    assert f.status == "fail" and f.severity == "advisory"
    assert "15 degree" in f.message and "screening" in f.message
    assert f.fix is not None and not any(c.isdigit() for c in f.fix.needs)


def test_a_form_that_would_tip_over_says_so():
    f = only(report(form_with(tip_angle_deg=-35.0, margin_mm=-4.9)), "form.balance")
    assert f.status == "fail" and "would tip over" in f.message.lower()
    assert "4.9" in f.message


def test_a_form_with_no_flat_base_is_not_assessed_not_passed():
    rep = report(form_with(has_flat_base=False, tip_angle_deg=None, margin_mm=None))
    f = only(rep, "form.balance")
    assert f.status == "not_assessed" and "no flat base" in f.message


# -- overlap -----------------------------------------------------------------------------


def test_overlapping_components_are_one_finding_each_with_the_volume():
    pair = [{"a": "usbc", "b": "base", "volume_mm3": 12.5}]
    fs = by_check(report(form_with(overlaps=pair)), "form.component_overlap")
    assert len(fs) == 1 and fs[0].status == "fail" and fs[0].severity == "advisory"
    assert "12.5" in fs[0].message and fs[0].target.kind == "part" and fs[0].target.id == "usbc"
    assert fs[0].fix is not None


def test_no_overlap_is_a_single_pass():
    fs = by_check(report(form_with()), "form.component_overlap")
    assert len(fs) == 1 and fs[0].status == "pass"


# -- they never move a verdict ------------------------------------------------------------


@pytest.mark.parametrize(
    "form",
    [
        form_with(),
        form_with(tip_angle_deg=-35.0, margin_mm=-4.9),
        form_with(overlaps=[{"a": "usbc", "b": "base", "volume_mm3": 3.0}]),
        form_with(has_flat_base=False, tip_angle_deg=None, margin_mm=None),
    ],
)
def test_measurements_never_change_the_verdict_a_gate_or_the_level(form):
    plain, measured = report(LAMP_FORM), report(form)
    assert measured.verdict == plain.verdict and measured.level == plain.level
    assert [(g.gate, g.decision) for g in measured.gates] == [
        (g.gate, g.decision) for g in plain.gates
    ]
    assert all(f.severity == "advisory" for f in form_findings(measured))


# -- the contract -------------------------------------------------------------------------


def parse(form):
    rev = revision()
    rev["form"] = form
    return ValidationRequest.model_validate(request(rev))


def test_a_revision_without_measurements_is_still_accepted():
    parse(LAMP_FORM)


@pytest.mark.parametrize(
    "bad",
    [
        {"overhang_share": 1.5},
        {"overhang_share": -0.1},
        {"tip_angle_deg": 120.0},
        {"tip_angle_deg": float("nan")},
        {"margin_mm": float("inf")},
        {"has_flat_base": False},  # a flat base is claimed absent but a tip angle is given
        {"tip_angle_deg": None},  # a flat base is claimed but there is no tip angle
        {"overlaps": [{"a": "ghost", "b": "base", "volume_mm3": 1.0}]},
        {"overlaps": [{"a": "usbc", "b": "base", "volume_mm3": -1.0}]},
        {"surprise": 1},
    ],
)
def test_a_measurement_in_the_wrong_shape_is_refused(bad):
    with pytest.raises(ValidationError):
        parse(form_with(**bad))


def test_an_enclosure_form_cannot_carry_measurements():
    with pytest.raises(ValidationError):
        parse({"kind": "enclosure", "parts": [], "measured": STABLE})


def test_the_service_says_the_numbers_are_estimates():
    text = " ".join(LIMITATIONS).lower()
    assert "estimate" in text and "overhang" in text
