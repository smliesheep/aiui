"""10 类动作的实现。每个动作只做「动作本身」，证据由 evidence 统一采集。"""

from __future__ import annotations

import time
from urllib.parse import urljoin

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select

from aiui.actions.base import BaseAction, StepResult, wait_element, wait_until
from aiui.errors import ActionError
from aiui.logging import get_logger
from aiui.planning.models import ActionType, Assertion

log = get_logger(__name__)


class NavigateAction(BaseAction):
    name = "navigate"
    action = ActionType.NAVIGATE

    def perform(self, ctx, es, loc) -> None:
        url = self.value(ctx, es.step)
        if not url.startswith(("http://", "https://", "file://")):
            url = urljoin(ctx.plan.base_url, url)
        ctx.driver.get(url)
        wait_until(lambda: ctx.driver.execute_script("return document.readyState") == "complete",
                   es.wait_ms)

    def postcheck(self, ctx, es, loc) -> StepResult:
        return StepResult(detail=f"打开 {ctx.driver.current_url}")


class ClickAction(BaseAction):
    name = "click"
    action = ActionType.CLICK

    def perform(self, ctx, es, loc) -> None:
        el = self.element(ctx, es, loc, want="clickable")
        try:
            ctx.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", el
            )
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.1)
        try:
            el.click()
        except Exception as exc:  # noqa: BLE001 - 被遮挡时降级 JS click
            log.warning("%s 原生点击失败（%s），降级 JS click", es.step.id, exc)
            ctx.driver.execute_script("arguments[0].click();", el)

    def postcheck(self, ctx, es, loc) -> StepResult:
        return StepResult(detail="clicked")


class InputAction(BaseAction):
    name = "input"
    action = ActionType.INPUT

    def perform(self, ctx, es, loc) -> None:
        el = self.element(ctx, es, loc, want="visible")
        text = self.value(ctx, es.step)
        try:
            el.clear()
        except Exception:  # noqa: BLE001
            pass
        el.send_keys(text)
        try:
            if el.get_attribute("value") in (None, ""):
                el.send_keys(Keys.END)
        except Exception:  # noqa: BLE001
            pass

    def postcheck(self, ctx, es, loc) -> StepResult:
        el = self.element(ctx, es, loc, want="visible")
        actual = el.get_attribute("value") or ""
        expected = self.value(ctx, es.step)
        ok = expected == actual or expected.replace(" ", "") == actual.replace(" ", "")
        return StepResult(
            detail=f"输入值回读 {'一致' if ok else '不一致'}：{actual!r}",
            extra={"expected": expected, "actual": actual, "match": ok},
        )


class SelectAction(BaseAction):
    name = "select"
    action = ActionType.SELECT

    def perform(self, ctx, es, loc) -> None:
        el = self.element(ctx, es, loc, want="visible")
        text = self.value(ctx, es.step)
        sel = Select(el)
        try:
            sel.select_by_visible_text(text)
        except Exception:  # noqa: BLE001
            sel.select_by_value(text)

    def postcheck(self, ctx, es, loc) -> StepResult:
        el = self.element(ctx, es, loc, want="present")
        return StepResult(detail=f"选中 {Select(el).first_selected_option.text!r}",
                          extra={"selected": Select(el).first_selected_option.text})


class AssertTextAction(BaseAction):
    name = "assert_text"
    action = ActionType.ASSERT_TEXT

    def _actual(self, ctx, es, loc) -> str:
        if loc is not None:
            el = self.element(ctx, es, loc, want="present")
            return (el.text or el.get_attribute("value") or "").strip()
        body = ctx.driver.find_element("tag name", "body")
        return (body.text or "").strip()

    def perform(self, ctx, es, loc) -> None:
        assertion: Assertion = es.step.assertion  # type: ignore[assignment]
        expected = ctx.render(assertion.expected) or ""
        deadline = time.time() + es.wait_ms / 1000
        actual = ""
        while True:
            try:
                actual = self._actual(ctx, es, loc)
            except Exception:  # noqa: BLE001 - 元素可能正在重绘
                actual = ""
            if _compare(assertion.kind, actual, expected):
                break
            if time.time() >= deadline:
                es.assert_diff = {"kind": assertion.kind, "expected": expected,
                                  "actual": actual[:500], "match": False}
                raise ActionError(
                    f"{es.step.id}: 文本断言超时 kind={assertion.kind} "
                    f"expected={expected!r} actual={actual[:200]!r}"
                )
            time.sleep(0.2)
        es.assert_diff = {"kind": assertion.kind, "expected": expected,
                          "actual": actual[:500], "match": True}

    def postcheck(self, ctx, es, loc) -> StepResult:
        d = getattr(es, "assert_diff", {})
        return StepResult(detail=f"断言通过：{d.get('expected')!r}", extra=d)


class AssertElementAction(BaseAction):
    name = "assert_element"
    action = ActionType.ASSERT_ELEMENT

    def perform(self, ctx, es, loc) -> None:
        assertion = es.step.assertion
        kind = assertion.kind if assertion else "exists"
        el = wait_element(ctx.driver, loc.locator, loc.marker, es.wait_ms, want="present")
        if kind == "exists" and el is None:
            raise ActionError(f"{es.step.id}: 期望元素存在，但没找到")
        if kind == "visible" and (el is None or not el.is_displayed()):
            raise ActionError(f"{es.step.id}: 期望元素可见，但不可见/不存在")
        if kind == "enabled" and (el is None or not el.is_enabled()):
            raise ActionError(f"{es.step.id}: 期望元素可用，但被禁用/不存在")
        es.assert_diff = {"kind": kind, "expected": True, "actual": True, "match": True}

    def postcheck(self, ctx, es, loc) -> StepResult:
        return StepResult(detail="元素断言通过", extra=getattr(es, "assert_diff", {}))


class ExtractAction(BaseAction):
    name = "extract"
    action = ActionType.EXTRACT

    def perform(self, ctx, es, loc) -> None:
        el = self.element(ctx, es, loc, want="present")
        raw = self.value(ctx, es.step)
        name, _, attr = raw.partition("@")
        if attr:
            val = el.get_attribute(attr) or ""
        elif name.lower() == "value":
            val = el.get_attribute("value") or ""
        else:
            val = (el.text or "").strip()
        ctx.vars[name] = val
        es.assert_diff = {"var": name, "value": val[:200]}

    def postcheck(self, ctx, es, loc) -> StepResult:
        d = getattr(es, "assert_diff", {})
        return StepResult(detail=f"提取 {d.get('var')}={d.get('value')!r}", extra=d)


class ScreenshotAction(BaseAction):
    name = "screenshot"
    action = ActionType.SCREENSHOT

    def perform(self, ctx, es, loc) -> None:
        ctx.want_screenshot = True

    def postcheck(self, ctx, es, loc) -> StepResult:
        return StepResult(detail="已标记截图")


class WaitAction(BaseAction):
    name = "wait"
    action = ActionType.WAIT

    def perform(self, ctx, es, loc) -> None:
        if loc is not None:
            el = wait_element(ctx.driver, loc.locator, loc.marker, es.wait_ms, want="present")
            if el is None:
                raise ActionError(f"{es.step.id}: 等待元素出现超时")
        else:
            ms = int(self.value(ctx, es.step) or 1000)
            time.sleep(min(ms, 30000) / 1000)

    def postcheck(self, ctx, es, loc) -> StepResult:
        return StepResult(detail="wait ok")


class ScrollAction(BaseAction):
    name = "scroll"
    action = ActionType.SCROLL

    def perform(self, ctx, es, loc) -> None:
        if loc is not None:
            el = self.element(ctx, es, loc, want="present")
            ctx.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        else:
            offset = int(self.value(ctx, es.step) or 500)
            ctx.driver.execute_script(f"window.scrollBy(0, {offset});")

    def postcheck(self, ctx, es, loc) -> StepResult:
        return StepResult(detail="scrolled")


def _compare(kind: str, actual: str, expected: str) -> bool:
    if kind == "contains":
        return expected in actual
    if kind == "equals":
        return actual.strip() == expected.strip()
    if kind == "regex":
        import re

        return re.search(expected, actual) is not None
    if kind == "exists":
        return bool(actual)
    return True
