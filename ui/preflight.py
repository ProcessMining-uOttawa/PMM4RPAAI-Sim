"""Detect Simod's runtime prerequisites and report them to the UI."""
from __future__ import annotations
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.simulation.runner import SIMOD_EXE, PROSIMOS_EXE

SIMOD_PYTHON_VERSION = "3.9"
REQUIRED_JAVA_MAJOR = 8

# Windows-only: on other platforms these dirs won't exist and _detect_corretto8()
# returns None, falling through to the system-Java check via PATH (correct behaviour).
CORRETTO_ROOTS = [
    Path(r"C:\Program Files\Amazon Corretto"),
    Path(r"C:\Program Files (x86)\Amazon Corretto"),
]


def _detect_corretto8() -> str | None:
    for root in CORRETTO_ROOTS:
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if d.is_dir() and d.name.startswith("jdk1.8") and (d / "bin" / "java.exe").exists():
                    return str(d)
    return None


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def _which_simod_python() -> str | None:
    # Windows py launcher
    for cand in ("py", "py.exe"):
        if shutil.which(cand):
            r = subprocess.run(
                [cand, f"-{SIMOD_PYTHON_VERSION}", "-c", "import sys;print(sys.version)"],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                return f"{cand} -{SIMOD_PYTHON_VERSION}"
    # Plain python3.x
    for cand in (f"python{SIMOD_PYTHON_VERSION}", f"python{SIMOD_PYTHON_VERSION}.exe"):
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


def run_checks() -> tuple[list[Check], str | None]:
    """Return (checks, suggested_java_home).

    suggested_java_home is the Corretto 8 path when auto-detected, or None.
    """
    out: list[Check] = []

    py = _which_simod_python()
    out.append(Check(
        f"Python {SIMOD_PYTHON_VERSION}", py is not None,
        f"found via `{py}`" if py else "not installed",
        f"Install Python {SIMOD_PYTHON_VERSION} from python.org and tick 'Add to PATH'.",
    ))

    corretto = _detect_corretto8()
    if corretto:
        out.append(Check(
            f"Java {REQUIRED_JAVA_MAJOR} (for SplitMiner)", True,
            f"Corretto {REQUIRED_JAVA_MAJOR} found at {corretto} — will be used for Simod",
        ))
    else:
        java_home = os.environ.get("JAVA_HOME")
        java_exe = (Path(java_home, "bin", "java.exe").as_posix()
                    if java_home and Path(java_home, "bin", "java.exe").exists()
                    else "java")
        major = _java_major(java_exe)
        out.append(Check(
            f"Java {REQUIRED_JAVA_MAJOR} (for SplitMiner)", major == REQUIRED_JAVA_MAJOR,
            f"system java is version {major}" if major else "java not found",
            f"Install Amazon Corretto {REQUIRED_JAVA_MAJOR} (winget install Amazon.Corretto.{REQUIRED_JAVA_MAJOR}.JDK).",
        ))

    py_cmd = py or f"py -{SIMOD_PYTHON_VERSION}"
    simod_ok = _venv_has_simod()
    out.append(Check(
        "Simod venv", simod_ok,
        f"simod.exe at {SIMOD_EXE}" if simod_ok else f"missing {SIMOD_EXE}",
        f"Create it: `{py_cmd} -m venv tools\\simod-venv && "
        f"tools\\simod-venv\\Scripts\\pip install simod`.",
    ))
    out.append(Check(
        "Prosimos venv", PROSIMOS_EXE.exists(),
        f"prosimos.exe at {PROSIMOS_EXE}" if PROSIMOS_EXE.exists() else f"missing {PROSIMOS_EXE}",
        f"Create it: `{py_cmd} -m venv tools\\prosimos-venv && "
        f"tools\\prosimos-venv\\Scripts\\pip install prosimos`.",
    ))
    return out, corretto


def all_ok(checks: list[Check]) -> bool:
    return all(c.ok for c in checks)
