from __future__ import annotations

import pytest

from aiui.config import Settings
from aiui.errors import ClarificationRequired
from aiui.planning.clarify import gate
from aiui.planning.models import (
    ActionType,
    PlanStep,
    TargetHints,
    TargetSpec,
    TestPlan,
)

SETTINGS = Settings(llm_mode="fake", allowed_hosts="localhost")


def _plan_with_pending() -> TestPlan:
    return TestPlan(plan_id="p", base_url="http://localhost", steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.INPUT, value="${AMOUNT}",
                 target=TargetSpec(description="备注输入框",
                                   hints=TargetHints(label="Remark"))),
    ])


def test_fill_missing_value_interactively():
    plan = _plan_with_pending()
    answers = iter(["100"])
    plan2, transcript = gate(plan, SETTINGS, set(), interactive=True,
                             input_fn=lambda q: next(answers))
    assert plan2.steps[1].value == "100"
    assert any("filled" in t for t in transcript)


def test_non_interactive_raises():
    plan = _plan_with_pending()
    with pytest.raises(ClarificationRequired):
        gate(plan, SETTINGS, set(), interactive=False)


def test_high_risk_approval():
    plan = TestPlan(plan_id="p", base_url="http://localhost", steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.CLICK,
                 target=TargetSpec(description="确认转账按钮",
                                   hints=TargetHints(text="Confirm Transfer"))),
    ])
    plan2, _ = gate(plan, SETTINGS, set(), interactive=True, input_fn=lambda q: "y")
    assert "s2" in plan2.approved_high_risk


def test_high_risk_rejected_leaves_unapproved():
    plan = TestPlan(plan_id="p", base_url="http://localhost", steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.CLICK,
                 target=TargetSpec(description="确认转账按钮")),
    ])
    plan2, _ = gate(plan, SETTINGS, set(), interactive=True, input_fn=lambda q: "n")
    assert plan2.approved_high_risk == []
