"""浏览器工厂。

驱动解析顺序：
1. 显式配置 AIUI_CHROMEDRIVER_PATH；
2. 仓库内 `.drivers/**/chromedriver.exe`（离线/内网环境用，已随项目放好）；
3. Selenium Manager 自动下载（需要外网，失败时给出明确提示）。
"""

from __future__ import annotations

from pathlib import Path

from aiui.config import Settings
from aiui.logging import get_logger

log = get_logger(__name__)


def find_local_driver(settings: Settings) -> str | None:
    if settings.chromedriver_path:
        p = Path(settings.chromedriver_path)
        return str(p) if p.exists() else None
    if settings.browser == "chrome":
        matches = sorted(Path(".drivers").rglob("chromedriver.exe"))
        if matches:
            return str(matches[-1])
    return None


def build_driver(settings: Settings):
    from selenium import webdriver

    is_edge = settings.browser == "edge"
    options = webdriver.EdgeOptions() if is_edge else webdriver.ChromeOptions()

    if settings.headless:
        options.add_argument("--headless=new")
    options.add_argument(f"--window-size={settings.window[0]},{settings.window[1]}")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver_path = find_local_driver(settings)
    try:
        if driver_path:
            from selenium.webdriver.chrome.service import Service as ChromeService
            from selenium.webdriver.edge.service import Service as EdgeService

            service = EdgeService(executable_path=driver_path) if is_edge \
                else ChromeService(executable_path=driver_path)
            driver = (webdriver.Edge if is_edge else webdriver.Chrome)(
                options=options, service=service
            )
            log.info("使用本地驱动：%s", driver_path)
        else:
            driver = (webdriver.Edge if is_edge else webdriver.Chrome)(options=options)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "浏览器启动失败。常见原因：浏览器版本与驱动不匹配且无法下载。\n"
            f"原始错误：{exc}\n"
            "解决：把对应版本的 chromedriver.exe 放到 .drivers/chromedriver/<版本>/ 下，"
            "或设置 AIUI_CHROMEDRIVER_PATH。"
        ) from exc

    driver.set_page_load_timeout(settings.page_load_timeout)
    driver.implicitly_wait(0)
    log.info("浏览器已启动：%s headless=%s", settings.browser, settings.headless)
    return driver
