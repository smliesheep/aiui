"""计划静态体检：不启动浏览器，先把「明显会翻车」的地方挑出来。

运行期才发现的问题（如 toast 断言写成 container_text）在这里就是一条 warn：
    [warn] s5 断言目标只有 container_text（弱信号），建议 target=null 断言整页
"""

from __future__ import annotations

from dataclasses import dataclass

from aiui.config import Settings
from aiui.planning.models import ActionType, PlanStep, TestPlan
from aiui.planning.validator import validate

WARN, ERROR = "warn", "error"


@dataclass
class Issue:
    level: str
    message: str
    step_id: str | None = None
    suggestion: str = ""

    def line(self) -> str:
        icon = "[FAIL]" if self.level == ERROR else "[WARN]"
        where = f"{self.step_id}: " if self.step_id else ""
        text = f"{icon} {where}{self.message}"
        if self.suggestion:
            text += f"\n        -> {self.suggestion}"
        return text


def _hints_empty(step: PlanStep) -> bool:
    if not step.target:
        return False
    h = step.target.hints
    return not any([
        h.text, h.label, h.placeholder, h.aria_label, h.role,
        h.name, h.test_id, h.nearby_text, h.container_text,
    ])


def _only_container(step: PlanStep) -> bool:
    if not step.target:
        return False
    h = step.target.hints
    others = [h.text, h.label, h.placeholder, h.aria_label, h.name, h.test_id, h.nearby_text]
    return bool(h.container_text) and not any(others)


def lint_plan(plan: TestPlan, settings: Settings | None = None) -> list[Issue]:
    issues: list[Issue] = []

    # 1) 复用业务校验（硬错误）
    for v in validate(plan, settings).errors:
        issues.append(Issue(ERROR, f"[{v.rule}] {v.message}", v.step_id))

    # 2) 目标可定位性
    for s in plan.steps:
        if s.target is None:
            continue
        if _hints_empty(s):
            issues.append(Issue(
                WARN, "目标没有任何 hints，只能靠描述文本模糊匹配",
                s.id, "补 label / placeholder / text / test_id 中任意一个",
            ))
        elif _only_container(s):
            if s.action is ActionType.ASSERT_TEXT:
                issues.append(Issue(
                    WARN, "文本断言的目标只有 container_text（弱信号）",
                    s.id, "整页提示类断言建议 target=null，让框架读整页文本",
                ))
            else:
                issues.append(Issue(
                    WARN, "目标只有 container_text（弱信号），规则命中率会偏低",
                    s.id, "补 label / placeholder / text 等强信号",
                ))
        if len(s.target.description) < 4:
            issues.append(Issue(WARN, f"目标描述过短：{s.target.description!r}",
                                s.id, "描述写具体一点，如「转账金额输入框」"))

    # 3) 断言覆盖
    has_assert = any(s.action in {ActionType.ASSERT_TEXT, ActionType.ASSERT_ELEMENT}
                     for s in plan.steps)
    if not has_assert:
        issues.append(Issue(WARN, "整个计划没有任何断言，跑通≠验证正确",
                            None, "至少加一条 assert_text / assert_element"))

    # 4) 高风险未签核
    unapproved = [s.id for s in plan.steps
                  if s.risk.value == "L3" and s.id not in set(plan.approved_high_risk)]
    if unapproved:
        issues.append(Issue(
            WARN, f"高风险步骤未签核：{', '.join(unapproved)}",
            None, f"aiui approve {plan.plan_id}.json {' '.join(unapproved)}",
        ))

    return issues


def summarize(issues: list[Issue]) -> tuple[int, int]:
    return (sum(i.level == ERROR for i in issues), sum(i.level == WARN for i in issues))
