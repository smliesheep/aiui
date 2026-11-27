from __future__ import annotations

import pytest

from aiui.config import Settings
from aiui.errors import LowConfidenceError
from aiui.llm.fake import FakeGateway
from aiui.locator.ai_matcher import AIMatcher
from aiui.locator.collector import Candidate
from aiui.planning.models import TargetHints, TargetSpec

SETTINGS = Settings(llm_mode="fake", confidence_min=0.60)


def cand(i, text="", visible=True, enabled=True, **attrs) -> Candidate:
    base = {"name": "", "id": "", "ph": "", "aria": "", "testid": "", "type": "",
            "cls": "", "label": "", "anc": ""}
    base.update(attrs)
    return Candidate(i=i, tag="button", role="", text=text, attrs=base,
                     box=[0, 0, 10, 10], visible=visible, enabled=enabled)


TARGET = TargetSpec(description="登录按钮", hints=TargetHints(text="Login"))


def matcher(responses: list[dict]) -> AIMatcher:
    return AIMatcher(FakeGateway(responses={"locate": responses}), SETTINGS)


def test_accepts_valid_candidate():
    m = matcher([{"candidate_id": 1, "confidence": 0.88, "reason": "文本完全匹配"}])
    res = m.match(TARGET, [cand(0, "Register"), cand(1, "Login")], [])
    assert res.tier == "ai" and res.candidate_id == 1
    assert res.confidence == pytest.approx(0.88)
    assert res.locator


def test_rejects_low_confidence():
    m = matcher([{"candidate_id": 1, "confidence": 0.42, "reason": "有点像"}])
    with pytest.raises(LowConfidenceError) as ei:
        m.match(TARGET, [cand(0, "X"), cand(1, "Login")], [])
    assert "0.42" in str(ei.value)


def test_rejects_invalid_id():
    m = matcher([{"candidate_id": 99, "confidence": 0.99, "reason": "编的"}])
    with pytest.raises(LowConfidenceError) as ei:
        m.match(TARGET, [cand(0, "Login")], [])
    assert "不存在" in str(ei.value)


def test_rejects_non_numeric_id():
    m = matcher([{"candidate_id": "s3", "confidence": 0.9, "reason": "x"}])
    with pytest.raises(LowConfidenceError):
        m.match(TARGET, [cand(0, "Login")], [])


def test_rejects_negative_choice():
    m = matcher([{"candidate_id": -1, "confidence": 0, "reason": "不确定"}])
    with pytest.raises(LowConfidenceError):
        m.match(TARGET, [cand(0, "Login")], [])


def test_pool_capped(monkeypatch):
    many = [cand(i, f"button-{i}") for i in range(60)]
    gw = FakeGateway(responses={"locate": [{"candidate_id": 0, "confidence": 0.9, "reason": "x"}]})
    m = AIMatcher(gw, Settings(llm_mode="fake", max_candidates=40, confidence_min=0.6))
    m.match(TARGET, many, [])
    assert gw.calls == 1
