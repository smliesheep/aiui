"""护栏：模型可以「建议」，但风险必须由程序「判定」。

三重判定（任一命中即 L3）：
1. 动作语义：点击提交类按钮；
2. 目标文本：支付/转账/删除/授权/发送/订单 等中英词表；
3. 值内容：金额 + 转账语义。

放行需要「双开关」：计划里人工签核过 + 运行时显式放行。
"""

from __future__ import annotations

import re

from aiui.config import Settings
from aiui.errors import HighRiskBlocked
from aiui.planning.models import ActionType, PlanStep, RiskLevel, TestPlan

HIGH_RISK_WORDS: dict[str, list[str]] = {
    "payment": [
        "支付", "付款", "转账", "汇款", "提现", "充值", "扣款",
        "pay", "payment", "pay now", "transfer", "remit", "withdraw", "top up", "checkout",
    ],
    "delete": [
        "删除", "注销", "解绑", "清空", "作废", "撤销",
        "delete", "remove", "unbind", "deactivate", "revoke", "clear",
    ],
    "auth": [
        "授权", "同意协议", "开通", "签署", "实名",
        "authorize", "authorise", "grant", "consent", "activate",
    ],
    "send": [
        "发送", "发消息", "发邮件", "通知", "推送",
        "send", "send message", "notify", "publish",
    ],
    "order": [
        "提交订单", "下单", "确认支付", "购买", "结算",
        "submit order", "place order", "confirm payment", "buy", "purchase",
    ],
}

SUBMIT_HINTS = ["提交", "保存", "确认", "submit", "save", "confirm", "continue", "下一步"]
AMOUNT_RE = re.compile(r"\d{2,}(?:[.,]\d{2})?")
TRANSFER_CONTEXT = ["转账", "支付", "付款", "汇款", "提现", "充值", "transfer", "pay", "withdraw"]

# 打开/查看类按钮即使带「转账」字样也不构成高风险（它只是打开表单，没有动钱）
OPENER_WORDS = [
    "quick", "open", "show", "add", "new", "record", "history",
    "查看", "打开", "新增", "详情", "记录", "快捷",
]

WRITE_ACTIONS = {ActionType.CLICK, ActionType.INPUT, ActionType.SELECT}
READ_ONLY = {
    ActionType.NAVIGATE, ActionType.ASSERT_TEXT, ActionType.ASSERT_ELEMENT,
    ActionType.EXTRACT, ActionType.SCREENSHOT, ActionType.WAIT, ActionType.SCROLL,
}


class Guardrail:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    # ------------------------------------------------------------------ 判定
    @staticmethod
    def _hit_word(text: str, word: str) -> bool:
        """英文用词边界匹配（避免 payee 命中 pay），中文用子串匹配。"""
        w = word.lower()
        if re.fullmatch(r"[a-z0-9 ]+", w):
            return re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text) is not None
        return w in text
    @staticmethod
    def _text_of(step: PlanStep) -> str:
        parts: list[str] = []
        if step.target:
            parts.append(step.target.description)
            hints = step.target.hints
            for v in (hints.text, hints.label, hints.placeholder, hints.aria_label,
                      hints.nearby_text, hints.container_text):
                if v:
                    parts.append(v)
        if step.value:
            parts.append(str(step.value))
        return " ".join(parts).lower()

    def hits(self, step: PlanStep) -> list[str]:
        text = self._text_of(step)
        found: list[str] = []
        for category, words in HIGH_RISK_WORDS.items():
            if any(self._hit_word(text, w) for w in words):
                found.append(category)
        return found

    def classify(self, step: PlanStep) -> RiskLevel:
        if step.action in READ_ONLY:
            return RiskLevel.L0
        found = self.hits(step)
        if step.action in WRITE_ACTIONS and found:
            text = self._text_of(step)
            if step.action is ActionType.CLICK and any(w in text for w in OPENER_WORDS):
                return RiskLevel.L2  # 只是打开表单/查看记录，不动钱
            return RiskLevel.L3
        if step.action is ActionType.INPUT:
            text = self._text_of(step)
            if AMOUNT_RE.search(step.value or "") and any(
                self._hit_word(text, c) for c in TRANSFER_CONTEXT
            ):
                return RiskLevel.L3
            return RiskLevel.L1
        if step.action is ActionType.SELECT:
            return RiskLevel.L1
        # click
        return RiskLevel.L2

    def _is_submit_click(self, step: PlanStep) -> bool:
        text = self._text_of(step)
        return step.action is ActionType.CLICK and any(h in text for h in SUBMIT_HINTS)

    # ------------------------------------------------------------------ 闸门
    def pre_check(self, es, plan: TestPlan, allow_ids: set[str] | None = None) -> None:
        allow_ids = allow_ids or set()
        if es.risk is not RiskLevel.L3:
            return
        approved_in_plan = es.step.id in set(plan.approved_high_risk)
        allowed_runtime = es.step.id in allow_ids
        if approved_in_plan and allowed_runtime:
            return
        reason = []
        if not approved_in_plan:
            reason.append("计划未签核")
        if not allowed_runtime:
            reason.append("运行时未放行")
        raise HighRiskBlocked(
            f"高风险动作被拦截（{es.step.id} {es.step.action.value}）：{'/'.join(reason)}",
            rule=",".join(self.hits(es.step)) or "submit",
            would_do=es.describe(),
            step_id=es.step.id,
        )

    def describe_risk(self, plan: TestPlan) -> list[dict]:
        return [
            {"step_id": s.id, "action": s.action.value,
             "target": s.target.description if s.target else "", "hits": self.hits(s)}
            for s in plan.steps if self.classify(s) is RiskLevel.L3
        ]
