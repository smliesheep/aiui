"""6 类证据采集：需求 / 计划 / 定位链路 / 文本 diff / 元素属性 / 截图。

目标：失败用例不用重跑，打开报告就能知道「点了哪、为什么点它、当时页面长什么样」。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from aiui.config import Settings
from aiui.evidence import masking
from aiui.locator import collector
from aiui.logging import get_logger
from aiui.planning.models import TestPlan
from aiui.reporting import allure_hooks as hooks

log = get_logger(__name__)


class EvidenceCollector:
    def __init__(self, root: Path, settings: Settings) -> None:
        self.root = Path(root)
        self.settings = settings

    # ------------------------------------------------------------------ 生命周期
    def start(self, plan: TestPlan, steps: list[Any], gateway: Any | None = None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "steps").mkdir(exist_ok=True)
        self._write(
            self.root / "00-requirement.md",
            f"# {plan.title or plan.plan_id}\n\n"
            f"**plan_id**: `{plan.plan_id}`\n\n"
            f"**plan_hash**: `{plan.plan_hash}`\n\n"
            f"**base_url**: {plan.base_url}\n\n"
            f"## 原始需求\n\n{plan.requirement}\n\n"
            f"## 前置条件\n\n" + ("\n".join(f"- {p}" for p in plan.preconditions) or "- 无") + "\n",
        )
        self._write(
            self.root / "01-plan.json",
            json.dumps(
                {
                    "plan": plan.model_dump(mode="json"),
                    "compiled": [
                        {"id": es.id, "action": es.action.value, "risk": es.risk.value,
                         "wait_ms": es.wait_ms, "var_refs": es.var_refs}
                        for es in steps
                    ],
                    "gateway": getattr(gateway, "stats", {}),
                },
                ensure_ascii=False, indent=2,
            ),
        )
        hooks.attach_file(self.root / "00-requirement.md", "00-需求")
        hooks.attach_file(self.root / "01-plan.json", "01-计划")

    def finish(self, summary: dict[str, Any]) -> None:
        self._write(self.root / "99-summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
        hooks.attach_file(self.root / "99-summary.json", "99-运行汇总")

    # ------------------------------------------------------------------ 单步
    def attach_step(self, es, loc, status: str, error: Exception | None = None,
                    driver=None, force_shot: bool = False) -> Path:
        d = self.root / "steps" / es.id
        d.mkdir(parents=True, exist_ok=True)
        step = es.step

        self._write(d / "02-step.json", json.dumps({
            "id": step.id, "action": step.action.value, "intent": step.intent,
            "risk": es.risk.value, "status": status,
            "target": step.target.model_dump(mode="json") if step.target else None,
            "value": masking.mask_text(step.value) if step.value else None,
            "error": _error_dict(error),
        }, ensure_ascii=False, indent=2))

        self._write(d / "03-locate.json", json.dumps(
            loc.to_dict() if loc else {"tier": None, "note": "该步骤不需要元素定位"},
            ensure_ascii=False, indent=2))

        diff = getattr(es, "assert_diff", None)
        self._write(d / "04-text.json", json.dumps(diff or {"note": "无断言/提取"}, ensure_ascii=False, indent=2))

        html = self._element_html(driver, loc)
        self._write(d / "05-element.html", html)

        shot = self._screenshot(driver, d, force=force_shot or status != "passed"
                                or self.settings.screenshot_on_success)
        for f in sorted(d.glob("*")):
            hooks.attach_file(f, f.name)
        if shot:
            log.debug("截图：%s", shot)
        return d

    def attach_blocked(self, es, exc: Exception, driver=None) -> Path:
        d = self.attach_step(es, None, "blocked", error=exc, driver=driver, force_shot=True)
        self._write(d / "02-blocked.md", _blocked_md(es, exc))
        return d

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.write_text(content or "", encoding="utf-8")

    def _element_html(self, driver, loc) -> str:
        if not driver or not loc:
            return "<no element>"
        try:
            el = collector.locate_element(driver, loc.locator, loc.marker)
            if el is None:
                return "<element not found at evidence time>"
            html = el.get_attribute("outerHTML") or ""
            return masking.mask_html(html)[:2048]
        except Exception as exc:  # noqa: BLE001
            return f"<failed to read element: {exc}>"

    def _screenshot(self, driver, folder: Path, force: bool) -> Path | None:
        if not driver or not force:
            return None
        try:
            png = driver.get_screenshot_as_png()
            if png:
                p = folder / "06-screenshot.png"
                p.write_bytes(png)
                return p
        except Exception as exc:  # noqa: BLE001
            log.warning("截图失败：%s", exc)
        return None


def _error_dict(error: Exception | None) -> dict[str, Any] | None:
    if error is None:
        return None
    if hasattr(error, "to_dict"):
        return error.to_dict()  # type: ignore[no-any-return]
    return {"code": type(error).__name__, "message": str(error)}


def _blocked_md(es, exc) -> str:
    rule = getattr(exc, "rule", "")
    would = getattr(exc, "would_do", "")
    return (
        f"# 高风险动作已被拦截\n\n"
        f"- 步骤：`{es.id}`\n"
        f"- 动作：`{es.step.action.value}`\n"
        f"- 目标：{es.step.target.description if es.step.target else '-'}\n"
        f"- 命中规则：{rule or '-'}\n"
        f"- 本应执行：{would or '-'}\n"
        f"- 拦截时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"> 放行需要「计划签核 + 运行时 --allow-high-risk」双开关。\n"
    )
