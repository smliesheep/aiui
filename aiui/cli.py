"""命令行入口：plan / run / go / sniff / report。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from aiui.config import Settings, get_settings
from aiui.errors import AiuiError, ClarificationRequired
from aiui.executor.runner import Runner
from aiui.llm.gateway import build_gateway
from aiui.logging import get_logger, setup_logging
from aiui.planning.clarify import gate as clarify_gate
from aiui.planning.models import TestPlan
from aiui.planning.parser import PlanParser
from aiui.sniff import build_page_map

log = get_logger("aiui.cli")


def _parse_vars(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in pairs:
        k, _, v = item.partition("=")
        if k.strip():
            out[k.strip().upper()] = v
    return out


def _apply_overrides(settings: Settings, args) -> Settings:
    if getattr(args, "fake", False):
        settings.llm_mode = "fake"
    if getattr(args, "headed", False):
        settings.headless = False
    if getattr(args, "yes", False):
        settings.interactive = False
    return settings


def _audit_path(settings: Settings, prefix: str) -> Path:
    folder = settings.artifacts_dir / "llm_calls"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"


def _print_plan(plan: TestPlan, notes: list[str], out: Path) -> None:
    from aiui.guardrail.policy import Guardrail

    print(f"\n[计划] {plan.plan_id}  {plan.title}")
    print(f"       需求：{plan.requirement}")
    print(f"       步骤：{len(plan.steps)} 步  hash={plan.plan_hash}")
    for s in plan.steps:
        target = s.target.description if s.target else (s.value or "")
        print(f"       - {s.id:<4} {s.action.value:<15} {s.risk.value}  {s.intent or target}")
    risks = Guardrail(get_settings()).describe_risk(plan)
    if risks:
        print("[高风险] 以下步骤会修改真实数据，运行前需签核 + 运行时放行：")
        for r in risks:
            mark = "已签核" if r["step_id"] in plan.approved_high_risk else "未签核"
            print(f"         {r['step_id']}  {r['action']}  {r['target']}  ({mark})")
        print(f"         签核：aiui approve {out} {' '.join(r['step_id'] for r in risks)}")
        print(f"         放行：aiui run {out} --allow-high-risk all")
    if notes:
        print("[提示] " + "; ".join(notes[:5]))
    print(f"[落盘] {out}\n")


def cmd_plan(args) -> int:
    settings = _apply_overrides(get_settings(reload=True), args)
    setup_logging(args.verbose)
    settings.ensure_dirs()
    vars_ = _parse_vars(args.var)
    gateway = build_gateway(settings, audit_path=_audit_path(settings, "plan"))

    page_map = build_page_map(args.base_url, settings) if args.sniff else None
    parser = PlanParser(gateway, settings)
    try:
        plan, notes = parser.parse(args.requirement, args.base_url, page_map, vars_)
        plan, transcript = clarify_gate(
            plan, settings, set(vars_),
            interactive=settings.interactive and sys.stdin.isatty(),
        )
    except ClarificationRequired as exc:
        print("\n[需要澄清] 以下问题无法自动补全：")
        for q in exc.questions:
            print(f"  - {q}")
        print("请用 --var KEY=VALUE 提供取值，或在交互终端里重跑。")
        return 3

    notes += transcript
    out = Path(args.out) if args.out else settings.plans_dir / f"{plan.plan_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    _print_plan(plan, notes, out)
    return 0


def cmd_run(args) -> int:
    settings = _apply_overrides(get_settings(reload=True), args)
    setup_logging(args.verbose)
    settings.ensure_dirs()
    path = Path(args.plan_file)
    if not path.exists():
        print(f"[错误] 计划文件不存在：{path}")
        return 3
    try:
        plan = TestPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] 计划文件不合法：{exc}")
        return 3

    allow = set(x for x in (args.allow_high_risk or []) if x != "all")
    if "all" in (args.allow_high_risk or []):
        allow |= set(plan.approved_high_risk)
    gateway = build_gateway(settings, audit_path=_audit_path(settings, "run"))
    runner = Runner(settings, gateway)
    summary = runner.run(plan, allow_high_risk=allow, variables=_parse_vars(args.var))
    _print_summary(summary)
    return {"passed": 0, "failed": 1, "blocked": 2}.get(summary.status, 1)


def cmd_approve(args) -> int:
    """人工签核：把选定的高风险步骤写进计划文件（运行时仍需 --allow-high-risk）。"""
    from aiui.guardrail.policy import Guardrail

    settings = get_settings(reload=True)
    setup_logging(args.verbose)
    path = Path(args.plan_file)
    if not path.exists():
        print(f"[错误] 计划文件不存在：{path}")
        return 3
    plan = TestPlan.model_validate_json(path.read_text(encoding="utf-8"))
    risks = Guardrail(settings).describe_risk(plan)
    if not risks:
        print("[信息] 该计划没有高风险步骤，无需签核")
        return 0
    if not args.step_ids:
        print("[高风险步骤]")
        for r in risks:
            print(f"  {r['step_id']}  {r['action']}  {r['target']}  命中={r['hits']}")
        print(f"\n签核命令：aiui approve {path} {' '.join(r['step_id'] for r in risks)}")
        return 0
    valid = {r["step_id"] for r in risks}
    bad = [s for s in args.step_ids if s not in valid]
    if bad:
        print(f"[错误] 这些步骤不是高风险步骤：{bad}")
        return 3
    plan.approved_high_risk = sorted(set(args.step_ids))
    plan.plan_hash = plan.compute_hash()
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print(f"[已签核] {', '.join(plan.approved_high_risk)}  ->  {path}")
    return 0


def cmd_go(args) -> int:
    settings = _apply_overrides(get_settings(reload=True), args)
    setup_logging(args.verbose)
    settings.ensure_dirs()
    vars_ = _parse_vars(args.var)
    gateway = build_gateway(settings, audit_path=_audit_path(settings, "go"))
    page_map = build_page_map(args.base_url, settings) if args.sniff else None

    parser = PlanParser(gateway, settings)
    try:
        plan, notes = parser.parse(args.requirement, args.base_url, page_map, vars_)
        plan, transcript = clarify_gate(
            plan, settings, set(vars_),
            interactive=settings.interactive and sys.stdin.isatty(),
        )
    except ClarificationRequired as exc:
        print("\n[需要澄清]")
        for q in exc.questions:
            print(f"  - {q}")
        return 3

    if notes or transcript:
        log.info("生成备注：%s", "; ".join(notes + transcript))

    allow = set(plan.approved_high_risk)
    if args.allow_high_risk and "all" not in args.allow_high_risk:
        allow &= set(args.allow_high_risk)
    runner = Runner(settings, gateway)
    summary = runner.run(plan, allow_high_risk=allow, variables=vars_)
    _print_summary(summary)
    return {"passed": 0, "failed": 1, "blocked": 2}.get(summary.status, 1)


def cmd_sniff(args) -> int:
    settings = _apply_overrides(get_settings(reload=True), args)
    setup_logging(args.verbose)
    data = build_page_map(args.url, settings)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_report(args) -> int:
    settings = get_settings(reload=True)
    results = Path(args.results or settings.artifacts_dir / "allure-results")
    out = Path(args.out or "allure-report")
    exe = shutil.which("allure")
    if not exe:
        print("[提示] 未找到 allure 命令。安装：scoop install allure 或 npm i -g allure-commandline")
        print(f"       结果目录：{results.resolve()}")
        return 3
    cmd = [exe, "generate", str(results), "-o", str(out), "--clean"]
    print("[执行] " + " ".join(cmd))
    return subprocess.call(cmd)


def _print_summary(summary) -> None:
    m = summary.metrics or {}
    print("\n" + "=" * 66)
    print(f"[结果] {summary.status.upper():<8} passed {summary.passed}/{summary.total}  "
          f"failed {summary.failed}  blocked {summary.blocked}  用时 {summary.duration_s}s")
    if m:
        print(f"[定位] cache {m.get('cache_hits', 0)} / rule {m.get('rule_hits', 0)} / "
              f"ai {m.get('ai_hits', 0)}  (AI占比 {m.get('ai_ratio_pct', 0)}%, "
              f"拒绝 {m.get('ai_rejected', 0)}, 平均 {m.get('avg_locate_ms', 0)}ms)")
        print(f"[模型] {m.get('gateway')} calls={m.get('calls', 0)} tokens={m.get('tokens', 0)}")
    if summary.error:
        print(f"[原因] {summary.error}")
    print(f"[产物] {summary.artifacts}")
    results = Path("artifacts") / "allure-results"
    if results.exists():
        print(f"[Allure] pytest --alluredir={results} 的结果可执行：aiui report")
    print("=" * 66 + "\n")


def cmd_doctor(args) -> int:
    """环境自检：驱动/key/依赖/目录/缓存，一次说清楚。"""
    from aiui import doctor
    from aiui.doctor import Check

    settings = _apply_overrides(get_settings(reload=True), args)
    setup_logging(args.verbose)
    checks = doctor.run_all(settings, browser=not args.no_browser)

    if args.llm and settings.deepseek_api_key:
        from aiui.llm.gateway import build_gateway

        t0 = time.time()
        try:
            gw = build_gateway(settings)
            gw.chat_json(
                [{"role": "user", "content": '只输出 json：{"ok": true}'}],
                purpose="doctor", max_tokens=20,
            )
            checks.append(Check("llm-ping", "ok", f"{int((time.time() - t0) * 1000)}ms"))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("llm-ping", "fail", str(exc)[:110], "检查网络/额度/key"))

    print()
    for c in checks:
        print(c.line())
    ok, warn, fail = doctor.summarize(checks)
    print(f"\n汇总：OK {ok} / WARN {warn} / FAIL {fail}")
    if fail:
        print("存在 FAIL 项，先按提示修复再跑计划。")
    return 1 if fail else 0


def _allow_set(plan: TestPlan, raw: list[str] | None) -> set[str]:
    raw = raw or []
    if "all" in raw:
        return set(plan.approved_high_risk)
    return set(x for x in raw if x != "all")


def cmd_bench(args) -> int:
    """同一计划连跑 N 轮，看冷缓存→暖缓存的收敛。"""
    from aiui import bench

    settings = _apply_overrides(get_settings(reload=True), args)
    setup_logging(args.verbose)
    settings.ensure_dirs()
    path = Path(args.plan_file)
    if not path.exists():
        print(f"[错误] 计划文件不存在：{path}")
        return 3
    plan = TestPlan.model_validate_json(path.read_text(encoding="utf-8"))
    gateway = build_gateway(settings, audit_path=_audit_path(settings, "bench"))
    allow = _allow_set(plan, args.allow_high_risk)
    rows = bench.run_rounds(plan, settings, gateway, rounds=args.rounds, allow=allow)
    print(f"\n[基准] {plan.plan_id}  {args.rounds} 轮\n")
    print(bench.format_table(rows))
    out = bench.write_report(rows, plan, settings.artifacts_dir)
    print(f"\n[报告] {out}")
    return 0 if all(r["status"] == "passed" for r in rows) else 1


def cmd_suite(args) -> int:
    """按 glob 批量跑计划，输出汇总表（M5 的 8 条 E2E 用它一把跑完）。"""
    import glob as globmod

    settings = _apply_overrides(get_settings(reload=True), args)
    setup_logging(args.verbose)
    settings.ensure_dirs()
    paths = [Path(p) for p in sorted(globmod.glob(args.pattern))]
    if not paths:
        print(f"[错误] 没有匹配的计划文件：{args.pattern}")
        return 3

    gateway = build_gateway(settings, audit_path=_audit_path(settings, "suite"))
    from aiui.executor.browser import build_driver

    driver = build_driver(settings)
    results: list[tuple[Path, object]] = []
    try:
        for p in paths:
            try:
                driver.delete_all_cookies()
            except Exception:  # noqa: BLE001
                pass
            plan = TestPlan.model_validate_json(p.read_text(encoding="utf-8"))
            allow = _allow_set(plan, args.allow_high_risk)
            summary = Runner(settings, gateway).run(
                plan, driver=driver, allow_high_risk=allow, close_driver=False,
            )
            results.append((p, summary))
            print(f"  {summary.status.upper():<8} {p.name:<28} "
                  f"{summary.passed}/{summary.total}  {summary.duration_s}s")
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass

    passed = sum(1 for _, s in results if s.status == "passed")
    total_steps = sum(s.total for _, s in results)
    ok_steps = sum(s.passed for _, s in results)
    agg = {"cache": 0, "rule": 0, "ai": 0}
    for _, s in results:
        m = s.metrics or {}
        for k in agg:
            agg[k] += m.get(f"{k}_hits", 0)
    located = sum(agg.values())
    print(f"\n[汇总] 计划 {passed}/{len(results)} 通过  步骤 {ok_steps}/{total_steps}  "
          f"cache {agg['cache']} / rule {agg['rule']} / ai {agg['ai']}"
          f"（AI 占比 {round(agg['ai'] * 100 / located, 1) if located else 0}%）")

    import json as _json

    report = settings.artifacts_dir / f"suite-{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.write_text(
        _json.dumps(
            [{"plan": p.name, "status": s.status, "passed": s.passed, "total": s.total,
              "metrics": s.metrics, "artifacts": s.artifacts} for p, s in results],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[报告] {report}")
    return 0 if passed == len(results) else 1


def cmd_lint(args) -> int:
    """计划静态体检：不启动浏览器，先挑出可定位性/断言/签核问题。"""
    from aiui.planning.lint import lint_plan, summarize

    settings = _apply_overrides(get_settings(reload=True), args)
    setup_logging(args.verbose)
    path = Path(args.plan_file)
    if not path.exists():
        print(f"[错误] 计划文件不存在：{path}")
        return 3
    plan = TestPlan.model_validate_json(path.read_text(encoding="utf-8"))
    issues = lint_plan(plan, settings)
    print(f"\n[体检] {plan.plan_id}  {len(plan.steps)} 步  hash={plan.plan_hash}")
    if not issues:
        print("  [OK] 未发现问题")
    for issue in issues:
        print("  " + issue.line().replace("\n", "\n  "))
    errors, warns = summarize(issues)
    print(f"\n汇总：ERROR {errors} / WARN {warns}")
    return 1 if errors else 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aiui", description="AI 驱动 UI 自动化测试框架")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--fake", action="store_true", help="用 Fake 网关离线跑")
        sp.add_argument("--headed", action="store_true", help="显示浏览器窗口")
        sp.add_argument("--var", action="append", default=[], metavar="K=V")
        sp.add_argument("-v", "--verbose", action="store_true")

    sp = sub.add_parser("plan", help="自然语言生成计划（不执行）")
    sp.add_argument("requirement")
    sp.add_argument("--base-url", required=True)
    sp.add_argument("--out")
    sp.add_argument("--sniff", action="store_true", help="先采集页面地图再生成")
    sp.add_argument("--yes", action="store_true", help="非交互模式")
    common(sp)
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("run", help="执行已有计划")
    sp.add_argument("plan_file")
    sp.add_argument("--allow-high-risk", action="append", default=[], metavar="STEP_ID")
    common(sp)
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("go", help="生成 + 澄清 + 执行")
    sp.add_argument("requirement")
    sp.add_argument("--base-url", required=True)
    sp.add_argument("--sniff", action="store_true")
    sp.add_argument("--yes", action="store_true")
    sp.add_argument("--allow-high-risk", action="append", default=[], metavar="STEP_ID")
    common(sp)
    sp.set_defaults(func=cmd_go)

    sp = sub.add_parser("approve", help="人工签核计划里的高风险步骤")
    sp.add_argument("plan_file")
    sp.add_argument("step_ids", nargs="*", metavar="STEP_ID")
    common(sp)
    sp.set_defaults(func=cmd_approve)

    sp = sub.add_parser("lint", help="计划静态体检（不启动浏览器）")
    sp.add_argument("plan_file")
    common(sp)
    sp.set_defaults(func=cmd_lint)

    sp = sub.add_parser("doctor", help="环境自检（驱动 / key / 依赖 / 目录）")
    sp.add_argument("--no-browser", action="store_true", help="跳过浏览器启动检查")
    sp.add_argument("--llm", action="store_true", help="额外发一次真实模型请求")
    sp.add_argument("--fake", action="store_true")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("bench", help="同一计划连跑 N 轮，看冷/暖缓存收敛")
    sp.add_argument("plan_file")
    sp.add_argument("--rounds", type=int, default=2)
    sp.add_argument("--allow-high-risk", action="append", default=[], metavar="STEP_ID|all")
    common(sp)
    sp.set_defaults(func=cmd_bench)

    sp = sub.add_parser("suite", help="按 glob 批量执行计划并汇总")
    sp.add_argument("pattern", help='例如 "plans/vb_*.json"')
    sp.add_argument("--allow-high-risk", action="append", default=[], metavar="STEP_ID|all")
    common(sp)
    sp.set_defaults(func=cmd_suite)

    sp = sub.add_parser("sniff", help="采集页面地图")
    sp.add_argument("url")
    common(sp)
    sp.set_defaults(func=cmd_sniff)

    sp = sub.add_parser("report", help="生成 Allure HTML 报告")
    sp.add_argument("--results")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    try:
        return int(args.func(args))
    except AiuiError as exc:
        print(f"\n[失败] {exc.code}: {exc.message}")
        return 1
    except KeyboardInterrupt:
        print("\n[中断] 用户取消")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
