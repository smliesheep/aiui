from __future__ import annotations

from aiui.locator.collector import Candidate, durable_locator
from aiui.locator.rules import best_match, norm, rank
from aiui.planning.models import TargetHints, TargetSpec


def cand(i: int, tag="button", text="", visible=True, enabled=True, **attrs) -> Candidate:
    base = {"name": "", "id": "", "ph": "", "aria": "", "testid": "", "type": "",
            "cls": "", "label": "", "anc": ""}
    base.update(attrs)
    return Candidate(i=i, tag=tag, role="", text=text, attrs=base,
                     box=[0, 0, 10, 10], visible=visible, enabled=enabled)


def test_norm_unifies_bilingual_and_punct():
    assert norm("Login！") == norm("login")
    assert norm("登录") == norm("Login")
    assert norm(" 用户 名 ") == "username"


def test_label_exact_alone_crosses_threshold():
    t = TargetSpec(description="用户名输入框", hints=TargetHints(label="Username"))
    c = [cand(0, tag="input", text="", label="Username", name="username"),
         cand(1, tag="input", text="", label="Password", name="password")]
    best, second, verdict = best_match(t, c, 0.70, 0.15)
    assert verdict == "rule_hit"
    assert best.cand.i == 0
    assert second.cand.i == 1


def test_two_identical_candidates_are_ambiguous():
    t = TargetSpec(description="确认按钮", hints=TargetHints(text="Confirm"))
    c = [cand(0, text="Confirm"), cand(1, text="Confirm")]
    _, _, verdict = best_match(t, c, 0.70, 0.15)
    assert verdict.startswith("ambiguous")


def test_invisible_penalised():
    t = TargetSpec(description="登录按钮", hints=TargetHints(text="Login"))
    c = [cand(0, text="Login", visible=False), cand(1, text="Register")]
    best, _, _ = best_match(t, c, 0.70, 0.15)
    assert best.cand.i == 0
    assert best.score < 0.70


def test_no_match_when_score_low():
    t = TargetSpec(description="完全不相关的元素", hints=TargetHints(text="zzz"))
    c = [cand(0, text="Login"), cand(1, text="Register")]
    _, _, verdict = best_match(t, c, 0.70, 0.15)
    assert verdict.startswith("low_score") or verdict.startswith("empty")


def test_testid_wins():
    t = TargetSpec(description="提交", hints=TargetHints(test_id="submit-btn"))
    c = [cand(0, text="提交"), cand(1, text="提交", testid="submit-btn")]
    ranked = rank(t, c)
    assert ranked[0].cand.i == 1
    assert ranked[0].score > 0.95


def test_nearby_text_helps():
    t = TargetSpec(description="金额输入框", hints=TargetHints(nearby_text="Amount"))
    c = [cand(0, tag="input", text="", anc="转账表单 Amount USD"),
         cand(1, tag="input", text="", anc="转账表单 Remark")]
    best, _, _ = best_match(t, c, 0.70, 0.15)
    assert best.cand.i == 0
    assert any("nearby" in h for h in best.hits)


def test_durable_locator_prefers_stable_attributes():
    assert durable_locator(cand(3, testid="x")) == '[data-testid="x"]'
    assert durable_locator(cand(3, id="login-btn")) == '[id="login-btn"]'
    assert durable_locator(cand(3, tag="input", name="username")) == 'input[name="username"]'
    assert durable_locator(cand(3, text="Login")).startswith("//button")
