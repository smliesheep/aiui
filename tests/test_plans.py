"""把 plans/*.json 变成 pytest 用例：天然获得 Allure 步骤树与失败截图。

运行：
    pytest tests/test_plans.py --alluredir=artifacts/allure-results
    allure generate artifacts/allure-results -o allure-report --clean

高风险步骤默认「按计划签核放行」；设置 AIUI_ALLOW_HIGH_RISK=0 可强制拦截验证。
"""

from __future__ import annotations

import functools
import os
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from aiui.config import Settings
from aiui.executor.runner import Runner
from aiui.planning.models import TestPlan

ROOT = Path(__file__).resolve().parent.parent
PLANS = sorted((ROOT / "plans").glob(os.environ.get("AIUI_PLANS_GLOB", "*.json")))
PAGES = ROOT / "tests" / "pages"


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session", autouse=True)
def demo_server():
    """计划里用的是 http://127.0.0.1:8765，没有外部服务时自动起一个。"""
    if not PLANS or _port_open(8765):
        yield
        return
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(PAGES))
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield
    srv.shutdown()


@pytest.mark.parametrize("plan_file", PLANS, ids=[p.stem for p in PLANS])
def test_plan_executes(plan_file: Path, tmp_path: Path):
    if not PLANS:
        pytest.skip("plans/ 下没有计划文件")
    plan = TestPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))
    settings = Settings(
        llm_mode="deepseek",  # 计划测试用真实模型；没有 key 就跳过（unit 测试另有 Fake 覆盖）
        artifacts_dir=tmp_path / "artifacts",
        cache_db=tmp_path / "locator.db",
        headless=True,
    )
    if not settings.deepseek_api_key:
        pytest.skip("未配置 AIUI_DEEPSEEK_API_KEY，跳过真实计划执行")
    allow = set(plan.approved_high_risk) if os.environ.get("AIUI_ALLOW_HIGH_RISK", "1") != "0" else set()
    summary = Runner(settings).run(plan, allow_high_risk=allow)
    assert summary.status == "passed", f"{summary.error}（产物：{summary.artifacts}）"
