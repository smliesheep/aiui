"""计划的数据契约（Pydantic v2）。

设计原则：
1. 模型输出只能落在这些结构里，结构外的内容进不来；
2. 结构合法 ≠ 业务合法，业务规则放在 validator.py；
3. 计划可序列化、可 diff、可 hash，是「可评审的资产」。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

VAR_RE = re.compile(r"\$\{([A-Za-z_]\w*)\}")


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    INPUT = "input"
    SELECT = "select"
    ASSERT_TEXT = "assert_text"
    ASSERT_ELEMENT = "assert_element"
    EXTRACT = "extract"
    SCREENSHOT = "screenshot"
    WAIT = "wait"
    SCROLL = "scroll"


class RiskLevel(str, Enum):
    L0 = "L0"  # 只读
    L1 = "L1"  # 可逆写
    L2 = "L2"  # 业务写
    L3 = "L3"  # 高风险不可逆

    @property
    def rank(self) -> int:
        return int(self.value[1])


class TargetHints(BaseModel):
    text: str | None = None
    label: str | None = None
    placeholder: str | None = None
    aria_label: str | None = None
    role: str | None = None
    name: str | None = None
    test_id: str | None = None
    nearby_text: str | None = None
    container_text: str | None = None


class TargetSpec(BaseModel):
    description: str = Field(min_length=2, max_length=200)
    hints: TargetHints = Field(default_factory=TargetHints)
    frame: str | None = None


class Assertion(BaseModel):
    kind: Literal["contains", "equals", "regex", "exists", "visible", "enabled", "value"]
    expected: str | None = None

    @model_validator(mode="after")
    def _need_expected(self) -> "Assertion":
        if self.kind in {"contains", "equals", "regex", "value"} and not self.expected:
            raise ValueError(f"断言 kind={self.kind} 需要 expected")
        return self


class PlanStep(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z][\w\-]*$", max_length=40)
    action: ActionType
    target: TargetSpec | None = None
    value: str | None = None
    assertion: Assertion | None = None
    timeout_ms: int = Field(default=8000, ge=500, le=60000)
    risk: RiskLevel = RiskLevel.L0
    intent: str = ""
    on_failure: Literal["abort", "continue", "retry"] = "abort"


class TestPlan(BaseModel):
    plan_id: str
    title: str = ""
    requirement: str = ""
    base_url: str = ""
    tags: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(min_length=1)
    approved_high_risk: list[str] = Field(default_factory=list)
    plan_hash: str = ""

    def canonical_json(self) -> str:
        data = self.model_dump(mode="json", exclude={"plan_hash"})
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()[:16]

    def step_by_id(self, step_id: str) -> PlanStep | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def high_risk_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.risk is RiskLevel.L3]


class PlanQuestion(BaseModel):
    """澄清阶段的问题，只允许三类，避免开放式提问。"""

    kind: Literal["missing_value", "ambiguous_target", "high_risk_confirm"]
    step_id: str | None = None
    message: str
    field: str | None = None
    options: list[str] = Field(default_factory=list)


class TestPlanDraft(BaseModel):
    """模型原始输出的宽松模型：允许缺 id/base_url，允许只出问题不出步骤。"""

    plan_id: str | None = None
    title: str = ""
    requirement: str = ""
    base_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)
    questions: list[PlanQuestion] = Field(default_factory=list)


def scan_vars(text: str | None) -> list[str]:
    return VAR_RE.findall(text or "")


def render_vars(text: str | None, variables: dict[str, str]) -> str | None:
    """只做字面量替换，不支持表达式/函数调用（防注入）。"""
    if text is None:
        return None
    return VAR_RE.sub(lambda m: str(variables.get(m.group(1), m.group(0))), text)


def slugify(text: str, fallback: str = "plan") -> str:
    s = unicodedata.normalize("NFKC", text or "").strip().lower()
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", s, flags=re.UNICODE).strip("_")
    return (s or fallback)[:48]


def as_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
