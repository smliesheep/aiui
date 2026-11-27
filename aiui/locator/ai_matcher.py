"""Tier3 AI 兜底：模型只做「选择题」，不做「填空题」。

输入是程序采集的候选清单（编号 + 标签 + 文本 + 关键属性），
输出只允许 {candidate_id, confidence, reason}，三道后置校验：
  编号必须存在 / 置信度 ≥ 阈值 / 元素必须可见可用
任一不过就抛 LowConfidenceError —— 宁可失败，也不瞎点。
"""

from __future__ import annotations

import json
from pathlib import Path

from aiui.config import Settings
from aiui.errors import LowConfidenceError
from aiui.llm.gateway import LLMGateway
from aiui.locator.collector import Candidate, durable_locator
from aiui.locator.rules import rank
from aiui.locator.types import LocateResult
from aiui.logging import get_logger
from aiui.planning.models import TargetSpec

log = get_logger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "locate.txt"


class AIMatcher:
    def __init__(self, gateway: LLMGateway, settings: Settings) -> None:
        self.gateway = gateway
        self.settings = settings
        self._template = PROMPT_PATH.read_text(encoding="utf-8")

    def _prompt(self, target: TargetSpec, cands: list[Candidate]) -> list[dict[str, str]]:
        task = json.dumps(
            {
                "description": target.description,
                "hints": {k: v for k, v in target.hints.model_dump().items() if v},
            },
            ensure_ascii=False,
        )
        lines = [
            f'{c.i} | {c.tag} | {c.text or "(无文本)"} | '
            f'label={c.attrs.get("label", "")} ph={c.attrs.get("ph", "")} '
            f'name={c.attrs.get("name", "")} id={c.attrs.get("id", "")} '
            f'testid={c.attrs.get("testid", "")} '
            f'{"可见" if c.visible else "不可见"}/{"可用" if c.enabled else "禁用"}'
            for c in cands
        ]
        body = self._template.replace("{{TASK}}", task).replace("{{CANDIDATES}}", "\n".join(lines))
        return [
            {"role": "system", "content": "你是 UI 元素定位助手，只能输出 json。"},
            {"role": "user", "content": body},
        ]

    def match(self, target: TargetSpec, cands: list[Candidate], chain: list[str]) -> LocateResult:
        pool = [c for c in cands if c.visible and c.enabled] or cands
        if not pool:
            raise LowConfidenceError("页面上没有可交互候选元素", chain=chain + ["ai:no_candidates"])

        if len(pool) > self.settings.max_candidates:
            ranked = rank(target, pool)
            keep = {s.cand.i for s in ranked[: self.settings.max_candidates]}
            pool = [c for c in pool if c.i in keep]

        data = self.gateway.chat_json(self._prompt(target, pool), purpose="locate", max_tokens=200)
        by_id = {c.i: c for c in pool}

        raw_id = data.get("candidate_id", -1)
        try:
            cid = int(raw_id)
        except (TypeError, ValueError):
            raise LowConfidenceError(f"模型返回非法编号 {raw_id!r}", chain=chain + ["ai:bad_id"])
        try:
            conf = float(data.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            conf = 0.0
        reason = str(data.get("reason", ""))[:80]

        if cid not in by_id:
            raise LowConfidenceError(
                f"模型返回了不存在的编号 {cid}", chain=chain + ["ai:invalid_candidate"],
                candidate_id=cid, reason=reason,
            )
        if conf < self.settings.confidence_min:
            raise LowConfidenceError(
                f"置信度 {conf:.2f} < 阈值 {self.settings.confidence_min:.2f}",
                chain=chain + [f"ai:low_conf({conf:.2f})"], candidate_id=cid, reason=reason,
            )

        cand = by_id[cid]
        if not (cand.visible and cand.enabled):
            raise LowConfidenceError(
                f"选中的元素不可用（visible={cand.visible}, enabled={cand.enabled}）",
                chain=chain + ["ai:not_actionable"], candidate_id=cid,
            )

        log.info("AI 定位命中：i=%s conf=%.2f %s", cid, conf, reason)
        return LocateResult(
            tier="ai",
            locator=durable_locator(cand),
            marker=cand.locator,
            confidence=conf,
            score=conf,
            reason=reason,
            candidate_id=cid,
            fallback_chain=chain + [f"ai:accept({conf:.2f})"],
            expect_text=cand.text,
        )
