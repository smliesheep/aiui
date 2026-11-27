"""定位结果与元素解析（放在独立模块，避免 resolver / ai_matcher 循环引用）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LocateResult:
    tier: str  # cache | rule | ai
    locator: str
    marker: str | None = None
    confidence: float = 0.0
    score: float = 0.0
    reason: str = ""
    candidate_id: int | None = None
    fallback_chain: list[str] = field(default_factory=list)
    in_frame: bool = False
    cache_hit: Any = None
    expect_text: str = ""

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "locator": self.locator,
            "marker": self.marker,
            "confidence": round(self.confidence, 3),
            "score": round(self.score, 3),
            "reason": self.reason,
            "candidate_id": self.candidate_id,
            "fallback_chain": self.fallback_chain,
        }

    @property
    def chain_text(self) -> str:
        return " -> ".join(self.fallback_chain)
