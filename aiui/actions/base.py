"""动作基类与通用等待工具。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from aiui.errors import ActionError
from aiui.locator import collector
from aiui.logging import get_logger
from aiui.planning.models import ActionType, PlanStep

log = get_logger(__name__)


@dataclass
class StepResult:
    status: str = "passed"
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def wait_until(fn, timeout_ms: int, interval: float = 0.2) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            if fn():
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(interval)
    return False


def wait_element(driver, locator: str, marker: str | None, timeout_ms: int,
                 want: str = "visible"):
    def _probe():
        el = collector.locate_element(driver, locator, marker)
        if el is None:
            return None
        if want == "present":
            return el
        if not el.is_displayed():
            return None
        if want == "clickable" and not el.is_enabled():
            return None
        return el

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            el = _probe()
            if el is not None:
                return el
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    return None


class BaseAction:
    name: str = ""
    action: ActionType

    def __init__(self, settings=None) -> None:
        self.settings = settings

    # 子类按需覆盖
    def precheck(self, ctx, es, loc) -> None:
        pass

    def perform(self, ctx, es, loc) -> None:
        raise NotImplementedError

    def postcheck(self, ctx, es, loc) -> StepResult:
        return StepResult()

    # 统一入口：四段式
    def run(self, ctx, es, loc) -> StepResult:
        self.precheck(ctx, es, loc)
        self.perform(ctx, es, loc)
        return self.postcheck(ctx, es, loc)

    # ------------------------------------------------------------------ 工具
    def element(self, ctx, es, loc, want: str = "visible"):
        if loc is None:
            raise ActionError(f"{es.step.id}: 该动作需要元素定位结果")
        el = wait_element(ctx.driver, loc.locator, loc.marker, es.wait_ms, want)
        if el is None:
            raise ActionError(
                f"{es.step.id}: 等待元素超时（{es.wait_ms}ms）locator={loc.locator}"
            )
        return el

    def value(self, ctx, step: PlanStep) -> str:
        rendered = ctx.render(step.value)
        if rendered is None:
            raise ActionError(f"{step.id}: 缺少 value")
        return rendered
