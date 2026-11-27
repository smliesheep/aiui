"""澄清确认：只在「缺值 / 歧义 / 高风险」时打扰人，其他一律不问。

对应简历里的「自然语言描述 — AI 澄清确认 — 自动执行」中间那一环。
"""

from __future__ import annotations

from typing import Callable

from aiui.config import Settings
from aiui.errors import ClarificationRequired
from aiui.guardrail.policy import Guardrail
from aiui.planning.models import ActionType, TestPlan
from aiui.planning.validator import validate_or_raise

InputFn = Callable[[str], str]


def gate(plan: TestPlan, settings: Settings, allowed_vars: set[str],
         interactive: bool | None = None,
         input_fn: InputFn = input) -> tuple[TestPlan, list[str]]:
    interactive = settings.interactive if interactive is None else interactive
    transcript: list[str] = []
    guard = Guardrail(settings)

    pending = _pending_values(plan, allowed_vars)
    risky = [s for s in plan.steps if guard.classify(s).value == "L3"
             and s.id not in set(plan.approved_high_risk)]

    if pending and not interactive:
        questions = [f"{sid}: 缺少取值（{var}）" for sid, var in pending]
        raise ClarificationRequired(questions)

    for sid, var in pending:
        raw = input_fn(f"[澄清] 步骤 {sid} 的 {var} 取值（如不填则跳过）：").strip()
        if not raw:
            continue
        step = plan.step_by_id(sid)
        if step is None:
            continue
        if var not in _vars_in(step.value or ""):
            step.value = raw
        else:
            step.value = (step.value or "").replace(f"${{{var}}}", raw)
        allowed_vars.add(var.upper())
        transcript.append(f"filled {sid}.{var}={raw}")

    if risky and interactive:
        print("\n[高风险动作清单]")
        for s in risky:
            print(f"  - {s.id} {s.action.value}：{s.intent or ''} "
                  f"{s.target.description if s.target else ''}")
        answer = input_fn("以上步骤会修改真实数据，允许执行吗？输入 y 允许，其他跳过：").strip().lower()
        if answer in {"y", "yes", "是"}:
            plan.approved_high_risk = sorted(set(plan.approved_high_risk) | {s.id for s in risky})
            transcript.append("approved high risk steps: " + ",".join(plan.approved_high_risk))
        else:
            transcript.append("high risk steps NOT approved (runtime will block)")

    validate_or_raise(plan, settings, allowed_vars)
    return plan, transcript


def _vars_in(text: str) -> list[str]:
    from aiui.planning.models import scan_vars

    return scan_vars(text)


def _pending_values(plan: TestPlan, allowed_vars: set[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for s in plan.steps:
        if s.action is not ActionType.INPUT or not s.value:
            continue
        for var in _vars_in(s.value):
            if var.upper() not in allowed_vars:
                out.append((s.id, var))
    return out
