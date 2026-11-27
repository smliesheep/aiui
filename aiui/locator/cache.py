"""Tier1 定位缓存：把「上次验证过、且现在仍然对得上」的定位器复用起来。

三个关键点：
1. 键里用路由模板（/accounts/{id}），不用真实 URL，否则命中率接近 0；
2. 复用前必须 revalidate —— 页面改版后老定位器可能指向别的元素；
3. 连续失效 3 次自动 retired，强制重新发现。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from aiui.locator.collector import find_elements
from aiui.locator.rules import norm
from aiui.logging import get_logger
from aiui.planning.models import TargetSpec

log = get_logger(__name__)


@dataclass
class CacheHit:
    key: str
    page_key: str
    locator: str
    tier: str
    confidence: float
    expect_text: str
    hit_count: int
    fail_streak: int


class LocatorCache:
    def __init__(self, db_path: Path, enabled: bool = True) -> None:
        self.enabled = enabled
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection | None = None
        if not enabled:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        assert self.conn
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS locator (
                key TEXT PRIMARY KEY,
                page_key TEXT NOT NULL,
                target_sig TEXT NOT NULL,
                locator TEXT NOT NULL,
                tier TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                expect_text TEXT DEFAULT '',
                hit_count INTEGER NOT NULL DEFAULT 0,
                fail_streak INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT,
                last_verified_at TEXT
            )
            """
        )
        self.conn.commit()

    # ---------------------------------------------------------------- keys
    @staticmethod
    def target_sig(target: TargetSpec) -> str:
        raw = json.dumps(
            {"d": norm(target.description), "h": target.hints.model_dump(mode="json")},
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def key_of(cls, page_key: str, target: TargetSpec) -> str:
        return hashlib.sha256(f"{page_key}|{cls.target_sig(target)}".encode()).hexdigest()[:32]

    # ---------------------------------------------------------------- ops
    def get(self, page_key: str, target: TargetSpec) -> CacheHit | None:
        if not self.conn:
            return None
        key = self.key_of(page_key, target)
        row = self.conn.execute(
            "SELECT * FROM locator WHERE key=? AND status='active'", (key,)
        ).fetchone()
        if not row:
            return None
        return CacheHit(
            key=row["key"], page_key=row["page_key"], locator=row["locator"],
            tier=row["tier"], confidence=row["confidence"], expect_text=row["expect_text"],
            hit_count=row["hit_count"], fail_streak=row["fail_streak"],
        )

    def revalidate(self, driver, hit: CacheHit) -> bool:
        els = find_elements(driver, hit.locator)
        if len(els) != 1:
            return False
        el = els[0]
        try:
            if not el.is_displayed():
                return False
        except Exception:  # noqa: BLE001
            return False
        if hit.expect_text:
            try:
                actual = norm(el.text or el.get_attribute("value") or "")
            except Exception:  # noqa: BLE001
                return False
            if norm(hit.expect_text) not in actual and actual not in norm(hit.expect_text):
                return False
        return True

    def save(self, page_key: str, target: TargetSpec, locator: str, tier: str,
             confidence: float, expect_text: str = "") -> None:
        if not self.conn:
            return
        key = self.key_of(page_key, target)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.conn.execute(
            """
            INSERT INTO locator(key,page_key,target_sig,locator,tier,confidence,expect_text,
                                hit_count,fail_streak,status,created_at,last_verified_at)
            VALUES(?,?,?,?,?,?,?,0,0,'active',?,?)
            ON CONFLICT(key) DO UPDATE SET
                locator=excluded.locator, tier=excluded.tier,
                confidence=excluded.confidence, expect_text=excluded.expect_text,
                fail_streak=0, status='active', last_verified_at=excluded.last_verified_at
            """,
            (key, page_key, self.target_sig(target), locator, tier, confidence,
             expect_text, now, now),
        )
        self.conn.commit()

    def confirm(self, hit: CacheHit) -> None:
        if not self.conn:
            return
        self.conn.execute(
            "UPDATE locator SET hit_count=hit_count+1, fail_streak=0, "
            "last_verified_at=? WHERE key=?",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), hit.key),
        )
        self.conn.commit()

    def on_fail(self, hit: CacheHit) -> bool:
        """返回是否因此被淘汰。"""
        if not self.conn:
            return False
        self.conn.execute(
            "UPDATE locator SET fail_streak=fail_streak+1 WHERE key=?", (hit.key,)
        )
        row = self.conn.execute(
            "SELECT fail_streak FROM locator WHERE key=?", (hit.key,)
        ).fetchone()
        retired = bool(row and row["fail_streak"] >= 3)
        if retired:
            self.conn.execute("UPDATE locator SET status='retired' WHERE key=?", (hit.key,))
            log.warning("定位器连续失效 3 次，已淘汰：%s", hit.locator)
        self.conn.commit()
        return retired

    def stats(self) -> dict:
        if not self.conn:
            return {"enabled": False}
        total = self.conn.execute("SELECT COUNT(*) c FROM locator").fetchone()["c"]
        retired = self.conn.execute(
            "SELECT COUNT(*) c FROM locator WHERE status='retired'"
        ).fetchone()["c"]
        hits = self.conn.execute("SELECT COALESCE(SUM(hit_count),0) s FROM locator").fetchone()["s"]
        return {"enabled": True, "rows": total, "retired": retired, "total_reuse": hits,
                "db": str(self.db_path)}

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None
