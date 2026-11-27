from __future__ import annotations

from pathlib import Path

import pytest

from aiui import doctor
from aiui.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_mode="fake",
        artifacts_dir=tmp_path / "artifacts",
        plans_dir=tmp_path / "plans",
        cache_db=tmp_path / "cache.db",
        llm_cache_dir=tmp_path / "llm_cache",
    )


def test_python_ok():
    c = doctor.check_python()
    assert c.status == doctor.OK
    assert c.detail.startswith("3.")


def test_deps_ok():
    c = doctor.check_deps()
    assert c.status == doctor.OK, c.detail
    assert "pydantic=" in c.detail


def test_paths_and_cache_ok(tmp_path):
    s = _settings(tmp_path)
    assert doctor.check_paths(s).status == doctor.OK
    c = doctor.check_cache(s)
    assert c.status in {doctor.OK, doctor.WARN}


def test_env_file_ignored():
    c = doctor.check_env_file(_settings(Path(".")))
    assert c.status in {doctor.OK, doctor.WARN}


def test_api_key_reports_fake_mode():
    c = doctor.check_api_key(_settings(Path(".")))
    assert c.status == doctor.WARN and "fake" in c.detail


def test_summarize_counts():
    checks = [doctor.Check("a", doctor.OK), doctor.Check("b", doctor.WARN),
              doctor.Check("c", doctor.FAIL)]
    assert doctor.summarize(checks) == (1, 1, 1)
