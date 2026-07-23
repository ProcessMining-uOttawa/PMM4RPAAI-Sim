"""Tests for runner — subprocess primitives (_run_logged, terminate_process; real
but trivial `python -c` subprocesses, never Simod/Prosimos), simulate()'s command
construction, and the CSV pre-flight (validate_simod_csv + its discover() wiring)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from core.simulation import runner


def _capture_run_logged(monkeypatch) -> dict:
    """Spy replacing _run_logged; the launched cmd lands in the returned dict."""
    captured: dict = {}
    monkeypatch.setattr(
        runner, "_run_logged", lambda cmd, *a, **k: captured.setdefault("cmd", cmd)
    )
    return captured


class TestSimulateCommand:
    def test_passes_event_log_flag(self, tmp_path, monkeypatch):
        # replication_metrics.py sources the case arrival from the intermediate-event rows that
        # this flag emits, so simulate() must always request them. Value "true":
        # Prosimos parses the flag truthily (even "false" would enable it).
        captured = _capture_run_logged(monkeypatch)
        runner.simulate(
            tmp_path / "m.bpmn", tmp_path / "p.json", 10, tmp_path / "out.csv"
        )
        cmd = captured["cmd"]
        flag_index = cmd.index("--is_event_added_to_log")
        assert cmd[flag_index + 1] == "true"


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


# ── CSV pre-flight (validate_simod_csv) ───────────────────────────────────────

_VALID_HEADER = "case_id,activity,start_time,end_time,resource"
_DATA_ROW = "c1,Fix Bug,2025-01-01T08:00:00,2025-01-01T09:00:00,R1"


def _csv_file(tmp_path, text: str, encoding: str = "utf-8"):
    path = tmp_path / "log.csv"
    path.write_text(text, encoding=encoding)
    return path


class TestValidateSimodCsv:
    """The pre-flight rejects a CSV Simod's reader would crash on, with a message
    naming the problem — missing vs found columns, case hints — instead of the
    opaque CalledProcessError the subprocess failure would surface as."""

    def test_accepts_exact_schema(self, tmp_path):
        runner.validate_simod_csv(
            _csv_file(tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n")
        )

    def test_accepts_extra_columns(self, tmp_path):
        # Simod reads by name and ignores extras — they must not reject.
        header = _VALID_HEADER + ",Role,Claim_Value"
        runner.validate_simod_csv(
            _csv_file(tmp_path, f"{header}\n{_DATA_ROW},Officer,100\n")
        )

    def test_column_order_irrelevant(self, tmp_path):
        header = "resource,end_time,start_time,activity,case_id"
        row = "R1,2025-01-01T09:00:00,2025-01-01T08:00:00,Fix Bug,c1"
        runner.validate_simod_csv(_csv_file(tmp_path, f"{header}\n{row}\n"))

    def test_missing_columns_named(self, tmp_path):
        path = _csv_file(tmp_path, "case_id,start_time,end_time\nc1,t0,t1\n")
        with pytest.raises(
            ValueError, match=r"missing required column\(s\): activity, resource"
        ):
            runner.validate_simod_csv(path)

    def test_found_columns_named(self, tmp_path):
        path = _csv_file(
            tmp_path, "case_id,start_time,end_time,claim_ref\nc1,t0,t1,x\n"
        )
        with pytest.raises(ValueError, match="claim_ref"):
            runner.validate_simod_csv(path)

    def test_whitespace_variant_rejected_with_hint(self, tmp_path):
        # Simod's reader does no whitespace normalisation — 'case_id ' would
        # crash it, so the pre-flight must reject rather than silently strip.
        header = "case_id ,activity,start_time,end_time,resource"
        path = _csv_file(tmp_path, f"{header}\n{_DATA_ROW}\n")
        with pytest.raises(ValueError) as exc:
            runner.validate_simod_csv(path)
        assert "'case_id '" in str(exc.value)  # culprit named, whitespace visible

    def test_case_mismatch_hint(self, tmp_path):
        # The Apromore export convention capitalises every header.
        header = "Case_ID,Activity,Start_Time,End_Time,Resource"
        path = _csv_file(tmp_path, f"{header}\n{_DATA_ROW}\n")
        with pytest.raises(ValueError) as exc:
            runner.validate_simod_csv(path)
        # Pin the hint sentence itself — the generic message parts also contain
        # both spellings, so bare substring checks cannot discriminate the hint.
        message = str(exc.value)
        assert "Found 'Case_ID' — Simod requires exactly 'case_id'." in message

    def test_empty_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="empty"):
            runner.validate_simod_csv(_csv_file(tmp_path, ""))

    def test_header_only_raises(self, tmp_path):
        with pytest.raises(ValueError, match="no event rows"):
            runner.validate_simod_csv(_csv_file(tmp_path, f"{_VALID_HEADER}\n"))

    def test_leading_blank_lines_skipped(self, tmp_path):
        # pandas skips blank lines by default; the pre-flight must match rather
        # than falsely reject a file Simod would accept.
        runner.validate_simod_csv(
            _csv_file(tmp_path, f"\n\n{_VALID_HEADER}\n{_DATA_ROW}\n")
        )

    def test_bom_header_accepted(self, tmp_path):
        # Excel writes UTF-8 with a BOM; it must not corrupt 'case_id'.
        path = _csv_file(
            tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n", encoding="utf-8-sig"
        )
        runner.validate_simod_csv(path)

    def test_semicolon_delimiter_hint(self, tmp_path):
        text = (
            _VALID_HEADER.replace(",", ";") + "\n" + _DATA_ROW.replace(",", ";") + "\n"
        )
        with pytest.raises(ValueError, match="semicolon"):
            runner.validate_simod_csv(_csv_file(tmp_path, text))

    def test_non_utf8_raises_clear_error(self, tmp_path):
        # Excel's "Unicode text" export is UTF-16 — must surface as a clear
        # ValueError, not a raw UnicodeDecodeError.
        path = _csv_file(tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n", encoding="utf-16")
        with pytest.raises(ValueError, match="UTF-8"):
            runner.validate_simod_csv(path)


class TestDiscoverValidatesCsv:
    def test_bad_csv_rejected_before_spawn(self, tmp_path, monkeypatch):
        captured = _capture_run_logged(monkeypatch)
        bad = _csv_file(
            tmp_path, "Case_ID,Activity,Start_Time,End_Time,Resource\nc1,A,t0,t1,R\n"
        )
        with pytest.raises(ValueError):
            runner.discover(bad, tmp_path / "run")
        assert captured == {}  # rejected before any subprocess was spawned

    def test_good_csv_proceeds_to_spawn(self, tmp_path, monkeypatch):
        # Guards against an over-eager validator (or a mis-placed call) silently
        # rejecting valid files: validation passes, the (mocked) subprocess runs,
        # and discover() then fails only on the absent Simod outputs.
        captured = _capture_run_logged(monkeypatch)
        good = _csv_file(tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n")
        with pytest.raises(RuntimeError, match="Expected exactly 1 BPMN"):
            runner.discover(good, tmp_path / "run")
        assert "cmd" in captured


_XES_TWO_EVENTS = """<?xml version="1.0" encoding="UTF-8"?>
<log xmlns="http://www.xes-standard.org/">
  <trace>
    <string key="concept:name" value="c1"/>
    <event>
      <string key="concept:name" value="A"/>
      <string key="org:resource" value="R1"/>
      <date key="time:timestamp" value="2025-01-01T08:00:00+00:00"/>
    </event>
    <event>
      <string key="concept:name" value="B"/>
      <string key="org:resource" value="R1"/>
      <date key="time:timestamp" value="2025-01-01T09:00:00+00:00"/>
    </event>
  </trace>
</log>
"""


class TestXesConversionSchema:
    def test_converted_xes_passes_validation(self, tmp_path):
        # Pins why discover() validates only the non-XES branch: the converter
        # emits the Simod schema by construction, so a converted log must always
        # satisfy the same validator a direct CSV upload faces.
        xes = tmp_path / "log.xes"
        xes.write_text(_XES_TWO_EVENTS)
        out = runner.xes_to_simod_csv(xes, tmp_path / "log.csv")
        runner.validate_simod_csv(out)  # must not raise
        header = out.read_text().splitlines()[0]
        assert header == ",".join(runner.SIMOD_LOG_COLUMNS)


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
