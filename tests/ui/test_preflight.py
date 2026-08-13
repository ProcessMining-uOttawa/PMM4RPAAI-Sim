"""Tests for ui/services/preflight.py — the Check builder and the OS-detection pipeline.

The detection helpers are unit-tested by monkeypatching only their OS
collaborators (shutil.which, subprocess.run, the root-path constants, and
JAVA_HOME) so the parsing/selection logic under test runs for real.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from ui.services import preflight
from ui.services.preflight import (
    Check,
    _detect_corretto8,
    _detect_macos_jdk8,
    _java_exe_from_home,
    _java_major,
    _venv_check,
    all_ok,
)


class TestVenvCheck:
    def test_missing_exe_is_not_ok(self):
        check = _venv_check(Path("nope/x/simod.exe"), "simod", "py -3.9")
        assert check.name == "Simod venv"
        assert check.ok is False
        assert "missing" in check.detail

    def test_fix_string_uses_package_and_cmd(self):
        # The venv dir and pip path in the fix message are derived from the exe
        # argument (exe.parent.parent, and pip beside the exe with its suffix).
        check = _venv_check(
            Path("tools/prosimos-venv/bin/prosimos"), "prosimos", "py -3.9"
        )
        assert check.name == "Prosimos venv"
        assert f"py -3.9 -m venv {Path('tools', 'prosimos-venv')}" in check.fix
        assert f"{Path('tools/prosimos-venv/bin/pip')} install prosimos" in check.fix

    def test_existing_exe_is_ok(self, tmp_path):
        exe = tmp_path / "simod.exe"
        exe.write_text("")  # create the file so .exists() is True
        check = _venv_check(exe, "simod", "py -3.9")
        assert check.ok is True
        assert check.detail == f"simod.exe at {exe}"


# ── _java_major ────────────────────────────────────────────────────────────────


class TestJavaMajor:
    @pytest.mark.parametrize(
        "version_line, expected",
        [
            ('java version "1.8.0_412"', 8),  # legacy "1.N" → minor
            ('openjdk version "24.0.2"', 24),
            ('openjdk version "11.0.2"', 11),
            ("something with no version token", None),  # regex miss → None
        ],
    )
    def test_parses_major_from_version_output(
        self, monkeypatch, version_line, expected
    ):
        # java writes -version to stderr; _java_major reads stderr + stdout.
        monkeypatch.setattr(preflight.shutil, "which", lambda exe: "/path/to/java")
        monkeypatch.setattr(
            preflight.subprocess,
            "run",
            lambda *a, **k: types.SimpleNamespace(stderr=version_line, stdout=""),
        )
        assert _java_major("java") == expected

    def test_returns_none_when_java_not_on_path(self, monkeypatch):
        monkeypatch.setattr(preflight.shutil, "which", lambda exe: None)
        # subprocess.run must not be reached when which() reports absence.
        monkeypatch.setattr(
            preflight.subprocess,
            "run",
            lambda *a, **k: pytest.fail("subprocess.run called despite which()==None"),
        )
        assert _java_major("java") is None


# ── _detect_corretto8 ──────────────────────────────────────────────────────────


class TestDetectCorretto8:
    def test_finds_jdk18_with_java_exe(self, monkeypatch, tmp_path):
        jdk = tmp_path / "jdk1.8.0_412"
        (jdk / "bin").mkdir(parents=True)
        (jdk / "bin" / "java.exe").write_text("")
        monkeypatch.setattr(preflight, "CORRETTO_ROOTS", [tmp_path])
        assert _detect_corretto8() == str(jdk)

    def test_none_when_root_absent(self, monkeypatch, tmp_path):
        # A root that does not exist — exercises the `is_dir()` False branch,
        # distinct from an existing-but-empty root.
        monkeypatch.setattr(preflight, "CORRETTO_ROOTS", [tmp_path / "nope"])
        assert _detect_corretto8() is None

    def test_none_when_jdk_lacks_java_exe(self, monkeypatch, tmp_path):
        jdk = tmp_path / "jdk1.8.0_412"
        (jdk / "bin").mkdir(parents=True)  # no java.exe inside
        monkeypatch.setattr(preflight, "CORRETTO_ROOTS", [tmp_path])
        assert _detect_corretto8() is None


# ── _detect_macos_jdk8 ─────────────────────────────────────────────────────────


class TestDetectMacosJdk8:
    def _make_jvm(self, tmp_path, dir_name):
        home = tmp_path / dir_name / "Contents" / "Home"
        (home / "bin").mkdir(parents=True)
        (home / "bin" / "java").write_text("")
        return home

    def test_finds_jdk8_home(self, monkeypatch, tmp_path):
        home = self._make_jvm(tmp_path, "temurin-8.jdk")
        monkeypatch.setattr(preflight, "MACOS_JVM_ROOTS", [tmp_path])
        monkeypatch.setattr(preflight, "_java_major", lambda java: 8)
        assert _detect_macos_jdk8() == str(home)

    def test_ignores_non_jdk8_by_version(self, monkeypatch, tmp_path):
        self._make_jvm(tmp_path, "temurin-17.jdk")
        monkeypatch.setattr(preflight, "MACOS_JVM_ROOTS", [tmp_path])
        monkeypatch.setattr(preflight, "_java_major", lambda java: 17)
        assert _detect_macos_jdk8() is None

    def test_none_when_root_absent(self, monkeypatch, tmp_path):
        # A root that does not exist — exercises the `not is_dir()` continue branch.
        monkeypatch.setattr(preflight, "MACOS_JVM_ROOTS", [tmp_path / "nope"])
        assert _detect_macos_jdk8() is None


# ── _java_exe_from_home ────────────────────────────────────────────────────────


class TestJavaExeFromHome:
    def test_bare_java_when_no_java_home(self, monkeypatch):
        monkeypatch.delenv("JAVA_HOME", raising=False)
        assert _java_exe_from_home() == "java"

    @pytest.mark.parametrize("is_windows", [True, False])
    def test_resolves_binary_under_java_home(self, monkeypatch, tmp_path, is_windows):
        # Cover both platform branches on any host: java.exe on Windows, java on
        # POSIX. _java_exe_from_home reads module-level _WINDOWS at call time.
        monkeypatch.setattr(preflight, "_WINDOWS", is_windows)
        exe_name = "java.exe" if is_windows else "java"
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / exe_name).write_text("")
        monkeypatch.setenv("JAVA_HOME", str(tmp_path))
        assert _java_exe_from_home() == (tmp_path / "bin" / exe_name).as_posix()

    def test_falls_back_when_java_home_has_no_binary(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JAVA_HOME", str(tmp_path))  # no bin/java under it
        assert _java_exe_from_home() == "java"


# ── all_ok ─────────────────────────────────────────────────────────────────────


class TestAllOk:
    def test_true_when_every_check_passes(self):
        assert all_ok([Check("a", True, ""), Check("b", True, "")]) is True

    def test_false_when_any_check_fails(self):
        assert all_ok([Check("a", True, ""), Check("b", False, "")]) is False
