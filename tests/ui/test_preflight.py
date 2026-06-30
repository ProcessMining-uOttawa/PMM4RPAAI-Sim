"""Tests for ui/preflight.py — the pure _venv_check Check builder."""

from __future__ import annotations

from pathlib import Path

from ui.preflight import _venv_check


class TestVenvCheck:
    def test_missing_exe_is_not_ok(self):
        check = _venv_check(Path("nope/x/simod.exe"), "simod", "py -3.9")
        assert check.name == "Simod venv"
        assert check.ok is False
        assert "missing" in check.detail

    def test_fix_string_uses_package_and_cmd(self):
        check = _venv_check(Path("nope/x/prosimos.exe"), "prosimos", "py -3.9")
        assert check.name == "Prosimos venv"
        assert "py -3.9 -m venv tools\\prosimos-venv" in check.fix
        assert "pip install prosimos" in check.fix

    def test_existing_exe_is_ok(self, tmp_path):
        exe = tmp_path / "simod.exe"
        exe.write_text("")  # create the file so .exists() is True
        check = _venv_check(exe, "simod", "py -3.9")
        assert check.ok is True
        assert check.detail == f"simod.exe at {exe}"
