"""日志：统一 UTF-8，避免 Windows 控制台 GBK 下的中文乱码。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_DATEFMT = "%H:%M:%S"


def setup_logging(verbose: bool = False, log_file: Path | None = None) -> None:
    root = logging.getLogger()
    if getattr(root, "_aiui_configured", False):
        return
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - 非标准流
            pass

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(console)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FMT, _DATEFMT))
        root.addHandler(fh)

    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    root._aiui_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
