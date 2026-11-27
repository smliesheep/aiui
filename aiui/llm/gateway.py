"""模型网关：系统里唯一和 LLM 通信的出口。

三个职责：
1. 约束输出为 json（DeepSeek json_object 模式，prompt 中必须出现 "json" 字样）；
2. 计量与审计（token、耗时、prompt 摘要、响应原文落盘）；
3. 响应缓存（同 prompt 命中即复用，回归期不重复烧 token）。
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from aiui.config import Settings
from aiui.errors import AiuiError
from aiui.logging import get_logger

log = get_logger(__name__)


class LLMError(AiuiError):
    code = "LLM_ERROR"


class LLMGateway(ABC):
    name = "base"

    def __init__(self) -> None:
        self.calls = 0
        self.total_tokens = 0
        self.total_latency_ms = 0

    @abstractmethod
    def chat_json(self, messages: list[dict[str, str]], *, purpose: str,
                  max_tokens: int = 1500) -> dict[str, Any]:
        ...

    @property
    def stats(self) -> dict[str, Any]:
        avg = self.total_latency_ms / self.calls if self.calls else 0
        return {
            "gateway": self.name,
            "calls": self.calls,
            "tokens": self.total_tokens,
            "avg_latency_ms": round(avg, 1),
        }


def extract_json(text: str) -> dict[str, Any]:
    """从模型回复里取 JSON：容忍 ```json 围栏与前后闲话。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError(f"模型未返回 JSON：{text[:200]!r}")
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型返回的 JSON 解析失败：{exc}；原文 {text[:300]!r}") from exc


class DeepSeekGateway(LLMGateway):
    name = "deepseek"

    def __init__(self, settings: Settings, audit_path: Path | None = None) -> None:
        super().__init__()
        if not settings.deepseek_api_key:
            raise LLMError("未配置 AIUI_DEEPSEEK_API_KEY")
        from openai import OpenAI

        self.settings = settings
        self.audit_path = audit_path
        self.cache_dir = settings.llm_cache_dir if settings.llm_cache_enabled else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=60,
            max_retries=2,
        )

    def _cache_key(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        raw = json.dumps(
            {"model": self.settings.model, "messages": messages, "max_tokens": max_tokens},
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def chat_json(self, messages: list[dict[str, str]], *, purpose: str,
                  max_tokens: int = 1500) -> dict[str, Any]:
        key = self._cache_key(messages, max_tokens)
        if self.cache_dir:
            cached = self.cache_dir / f"{key}.json"
            if cached.exists():
                log.debug("LLM 缓存命中 %s (%s)", key, purpose)
                self.calls += 1
                return json.loads(cached.read_text(encoding="utf-8"))

        started = time.time()
        try:
            resp = self.client.chat.completions.create(
                model=self.settings.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=self.settings.llm_temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001 - 统一转成框架异常
            raise LLMError(f"模型调用失败：{exc}") from exc
        latency = int((time.time() - started) * 1000)

        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
        self.calls += 1
        self.total_tokens += tokens
        self.total_latency_ms += latency

        data = extract_json(text)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": purpose,
            "model": getattr(resp, "model", self.settings.model),
            "latency_ms": latency,
            "tokens": tokens,
            "prompt_chars": sum(len(m.get("content", "")) for m in messages),
            "response": data,
        }
        self._audit(record)
        if self.cache_dir:
            (self.cache_dir / f"{key}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return data

    def _audit(self, record: dict[str, Any]) -> None:
        if not self.audit_path:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_gateway(settings: Settings, audit_path: Path | None = None,
                  fixtures_dir: Path | None = None) -> LLMGateway:
    from aiui.llm.fake import FakeGateway

    if settings.llm_mode == "fake":
        return FakeGateway(fixtures_dir or Path("fixtures/llm"))
    if not settings.deepseek_api_key:
        log.warning("未配置 API Key，自动降级为 fake 模式")
        return FakeGateway(fixtures_dir or Path("fixtures/llm"))
    return DeepSeekGateway(settings, audit_path=audit_path)
