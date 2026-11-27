"""全局配置：全部来自环境变量 / .env，密钥不落代码。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AIUI_",
        extra="ignore",
    )

    # ---- 模型 ----
    llm_mode: Literal["deepseek", "fake"] = "fake"
    deepseek_api_key: str = Field(default="", repr=False)  # repr=False: 不进日志
    deepseek_base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    llm_temperature: float = 0.0
    llm_max_repair: int = 2  # 计划修复重问次数
    llm_cache_enabled: bool = True

    # ---- 定位阈值 ----
    confidence_min: float = 0.60
    rule_min_score: float = 0.70
    rule_min_gap: float = 0.15
    max_candidates: int = 40
    collect_limit: int = 200
    cache_enabled: bool = True

    # ---- 执行 ----
    headless: bool = True
    browser: Literal["chrome", "edge"] = "chrome"
    chromedriver_path: str = ""  # 留空则自动在 .drivers/ 下找，最后回退 Selenium Manager
    window_size: str = "1440,900"
    page_load_timeout: int = 20
    timeout_ms: int = 8000
    screenshot_on_success: bool = False
    evidence_max_bytes: int = 8 * 1024 * 1024

    # ---- 路径 ----
    artifacts_dir: Path = Path("artifacts")
    cache_db: Path = Path(".aiui/locator.db")
    llm_cache_dir: Path = Path(".aiui/llm_cache")
    plans_dir: Path = Path("plans")

    # ---- 安全 ----
    allowed_hosts: str = ""
    interactive: bool = True
    allow_high_risk_flag: bool = False

    @field_validator("window_size")
    @classmethod
    def _check_window(cls, v: str) -> str:
        if "," not in v:
            raise ValueError("window_size 形如 1440,900")
        return v

    @property
    def hosts(self) -> list[str]:
        return [h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def window(self) -> tuple[int, int]:
        w, h = self.window_size.split(",")
        return int(w), int(h)

    def ensure_dirs(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.cache_db.parent.mkdir(parents=True, exist_ok=True)
        self.llm_cache_dir.mkdir(parents=True, exist_ok=True)
        self.plans_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    global _settings
    if _settings is None or reload:
        _settings = Settings()
    return _settings
