from __future__ import annotations

import json
from pathlib import Path

from aiui.config import Settings
from aiui.evidence import masking
from aiui.evidence.collector import EvidenceCollector
from aiui.planning.models import ActionType, PlanStep, TestPlan


def test_mask_card_and_phone():
    s = masking.mask_text("card 6222021234567890123 phone 13812345678")
    assert "6222021234567890123" not in s
    assert "13812345678" not in s


def test_mask_password_input_value():
    html = '<input type="password" name="pwd" value="secret" />'
    assert "secret" not in masking.mask_html(html)


def test_collector_writes_requirement_and_plan(tmp_path: Path):
    settings = Settings(llm_mode="fake", artifacts_dir=tmp_path, cache_db=tmp_path / "c.db")
    plan = TestPlan(plan_id="p", title="演示", requirement="打开页面",
                    base_url="http://localhost", steps=[
                        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/")
                    ])
    collector = EvidenceCollector(tmp_path, settings)
    collector.start(plan, [])
    collector.finish({"status": "passed"})
    assert (tmp_path / "00-requirement.md").exists()
    data = json.loads((tmp_path / "01-plan.json").read_text(encoding="utf-8"))
    assert data["plan"]["plan_id"] == "p"
    assert json.loads((tmp_path / "99-summary.json").read_text(encoding="utf-8"))["status"] == "passed"
