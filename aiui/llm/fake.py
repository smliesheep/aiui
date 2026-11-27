"""Fake 网关：离线跑通全链路 + 单测可复现。

两种用法：
- `FakeGateway(responses={"plan": [ {...draft...} ]})`：单测里精确控制；
- `FakeGateway(fixtures_dir=Path("fixtures/llm"))`：CLI 演示时从磁盘回放，
  文件按 `<purpose>/<序号>.json` 存放。
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from aiui.errors import AiuiError
from aiui.llm.gateway import LLMGateway


class FakeGateway(LLMGateway):
    name = "fake"

    def __init__(self, fixtures_dir: Path | None = None,
                 responses: dict[str, list[dict[str, Any]]] | None = None) -> None:
        super().__init__()
        self.fixtures_dir = fixtures_dir
        self._queues: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        self._served: dict[str, int] = defaultdict(int)
        for purpose, items in (responses or {}).items():
            self._queues[purpose].extend(items)

    def _load_fixture(self, purpose: str, index: int) -> dict[str, Any] | None:
        if not self.fixtures_dir:
            return None
        folder = self.fixtures_dir / purpose
        if not folder.is_dir():
            return None
        files = sorted(folder.glob("*.json"))
        if index >= len(files):
            return None
        return json.loads(files[index].read_text(encoding="utf-8"))

    def chat_json(self, messages: list[dict[str, str]], *, purpose: str,
                  max_tokens: int = 1500) -> dict[str, Any]:
        self.calls += 1
        self.total_latency_ms += 1
        if self._queues[purpose]:
            return self._queues[purpose].popleft()
        idx = self._served[purpose]
        data = self._load_fixture(purpose, idx)
        if data is None:
            raise AiuiError(
                f"FakeGateway 没有可回放的 {purpose!r} 响应"
                f"（fixtures_dir={self.fixtures_dir}）"
            )
        self._served[purpose] += 1
        return data
