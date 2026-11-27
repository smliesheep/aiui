"""动作注册表：枚举 → 类，静态导入，没有任何反射/动态加载。"""

from __future__ import annotations

from aiui.actions.basic import (
    AssertElementAction,
    AssertTextAction,
    ClickAction,
    ExtractAction,
    InputAction,
    NavigateAction,
    ScreenshotAction,
    ScrollAction,
    SelectAction,
    WaitAction,
)
from aiui.planning.models import ActionType

ACTION_REGISTRY = {
    ActionType.NAVIGATE: NavigateAction,
    ActionType.CLICK: ClickAction,
    ActionType.INPUT: InputAction,
    ActionType.SELECT: SelectAction,
    ActionType.ASSERT_TEXT: AssertTextAction,
    ActionType.ASSERT_ELEMENT: AssertElementAction,
    ActionType.EXTRACT: ExtractAction,
    ActionType.SCREENSHOT: ScreenshotAction,
    ActionType.WAIT: WaitAction,
    ActionType.SCROLL: ScrollAction,
}
