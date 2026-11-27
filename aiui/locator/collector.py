"""页面元素采集：程序负责「看见」，模型只负责「挑一个」。

一次采集同时服务规则匹配和 AI 兜底，避免重复 DOM 分析。
采集时给元素打 `data-aiui-id` 临时标记，后续用稳定 CSS 取回元素。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from aiui.logging import get_logger

log = get_logger(__name__)

SELECTOR = (
    "a,button,input,select,textarea,[role=button],[role=link],[role=checkbox],"
    "[role=tab],[onclick],label,img[title],img[alt]"
)

# 文本类元素：extract / assert_text 的目标往往不是可交互元素（余额、提示、单元格）
TEXT_SELECTOR = "span,td,th,strong,em,p,h1,h2,h3,h4,li,dt,dd"

JS_COLLECT = r"""
const limit = arguments[0] || 200;
const interactive = Array.from(document.querySelectorAll(arguments[1]));
const texty = Array.from(document.querySelectorAll(arguments[2])).filter(function(el){
  if (el.children && el.children.length > 0) return false;   // 只收叶子节点
  const t = (el.innerText || '').trim();
  return t.length > 0 && t.length <= 60;
}).slice(0, 90);
const msg = Array.from(document.querySelectorAll('div[id],div[class]')).filter(function(el){
  if (el.children && el.children.length > 0) return false;
  const sig = ((el.id || '') + ' ' + (el.className || '')).toLowerCase();
  return /toast|alert|message|notice|notification|error|success|hint|tip/.test(sig);
}).slice(0, 10);
const seen = new Set();
const nodes = interactive.concat(texty, msg).filter(function(el){
  if (seen.has(el)) return false;
  seen.add(el);
  return true;
});
function visible(el){
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 1 && r.height > 1 && s.visibility !== 'hidden'
         && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.01;
}
function labelOf(el){
  try {
    if (el.labels && el.labels.length) return (el.labels[0].innerText || '').trim();
  } catch (e) {}
  const l = el.closest('label');
  if (l) return (l.innerText || '').trim();
  if (el.id) {
    const q = document.querySelector('label[for="' + el.id.replace(/"/g, '') + '"]');
    if (q) return (q.innerText || '').trim();
  }
  return '';
}
function ancestorText(el){
  const out = []; let n = el.parentElement; let d = 0;
  while (n && d < 4) {
    const t = (n.innerText || '').trim();
    if (t) out.push(t.slice(0, 60));
    n = n.parentElement; d++;
  }
  return out.join(' | ').slice(0, 160);
}
const out = [];
let i = 0;
for (const el of nodes) {
  if (i >= limit) break;
  const tag = el.tagName.toLowerCase();
  if (tag === 'label' && el.control) continue;
  let r;
  try { r = el.getBoundingClientRect(); } catch (e) { continue; }
  el.setAttribute('data-aiui-id', String(i));
  out.push({
    i: i,
    tag: tag,
    role: el.getAttribute('role') || '',
    text: ((el.innerText || el.value || el.getAttribute('aria-label')
            || el.getAttribute('title') || el.getAttribute('alt') || '') + '').trim().slice(0, 60),
    attrs: {
      name: el.getAttribute('name') || '',
      id: el.id || '',
      ph: el.getAttribute('placeholder') || '',
      aria: el.getAttribute('aria-label') || '',
      testid: (el.dataset && (el.dataset.testid || el.dataset.testId)) || '',
      type: el.getAttribute('type') || '',
      cls: ((el.className && el.className.toString()) || '').slice(0, 40),
      label: labelOf(el),
      anc: ancestorText(el)
    },
    box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    visible: visible(el),
    enabled: !el.disabled
  });
  i++;
}
return out;
"""

JS_PAGE_KEY = r"""
const h = document.querySelector('h1,h2,[role=heading]');
const f = document.querySelector('form');
return [((h && h.innerText) || '').trim().slice(0, 40),
        (f && (f.getAttribute('name') || f.id || '')) || ''].join('|');
"""

JS_CLEAR = r"""
document.querySelectorAll('[data-aiui-id]').forEach(function(el){
  el.removeAttribute('data-aiui-id');
});
"""


@dataclass
class Candidate:
    i: int
    tag: str
    role: str
    text: str
    attrs: dict[str, str] = field(default_factory=dict)
    box: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    visible: bool = True
    enabled: bool = True

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Candidate":
        return cls(
            i=int(raw.get("i", -1)),
            tag=str(raw.get("tag", "")),
            role=str(raw.get("role", "")),
            text=str(raw.get("text", "")),
            attrs={k: str(v or "") for k, v in (raw.get("attrs") or {}).items()},
            box=list(raw.get("box") or [0, 0, 0, 0]),
            visible=bool(raw.get("visible", True)),
            enabled=bool(raw.get("enabled", True)),
        )

    @property
    def locator(self) -> str:
        return css_for(self.i)

    def compact(self) -> dict[str, Any]:
        """给模型看的紧凑描述：字段越少，token 越省，幻觉空间越小。"""
        return {
            "i": self.i,
            "tag": self.tag,
            "text": self.text,
            "attrs": {
                k: v
                for k, v in self.attrs.items()
                if k in {"name", "id", "ph", "aria", "testid", "type", "label"} and v
            },
            "visible": self.visible,
            "enabled": self.enabled,
        }


def css_for(index: int) -> str:
    return f'[data-aiui-id="{index}"]'


def collect(driver, limit: int = 200) -> list[Candidate]:
    try:
        raw = driver.execute_script(JS_COLLECT, limit, SELECTOR, TEXT_SELECTOR)
    except Exception as exc:  # noqa: BLE001
        log.warning("元素采集失败：%s", exc)
        return []
    return [Candidate.from_raw(item) for item in (raw or [])]


def clear_markers(driver) -> None:
    try:
        driver.execute_script(JS_CLEAR)
    except Exception:  # noqa: BLE001
        pass


def _xpath_literal(text: str) -> str:
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"
    parts = text.split('"')
    return "concat(" + ", '\"', ".join(f'"{p}"' for p in parts) + ")"


def _attr_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def durable_locator(c: Candidate) -> str:
    """生成「页面刷新后依然有效」的定位器，缓存里存的必须是它，而不是临时标记。"""
    a = c.attrs
    if a.get("testid"):
        return f'[data-testid="{_attr_escape(a["testid"])}"]'
    if a.get("id"):
        return f'[id="{_attr_escape(a["id"])}"]'
    if a.get("name"):
        return f'{c.tag}[name="{_attr_escape(a["name"])}"]'
    text = (c.text or "").strip()
    if text and c.tag not in {"input", "textarea", "select"}:
        return f"//{c.tag}[normalize-space(.)={_xpath_literal(text)}]"
    if a.get("label") and c.tag in {"input", "textarea", "select"}:
        return f"//label[normalize-space(.)={_xpath_literal(a['label'])}]//{c.tag}"
    return c.locator  # 兜底：仅本次会话有效


def find_elements(driver, locator: str) -> list:
    from selenium.webdriver.common.by import By

    by = By.XPATH if locator.startswith("//") or locator.startswith("(") else By.CSS_SELECTOR
    try:
        return driver.find_elements(by, locator)
    except Exception:  # noqa: BLE001
        return []


def locate_element(driver, locator: str, marker: str | None = None):
    """优先用持久定位器；唯一性不成立时退回本次会话的标记。"""
    els = find_elements(driver, locator)
    if len(els) == 1:
        return els[0]
    if len(els) > 1:
        visible = [e for e in els if _safe(lambda: e.is_displayed())]
        if len(visible) == 1:
            return visible[0]
    if marker:
        m = find_elements(driver, marker)
        if len(m) == 1:
            return m[0]
    return els[0] if els else None


def _safe(fn, default=False):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def route_template(url: str) -> str:
    """把 /accounts/123 归一成 /accounts/{id}，否则缓存命中率接近 0。"""
    path = re.sub(r"https?://[^/]+", "", url or "")
    path = path.split("?")[0].split("#")[0]
    path = re.sub(r"/\d+(?=/|$)", "/{id}", path)
    path = re.sub(r"/[0-9a-f]{8}-[0-9a-f-]{20,}(?=/|$)", "/{uuid}", path)
    return path or "/"


def page_key(driver) -> str:
    try:
        url = driver.current_url
    except Exception:  # noqa: BLE001
        url = ""
    try:
        landmarks = driver.execute_script(JS_PAGE_KEY) or ""
    except Exception:  # noqa: BLE001
        landmarks = ""
    raw = f"{route_template(url)}|{landmarks}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
