from __future__ import annotations

import pytest

from aiui.config import Settings
from aiui.errors import HighRiskBlocked
from aiui.guardrail.policy import Guardrail
from aiui.planning.compiler import compile_plan
from aiui.planning.models import (
    ActionType,
    PlanStep,
    RiskLevel,
    TargetHints,
    TargetSpec,
)


def _settings() -> Settings:
    return Settings(llm_mode="fake", allowed_hosts="localhost")


def _step(action: ActionType, desc: str = "按钮", value: str | None = None,
          **hints) -> PlanStep:
    return PlanStep(
        id="s2", action=action, value=value,
        target=TargetSpec(description=desc, hints=TargetHints(**hints)),
    )


@pytest.mark.parametrize("phrase", [
    "确认转账", "立即支付", "删除账户", "解绑银行卡", "授权登录", "发送验证码",
    "提交订单", "确认支付", "提现", "Transfer Now", "Delete Account", "Submit Order",
])
def test_high_risk_phrases_are_l3(phrase):
    guard = Guardrail(_settings())
    assert guard.classify(_step(ActionType.CLICK, phrase)) is RiskLevel.L3


def test_read_only_actions_are_l0():
    guard = Guardrail(_settings())
    assert guard.classify(PlanStep(id="s2", action=ActionType.SCREENSHOT)) is RiskLevel.L0
    assert guard.classify(PlanStep(id="s3", action=ActionType.WAIT, value="500")) is RiskLevel.L0


def test_plain_input_is_l1_and_plain_click_is_l2():
    guard = Guardrail(_settings())
    assert guard.classify(_step(ActionType.INPUT, "用户名", "alice")) is RiskLevel.L1
    assert guard.classify(_step(ActionType.CLICK, "下一步")) is RiskLevel.L2


def test_amount_input_in_transfer_context_is_l3():
    guard = Guardrail(_settings())
    step = _step(ActionType.INPUT, "转账金额输入框", "100")
    assert guard.classify(step) is RiskLevel.L3


def test_precheck_requires_double_switch(make_plan):
    settings = _settings()
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        _step(ActionType.CLICK, "确认转账"),
    ])
    guard = Guardrail(settings)
    es = compile_plan(plan, settings, guard)[1]

    with pytest.raises(HighRiskBlocked):
        guard.pre_check(es, plan, set())

    plan.approved_high_risk = ["s2"]
    with pytest.raises(HighRiskBlocked):  # 只签核、没运行时放行
        guard.pre_check(es, plan, set())

    guard.pre_check(es, plan, {"s2"})  # 双开关齐了

    plan.approved_high_risk = []
    with pytest.raises(HighRiskBlocked):  # 只放行、没签核
        guard.pre_check(es, plan, {"s2"})


def test_model_declared_risk_is_ignored(make_plan):
    """模型把高风险步骤标成 L0，编译期仍要按程序判定升级为 L3。"""
    settings = _settings()
    plan = make_plan(steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        _step(ActionType.CLICK, "确认转账"),
    ])
    plan.steps[1].risk = RiskLevel.L0
    es = compile_plan(plan, settings, Guardrail(settings))[1]
    assert es.risk is RiskLevel.L3


def test_describe_risk_lists_l3():
    settings = _settings()
    from aiui.planning.models import TestPlan

    p = TestPlan(plan_id="p", steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        _step(ActionType.CLICK, "删除用户"),
    ])
    out = Guardrail(settings).describe_risk(p)
    assert len(out) == 1 and out[0]["step_id"] == "s2"
