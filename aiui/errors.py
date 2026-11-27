"""异常体系：异常类型决定报告里的失败分类，分类决定人怎么排查。"""

from __future__ import annotations

from typing import Any


class AiuiError(Exception):
    code = "AIUI_ERROR"

    def __init__(self, message: str, **ctx: Any) -> None:
        super().__init__(message)
        self.message = message
        self.ctx = ctx

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.ctx}


class PlanGenerationError(AiuiError):
    code = "PLAN_GENERATION_ERROR"


class PlanValidationError(AiuiError):
    code = "PLAN_VALIDATION_ERROR"

    def __init__(self, message: str, violations: list[Any] | None = None, **ctx: Any) -> None:
        super().__init__(message, **ctx)
        self.violations = violations or []

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["violations"] = [getattr(v, "__dict__", v) for v in self.violations]
        return d


class ClarificationRequired(AiuiError):
    code = "CLARIFICATION_REQUIRED"

    def __init__(self, questions: list[Any], **ctx: Any) -> None:
        super().__init__(f"需要澄清 {len(questions)} 个问题", **ctx)
        self.questions = questions


class LocateError(AiuiError):
    code = "LOCATE_ERROR"

    def __init__(self, message: str, chain: list[str] | None = None, **ctx: Any) -> None:
        super().__init__(message, **ctx)
        self.chain = chain or []


class LowConfidenceError(LocateError):
    code = "LOW_CONFIDENCE"


class AmbiguousError(LocateError):
    code = "AMBIGUOUS"


class RetiredError(LocateError):
    code = "RETIRED"


class HighRiskBlocked(AiuiError):
    code = "HIGH_RISK_BLOCKED"

    def __init__(self, message: str, rule: str = "", would_do: str = "", **ctx: Any) -> None:
        super().__init__(message, **ctx)
        self.rule = rule
        self.would_do = would_do


class StepTimeout(AiuiError):
    code = "STEP_TIMEOUT"


class ActionError(AiuiError):
    code = "ACTION_ERROR"
