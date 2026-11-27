"""Allure 集成（可选依赖）：没装 allure-pytest 时自动降级为空操作。

所有报告相关的操作都从这里走，保证 evidence / runner 不直接依赖 allure。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:  # pragma: no cover - 取决于环境
    import allure  # type: ignore

    HAS_ALLURE = True
except Exception:  # noqa: BLE001
    allure = None  # type: ignore
    HAS_ALLURE = False


_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".json": "application/json", ".html": "text/html", ".md": "text/markdown",
    ".txt": "text/plain",
}


@contextmanager
def span(title: str):
    if HAS_ALLURE:
        with allure.step(title):  # type: ignore[union-attr]
            yield
    else:
        yield


def attach_file(path: Path, name: str | None = None) -> None:
    if not HAS_ALLURE or not Path(path).exists():
        return
    p = Path(path)
    mime = _MIME.get(p.suffix.lower(), "text/plain")
    type_map = {
        "image/png": allure.attachment_type.PNG,  # type: ignore[union-attr]
        "image/jpeg": allure.attachment_type.JPG,  # type: ignore[union-attr]
        "application/json": allure.attachment_type.JSON,  # type: ignore[union-attr]
        "text/html": allure.attachment_type.HTML,  # type: ignore[union-attr]
        "text/plain": allure.attachment_type.TEXT,  # type: ignore[union-attr]
    }
    allure.attach.file(  # type: ignore[union-attr]
        str(p), name=name or p.name, attachment_type=type_map.get(mime, allure.attachment_type.TEXT)  # type: ignore[union-attr]
    )


def attach_text(body: str, name: str) -> None:
    if HAS_ALLURE:
        allure.attach(body, name=name, attachment_type=allure.attachment_type.TEXT)  # type: ignore[union-attr]


def attach_json(data: Any, name: str) -> None:
    if HAS_ALLURE:
        allure.attach(
            json.dumps(data, ensure_ascii=False, indent=2),
            name=name,
            attachment_type=allure.attachment_type.JSON,  # type: ignore[union-attr]
        )


def set_title(title: str) -> None:
    if HAS_ALLURE:
        allure.dynamic.title(title)  # type: ignore[union-attr]


def set_description(text: str) -> None:
    if HAS_ALLURE:
        allure.dynamic.description(text)  # type: ignore[union-attr]


def tag(*names: str) -> None:
    if HAS_ALLURE:
        for n in names:
            allure.dynamic.tag(n)  # type: ignore[union-attr]


def set_environment(data: dict[str, Any]) -> None:
    if not HAS_ALLURE:
        return
    try:
        allure.environment(**{k: str(v) for k, v in data.items()})  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - 版本差异，降级忽略
        pass
