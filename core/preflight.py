"""Detect Simod's runtime prerequisites and report them to the UI."""
from __future__ import annotations
import os, re, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path

from .runner import SIMOD_EXE, PROSIMOS_EXE


SIMOD_VENV_PY = Path("tools/simod-venv/Scripts/python.exe")

CORRETTO_ROOTS = [
    Path(r"C:\Program Files\Amazon Corretto"),
    Path(r"C:\Program Files (x86)\Amazon Corretto"),
]


def detect_corretto8() -> str | None:
    """Return JAVA_HOME for an installed Corretto 8, or None."""
    for root in CORRETTO_ROOTS:
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if d.is_dir() and d.name.startswith("jdk1.8") and (d/"bin"/"java.exe").exists():
                    return str(d)
    return None


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def _which_python39() -> str | None:
    # Windows py launcher
    for cand in ("py", "py.exe"):
        if shutil.which(cand):
            r = subprocess.run([cand, "-3.9", "-c", "import sys;print(sys.version)"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                return f"{cand} -3.9"
    # Plain python3.9
    for cand in ("python3.9", "python3.9.exe"):
        if shutil.which(cand):
            return cand
    return None


def _java_major(java_exe: str = "java") -> int | None:
    if not shutil.which(java_exe):
        return None
    r = subprocess.run([java_exe, "-version"], capture_output=True, text=True)
    out = (r.stderr or "") + (r.stdout or "")
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out)
    if not m:
        return None
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    return minor if major == 1 else major   # "1.8.0" → 8, "24.0.2" → 24


def _venv_has_simod() -> bool:
    return SIMOD_EXE.exists()


def run_checks() -> list[Check]:
    out: list[Check] = []

    py39 = _which_python39()
    out.append(Check(
        "Python 3.9", py39 is not None,
        f"found via `{py39}`" if py39 else "not installed",
        "Install Python 3.9.13 from python.org and tick 'Add to PATH'.",
    ))

    corretto = detect_corretto8()
    if corretto:
        out.append(Check(
            "Java 8 (for SplitMiner)", True,
            f"Corretto 8 found at {corretto} — will be used for Simod",
        ))
    else:
        java_home = os.environ.get("JAVA_HOME")
        java_exe = (Path(java_home, "bin", "java.exe").as_posix()
                    if java_home and Path(java_home, "bin", "java.exe").exists()
                    else "java")
        major = _java_major(java_exe)
        out.append(Check(
            "Java 8 (for SplitMiner)", major == 8,
            f"system java is version {major}" if major else "java not found",
            "Install Amazon Corretto 8 (winget install Amazon.Corretto.8.JDK).",
        ))

    simod_ok = _venv_has_simod()
    out.append(Check(
        "Simod venv", simod_ok,
        f"simod.exe at {SIMOD_EXE}" if simod_ok
        else f"missing {SIMOD_EXE}",
        f"Create it: `{py39 or 'py -3.9'} -m venv tools\\simod-venv && "
        f"tools\\simod-venv\\Scripts\\pip install simod`.",
    ))
    out.append(Check(
        "Prosimos venv", PROSIMOS_EXE.exists(),
        f"prosimos.exe at {PROSIMOS_EXE}" if PROSIMOS_EXE.exists()
        else f"missing {PROSIMOS_EXE}",
        f"Create it: `{py39 or 'py -3.9'} -m venv tools\\prosimos-venv && "
        f"tools\\prosimos-venv\\Scripts\\pip install prosimos`.",
    ))
    return out


def all_ok(checks: list[Check]) -> bool:
    return all(c.ok for c in checks)
