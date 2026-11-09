"""An authored design's form (spec 23.6): what the revision says and what the profile does.

A client whose product form is not the engine's one enclosure template says so with an
optional ``form`` on the revision. The block is additive: a revision without it, or with an
enclosure form, produces exactly the report it always did, so an older client is unaffected.

For an authored form the profile adds two advisory findings and never a blocking one. Advisory
findings cannot change a verdict, so adding a form never moves a design toward or away from
handover; it makes what was not assessed visible.
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_profile import check, only, request, revision

from metaforge_verification.profile import evaluate
from metaforge_verification.profile.contracts import ValidationRequest

LAMP_FORM = {
    "kind": "authored",
    "parts": [
        {"id": "base", "kind": "generated", "body": True},
        {"id": "arm", "kind": "generated"},
        {"id": "shade", "kind": "generated"},
        {"id": "usbc", "kind": "component"},
    ],
}


def report(form=None, **over):
    rev = revision(**over)
    if form is not None:
        rev["form"] = form
    return evaluate.validate(request(rev))


def form_findings(rep):
    return [f for f in rep.findings if f.check_id.startswith("form.")]


# -- additive: nothing changes without a form ------------------------------------


def test_a_revision_without_a_form_is_exactly_what_it_was():
    plain = report()
    assert form_findings(plain) == []
    assert "form" not in revision()


def test_an_enclosure_form_adds_nothing():
    rep = report({"kind": "enclosure", "parts": []})
    assert form_findings(rep) == []
    assert [f.id for f in rep.findings] == [f.id for f in report().findings]


# -- an authored form says what was not assessed ----------------------------------


def test_an_authored_form_reports_that_enclosure_checks_were_not_assessed():
    f = only(report(LAMP_FORM), "form.enclosure_checks")
    assert f.status == "not_assessed"
    assert f.severity == "advisory" and f.gate == "handover"
    assert "authored" in f.message and "not assessed" in f.message
    assert f.target.kind == "studio" and f.target.id == "form"
    assert f.fix is None, "nothing to fix: it is a statement, not a defect"


def test_the_enclosure_note_never_reads_as_a_pass():
    for f in form_findings(report(LAMP_FORM)):
        if f.check_id == "form.enclosure_checks":
            assert f.status != "pass"


def test_a_form_with_shaped_parts_has_no_confidence_complaint():
    assert check(report(LAMP_FORM), "form.confidence_mix") == []


def test_a_form_made_only_of_bought_parts_is_called_out_with_what_is_needed():
    only_bought = {
        "kind": "authored",
        "parts": [{"id": "usbc", "kind": "component"}, {"id": "btn", "kind": "component"}],
    }
    f = only(report(only_bought), "form.confidence_mix")
    assert f.status == "fail" and f.severity == "advisory" and f.resolver == "agent"
    assert f.fix is not None and f.fix.op == "add" and f.fix.pointer == "/form/parts"
    assert "value" not in f.fix.model_dump(), "a fix never carries a value"


def test_a_declared_primitive_counts_as_shaping_the_form():
    rep = report(
        {
            "kind": "authored",
            "parts": [{"id": "usbc", "kind": "component"}, {"id": "box", "kind": "primitive"}],
        }
    )
    assert check(rep, "form.confidence_mix") == []


# -- a form never moves the verdict -------------------------------------------------


@pytest.mark.parametrize(
    "form",
    [
        LAMP_FORM,
        {"kind": "authored", "parts": [{"id": "usbc", "kind": "component"}]},
        {"kind": "enclosure", "parts": []},
    ],
)
def test_a_form_does_not_change_the_verdict_the_gates_or_the_level(form):
    with_form, without = report(form), report()
    assert with_form.verdict == without.verdict == "ready_for_handover"
    assert [(g.gate, g.decision) for g in with_form.gates] == [
        (g.gate, g.decision) for g in without.gates
    ]
    assert with_form.level == without.level


def test_a_form_does_not_hide_a_real_blocker():
    rep = report(LAMP_FORM, process={"process": None, "material": None, "quantity": None})
    assert rep.verdict == "needs_agent"
    assert only(rep, "form.enclosure_checks").status == "not_assessed"


def test_the_same_input_gives_the_same_report():
    a, b = report(LAMP_FORM), report(LAMP_FORM)
    assert a.model_dump() == b.model_dump()
    assert a.input_fingerprint == b.input_fingerprint
    assert a.input_fingerprint != report().input_fingerprint, "the form is part of the input"


def test_scope_can_address_the_form():
    rep = evaluate.validate(
        ValidationRequest.model_validate(
            {
                "revision": {**revision(), "form": LAMP_FORM},
                "scope": [{"kind": "studio", "id": "form"}],
            }
        )
    )
    assert {f.check_id for f in rep.findings} >= {"form.enclosure_checks"}


# -- the contract refuses what it cannot read ---------------------------------------


def bad(**form_over):
    rev = revision()
    rev["form"] = {**deepcopy(LAMP_FORM), **form_over}
    return rev


@pytest.mark.parametrize(
    "form_over",
    [
        {"kind": "freeform"},
        {"parts": [{"id": "a", "kind": "magic"}]},
        {"parts": [{"id": "a", "kind": "generated"}, {"id": "a", "kind": "primitive"}]},
        {
            "parts": [
                {"id": "a", "kind": "generated", "body": True},
                {"id": "b", "kind": "generated", "body": True},
            ]
        },
        {"parts": [{"id": "bad id", "kind": "generated"}]},
        {"parts": [{"id": f"p{i}", "kind": "generated"} for i in range(25)]},
        {"extra": 1},
        {"parts": [{"id": "a", "kind": "generated", "code": "return []"}]},
    ],
)
def test_a_form_the_contract_cannot_read_is_refused(form_over):
    with pytest.raises(ValidationError):
        ValidationRequest.model_validate({"revision": bad(**form_over)})


def test_an_authored_form_with_no_parts_is_refused():
    with pytest.raises(ValidationError):
        ValidationRequest.model_validate({"revision": bad(parts=[])})
