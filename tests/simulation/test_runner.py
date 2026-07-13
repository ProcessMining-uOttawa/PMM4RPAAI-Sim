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
    # The POSIX self-group guard is tested via MOCKED os.getpgid
    # (test_self_group_guard_refuses_killpg) rather than a real non-session child:
    # a real test would spawn a child sharing pytest's own process group and, if
    # the guard regressed, killpg the test runner. Mocking keeps it safe.

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
        try:
            assert proc.poll() is None  # actually running before we kill it
            runner.terminate_process(proc)
            proc.wait(timeout=5)  # raises TimeoutExpired if the kill failed to land
            assert proc.returncode is not None
        finally:
            if proc.poll() is None:  # a failed kill must not leak the subprocess
                proc.kill()
                proc.wait(timeout=5)

    def test_survives_taskkill_timeout(self, monkeypatch):
        # A hung taskkill (subprocess.run timing out) must not block: terminate_process
        # falls back to killing the tracked launcher directly, so the target exits and
        # proc.wait() unblocks. Forces the Windows branch cross-platform by faking
        # sys.platform + subprocess.run against a real, still-running process.
        monkeypatch.setattr(runner.sys, "platform", "win32")

        def _timeout(*a, **k):
            raise subprocess.TimeoutExpired("taskkill", runner._KILL_GRACE_SECONDS)

        monkeypatch.setattr(runner.subprocess, "run", _timeout)
        proc = runner._spawn([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            runner.terminate_process(proc)  # taskkill "hangs" → fallback proc.kill()
            proc.wait(timeout=5)
            assert proc.returncode is not None  # the target actually exited
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_self_group_guard_refuses_killpg(self, monkeypatch):
        # POSIX self-group guard: if a proc resolves to the runner's OWN process
        # group (the invariant-violation case), terminate_process must NOT killpg —
        # that would signal the Streamlit server / this test process. Fully mocked,
        # so no real signal is ever sent (getpgid returns one value for both).
        monkeypatch.setattr(runner.sys, "platform", "linux")
        monkeypatch.setattr(runner.os, "getpgid", lambda pid: 4242, raising=False)
        monkeypatch.setattr(
            runner.os,
            "killpg",
            lambda *a: pytest.fail("killpg called despite the self-group guard"),
            raising=False,
        )

        class _Running:
            pid = 999999

            def poll(self):
                return None

        runner.terminate_process(_Running())  # guard returns before any killpg
