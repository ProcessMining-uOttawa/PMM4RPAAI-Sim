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


@pytest.fixture
def sleeping_proc():
    """Spawn managed subprocesses (default cmd: sleep 30s) that are force-killed
    and reaped at teardown, so a failed kill can't leak a subprocess."""
    procs = []

    def _make(cmd=None, **kwargs):
        proc = runner._spawn(
            cmd or [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
        )
        procs.append(proc)
        return proc

    yield _make
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if proc.stdout:
            proc.stdout.close()


class TestTerminateProcess:
    def test_noop_on_finished_process(self):
        proc = runner._spawn([sys.executable, "-c", "pass"])
        proc.wait()
        runner.terminate_process(proc)  # already exited → must not raise
        assert proc.returncode is not None

    def test_kills_running_process(self, sleeping_proc):
        # new_session=True (POSIX) so terminate_process's killpg targets this
        # process's own group, never the test runner's.
        proc = sleeping_proc(new_session=True)
        assert proc.poll() is None  # actually running before we kill it
        runner.terminate_process(proc)
        proc.wait(timeout=5)  # raises TimeoutExpired if the kill failed to land
        assert proc.returncode is not None

    @pytest.mark.parametrize("taskkill_hangs", [True, False], ids=["hangs", "fails"])
    def test_taskkill_failure_falls_back_to_kill(
        self, monkeypatch, sleeping_proc, taskkill_hangs
    ):
        # taskkill hanging (TimeoutExpired) or reporting failure (non-zero exit)
        # with the target still alive must fall back to killing the tracked launcher,
        # so proc.wait() unblocks and cancel stays prompt. Forces the Windows branch
        # cross-platform.
        monkeypatch.setattr(runner.sys, "platform", "win32")

        def _fake_run(*a, **k):
            if taskkill_hangs:
                raise subprocess.TimeoutExpired("taskkill", runner._KILL_GRACE_SECONDS)
            return subprocess.CompletedProcess(a, returncode=1)

        monkeypatch.setattr(runner.subprocess, "run", _fake_run)
        proc = sleeping_proc()
        runner.terminate_process(proc)  # taskkill fails → fallback proc.kill()
        proc.wait(timeout=5)
        assert proc.returncode is not None  # the fallback exited the target

    @pytest.mark.skipif(
        sys.platform == "win32", reason="POSIX SIGTERM->SIGKILL escalation"
    )
    def test_posix_sigkill_escalation(self, monkeypatch, sleeping_proc):
        # A process that ignores SIGTERM must still die via the wait-timeout ->
        # SIGKILL escalation. The child prints readiness AFTER installing SIG_IGN,
        # so we don't SIGTERM it before it can ignore. Grace shrunk to stay fast.
        monkeypatch.setattr(runner, "_KILL_GRACE_SECONDS", 0.3)
        code = (
            "import signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print('ready', flush=True); "
            "time.sleep(30)"
        )
        proc = sleeping_proc(
            [sys.executable, "-c", code], new_session=True, stdout=subprocess.PIPE
        )
        assert proc.stdout.readline().strip() == b"ready"  # SIG_IGN installed
        runner.terminate_process(proc)  # SIGTERM ignored → grace → SIGKILL
        proc.wait(timeout=5)
        assert proc.returncode is not None

    def test_self_group_guard_refuses_killpg(self, monkeypatch):
        # POSIX self-group guard, tested via MOCKED os.getpgid rather than a real
        # non-session child: a real test would spawn a child sharing pytest's own
        # process group and, if the guard regressed, killpg the test runner. Mocked
        # so no real signal is sent — getpgid collides the child's group with the
        # runner's (one value for both) and killpg must NOT be called.
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
