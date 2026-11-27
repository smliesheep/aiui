"""编译：把「可评审的计划」变成「可执行的步骤」。

关键约束：
- 动作从静态注册表取，KeyError 即拒绝，没有任何动态导入/反射；
- 风险由护栏重新判定，覆盖模型自报值；
- 变量依赖在此结算，执行期不再解析表达式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiui.config import Settings
from aiui.planning.models import ActionType, PlanStep, RiskLevel, TestPlan, scan_vars


@dataclass
class ExecutableStep:
    step: PlanStep
    action_cls: Any
    wait_ms: int
    risk: RiskLevel
    var_refs: list[str] = field(default_factory=list)
    index: int = 0

    @property
    def id(self) -> str:
        return self.step.id

    @property
    def action(self) -> ActionType:
        return self.step.action

    @property
    def is_high_risk(self) -> bool:
        return self.risk is RiskLevel.L3

    def describe(self) -> str:
        t = self.step.target.description if self.step.target else ""
        v = f" = {self.step.value}" if self.step.value else ""
        return f"{self.step.action.value} {t}{v}".strip()


def compile_plan(plan: TestPlan, settings: Settings, guard: Any | None = None) -> list[ExecutableStep]:
    from aiui.actions.registry import ACTION_REGISTRY
    from aiui.guardrail.policy import Guardrail

    guard = guard or Guardrail(settings)
    out: list[ExecutableStep] = []
    for idx, step in enumerate(plan.steps):
        try:
            action_cls = ACTION_REGISTRY[step.action]
        except KeyError as exc:  # pragma: no cover - 枚举已限制，防御性分支
            raise ValueError(f"未注册的动作类型：{step.action}") from exc
        out.append(
            ExecutableStep(
                step=step,
                action_cls=action_cls,
                wait_ms=step.timeout_ms or settings.timeout_ms,
                risk=guard.classify(step),
                var_refs=scan_vars(step.value),
                index=idx,
            )
        )
    plan.plan_hash = plan.compute_hash()
    return out
