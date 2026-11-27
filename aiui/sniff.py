"""页面地图：给模型「看一眼真实页面」，让生成的 hints 有依据。

只采集结构（表单/输入框/按钮/标题），不采集任何用户数据。
"""

from __future__ import annotations

from typing import Any

from aiui.config import Settings
from aiui.executor.browser import build_driver
from aiui.logging import get_logger

log = get_logger(__name__)

JS_MAP = r"""
function txt(el){ return (el.innerText || el.value || '').trim().slice(0, 40); }
const forms = Array.from(document.querySelectorAll('form')).slice(0, 5).map(function(f){
  return {
    name: f.getAttribute('name') || f.id || '',
    action: f.getAttribute('action') || '',
    inputs: Array.from(f.querySelectorAll('input,select,textarea')).slice(0, 12).map(function(i){
      return {tag: i.tagName.toLowerCase(), type: i.type || '', name: i.name || '', id: i.id || '',
              label: (i.labels && i.labels[0] ? txt(i.labels[0]) : (i.placeholder || '')).slice(0, 40)};
    }),
    buttons: Array.from(f.querySelectorAll('button,[type=submit]')).slice(0, 6).map(txt)
  };
});
const buttons = Array.from(document.querySelectorAll('button,a,[role=button]'))
  .filter(function(b){ const r=b.getBoundingClientRect(); return r.width>1 && r.height>1; })
  .slice(0, 20).map(txt).filter(Boolean);
const headings = Array.from(document.querySelectorAll('h1,h2,h3')).slice(0, 8).map(txt).filter(Boolean);
return {title: document.title, headings: headings, forms: forms, buttons: buttons,
        has_table: !!document.querySelector('table'), has_modal: !!document.querySelector('[role=dialog],.modal')};
"""


def build_page_map(url: str, settings: Settings) -> dict[str, Any]:
    driver = None
    try:
        driver = build_driver(settings)
        driver.get(url)
        data = driver.execute_script(JS_MAP) or {}
        data["url"] = url
        log.info("页面地图采集完成：%d 个表单 / %d 个按钮",
                 len(data.get("forms", [])), len(data.get("buttons", [])))
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("页面地图采集失败（继续无障碍生成）：%s", exc)
        return {"url": url, "error": str(exc)}
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass
