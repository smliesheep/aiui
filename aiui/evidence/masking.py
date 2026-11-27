"""证据脱敏：密码、卡号、手机号、身份证一律不进报告。"""

from __future__ import annotations

import re

CARD_RE = re.compile(r"\b(?:\d[ -]?){15,19}\b")
PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")
ID_RE = re.compile(r"\b\d{17}[\dXx]\b")

SENSITIVE_ATTR_RE = re.compile(
    r'(type=["\']password["\']|name=["\'][^"\']*(?:password|passwd|pwd|cvv|otp|token)[^"\']*["\'])',
    re.IGNORECASE,
)


def mask_text(text: str | None) -> str:
    if not text:
        return ""
    s = CARD_RE.sub("****", text)
    s = PHONE_RE.sub("1**********", s)
    s = ID_RE.sub("******************", s)
    return s


def mask_html(html: str | None) -> str:
    if not html:
        return ""
    s = mask_text(html)
    s = re.sub(
        r'(<input[^>]*type=["\']password["\'][^>]*value=["\'])[^"\']*(["\'])',
        r"\1***\2", s, flags=re.IGNORECASE,
    )
    return s
