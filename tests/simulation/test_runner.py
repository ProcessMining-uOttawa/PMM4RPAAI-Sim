"""Tests for runner's subprocess primitives — the _run_logged Popen rewrite (shared
by simulate() and discover()) and terminate_process. Uses real but trivial
`python -c` subprocesses (cross-platform, sub-second), never Simod/Prosimos."""

from __future__ import annotations

import subprocess
import sys

import pytest

from core.simulation import runner


class TestRunLogged:
    def test_success_captures_output(self, tmp_path):
        log = tmp_path / "log.txt"
        runner._run_logged([sys.executable, "-c", "print('hello')"], log)
        assert "hello" in log.read_text()

    def test_raises_on_nonzero_with_tail(self, tmp_path):
        log = tmp_path / "log.txt"
        with pytest.raises(subprocess.CalledProcessError):
            runner._run_logged([sys.executable, "-c", "import sys; sys.exit(3)"], log)

    def test_bare_branch_raises_on_nonzero(self):
        # proc_log=None path (used by simulate retries) still raises on failure.
        with pytest.raises(subprocess.CalledProcessError):
            runner._run_logged([sys.executable, "-c", "import sys; sys.exit(1)"], None)

    def test_bare_branch_invokes_on_spawn(self):
        # proc_log=None AND on_spawn set is the production retry path: run_all
        # re-submits with proc_log=None but _submit always passes on_spawn. Pins
        # the bare-branch on_spawn(proc) call, distinct from the logged branch.
        spawned: list = []
        runner._run_logged(
            [sys.executable, "-c", "pass"], None, on_spawn=lambda p: spawned.append(p)
        )
        assert len(spawned) == 1
        assert isinstance(spawned[0], subprocess.Popen)

    def test_invokes_on_spawn_with_popen(self, tmp_path):
        log = tmp_path / "log.txt"
        spawned: list = []
        runner._run_logged(
            [sys.executable, "-c", "pass"], log, on_spawn=lambda p: spawned.append(p)
        )
        assert len(spawned) == 1
        assert isinstance(spawned[0], subprocess.Popen)


class TestTerminateProcess:
    # The POSIX self-group guard (`if pgid == os.getpgid(0): return`) is
    # deliberately NOT tested: a direct test would spawn a non-session child
    # (which shares pytest's own process group) and assert the guard refuses to
    # kill it — but if the guard ever regressed, that test would killpg the test
    # runner. It is defense-in-depth for an invariant (on_spawn <-> new_session)
    # enforced in _run_logged, so it stays covered by construction, not by a test.

    def test_noop_on_finished_process(self):
        proc = runner._spawn([sys.executable, "-c", "pass"])
        proc.wait()
        runner.terminate_process(proc)  # already exited → must not raise
        assert proc.returncode is not None

    def test_kills_running_process(self):
        # new_session=True (POSIX) so terminate_process's killpg targets this
        # process's own group, never the test runner's.
        proc = runner._spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"], new_session=True
        )
        runner.terminate_process(proc)
        proc.wait(timeout=5)  # raises TimeoutExpired if the kill failed to land
        assert proc.returncode is not None
