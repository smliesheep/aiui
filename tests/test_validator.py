from __future__ import annotations

from aiui.config import Settings
from aiui.planning.models import (
    ActionType,
    Assertion,
    PlanStep,
    RiskLevel,
    TargetHints,
    TargetSpec,
    TestPlan,
)
from aiui.planning.validator import apply_auto_fixes, validate


def _t(desc="按钮", **hints):
    return TargetSpec(description=desc, hints=TargetHints(**hints))


def _settings(**kw) -> Settings:
    base = {"llm_mode": "fake", "allowed_hosts": "localhost"}
    base.update(kw)
    return Settings(**base)


def test_auto_fix_prepends_navigate(make_plan):
    plan = make_plan(steps=[PlanStep(id="s1", action=ActionType.CLICK, target=_t())])
    fixes = apply_auto_fixes(plan)
    assert fixes and plan.steps[0].action is ActionType.NAVIGATE


def test_duplicate_ids(make_plan):
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s1", action=ActionType.SCREENSHOT),
    ])
    res = validate(plan, _settings())
    assert any(v.rule == "unique_step_id" for v in res.errors)


def test_input_requires_value(make_plan):
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.INPUT, target=_t("用户名")),
    ])
    res = validate(plan, _settings())
    assert any(v.rule == "required_value" and v.step_id == "s2" for v in res.errors)


def test_host_allowlist(make_plan):
    plan = make_plan(base_url="http://evil.example.com")
    res = validate(plan, _settings())
    assert any(v.rule == "host_allowlist" for v in res.errors)


def test_undefined_var_outside_input_is_error(make_plan):
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.ASSERT_TEXT,
                 assertion=Assertion(kind="contains", expected="${NOPE}")),
    ])
    res = validate(plan, _settings())
    assert any(v.rule == "undefined_var" for v in res.errors)


def test_pending_var_in_input_is_warning(make_plan):
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.INPUT, target=_t("金额"), value="${AMOUNT}"),
    ])
    res = validate(plan, _settings())
    assert not [v for v in res.errors if v.rule == "undefined_var"]
    assert any(v.rule == "pending_value" and v.severity == "warn" for v in res.violations)


def test_extract_defines_var(make_plan):
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.EXTRACT, target=_t("余额"), value="BAL"),
        PlanStep(id="s3", action=ActionType.INPUT, target=_t("金额"), value="${BAL}"),
    ])
    res = validate(plan, _settings())
    assert not res.errors


def test_assert_before_navigate(make_plan):
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.SCREENSHOT),
        PlanStep(id="s2", action=ActionType.ASSERT_TEXT,
                 assertion=Assertion(kind="contains", expected="x")),
    ])
    res = validate(plan, _settings())
    assert any(v.rule == "navigate_first" or v.rule == "order_sanity" for v in res.errors)


def test_risk_consistency_warns(make_plan):
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.ASSERT_TEXT, risk=RiskLevel.L3,
                 assertion=Assertion(kind="exists")),
    ])
    res = validate(plan, _settings())
    assert any(v.rule == "risk_consistency" and v.severity == "warn" for v in res.violations)


def test_valid_plan_passes(make_plan):
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/login"),
        PlanStep(id="s2", action=ActionType.INPUT, target=_t("用户名"), value="alice"),
        PlanStep(id="s3", action=ActionType.CLICK, target=_t("登录")),
        PlanStep(id="s4", action=ActionType.ASSERT_TEXT,
                 assertion=Assertion(kind="contains", expected="欢迎")),
    ])
    assert validate(plan, _settings()).ok
