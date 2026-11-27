from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiui.cli import main
from aiui.planning.models import ActionType, Assertion, PlanStep, TestPlan


@pytest.fixture()
def plan_file(tmp_path: Path) -> Path:
    plan = TestPlan(
        plan_id="cli_demo", title="CLI 演示", requirement="打开页面并断言",
        base_url="http://localhost:8040",
        steps=[
            PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
            PlanStep(id="s2", action=ActionType.ASSERT_TEXT,
                     assertion=Assertion(kind="contains", expected="ok")),
        ],
    )
    p = tmp_path / "cli_demo.json"
    p.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return p


def test_lint_command_ok(plan_file: Path):
    assert main(["lint", str(plan_file)]) == 0


def test_lint_missing_file(tmp_path: Path):
    assert main(["lint", str(tmp_path / "nope.json")]) == 3


def test_run_missing_file(tmp_path: Path):
    assert main(["run", str(tmp_path / "nope.json")]) == 3


def test_approve_lists_risks(plan_file: Path):
    assert main(["approve", str(plan_file)]) == 0


def test_doctor_without_browser():
    assert main(["doctor", "--no-browser", "--fake"]) == 0


def test_lint_reports_error(tmp_path: Path):
    bad = TestPlan(plan_id="bad", base_url="http://localhost", steps=[
        PlanStep(id="s1", action=ActionType.NAVIGATE, value="/"),
        PlanStep(id="s2", action=ActionType.INPUT,
                 target=None),
    ])
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad.model_dump(mode="json")), encoding="utf-8")
    assert main(["lint", str(p)]) == 1
