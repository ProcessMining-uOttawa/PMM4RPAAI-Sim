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
_WINDOWS = os.name == "nt"

# Windows-only: on other platforms these dirs won't exist and _detect_corretto8()
# returns None, falling through to the system-Java check via PATH (correct behaviour).
CORRETTO_ROOTS = [
    Path(r"C:\Program Files\Amazon Corretto"),
    Path(r"C:\Program Files (x86)\Amazon Corretto"),
]

# macOS-only: same fall-through logic as CORRETTO_ROOTS. Any vendor's JDK 8 in a
# JVM directory qualifies (Corretto, Temurin, Zulu, …) — verified by version, not
# name, because /usr/libexec/java_home can prefer the legacy Oracle applet JRE.
MACOS_JVM_ROOTS = [
    Path.home() / "Library" / "Java" / "JavaVirtualMachines",
    Path("/Library/Java/JavaVirtualMachines"),
]


def _detect_corretto8() -> str | None:
    for root in CORRETTO_ROOTS:
        if root.is_dir():
            for jdk_dir in sorted(root.iterdir()):
                if (
                    jdk_dir.is_dir()
                    and jdk_dir.name.startswith("jdk1.8")
                    and (jdk_dir / "bin" / "java.exe").exists()
                ):
                    return str(jdk_dir)
    return None


def _detect_macos_jdk8() -> str | None:
    for root in MACOS_JVM_ROOTS:
        if not root.is_dir():
            continue
        for jdk_dir in sorted(root.iterdir()):
            home = jdk_dir / "Contents" / "Home"
            java = home / "bin" / "java"
            if java.exists() and _java_major(str(java)) == REQUIRED_JAVA_MAJOR:
                return str(home)
    return None


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def _which_simod_python() -> str | None:
    # Windows py launcher
    for candidate in ("py", "py.exe"):
        if shutil.which(candidate):
            proc = subprocess.run(
                [
                    candidate,
                    f"-{SIMOD_PYTHON_VERSION}",
                    "-c",
                    "import sys;print(sys.version)",
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                return f"{candidate} -{SIMOD_PYTHON_VERSION}"
    # Plain python3.x on PATH, then Homebrew keg-only installs (never linked
    # onto PATH): /opt/homebrew is Apple Silicon, /usr/local is Intel.
    for candidate in (
        f"python{SIMOD_PYTHON_VERSION}",
        f"python{SIMOD_PYTHON_VERSION}.exe",
        f"/opt/homebrew/opt/python@{SIMOD_PYTHON_VERSION}/bin/python{SIMOD_PYTHON_VERSION}",
        f"/usr/local/opt/python@{SIMOD_PYTHON_VERSION}/bin/python{SIMOD_PYTHON_VERSION}",
    ):
        if shutil.which(candidate):
            return candidate
    return None


def _java_major(java_exe: str = "java") -> int | None:
    if not shutil.which(java_exe):
        return None
    proc = subprocess.run([java_exe, "-version"], capture_output=True, text=True)
    output = (proc.stderr or "") + (proc.stdout or "")
    match = re.search(r'version "(\d+)(?:\.(\d+))?', output)
    if not match:
        return None
    major, minor = int(match.group(1)), int(match.group(2) or 0)
    return minor if major == 1 else major  # "1.8.0" → 8, "24.0.2" → 24


def _java_exe_from_home() -> str:
    """Path to the java binary under JAVA_HOME if present, else the bare 'java' on PATH."""
    java_home = os.environ.get("JAVA_HOME")
    if not java_home:
        return "java"
    exe_name = "java.exe" if _WINDOWS else "java"
    candidate = Path(java_home, "bin", exe_name)
    return candidate.as_posix() if candidate.exists() else "java"


def _venv_check(exe: Path, package: str, py_cmd: str) -> Check:
    """Build the venv Check for `package`, reporting `exe` and its create command."""
    ok = exe.exists()
    # The venv dir and pip path share the exe's layout — derive, don't re-encode.
    pip = exe.parent / f"pip{exe.suffix}"
    return Check(
        f"{package.capitalize()} venv",
        ok,
        f"{exe.name} at {exe}" if ok else f"missing {exe}",
        f"Create it: `{py_cmd} -m venv {exe.parent.parent} && "
        f"{pip} install {package}`.",
    )


def run_checks() -> tuple[list[Check], str | None]:
    """Return (checks, suggested_java_home).

    suggested_java_home is the auto-detected JDK 8 home (Windows Corretto
    or a macOS JVM-directory JDK), or None.
    """
    checks: list[Check] = []

    py_fix = (
        f"Install Python {SIMOD_PYTHON_VERSION} from python.org and tick 'Add to PATH'."
        if _WINDOWS
        else f"Install Python {SIMOD_PYTHON_VERSION}: `brew install python@{SIMOD_PYTHON_VERSION}`."
    )
    py = _which_simod_python()
    checks.append(
        Check(
            f"Python {SIMOD_PYTHON_VERSION}",
            py is not None,
            f"found via `{py}`" if py else "not installed",
            py_fix,
        )
    )

    jdk8 = _detect_corretto8() or _detect_macos_jdk8()
    if jdk8:
        checks.append(
            Check(
                f"Java {REQUIRED_JAVA_MAJOR} (for SplitMiner)",
                True,
                f"JDK {REQUIRED_JAVA_MAJOR} found at {jdk8} — will be used for Simod",
            )
        )
    else:
        java_fix = (
            f"Install Amazon Corretto {REQUIRED_JAVA_MAJOR} (winget install Amazon.Corretto.{REQUIRED_JAVA_MAJOR}.JDK)."
            if _WINDOWS
            else f"Install a JDK {REQUIRED_JAVA_MAJOR} into ~/Library/Java/JavaVirtualMachines (see README)."
        )
        major = _java_major(_java_exe_from_home())
        checks.append(
            Check(
                f"Java {REQUIRED_JAVA_MAJOR} (for SplitMiner)",
                major == REQUIRED_JAVA_MAJOR,
                f"system java is version {major}" if major else "java not found",
                java_fix,
            )
        )

    py_cmd = py or (
        f"py -{SIMOD_PYTHON_VERSION}" if _WINDOWS else f"python{SIMOD_PYTHON_VERSION}"
    )
    checks.append(_venv_check(SIMOD_EXE, "simod", py_cmd))
    checks.append(_venv_check(PROSIMOS_EXE, "prosimos", py_cmd))
    return checks, jdk8


def all_ok(checks: list[Check]) -> bool:
    return all(c.ok for c in checks)
