from __future__ import annotations

import pytest

from aiui.config import Settings
from aiui.errors import PlanGenerationError
from aiui.llm.fake import FakeGateway
from aiui.planning.parser import PlanParser

SETTINGS = Settings(llm_mode="fake", allowed_hosts="localhost,127.0.0.1")

GOOD = {
    "plan_id": "login",
    "title": "登录",
    "requirement": "登录系统",
    "base_url": "http://localhost:8040",
    "steps": [
        {"id": "s1", "action": "navigate", "value": "/login", "risk": "L0", "intent": "打开登录页"},
        {"id": "s2", "action": "input", "value": "${USER}", "risk": "L1",
         "target": {"description": "用户名输入框", "hints": {"label": "Username"}}},
        {"id": "s3", "action": "click", "risk": "L2",
         "target": {"description": "登录按钮", "hints": {"text": "Login"}}},
    ],
    "questions": [],
}


def test_parse_good_draft():
    parser = PlanParser(FakeGateway(responses={"plan": [GOOD]}), SETTINGS)
    plan, notes = parser.parse("登录系统", "http://localhost:8040", None,
                               {"USER": "alice"})
    assert plan.plan_id == "login"
    assert len(plan.steps) == 3
    assert plan.plan_hash


def test_auto_adds_navigate_when_missing():
    draft = dict(GOOD)
    draft["steps"] = GOOD["steps"][1:]
    parser = PlanParser(FakeGateway(responses={"plan": [draft]}), SETTINGS)
    plan, notes = parser.parse("登录系统", "http://localhost:8040", None, {"USER": "a"})
    assert plan.steps[0].action.value == "navigate"
    assert any("navigate" in n for n in notes)


def test_repairs_invalid_draft():
    bad = {"steps": [{"id": "s1", "action": "click", "risk": "L0"}]}
    parser = PlanParser(FakeGateway(responses={"plan": [bad, GOOD]}), SETTINGS)
    plan, _ = parser.parse("登录系统", "http://localhost:8040", None, {"USER": "a"})
    assert plan.plan_id == "login"


def test_gives_up_after_max_repair():
    bad = {"steps": [{"id": "s1", "action": "click"}]}
    gw = FakeGateway(responses={"plan": [bad, bad, bad]})
    parser = PlanParser(gw, Settings(llm_mode="fake", llm_max_repair=2,
                                     allowed_hosts="localhost"))
    with pytest.raises(PlanGenerationError):
        parser.parse("登录", "http://localhost:8040", None, {})


def test_no_steps_raises():
    parser = PlanParser(FakeGateway(responses={"plan": [{"steps": [], "questions": []}]}), SETTINGS)
    with pytest.raises(PlanGenerationError):
        parser.parse("登录", "http://localhost:8040", None, {})


def test_prompt_contains_json_and_whitelist():
    parser = PlanParser(FakeGateway(responses={"plan": [GOOD]}), SETTINGS)
    msgs = parser.build_messages("登录", "http://localhost:8040", {"title": "Demo"}, {"USER": "a"})
    text = "\n".join(m["content"] for m in msgs)
    assert "json" in text
    for action in ("navigate", "click", "input", "assert_text", "extract"):
        assert action in text
    assert "禁止输出选择器" in text
