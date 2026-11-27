"""需求 -> 计划：Prompt 组装 + 校验失败带错回问（最多 2 次）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from aiui.config import Settings
from aiui.errors import PlanGenerationError
from aiui.llm.gateway import LLMGateway
from aiui.logging import get_logger
from aiui.planning.models import (
    ActionType,
    RiskLevel,
    TestPlan,
    TestPlanDraft,
    slugify,
)
from aiui.planning.validator import apply_auto_fixes, validate

log = get_logger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "llm" / "prompts"

EXAMPLES = """
示例 1（登录）：
{"plan_id":"login","title":"登录","requirement":"登录系统","base_url":"{{BASE_URL}}","tags":["auth"],"preconditions":[],
 "steps":[
  {"id":"s1","action":"navigate","value":"/login","risk":"L0","intent":"打开登录页"},
  {"id":"s2","action":"input","target":{"description":"用户名输入框","hints":{"label":"Username","name":"username"}},"value":"${USER}","risk":"L1","intent":"输入用户名"},
  {"id":"s3","action":"input","target":{"description":"密码输入框","hints":{"label":"Password","name":"password"}},"value":"${PASS}","risk":"L1","intent":"输入密码"},
  {"id":"s4","action":"click","target":{"description":"登录按钮","hints":{"text":"Login","role":"button"}},"risk":"L2","intent":"点击登录"},
  {"id":"s5","action":"assert_text","target":{"description":"页面提示","hints":{"container_text":"toast"}},"assertion":{"kind":"contains","expected":"欢迎"},"risk":"L0","intent":"确认登录成功"}
 ],"questions":[]}

示例 2（转账，注意高风险必须标 L3）：
{"plan_id":"transfer","title":"同币种转账","requirement":"向账户转账 100 USD","base_url":"{{BASE_URL}}","tags":["transfer"],"preconditions":["已登录"],
 "steps":[
  {"id":"s1","action":"navigate","value":"/transfer","risk":"L0","intent":"打开转账页"},
  {"id":"s2","action":"input","target":{"description":"收款账号输入框","hints":{"label":"Payee Account"}},"value":"11111111","risk":"L1","intent":"输入收款账号"},
  {"id":"s3","action":"input","target":{"description":"转账金额输入框","hints":{"label":"Amount"}},"value":"100","risk":"L3","intent":"输入转账金额"},
  {"id":"s4","action":"click","target":{"description":"确认转账按钮","hints":{"text":"Confirm Transfer","role":"button"}},"risk":"L3","intent":"提交转账"},
  {"id":"s5","action":"assert_text","target":{"description":"结果提示","hints":{"container_text":"alert"}},"assertion":{"kind":"contains","expected":"成功"},"risk":"L0","intent":"确认转账成功"}
 ],"questions":[]}
"""


class PlanParser:
    def __init__(self, gateway: LLMGateway, settings: Settings) -> None:
        self.gateway = gateway
        self.settings = settings
        self._template = (PROMPT_DIR / "plan.txt").read_text(encoding="utf-8")

    # ------------------------------------------------------------------ prompt
    def build_messages(self, requirement: str, base_url: str,
                       page_map: dict[str, Any] | None = None,
                       variables: dict[str, str] | None = None) -> list[dict[str, str]]:
        ctx = {
            "base_url": base_url,
            "available_variables": sorted((variables or {}).keys()),
            "page_map": page_map or {},
            "constraints": [
                "只输出 json",
                f"动作只能是：{[a.value for a in ActionType]}",
                "禁止输出选择器/代码",
            ],
        }
        body = (
            self._template
            .replace("{{CONTEXT}}", json.dumps(ctx, ensure_ascii=False)[:3000])
            .replace("{{EXAMPLES}}", EXAMPLES.replace("{{BASE_URL}}", base_url)[:2600])
            .replace("{{REQUIREMENT}}", requirement)
        )
        return [
            {"role": "system", "content": "你是 UI 测试计划生成器，只输出 json 对象。"},
            {"role": "user", "content": body},
        ]

    # ------------------------------------------------------------------ parse
    def parse(self, requirement: str, base_url: str,
              page_map: dict[str, Any] | None = None,
              variables: dict[str, str] | None = None) -> tuple[TestPlan, list[str]]:
        messages = self.build_messages(requirement, base_url, page_map, variables)
        notes: list[str] = []
        allowed = {k.upper() for k in (variables or {})}
        last_error = ""

        for attempt in range(self.settings.llm_max_repair + 1):
            data = self.gateway.chat_json(messages, purpose="plan", max_tokens=2000)
            error_text = ""
            try:
                draft = TestPlanDraft.model_validate(data)
            except ValidationError as exc:
                error_text = json.dumps(
                    [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()],
                    ensure_ascii=False,
                )
            else:
                plan = self._draft_to_plan(draft, requirement, base_url)
                fixes = apply_auto_fixes(plan)
                res = validate(plan, self.settings, allowed)
                notes = fixes + [f"[warn] {v.message}" for v in res.warnings]
                if res.ok:
                    plan.plan_hash = plan.compute_hash()
                    log.info("计划生成成功：%s（%d 步，attempt=%d）",
                             plan.plan_id, len(plan.steps), attempt + 1)
                    return plan, notes
                error_text = "; ".join(f"[{v.rule}] {v.message}" for v in res.errors[:6])
                last_error = error_text

            if attempt >= self.settings.llm_max_repair:
                break
            log.warning("计划不合法（第 %d 次），带错回问：%s", attempt + 1, error_text[:200])
            messages = messages + [
                {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)[:4000]},
                {"role": "user", "content":
                 "上面的 json 不合法。请只修正下列问题后，重新输出完整 json（不要解释）：\n" + error_text},
            ]

        raise PlanGenerationError(f"计划生成失败：{last_error or '模型未给出可用步骤'}")

    # ------------------------------------------------------------------ convert
    def _draft_to_plan(self, draft: TestPlanDraft, requirement: str, base_url: str) -> TestPlan:
        if not draft.steps:
            qs = [q.model_dump(mode="json") for q in draft.questions]
            raise PlanGenerationError(f"模型没有给出任何步骤，只有问题：{qs}")
        plan_id = draft.plan_id or slugify(draft.title or requirement)
        return TestPlan(
            plan_id=plan_id,
            title=draft.title or requirement[:30],
            requirement=requirement,
            base_url=base_url or draft.base_url or "",
            tags=draft.tags,
            preconditions=draft.preconditions,
            steps=draft.steps,
            approved_high_risk=[],
        )
