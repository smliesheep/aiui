"""Tier2 规则匹配：可解释、可调参、零模型调用。

打分用「饱和累加」：score = 1 - Π(1 - w_i)。
好处是单个强信号（label 精确命中）就能过阈值，多个弱信号也能叠加；
坏处是需要调好单信号权重，所以权重集中放在 WEIGHTS 里，便于回归调参。

唯一命中要求「分数够高 + 领先第二名够多」：
只卡绝对分会把「两个都像」误当成命中，卡 gap 才能识别真歧义。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from aiui.locator.collector import Candidate
from aiui.planning.models import TargetSpec

# 归一化同义词：把「登录/login/sign in」收敛成同一个 token
SYNONYMS = {
    "登录": "login", "登陆": "login", "signin": "login",
    "注册": "register", "signup": "register",
    "转账": "transfer", "汇款": "transfer",
    "余额": "balance", "可用余额": "balance",
    "确认": "confirm", "确定": "confirm",
    "取消": "cancel",
    "提交": "submit", "保存": "save",
    "密码": "password",
    "用户名": "username",
    "账号": "account",
    "金额": "amount",
}

# 单信号权重：0.72 类表示「这一个信号本身就足以定位」
WEIGHTS = {
    "testid": 0.95,
    "name": 0.75,
    "id": 0.75,
    "label_eq": 0.72,
    "placeholder_eq": 0.68,
    "aria_eq": 0.70,
    "label_in": 0.55,
    "placeholder_in": 0.52,
    "aria_in": 0.52,
    "text_eq": 0.72,
    "text_in": 0.55,
    "nearby": 0.30,
    "container": 0.18,
    "fuzzy_max": 0.15,
}

_PUNCT = re.compile(
    r"[\s\u3000`~!@#$%^&*()\-_=+\[\]{}\\|;:'\",.<>/?·！￥…（）—【】；：‘’“”、。，《》？]+"
)


def norm(text: str | None) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).strip().lower()
    s = re.sub(r"\s+", "", s)  # 先去空白，避免「用户 名」绕过同义词
    for src, dst in SYNONYMS.items():
        if src in s:
            s = s.replace(src, dst)
    s = _PUNCT.sub("", s)
    return s


@dataclass
class Scored:
    cand: Candidate
    score: float = 0.0
    hits: list[str] = field(default_factory=list)

    def add(self, weight: float, reason: str) -> None:
        self.score = 1.0 - (1.0 - self.score) * (1.0 - weight)
        self.hits.append(f"{reason}+{weight:.2f}")

    def to_dict(self) -> dict:
        return {
            "i": self.cand.i, "text": self.cand.text,
            "score": round(self.score, 3), "hits": self.hits,
        }


def score_candidate(target: TargetSpec, cand: Candidate) -> Scored:
    s = Scored(cand=cand)
    hints = target.hints
    attrs = cand.attrs

    if hints.test_id and attrs.get("testid") and hints.test_id == attrs["testid"]:
        s.add(WEIGHTS["testid"], "testid")

    if hints.name and norm(hints.name) == norm(attrs.get("name")):
        s.add(WEIGHTS["name"], "name")

    if hints.name and attrs.get("id") and norm(hints.name) == norm(attrs["id"]):
        s.add(WEIGHTS["id"], "id")

    for hint_val, attr_key, eq_key, in_key, label in (
        (hints.label, "label", "label_eq", "label_in", "label"),
        (hints.placeholder, "ph", "placeholder_eq", "placeholder_in", "placeholder"),
        (hints.aria_label, "aria", "aria_eq", "aria_in", "aria"),
    ):
        if not hint_val:
            continue
        hv, av = norm(hint_val), norm(attrs.get(attr_key))
        if not av or not hv:
            continue
        if hv == av:
            s.add(WEIGHTS[eq_key], label)
        elif hv in av or av in hv:
            s.add(WEIGHTS[in_key], f"{label}_in")

    if hints.text:
        ht, ct = norm(hints.text), norm(cand.text)
        if ht and ht == ct:
            s.add(WEIGHTS["text_eq"], "text")
        elif ht and (ht in ct or ct in ht):
            s.add(WEIGHTS["text_in"], "text_in")

    ancestor = norm(attrs.get("anc"))
    if hints.nearby_text and norm(hints.nearby_text) in ancestor:
        s.add(WEIGHTS["nearby"], "nearby")
    if hints.container_text and norm(hints.container_text) in ancestor:
        s.add(WEIGHTS["container"], "container")

    fuzzy_src = norm(hints.text or hints.label or hints.placeholder or target.description)
    ratio = SequenceMatcher(None, fuzzy_src, norm(cand.text)).ratio()
    if ratio > 0.5:
        s.add(WEIGHTS["fuzzy_max"] * ratio, "fuzzy")

    if not cand.visible:
        s.score = max(0.0, s.score - 0.5)
        s.hits.append("invisible-0.50")

    s.score = max(0.0, min(s.score, 0.99))
    return s


def rank(target: TargetSpec, cands: list[Candidate]) -> list[Scored]:
    return sorted((score_candidate(target, c) for c in cands), key=lambda x: x.score, reverse=True)


def best_match(target: TargetSpec, cands: list[Candidate], min_score: float,
               min_gap: float) -> tuple[Scored | None, Scored | None, str]:
    """返回 (最优, 次优, 判定说明)。判定值：rule_hit / ambiguous / low_score / empty。"""
    ranked = rank(target, cands)
    if not ranked:
        return None, None, "empty"
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    gap = best.score - (second.score if second else 0.0)
    if best.score < min_score:
        return best, second, f"low_score({best.score:.2f})"
    if gap < min_gap:
        return best, second, f"ambiguous(gap={gap:.2f})"
    return best, second, "rule_hit"
