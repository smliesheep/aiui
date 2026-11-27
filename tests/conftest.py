from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AIUI_LLM_MODE", "fake")

import pytest  # noqa: E402

from aiui.planning.models import (  # noqa: E402
    ActionType,
    PlanStep,
    RiskLevel,
    TargetHints,
    TargetSpec,
    TestPlan,
)


@pytest.fixture()
def make_plan():
    def _make(steps: list[PlanStep] | None = None, **kwargs) -> TestPlan:
        return TestPlan(
            plan_id=kwargs.get("plan_id", "demo"),
            title=kwargs.get("title", "示例计划"),
            requirement=kwargs.get("requirement", "打开页面"),
            base_url=kwargs.get("base_url", "http://localhost:8040"),
            steps=steps or [
                PlanStep(id="s1", action=ActionType.NAVIGATE, value="/", risk=RiskLevel.L0)
            ],
            tags=kwargs.get("tags", []),
        )

    return _make


@pytest.fixture()
def target():
    return TargetSpec(description="登录按钮", hints=TargetHints(text="Login"))
