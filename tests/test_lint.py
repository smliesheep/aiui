from __future__ import annotations

from aiui.config import Settings
from aiui.planning.lint import ERROR, WARN, lint_plan
from aiui.planning.models import (
    ActionType,
    Assertion,
    PlanStep,
    RiskLevel,
    TargetHints,
    TargetSpec,
    TestPlan,
)

SETTINGS = Settings(llm_mode="fake", allowed_hosts="localhost")


def _plan(steps) -> TestPlan:
    return TestPlan(plan_id="lint", base_url="http://localhost", steps=steps)


def _nav() -> PlanStep:
    return PlanStep(id="s1", action=ActionType.NAVIGATE, value="/")


def test_target_without_hints_warns():
    plan = _plan([
        _nav(),
        PlanStep(id="s2", action=ActionType.CLICK, target=TargetSpec(description="登录按钮")),
        PlanStep(id="s3", action=ActionType.ASSERT_TEXT,
                 assertion=Assertion(kind="contains", expected="欢迎")),
    ])
    issues = lint_plan(plan, SETTINGS)
    assert any(i.level == WARN and "hints" in i.message for i in issues)


def test_assert_with_only_container_suggests_null_target():
    plan = _plan([
        _nav(),
        PlanStep(id="s2", action=ActionType.ASSERT_TEXT,
                 target=TargetSpec(description="页面提示区域",
                                   hints=TargetHints(container_text="toast")),
                 assertion=Assertion(kind="contains", expected="成功")),
    ])
    issues = lint_plan(plan, SETTINGS)
    assert any("container_text" in i.message and "target=null" in i.suggestion for i in issues)


def test_no_assertions_warns():
    plan = _plan([
        _nav(),
        PlanStep(id="s2", action=ActionType.CLICK,
                 target=TargetSpec(description="登录按钮", hints=TargetHints(text="Login"))),
    ])
    issues = lint_plan(plan, SETTINGS)
    assert any("没有任何断言" in i.message for i in issues)


def test_unapproved_high_risk_warns():
    plan = _plan([
        _nav(),
        PlanStep(id="s2", action=ActionType.CLICK, risk=RiskLevel.L3,
                 target=TargetSpec(description="确认转账", hints=TargetHints(text="Confirm"))),
    ])
    issues = lint_plan(plan, SETTINGS)
    assert any(i.level == WARN and "未签核" in i.message for i in issues)


def test_hard_error_is_error_level():
    plan = _plan([
        _nav(),
        PlanStep(id="s2", action=ActionType.INPUT,
                 target=TargetSpec(description="用户名输入框",
                                   hints=TargetHints(label="Username"))),
    ])
    issues = lint_plan(plan, SETTINGS)
    assert any(i.level == ERROR for i in issues)


def test_clean_plan_has_no_issues():
    plan = _plan([
        _nav(),
        PlanStep(id="s2", action=ActionType.INPUT, value="alice",
                 target=TargetSpec(description="用户名输入框",
                                   hints=TargetHints(label="Username", name="username"))),
        PlanStep(id="s3", action=ActionType.CLICK,
                 target=TargetSpec(description="登录按钮", hints=TargetHints(text="Login"))),
        PlanStep(id="s4", action=ActionType.ASSERT_TEXT,
                 assertion=Assertion(kind="contains", expected="欢迎")),
    ])
    assert lint_plan(plan, SETTINGS) == []


def test_short_description_warns():
    plan = _plan([
        _nav(),
        PlanStep(id="s2", action=ActionType.CLICK,
                 target=TargetSpec(description="按钮", hints=TargetHints(text="OK"))),
        PlanStep(id="s3", action=ActionType.ASSERT_TEXT,
                 assertion=Assertion(kind="exists")),
    ])
    issues = lint_plan(plan, SETTINGS)
    assert any("描述过短" in i.message for i in issues)
