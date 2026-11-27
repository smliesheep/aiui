"""三级定位统一入口：缓存优先 → 规则匹配 → AI 兜底。"""

from __future__ import annotations

from aiui.config import Settings
from aiui.errors import AmbiguousError, LowConfidenceError
from aiui.llm.gateway import LLMGateway
from aiui.locator import collector
from aiui.locator.ai_matcher import AIMatcher
from aiui.locator.cache import LocatorCache
from aiui.locator.rules import best_match
from aiui.locator.types import LocateResult
from aiui.logging import get_logger
from aiui.planning.models import TargetSpec

log = get_logger(__name__)


class LocatorResolver:
    def __init__(self, settings: Settings, gateway: LLMGateway,
                 cache: LocatorCache | None = None) -> None:
        self.settings = settings
        self.cache = cache
        self.ai = AIMatcher(gateway, settings)

    def resolve(self, driver, target: TargetSpec, page_key: str,
                force_rule: bool = False) -> LocateResult:
        chain: list[str] = []
        in_frame = False

        if target.frame:
            try:
                driver.switch_to.frame(target.frame)
                in_frame = True
                chain.append(f"frame:{target.frame}")
            except Exception as exc:  # noqa: BLE001
                log.warning("切换到 iframe 失败：%s", exc)

        # ---- Tier1 缓存（重试时强制跳过，避免脏缓存）
        if self.cache and not force_rule:
            hit = self.cache.get(page_key, target)
            if hit and self.cache.revalidate(driver, hit):
                return LocateResult(
                    tier="cache", locator=hit.locator, confidence=hit.confidence,
                    fallback_chain=chain + ["cache:hit"], in_frame=in_frame, cache_hit=hit,
                    expect_text=hit.expect_text,
                )
            chain.append("cache:miss" if not hit else "cache:invalid")
        elif force_rule:
            chain.append("cache:skipped")

        # ---- Tier2 规则（一次采集，两级共用）
        cands = collector.collect(driver, self.settings.collect_limit)
        best, second, verdict = best_match(
            target, cands, self.settings.rule_min_score, self.settings.rule_min_gap
        )
        if verdict == "rule_hit" and best is not None:
            return LocateResult(
                tier="rule",
                locator=collector.durable_locator(best.cand),
                marker=best.cand.locator,
                confidence=best.score,
                score=best.score,
                reason="; ".join(best.hits),
                candidate_id=best.cand.i,
                fallback_chain=chain + [f"rule:hit({best.score:.2f})"],
                in_frame=in_frame,
                expect_text=best.cand.text,
            )

        detail = verdict
        if second is not None and best is not None:
            detail = f"{verdict}; best={best.score:.2f} second={second.score:.2f}"
        chain.append(f"rule:{detail}")

        # ---- Tier3 AI
        try:
            result = self.ai.match(target, cands, chain)
            result.in_frame = in_frame
            return result
        except LowConfidenceError as exc:
            exc.chain = exc.chain or chain
            raise

    def _raise_ambiguous(self, chain: list[str], best, second) -> None:
        raise AmbiguousError("规则存在多个高分候选，且无法收敛", chain=chain)
