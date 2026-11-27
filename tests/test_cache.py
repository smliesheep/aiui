from __future__ import annotations

from pathlib import Path

from aiui.locator.cache import LocatorCache
from aiui.planning.models import TargetHints, TargetSpec


class FakeEl:
    def __init__(self, text="Login"):
        self.text = text

    def is_displayed(self) -> bool:
        return True

    def get_attribute(self, name):
        return ""


class FakeDriver:
    def __init__(self, els):
        self.els = els

    def find_elements(self, by, locator):
        return self.els


TARGET = TargetSpec(description="登录按钮", hints=TargetHints(text="Login"))


def test_save_and_get(tmp_path: Path):
    cache = LocatorCache(tmp_path / "c.db")
    cache.save("page1", TARGET, '[id="login"]', "rule", 0.9, "Login")
    hit = cache.get("page1", TARGET)
    assert hit is not None and hit.locator == '[id="login"]'
    assert cache.get("page2", TARGET) is None
    cache.close()


def test_revalidate_ok_and_fail(tmp_path: Path):
    cache = LocatorCache(tmp_path / "c.db")
    cache.save("p", TARGET, '[id="login"]', "rule", 0.9, "Login")
    hit = cache.get("p", TARGET)
    assert cache.revalidate(FakeDriver([FakeEl("Login")]), hit) is True
    assert cache.revalidate(FakeDriver([]), hit) is False
    assert cache.revalidate(FakeDriver([FakeEl("Sign up")]), hit) is False
    cache.close()


def test_retire_after_three_failures(tmp_path: Path):
    cache = LocatorCache(tmp_path / "c.db")
    cache.save("p", TARGET, '[id="login"]', "rule", 0.9, "Login")
    hit = cache.get("p", TARGET)
    assert cache.on_fail(hit) is False
    assert cache.on_fail(hit) is False
    assert cache.on_fail(hit) is True
    assert cache.get("p", TARGET) is None  # retired
    assert cache.stats()["retired"] == 1
    cache.close()


def test_confirm_resets_streak(tmp_path: Path):
    cache = LocatorCache(tmp_path / "c.db")
    cache.save("p", TARGET, '[id="login"]', "rule", 0.9, "Login")
    hit = cache.get("p", TARGET)
    cache.on_fail(hit)
    cache.confirm(hit)
    hit2 = cache.get("p", TARGET)
    assert hit2.fail_streak == 0 and hit2.hit_count == 1
    cache.close()


def test_disabled_cache_is_noop(tmp_path: Path):
    cache = LocatorCache(tmp_path / "c.db", enabled=False)
    cache.save("p", TARGET, "x", "rule", 1.0)
    assert cache.get("p", TARGET) is None
    assert cache.stats() == {"enabled": False}
