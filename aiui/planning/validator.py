"""计划校验：Pydantic 保证「结构合法」，这里保证「业务说得通」。

8 条规则对应设计文档 §6.2.2。每条规则独立、可单测、可单独开关。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal
from urllib.parse import urlparse

from aiui.config import Settings
from aiui.planning.models import (
    ActionType,
    PlanStep,
    RiskLevel,
    TestPlan,
    scan_vars,
)

READ_ONLY_ACTIONS = {
    ActionType.NAVIGATE,
    ActionType.ASSERT_TEXT,
    ActionType.ASSERT_ELEMENT,
    ActionType.EXTRACT,
    ActionType.SCREENSHOT,
    ActionType.WAIT,
    ActionType.SCROLL,
}
WRITE_ACTIONS = {ActionType.CLICK, ActionType.INPUT, ActionType.SELECT}


@dataclass
class Violation:
    rule: str
    message: str
    step_id: str | None = None
    severity: Literal["error", "warn"] = "error"

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "message": self.message,
            "step_id": self.step_id,
            "severity": self.severity,
        }


@dataclass
class ValidationResult:
    violations: list[Violation] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors


def apply_auto_fixes(plan: TestPlan) -> list[str]:
    """编译器能安全补全的东西在这里补齐，补不了的交给规则报错。"""
    fixes: list[str] = []
    if plan.steps and plan.steps[0].action is not ActionType.NAVIGATE:
        nav = PlanStep(
            id="s0_navigate",
            action=ActionType.NAVIGATE,
            value=plan.base_url or "/",
            intent="打开被测页面",
            risk=RiskLevel.L0,
        )
        plan.steps.insert(0, nav)
        fixes.append("自动补全首步 navigate")
    return fixes


def validate(plan: TestPlan, settings: Settings | None = None,
             allowed_vars: Iterable[str] = ()) -> ValidationResult:
    res = ValidationResult()
    allowed = {v.upper() for v in allowed_vars}

    _r_non_empty(plan, res)
    _r_unique_ids(plan, res)
    _r_navigate_first(plan, res)
    _r_required_fields(plan, res)
    _r_host_allowlist(plan, settings, res)
    _r_order_sanity(plan, res)
    _r_variables(plan, allowed, res)
    _r_risk_consistency(plan, res)
    return res


def validate_or_raise(plan: TestPlan, settings: Settings | None = None,
                      allowed_vars: Iterable[str] = ()) -> ValidationResult:
    from aiui.errors import PlanValidationError

    res = validate(plan, settings, allowed_vars)
    if not res.ok:
        detail = "; ".join(f"[{v.rule}] {v.message}" for v in res.errors[:5])
        raise PlanValidationError(f"计划校验失败（{len(res.errors)} 项）：{detail}", res.violations)
    return res


# --------------------------------------------------------------------------- rules
def _r_non_empty(plan: TestPlan, res: ValidationResult) -> None:
    if not plan.steps:
        res.violations.append(Violation("steps_non_empty", "计划没有任何步骤"))


def _r_unique_ids(plan: TestPlan, res: ValidationResult) -> None:
    seen: set[str] = set()
    for s in plan.steps:
        if s.id in seen:
            res.violations.append(Violation("unique_step_id", f"步骤 id 重复：{s.id}", s.id))
        seen.add(s.id)


def _r_navigate_first(plan: TestPlan, res: ValidationResult) -> None:
    if not plan.steps:
        return
    if plan.steps[0].action is not ActionType.NAVIGATE:
        res.violations.append(
            Violation("navigate_first", "首个步骤必须是 navigate", plan.steps[0].id)
        )


def _r_required_fields(plan: TestPlan, res: ValidationResult) -> None:
    for s in plan.steps:
        if s.action is ActionType.NAVIGATE and not s.value:
            res.violations.append(Violation("required_value", "navigate 需要 value(url)", s.id))
        if s.action in {ActionType.CLICK, ActionType.ASSERT_ELEMENT} and s.target is None:
            res.violations.append(Violation("required_target", f"{s.action.value} 需要 target", s.id))
        if s.action in {ActionType.INPUT, ActionType.SELECT}:
            if s.target is None:
                res.violations.append(Violation("required_target", f"{s.action.value} 需要 target", s.id))
            if s.value is None:
                res.violations.append(Violation("required_value", f"{s.action.value} 需要 value", s.id))
        if s.action in {ActionType.ASSERT_TEXT, ActionType.ASSERT_ELEMENT} and s.assertion is None:
            res.violations.append(Violation("required_assertion", "断言动作需要 assertion", s.id))
        if s.action is ActionType.EXTRACT:
            if s.target is None:
                res.violations.append(Violation("required_target", "extract 需要 target", s.id))
            if not s.value:
                res.violations.append(Violation("required_value", "extract 需要 value(变量名)", s.id))
            elif not s.value.isidentifier():
                res.violations.append(
                    Violation("bad_var_name", f"extract 变量名非法：{s.value}", s.id)
                )
        if s.action in {ActionType.WAIT, ActionType.SCROLL} and not (s.target or s.value):
            res.violations.append(
                Violation("required_target", f"{s.action.value} 需要 target 或 value", s.id)
            )


def _r_host_allowlist(plan: TestPlan, settings: Settings | None, res: ValidationResult) -> None:
    if not settings or not settings.hosts:
        return
    parsed = urlparse(plan.base_url)
    if parsed.scheme == "file":
        return  # 本地 file:// 页面（demo/离线演练）不做域名限制
    host = (parsed.hostname or "").lower()
    if host not in settings.hosts:
        res.violations.append(
            Violation(
                "host_allowlist",
                f"base_url 域名 {host!r} 不在白名单 {settings.hosts} 内",
            )
        )


def _r_order_sanity(plan: TestPlan, res: ValidationResult) -> None:
    navigated = False
    for s in plan.steps:
        if s.action is ActionType.NAVIGATE:
            navigated = True
        if not navigated and s.action in {ActionType.ASSERT_TEXT, ActionType.ASSERT_ELEMENT}:
            res.violations.append(
                Violation("order_sanity", "断言出现在首次 navigate 之前", s.id)
            )


def _r_variables(plan: TestPlan, allowed: set[str], res: ValidationResult) -> None:
    defined = set(allowed)
    for s in plan.steps:
        refs = scan_vars(s.value)
        refs += scan_vars(s.target.description if s.target else None)
        refs += scan_vars(s.assertion.expected if s.assertion else None)
        for var in refs:
            if var.upper() in defined:
                continue
            if s.action is ActionType.INPUT:
                # 输入值缺失不算硬错误：澄清阶段可以补，补不上再在执行期失败
                res.violations.append(
                    Violation("pending_value", f"变量 ${{{var}}} 待澄清取值", s.id,
                              severity="warn")
                )
            else:
                res.violations.append(
                    Violation("undefined_var", f"变量 ${{{var}}} 未定义", s.id)
                )
        if s.action is ActionType.EXTRACT and s.value:
            defined.add(s.value.upper())


def _r_risk_consistency(plan: TestPlan, res: ValidationResult) -> None:
    for s in plan.steps:
        if s.action in READ_ONLY_ACTIONS and s.risk.rank >= 2:
            res.violations.append(
                Violation(
                    "risk_consistency",
                    f"只读动作 {s.action.value} 不应标 {s.risk.value}，将按 L0 处理",
                    s.id,
                    severity="warn",
                )
            )
        if s.action in WRITE_ACTIONS and s.risk is RiskLevel.L0:
            res.violations.append(
                Violation(
                    "risk_consistency",
                    f"写动作 {s.action.value} 标了 L0，执行期将由护栏重新判定",
                    s.id,
                    severity="warn",
                )
            )


def collect_questions(plan: TestPlan, allowed_vars: Iterable[str] = ()) -> list:
    """收集「输入值待补」的问题（对话澄清用）。"""
    from aiui.planning.models import PlanQuestion

    allowed = {v.upper() for v in allowed_vars}
    defined = set(allowed)
    qs: list[PlanQuestion] = []
    for s in plan.steps:
        if s.action is ActionType.EXTRACT and s.value:
            defined.add(s.value.upper())
            continue
        if s.action is not ActionType.INPUT:
            continue
        for var in scan_vars(s.value):
            if var.upper() not in defined:
                qs.append(
                    PlanQuestion(
                        kind="missing_value",
                        step_id=s.id,
                        field="value",
                        message=f"步骤 {s.id}（{s.intent or '输入'}）需要 {var} 的取值",
                    )
                )
    return qs
