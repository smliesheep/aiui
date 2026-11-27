from __future__ import annotations

from aiui.actions.registry import ACTION_REGISTRY
from aiui.config import Settings
from aiui.guardrail.policy import Guardrail
from aiui.planning.compiler import compile_plan
from aiui.planning.models import (
    ActionType,
    PlanStep,
    RiskLevel,
    TargetHints,
    TargetSpec,
    TestPlan,
)

SETTINGS = Settings(llm_mode="fake", allowed_hosts="localhost")


def test_all_actions_registered():
    assert len(ACTION_REGISTRY) == 10
    assert set(ACTION_REGISTRY) == set(ActionType)


def test_compile_assigns_classes_and_hash():
    plan = TestPlan(plan_id="p", base_url="http://localhost", steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.CLICK,
                 target=TargetSpec(description="登录按钮", hints=TargetHints(text="Login"))),
    ])
    steps = compile_plan(plan, SETTINGS)
    assert steps[0].action_cls.__name__ == "NavigateAction"
    assert steps[1].action_cls.__name__ == "ClickAction"
    assert plan.plan_hash


def test_compile_overrides_model_risk():
    plan = TestPlan(plan_id="p", base_url="http://localhost", steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.INPUT, risk=RiskLevel.L0, value="100",
                 target=TargetSpec(description="转账金额", hints=TargetHints(label="Amount"))),
    ])
    steps = compile_plan(plan, SETTINGS, Guardrail(SETTINGS))
    assert steps[1].risk is RiskLevel.L3


def test_compile_collects_var_refs():
    plan = TestPlan(plan_id="p", base_url="http://localhost", steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.INPUT, value="${USER}",
                 target=TargetSpec(description="用户名")),
    ])
    steps = compile_plan(plan, SETTINGS)
    assert steps[1].var_refs == ["USER"]


def test_executable_step_describe():
    plan = TestPlan(plan_id="p", base_url="http://localhost", steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.CLICK, target=TargetSpec(description="登录按钮")),
    ])
    steps = compile_plan(plan, SETTINGS)
    assert "click" in steps[1].describe() and "登录按钮" in steps[1].describe()
