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


def _stub_simod_outputs(tmp_path, monkeypatch) -> None:
    """Stub the output locator — discover() tests spawn no Simod, so no tree exists."""
    monkeypatch.setattr(
        runner,
        "_locate_simod_outputs",
        lambda out_dir: (tmp_path / "m.bpmn", tmp_path / "p.json"),
    )


class TestSimulateCommand:
    def test_omits_event_log_flag(self, tmp_path, monkeypatch):
        # Absence is the ONLY safe encoding: Prosimos parses the flag's value
        # truthily, so even "--is_event_added_to_log false" would enable the
        # intermediate-event rows that replication_metrics rejects.
        captured = _capture_run_logged(monkeypatch)
        runner.simulate(
            tmp_path / "m.bpmn", tmp_path / "p.json", 10, tmp_path / "out.csv"
        )
        assert "--is_event_added_to_log" not in captured["cmd"]


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
# The Apromore export convention (capitalised headers) — the canonical
# rejected-upload fixture.
_BAD_HEADER_CSV = "Case_ID,Activity,Start_Time,End_Time,Resource\nc1,A,t0,t1,R\n"


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
        bad = _csv_file(tmp_path, _BAD_HEADER_CSV)
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


class TestSimodCsvCaseCount:
    def test_counts_distinct_cases_not_rows(self, tmp_path):
        csv_path = _csv_file(
            tmp_path,
            f"{_VALID_HEADER}\n"
            "c1,A,2025-01-01T08:00:00,2025-01-01T09:00:00,R1\n"
            "c1,B,2025-01-01T09:00:00,2025-01-01T10:00:00,R1\n"
            "c2,A,2025-01-01T08:00:00,2025-01-01T09:00:00,R1\n",
        )
        assert runner.simod_csv_case_count(csv_path) == 2

    def test_bom_header_tolerated(self, tmp_path):
        # The converted/validated CSV may carry a BOM (validate_simod_csv
        # accepts one); the counter must read the same encoding.
        path = _csv_file(
            tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n", encoding="utf-8-sig"
        )
        assert runner.simod_csv_case_count(path) == 1

    def test_leading_blank_lines_tolerated(self, tmp_path):
        # validate_simod_csv accepts leading blank lines (its header scan takes
        # the first non-blank row), so every file the pre-flight passes must
        # count cleanly here — the validator's acceptance set is the counter's
        # contract.
        path = _csv_file(tmp_path, f"\n\n{_VALID_HEADER}\n{_DATA_ROW}\n")
        assert runner.simod_csv_case_count(path) == 1


class TestDiscoverReturnsSimodCsv:
    """The triple's third element is the Simod-ready CSV — the file the model
    fidelity check computes its observed statistics from."""

    def test_csv_branch_returns_the_upload_itself(self, tmp_path, monkeypatch):
        _capture_run_logged(monkeypatch)
        _stub_simod_outputs(tmp_path, monkeypatch)
        good = _csv_file(tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n")
        # Full triple asserted: (bpmn, params, simod_csv) — the first two come
        # from the stub, so this pins the return ORDER app.py unpacks by.
        assert runner.discover(good, tmp_path / "run") == (
            tmp_path / "m.bpmn",
            tmp_path / "p.json",
            good,
        )

    def test_xes_branch_returns_the_converted_csv(self, tmp_path, monkeypatch):
        _capture_run_logged(monkeypatch)
        _stub_simod_outputs(tmp_path, monkeypatch)
        xes = tmp_path / "log.xes"
        xes.write_text(_XES_TWO_EVENTS)
        run_dir = tmp_path / "run"
        _, _, simod_csv = runner.discover(xes, run_dir)
        assert simod_csv == run_dir / "log.csv"
        runner.validate_simod_csv(simod_csv)  # written to disk, Simod-schema


class TestDiscoverCommand:
    """The discovery-mode branch: search_iterations=None is one-shot,
    an int is the calibrated recipe via a generated config YAML."""

    def test_default_is_one_shot(self, tmp_path, monkeypatch):
        captured = _capture_run_logged(monkeypatch)
        _stub_simod_outputs(tmp_path, monkeypatch)
        good = _csv_file(tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n")
        runner.discover(good, tmp_path / "run")
        assert "--one-shot" in captured["cmd"]
        assert "--configuration" not in captured["cmd"]

    def test_calibrated_cmd_uses_config(self, tmp_path, monkeypatch):
        captured = _capture_run_logged(monkeypatch)
        _stub_simod_outputs(tmp_path, monkeypatch)
        good = _csv_file(tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n")
        run_dir = tmp_path / "run"
        runner.discover(good, run_dir, search_iterations=10)
        config_path = run_dir / "simod_config.yaml"
        assert config_path.exists()
        assert captured["cmd"][1:] == [
            "--configuration",
            str(config_path.resolve()),
            "--output",
            str((run_dir / "outputs").resolve()),
        ]

    def test_calibrated_config_content(self, tmp_path, monkeypatch):
        _capture_run_logged(monkeypatch)
        _stub_simod_outputs(tmp_path, monkeypatch)
        good = _csv_file(tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n")
        run_dir = tmp_path / "run"
        runner.discover(good, run_dir, search_iterations=10)
        config = (run_dir / "simod_config.yaml").read_text(encoding="utf-8")
        # Both searched stages get the budget; every pinned field is present.
        assert config.count("num_iterations: 10") == 2
        assert "discovery_type: differentiated_by_resource" in config
        assert "use_observed_arrival_distribution: false" in config
        assert "clean_intermediate_files: true" in config
        assert "perform_final_evaluation: false" in config
        assert "extraneous_activity_delays:" in config
        assert good.resolve().as_posix() in config

    def test_calibrated_xes_config_points_at_converted_csv(self, tmp_path, monkeypatch):
        _capture_run_logged(monkeypatch)
        _stub_simod_outputs(tmp_path, monkeypatch)
        xes = tmp_path / "log.xes"
        xes.write_text(_XES_TWO_EVENTS)
        run_dir = tmp_path / "run"
        runner.discover(xes, run_dir, search_iterations=5)
        config = (run_dir / "simod_config.yaml").read_text(encoding="utf-8")
        assert (run_dir / "log.csv").resolve().as_posix() in config
        assert "log.xes" not in config

    def test_discover_forwards_on_spawn(self, tmp_path, monkeypatch):
        # The kill-registration hook must reach _run_logged — it is what lets
        # cancel_discovery terminate a live Simod.
        forwarded = {}
        monkeypatch.setattr(
            runner,
            "_run_logged",
            lambda cmd, proc_log, on_spawn=None, **k: forwarded.setdefault(
                "on_spawn", on_spawn
            ),
        )
        _stub_simod_outputs(tmp_path, monkeypatch)
        good = _csv_file(tmp_path, f"{_VALID_HEADER}\n{_DATA_ROW}\n")

        def registration_hook(process):
            pass

        runner.discover(good, tmp_path / "run", on_spawn=registration_hook)
        assert forwarded["on_spawn"] is registration_hook

    def test_calibrated_bad_csv_rejected_before_spawn(self, tmp_path, monkeypatch):
        # Validation ordering holds in calibrated mode too: no subprocess, and
        # no config YAML left on disk for a rejected upload.
        captured = _capture_run_logged(monkeypatch)
        bad = _csv_file(tmp_path, _BAD_HEADER_CSV)
        run_dir = tmp_path / "run"
        with pytest.raises(ValueError):
            runner.discover(bad, run_dir, search_iterations=10)
        assert captured == {}
        assert not (run_dir / "simod_config.yaml").exists()


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
