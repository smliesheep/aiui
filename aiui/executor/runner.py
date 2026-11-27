"""执行主循环：四拍一步（闸门 → 定位 → 动作 → 取证），失败分类决定是否重试。"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aiui.config import Settings
from aiui.errors import (
    ActionError,
    AiuiError,
    AmbiguousError,
    HighRiskBlocked,
    LocateError,
    LowConfidenceError,
    StepTimeout,
)
from aiui.evidence.collector import EvidenceCollector
from aiui.executor.browser import build_driver
from aiui.executor.context import Metrics, RunContext
from aiui.guardrail.policy import Guardrail
from aiui.llm.gateway import LLMGateway, build_gateway
from aiui.locator.cache import LocatorCache
from aiui.locator.resolver import LocatorResolver
from aiui.locator.types import LocateResult
from aiui.logging import get_logger
from aiui.planning.compiler import compile_plan
from aiui.planning.models import ActionType, TestPlan
from aiui.reporting import allure_hooks as hooks

log = get_logger(__name__)

RETRYABLE = (StepTimeout, AmbiguousError, ActionError)


@dataclass
class StepRecord:
    id: str
    action: str
    intent: str
    status: str
    tier: str | None = None
    detail: str = ""
    error: str | None = None


@dataclass
class RunSummary:
    run_id: str
    plan_id: str
    title: str
    status: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    duration_s: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    artifacts: str = ""
    plan_hash: str = ""
    steps: list[StepRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["steps"] = [asdict(s) for s in self.steps]
        return d


class Runner:
    def __init__(self, settings: Settings, gateway: LLMGateway | None = None) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self.gateway = gateway

    # ------------------------------------------------------------------ 主流程
    def run(self, plan: TestPlan, driver=None, allow_high_risk: set[str] | None = None,
            variables: dict[str, str] | None = None, close_driver: bool = True) -> RunSummary:
        settings = self.settings
        allow = set(allow_high_risk or ())
        started = time.time()
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        artifacts = settings.artifacts_dir / run_id
        artifacts.mkdir(parents=True, exist_ok=True)

        plan.plan_hash = plan.plan_hash or plan.compute_hash()
        cache = LocatorCache(settings.cache_db, settings.cache_enabled)
        gateway = self.gateway or build_gateway(settings, audit_path=artifacts / "llm_calls.jsonl")
        self.gateway = gateway
        guard = Guardrail(settings)
        resolver = LocatorResolver(settings, gateway, cache)
        evidence = EvidenceCollector(artifacts, settings)
        steps = compile_plan(plan, settings, guard)

        ctx = RunContext(
            settings=settings, plan=plan, run_id=run_id, artifacts=artifacts,
            vars=dict(variables or {}), cache=cache, resolver=resolver,
            evidence=evidence, guard=guard,
        )

        hooks.set_title(plan.title or plan.plan_id)
        hooks.set_description(plan.requirement or plan.title)
        hooks.tag(*(plan.tags or ["aiui"]))
        evidence.start(plan, steps, gateway)

        own_driver = driver is None
        if own_driver:
            driver = build_driver(settings)
        ctx.driver = driver

        summary = RunSummary(
            run_id=run_id, plan_id=plan.plan_id, title=plan.title,
            status="passed", total=0, plan_hash=plan.plan_hash,
            artifacts=str(artifacts),
        )

        try:
            for es in steps:
                summary.total += 1
                ctx.metrics.steps_total += 1
                with hooks.span(f"{es.id} {es.action.value} {es.step.intent}".strip()):
                    try:
                        status, loc, err = self._execute_step(ctx, es, allow)
                    except Exception as exc:  # noqa: BLE001 - 任何漏网异常都收敛为步骤失败
                        status, loc, err = "failed", None, ActionError(f"{es.id}: {exc}")
                    rec = StepRecord(
                        id=es.id, action=es.action.value, intent=es.step.intent,
                        status=status, tier=loc.tier if loc else None,
                        detail=(loc.reason if loc else ""),
                        error=err.message if err else None,
                    )
                    summary.steps.append(rec)

                    if status == "passed":
                        summary.passed += 1
                        ctx.metrics.passed += 1
                        evidence.attach_step(es, loc, "passed", driver=driver,
                                             force_shot=ctx.want_screenshot)
                        ctx.want_screenshot = False
                    elif status == "blocked":
                        summary.blocked += 1
                        ctx.metrics.blocked += 1
                        evidence.attach_blocked(es, err, driver=driver)  # type: ignore[arg-type]
                        summary.status = "blocked"
                        summary.error = err.message if err else None
                        log.error("计划被护栏拦截：%s", summary.error)
                        break
                    else:
                        summary.failed += 1
                        ctx.metrics.failed += 1
                        evidence.attach_step(es, loc, "failed", error=err, driver=driver,
                                             force_shot=True)
                        summary.status = "failed"
                        summary.error = err.message if err else None
                        log.error("步骤失败 %s: %s", es.id, summary.error)
                        if es.step.on_failure == "continue":
                            continue
                        break
                    ctx.invalidate_page_key()
        finally:
            summary.duration_s = round(time.time() - started, 2)
            summary.metrics = {**ctx.metrics.summary(), **gateway.stats, "cache": cache.stats()}
            evidence.finish(summary.to_dict())
            if cache:
                cache.close()
            if own_driver and close_driver:
                try:
                    driver.quit()
                except Exception:  # noqa: BLE001
                    pass
        return summary

    # ------------------------------------------------------------------ 单步
    def _execute_step(self, ctx: RunContext, es, allow: set[str]):
        loc: LocateResult | None = None
        attempt = 0
        while True:
            attempt += 1
            try:
                ctx.guard.pre_check(es, ctx.plan, allow)

                if es.step.target:
                    t0 = time.time()
                    try:
                        loc = ctx.resolver.resolve(  # type: ignore[union-attr]
                            ctx.driver, es.step.target, ctx.page_key(),
                            force_rule=ctx.force_tier == "rule",
                        )
                    except LowConfidenceError as exc:
                        if es.step.action is ActionType.ASSERT_TEXT:
                            # 断言是只读动作：定位不到就降级为整页断言，绝不误点
                            log.warning("%s 目标定位失败，降级为整页文本断言：%s", es.id, exc)
                            loc = None
                        else:
                            ctx.metrics.ai_rejected += 1
                            exc.chain = exc.chain or ["ai:rejected"]
                            return "failed", None, exc
                    finally:
                        ctx.metrics.locate_ms.append((time.time() - t0) * 1000)
                    if loc is not None:
                        ctx.metrics.hit(loc.tier)
                        if loc.cache_hit and ctx.cache:
                            ctx.cache.confirm(loc.cache_hit)

                action = es.action_cls(ctx.settings)
                action.run(ctx, es, loc)

                if loc and ctx.cache and es.step.target and loc.tier in {"rule", "ai"}:
                    ctx.cache.save(
                        ctx.page_key(), es.step.target, loc.locator,
                        loc.tier, loc.confidence, loc.expect_text,
                    )
                ctx.force_tier = None
                return "passed", loc, None

            except HighRiskBlocked as exc:
                return "blocked", loc, exc
            except LowConfidenceError as exc:
                return "failed", loc, exc
            except AiuiError as exc:
                if attempt == 1 and isinstance(exc, RETRYABLE):
                    ctx.metrics.retries += 1
                    ctx.force_tier = "rule"
                    ctx.invalidate_page_key()
                    log.warning("%s 首次失败，重试一次（跳过缓存）：%s", es.id, exc)
                    time.sleep(0.4)
                    continue
                self._retire(ctx, loc)
                return "failed", loc, exc
            except Exception as exc:  # noqa: BLE001 - 兜底：任何异常都要转成步骤失败
                if attempt == 1:
                    ctx.metrics.retries += 1
                    ctx.force_tier = "rule"
                    ctx.invalidate_page_key()
                    log.warning("%s 首次异常，重试一次：%s", es.id, exc)
                    time.sleep(0.4)
                    continue
                self._retire(ctx, loc)
                return "failed", loc, ActionError(f"{es.id}: {exc}")

    @staticmethod
    def _retire(ctx: RunContext, loc: LocateResult | None) -> None:
        if loc and loc.cache_hit and ctx.cache:
            if ctx.cache.on_fail(loc.cache_hit):
                ctx.metrics.retired += 1
