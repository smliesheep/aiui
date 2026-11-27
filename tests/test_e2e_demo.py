"""端到端冒烟：本地 demo.html + 真实 Chrome + 三级定位 + 护栏放行。

默认执行；设置 AIUI_SKIP_E2E=1 可跳过（无浏览器环境）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aiui.config import Settings
from aiui.executor.runner import Runner
from aiui.llm.fake import FakeGateway
from aiui.planning.models import (
    ActionType,
    Assertion,
    PlanStep,
    RiskLevel,
    TargetHints,
    TargetSpec,
    TestPlan,
)

pytestmark = pytest.mark.skipif(os.environ.get("AIUI_SKIP_E2E") == "1",
                                reason="AIUI_SKIP_E2E=1")

DEMO = Path(__file__).parent / "pages" / "demo.html"


def _plan(url: str) -> TestPlan:
    return TestPlan(
        plan_id="demo_transfer", title="Demo 登录 + 转账", requirement="登录并转账 100",
        base_url=url,
        steps=[
            PlanStep(id="s1", action=ActionType.NAVIGATE, value=url),
            PlanStep(id="s2", action=ActionType.INPUT, value="alice", risk=RiskLevel.L1,
                     target=TargetSpec(description="用户名输入框",
                                       hints=TargetHints(label="Username", placeholder="Username"))),
            PlanStep(id="s3", action=ActionType.INPUT, value="secret", risk=RiskLevel.L1,
                     target=TargetSpec(description="密码输入框",
                                       hints=TargetHints(label="Password", placeholder="Password"))),
            PlanStep(id="s4", action=ActionType.CLICK, risk=RiskLevel.L2,
                     target=TargetSpec(description="登录按钮", hints=TargetHints(text="Login"))),
            PlanStep(id="s5", action=ActionType.ASSERT_TEXT,
                     assertion=Assertion(kind="contains", expected="Login successful")),
            PlanStep(id="s6", action=ActionType.EXTRACT, value="balance_before",
                     target=TargetSpec(description="余额数字",
                                       hints=TargetHints(text="1,250.00"))),
            PlanStep(id="s7", action=ActionType.INPUT, value="11111111", risk=RiskLevel.L1,
                     target=TargetSpec(description="收款账号输入框",
                                       hints=TargetHints(label="Payee Account",
                                                         placeholder="Payee Account"))),
            PlanStep(id="s8", action=ActionType.INPUT, value="100",
                     target=TargetSpec(description="转账金额输入框",
                                       hints=TargetHints(label="Amount", placeholder="Amount"))),
            PlanStep(id="s9", action=ActionType.CLICK,
                     target=TargetSpec(description="确认转账按钮",
                                       hints=TargetHints(text="Confirm Transfer"))),
            PlanStep(id="s10", action=ActionType.ASSERT_TEXT,
                     assertion=Assertion(kind="contains", expected="Transfer successful")),
            PlanStep(id="s11", action=ActionType.ASSERT_TEXT,
                     assertion=Assertion(kind="contains", expected="1,150.00")),
        ],
        approved_high_risk=["s8", "s9"],
    )


def test_demo_end_to_end(tmp_path: Path):
    url = DEMO.resolve().as_uri()
    settings = Settings(
        llm_mode="fake", headless=True, allowed_hosts="",
        artifacts_dir=tmp_path / "artifacts", cache_db=tmp_path / "locator.db",
        screenshot_on_success=False,
    )
    plan = _plan(url)
    summary = Runner(settings, FakeGateway()).run(
        plan, allow_high_risk={"s8", "s9"}, variables={}
    )
    assert summary.status == "passed", summary.error
    assert summary.passed == 11
    assert summary.blocked == 0
    assert Path(summary.artifacts, "steps", "s9", "03-locate.json").exists()


def test_high_risk_blocks_without_approval(tmp_path: Path):
    url = DEMO.resolve().as_uri()
    settings = Settings(
        llm_mode="fake", headless=True, allowed_hosts="",
        artifacts_dir=tmp_path / "artifacts", cache_db=tmp_path / "locator.db",
    )
    plan = _plan(url)
    plan.approved_high_risk = []
    summary = Runner(settings, FakeGateway()).run(plan, allow_high_risk=set())
    assert summary.status == "blocked"
    assert summary.blocked == 1
