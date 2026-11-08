"""Conservative dependency invalidation and finding comparison; no unqualified cache reuse."""

from metaforge_verification.contracts import VerificationRequest, fingerprint


def dependencies(request, rule):
    def facts(*names):
        return {n: request.twin.facts.get(n) for n in names}

    if rule == "device.power_budget":
        return facts("supply_power", "load_power")
    if rule == "device.thermal_estimate":
        return facts("ambient_temperature", "dissipated_power", "thermal_resistance")
    if rule == "device.thermal_worst_case":
        return {
            "bounds": request.thermal_bounds,
            "nominal": facts("ambient_temperature", "dissipated_power", "thermal_resistance"),
        }
    if rule.startswith("geometry.step_"):
        return request.cad
    if rule == "geometry.declared_box_fit":
        return facts(*(f"{kind}_{axis}" for kind in ("cavity", "pcb") for axis in ("x", "y", "z")))
    if rule.startswith("electrical."):
        return request.circuit
    if rule == "system.circuit_thermal_temperature":
        return {
            "circuit": request.circuit,
            "boundary": facts("ambient_temperature", "thermal_resistance"),
        }
    if rule == "scenario.device_behavior":
        return {"model": request.behavior_model, "scenarios": request.scenarios}
    if rule.startswith("visual."):
        return {
            "visual": request.visual,
            "regions": request.visual_features,
            "revision": request.twin.revision_id,
        }
    return request


def digest(value):
    from pydantic_core import to_jsonable_python

    return fingerprint(to_jsonable_python(value))


def compare_jobs(previous, current):
    if previous["report"] is None or current["report"] is None:
        raise ValueError("Both revisions require completed reports")
    a, b = [VerificationRequest.model_validate(row["request"]) for row in (previous, current)]
    if a.twin.twin_id != b.twin.twin_id:
        raise ValueError("Comparison requires the same twin")
    findings = [
        {f["requirement_id"]: f for f in row["report"]["findings"]} for row in (previous, current)
    ]
    rows = []
    for key in sorted(set(findings[0]) | set(findings[1])):
        old, new = findings[0].get(key), findings[1].get(key)
        before, after = (old or {}).get("outcome"), (new or {}).get("outcome")
        state = "persistent"
        if new is None:
            state = "removed"
        elif after in {"not_assessed", "inconclusive"}:
            state = "unassessed"
        elif old is None:
            state = "new"
        elif before != "pass" and after == "pass":
            state = "resolved"
        elif before == "pass" and after == "fail":
            state = "regression"
        rows.append({"requirement_id": key, "before": before, "after": after, "change": state})
    invalidated, changed_criteria = [], []
    old_requirements = {r.id: r for r in a.requirements}
    for r in b.requirements:
        old = old_requirements.get(r.id)
        if old is None or digest(dependencies(a, r.rule_id)) != digest(dependencies(b, r.rule_id)):
            invalidated.append(r.id)
        if old is None or digest(old) != digest(r):
            changed_criteria.append(r.id)
    return {
        "previous_id": previous["id"],
        "current_id": current["id"],
        "findings": rows,
        "invalidated_requirements": invalidated,
        "changed_criteria": changed_criteria,
        "evidence_reused": False,
        "policy": "Conservative dependency comparison; all measurements were freshly executed.",
    }
