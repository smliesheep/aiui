"""环境自检：在跑计划之前先回答「这台机器能不能跑」。

覆盖实际踩过的坑：驱动版本不匹配、缺 key、缺 allure、目录不可写、.env 没被忽略。
"""

from __future__ import annotations

import importlib
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from aiui.config import Settings

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    hint: str = ""

    def line(self) -> str:
        icon = {OK: "[OK]  ", WARN: "[WARN]", FAIL: "[FAIL]"}.get(self.status, "[?]   ")
        text = f"{icon} {self.name:<14} {self.detail}"
        if self.hint and self.status != OK:
            text += f"\n          -> {self.hint}"
        return text


def check_python() -> Check:
    v = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        return Check("python", OK, v)
    return Check("python", FAIL, v, "需要 Python 3.10+")


def check_deps() -> Check:
    versions: list[str] = []
    missing: list[str] = []
    for mod, pkg in (("pydantic", "pydantic"), ("pydantic_settings", "pydantic-settings"),
                     ("selenium", "selenium"), ("openai", "openai"),
                     ("yaml", "PyYAML"), ("pytest", "pytest")):
        try:
            m = importlib.import_module(mod)
            versions.append(f"{pkg}={getattr(m, '__version__', '?')}")
        except Exception:  # noqa: BLE001
            missing.append(pkg)
    if missing:
        return Check("dependencies", FAIL, f"缺少 {missing}", 'pip install -e ".[dev]"')
    return Check("dependencies", OK, " ".join(versions))


def check_allure() -> Check:
    try:
        import allure  # noqa: F401
    except Exception:  # noqa: BLE001
        return Check("allure-pytest", WARN, "未安装（报告降级为纯日志）", "pip install allure-pytest")
    exe = shutil.which("allure")
    if exe:
        return Check("allure-cli", OK, exe)
    return Check("allure-cli", WARN, "未找到 allure 命令", "npm i -g allure-commandline")


def check_env_file(settings: Settings) -> Check:
    env = Path(".env")
    if not env.exists():
        return Check(".env", WARN, "不存在", "copy .env.example .env 并填入 key")
    ignored = Path(".gitignore")
    ok_ignored = ignored.exists() and ".env" in ignored.read_text(encoding="utf-8", errors="ignore")
    if not ok_ignored:
        return Check(".env", FAIL, "存在但未被 .gitignore 忽略", "在 .gitignore 中加入 .env")
    return Check(".env", OK, "存在且已被忽略")


def check_api_key(settings: Settings) -> Check:
    if settings.llm_mode == "fake":
        return Check("llm", WARN, "当前为 fake 模式", "需要真实规划时设 AIUI_LLM_MODE=deepseek")
    if settings.deepseek_api_key:
        masked = settings.deepseek_api_key[:6] + "..." + settings.deepseek_api_key[-4:]
        return Check("llm", OK, f"{settings.model} key={masked}")
    return Check("llm", FAIL, "未配置 AIUI_DEEPSEEK_API_KEY", "在 .env 中填写 key，或改用 --fake")


def check_paths(settings: Settings) -> Check:
    try:
        settings.ensure_dirs()
        probe = Path(tempfile.gettempdir()) / "aiui-write-probe"
        settings.plans_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Check("paths", OK, f"artifacts={settings.artifacts_dir} plans={settings.plans_dir}")
    except Exception as exc:  # noqa: BLE001
        return Check("paths", FAIL, str(exc), "检查目录权限")


def check_browser(settings: Settings) -> Check:
    from aiui.executor.browser import build_driver, find_local_driver

    driver_path = find_local_driver(settings)
    try:
        driver = build_driver(settings)
    except Exception as exc:  # noqa: BLE001
        return Check("browser", FAIL, str(exc).splitlines()[0][:120],
                     "把匹配版本的 chromedriver 放到 .drivers/ 或设 AIUI_CHROMEDRIVER_PATH")
    try:
        caps = driver.capabilities
        ver = caps.get("browserVersion", "?")
        name = caps.get("browserName", settings.browser)
        src = f"driver={Path(driver_path).parent.name}" if driver_path else "driver=selenium-manager"
        return Check("browser", OK, f"{name} {ver} （{src}）")
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass


def check_cache(settings: Settings) -> Check:
    try:
        from aiui.locator.cache import LocatorCache

        cache = LocatorCache(settings.cache_db, settings.cache_enabled)
        stats = cache.stats()
        cache.close()
        if not stats.get("enabled"):
            return Check("locator-cache", WARN, "已禁用", "AIUI_CACHE_ENABLED=true 可开启")
        return Check("locator-cache", OK, f"{stats['rows']} 条记录，复用 {stats['total_reuse']} 次")
    except Exception as exc:  # noqa: BLE001
        return Check("locator-cache", FAIL, str(exc), "检查 .aiui 目录权限")


def run_all(settings: Settings, browser: bool = True) -> list[Check]:
    checks: list[Callable[[], Check]] = [
        check_python,
        check_deps,
        check_allure,
        lambda: check_env_file(settings),
        lambda: check_api_key(settings),
        lambda: check_paths(settings),
        lambda: check_cache(settings),
    ]
    if browser:
        checks.append(lambda: check_browser(settings))
    return [c() for c in checks]


def summarize(checks: list[Check]) -> tuple[int, int, int]:
    return (
        sum(c.status == OK for c in checks),
        sum(c.status == WARN for c in checks),
        sum(c.status == FAIL for c in checks),
    )
