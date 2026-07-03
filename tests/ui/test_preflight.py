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
