"""运行上下文：一次执行里所有模块共享的状态与计数器。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiui.config import Settings
from aiui.locator import collector
from aiui.locator.cache import LocatorCache
from aiui.locator.resolver import LocatorResolver
from aiui.planning.models import TestPlan, render_vars


@dataclass
class Metrics:
    steps_total: int = 0
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    retries: int = 0
    cache_hits: int = 0
    rule_hits: int = 0
    ai_hits: int = 0
    ai_rejected: int = 0
    retired: int = 0
    locate_ms: list[float] = field(default_factory=list)

    def hit(self, tier: str) -> None:
        if tier == "cache":
            self.cache_hits += 1
        elif tier == "rule":
            self.rule_hits += 1
        elif tier == "ai":
            self.ai_hits += 1

    def summary(self) -> dict[str, Any]:
        located = self.cache_hits + self.rule_hits + self.ai_hits
        attempts = located + self.ai_rejected

        def pct(n: int) -> float:
            return round(n * 100.0 / attempts, 1) if attempts else 0.0

        return {
            "steps_total": self.steps_total,
            "passed": self.passed,
            "failed": self.failed,
            "blocked": self.blocked,
            "retries": self.retries,
            "located": located,
            "cache_hits": self.cache_hits,
            "rule_hits": self.rule_hits,
            "ai_hits": self.ai_hits,
            "ai_rejected": self.ai_rejected,
            "ai_ratio_pct": pct(self.ai_hits),
            "cache_ratio_pct": pct(self.cache_hits),
            "rule_ratio_pct": pct(self.rule_hits),
            "ai_reject_pct": pct(self.ai_rejected),
            "retired": self.retired,
            "avg_locate_ms": round(sum(self.locate_ms) / len(self.locate_ms), 1) if self.locate_ms else 0.0,
        }


@dataclass
class RunContext:
    settings: Settings
    plan: TestPlan
    run_id: str
    artifacts: Path
    driver: Any = None
    vars: dict[str, str] = field(default_factory=dict)
    metrics: Metrics = field(default_factory=Metrics)
    cache: LocatorCache | None = None
    resolver: LocatorResolver | None = None
    evidence: Any = None
    guard: Any = None
    force_tier: str | None = None
    want_screenshot: bool = False
    _page_key: str = ""

    def page_key(self) -> str:
        if not self._page_key:
            self._page_key = collector.page_key(self.driver) if self.driver else "no-driver"
        return self._page_key

    def invalidate_page_key(self) -> None:
        self._page_key = ""

    def render(self, text: str | None) -> str | None:
        return render_vars(text, self.vars)

    def get_var(self, name: str, default: str = "") -> str:
        return self.vars.get(name, default)

    def elapsed(self, started: float) -> float:
        return round(time.time() - started, 3)
