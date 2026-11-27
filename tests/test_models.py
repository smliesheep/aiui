from __future__ import annotations

import pytest
from pydantic import ValidationError

from aiui.planning.models import (
    ActionType,
    Assertion,
    PlanStep,
    RiskLevel,
    TargetHints,
    TargetSpec,
    TestPlan,
    render_vars,
    scan_vars,
    slugify,
)


def test_action_whitelist_is_ten():
    assert len(ActionType) == 10
    assert {a.value for a in ActionType} == {
        "navigate", "click", "input", "select", "assert_text",
        "assert_element", "extract", "screenshot", "wait", "scroll",
    }


def test_plan_hash_changes_with_content(make_plan):
    plan = make_plan()
    h1 = plan.compute_hash()
    assert len(h1) == 16
    plan.steps[0].value = "/login"
    assert plan.compute_hash() != h1


def test_plan_hash_excludes_itself(make_plan):
    plan = make_plan()
    plan.plan_hash = "deadbeef"
    assert plan.compute_hash() == make_plan().compute_hash()


def test_render_vars_only_literal():
    assert render_vars("${USER}/${PASS}", {"USER": "alice", "PASS": "p"}) == "alice/p"
    # 不支持表达式求值（防注入）
    assert render_vars("${1+1}", {}) == "${1+1}"
    assert scan_vars("${A} + ${B}") == ["A", "B"]


def test_assertion_requires_expected():
    with pytest.raises(ValidationError):
        Assertion(kind="contains")
    assert Assertion(kind="exists").expected is None


def test_step_id_pattern():
    with pytest.raises(ValidationError):
        PlanStep(id="1-bad", action=ActionType.CLICK)


def test_empty_steps_rejected():
    with pytest.raises(ValidationError):
        TestPlan(plan_id="x", steps=[])


def test_slugify_keeps_chinese():
    assert slugify("登录 测试!") == "登录_测试"


def test_target_spec_description_min_length():
    with pytest.raises(ValidationError):
        TargetSpec(description="a")


def test_risk_rank():
    assert RiskLevel.L3.rank > RiskLevel.L0.rank
