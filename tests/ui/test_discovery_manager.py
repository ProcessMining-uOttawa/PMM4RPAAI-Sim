"""Tests for ui/discovery_manager — the commit_discovery session-key contract.

The fidelity panel reads ss.simod_csv_path / ss.log_case_count by exact name
(its toggle disables when either is None), so the producer side must be pinned
— the commit_as_discovered precedent in test_run_manager.py.
"""

from __future__ import annotations

from pathlib import Path

from ui.discovery_manager import DiscoveryResult, commit_discovery


class _FakeSession(dict):
    """Attribute-style dict standing in for st.session_state."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def _result() -> DiscoveryResult:
    return DiscoveryResult(
        bpmn_path=Path("outputs/model.bpmn"),
        json_path=Path("outputs/params.json"),
        activities=["Fix Bug"],
        log_name="log.csv",
        log_path=Path("log.csv"),
        simod_csv_path=Path("log.csv"),
        log_case_count=42,
    )


class TestCommitDiscovery:
    def test_writes_the_fidelity_keys(self):
        ss = _FakeSession()
        commit_discovery(ss, _result(), fingerprint=("log.csv", 10))
        assert ss.simod_csv_path == Path("log.csv")
        assert ss.log_case_count == 42

    def test_stamps_the_fingerprint(self):
        # log_fingerprint is what makes the upload read as already-discovered.
        ss = _FakeSession()
        commit_discovery(ss, _result(), fingerprint=("log.csv", 10))
        assert ss.log_fingerprint == ("log.csv", 10)
