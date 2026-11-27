"""多轮基准：验证「冷缓存 → 暖缓存」的收敛效果，也是 M5 对比实验的取数工具。

同一份计划、同一个浏览器会话、同一份缓存库连跑 N 轮：
第 1 轮代表冷启动（允许走 AI），第 2 轮起代表稳态（应该基本全是缓存/规则命中）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiui.config import Settings
from aiui.executor.browser import build_driver
from aiui.executor.runner import Runner
from aiui.llm.gateway import LLMGateway
from aiui.planning.models import TestPlan


def run_rounds(plan: TestPlan, settings: Settings, gateway: LLMGateway,
               rounds: int = 2, allow: set[str] | None = None) -> list[dict[str, Any]]:
    driver = build_driver(settings)
    rows: list[dict[str, Any]] = []
    try:
        for i in range(1, rounds + 1):
            calls_before = gateway.calls
            tokens_before = gateway.total_tokens
            summary = Runner(settings, gateway).run(
                plan, driver=driver, allow_high_risk=allow or set(),
                variables={}, close_driver=False,
            )
            m = summary.metrics or {}
            rows.append({
                "round": i,
                "status": summary.status,
                "passed": summary.passed,
                "total": summary.total,
                "cache": m.get("cache_hits", 0),
                "rule": m.get("rule_hits", 0),
                "ai": m.get("ai_hits", 0),
                "ai_rejected": m.get("ai_rejected", 0),
                "ai_pct": m.get("ai_ratio_pct", 0.0),
                "cache_pct": m.get("cache_ratio_pct", 0.0),
                "avg_locate_ms": m.get("avg_locate_ms", 0.0),
                "tokens": gateway.total_tokens - tokens_before,
                "llm_calls": gateway.calls - calls_before,
                "duration_s": summary.duration_s,
                "error": summary.error,
            })
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass
    return rows


def format_table(rows: list[dict[str, Any]]) -> str:
    head = (f"{'轮次':<4}{'状态':<9}{'步骤':<8}{'cache':<7}{'rule':<6}{'ai':<5}"
            f"{'AI占比':<9}{'平均定位':<10}{'tokens':<8}{'耗时':<7}")
    lines = [head, "-" * 72]
    for r in rows:
        lines.append(
            f"{r['round']:<4}{r['status']:<9}{str(r['passed']) + '/' + str(r['total']):<8}"
            f"{r['cache']:<7}{r['rule']:<6}{r['ai']:<5}"
            f"{str(r['ai_pct']) + '%':<9}{str(r['avg_locate_ms']) + 'ms':<10}"
            f"{r['tokens']:<8}{str(r['duration_s']) + 's':<7}"
        )
        if r.get("error"):
            lines.append(f"     ! {r['error'][:90]}")
    return "\n".join(lines)


def write_report(rows: list[dict[str, Any]], plan: TestPlan, out_dir: Path) -> Path:
    import json
    import time

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"bench-{plan.plan_id}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(
        json.dumps({"plan_id": plan.plan_id, "plan_hash": plan.plan_hash,
                    "rounds": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
