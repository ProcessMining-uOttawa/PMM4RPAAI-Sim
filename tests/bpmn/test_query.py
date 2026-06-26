"""Tests for core/bpmn/query.py — no external tools required."""

from __future__ import annotations
import xml.etree.ElementTree as ET

import pytest

from core.bpmn.query import find_task_by_name, list_activities

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

_BPMN_XML = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{_BPMN_NS}">
  <bpmn:process>
    <bpmn:task     id="task_1" name="My Task"/>
    <bpmn:userTask id="task_2" name="User Task"/>
  </bpmn:process>
</bpmn:definitions>
"""


# ── find_task_by_name ─────────────────────────────────────────────────────────


class TestFindTaskByName:
    @pytest.fixture
    def tree(self):
        return ET.ElementTree(ET.fromstring(_BPMN_XML))

    def test_finds_plain_task(self, tree):
        el = find_task_by_name(tree, "My Task")
        assert el is not None and el.get("id") == "task_1"

    def test_finds_user_task(self, tree):
        el = find_task_by_name(tree, "User Task")
        assert el is not None and el.get("id") == "task_2"

    def test_returns_none_when_not_found(self, tree):
        assert find_task_by_name(tree, "Nonexistent") is None


# ── list_activities ───────────────────────────────────────────────────────────


class TestListActivities:
    def _write_bpmn(self, tmp_path, names: list[str]):
        bpmn = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{_BPMN_NS}">
  <bpmn:process>
    {"".join(f'<bpmn:task id="t{i}" name="{n}"/>' for i, n in enumerate(names))}
  </bpmn:process>
</bpmn:definitions>"""
        path = tmp_path / "model.bpmn"
        path.write_text(bpmn)
        return path

    def test_returns_task_names(self, tmp_path):
        path = self._write_bpmn(tmp_path, ["Fix Bug", "Review"])
        assert list_activities(path) == ["Fix Bug", "Review"]

    def test_task_names_ordered(self, tmp_path):
        path = self._write_bpmn(tmp_path, ["Fix Bug", "Review"])
        assert list_activities(path) != ["Review", "Fix Bug"]
        
    def test_deduplicates_names(self, tmp_path):
        path = self._write_bpmn(tmp_path, ["Fix Bug", "Fix Bug"])
        assert list_activities(path) == ["Fix Bug"]

    def test_excludes_nameless_tasks(self, tmp_path):
        bpmn = f"""\
<?xml version="1.0"?>
<bpmn:definitions xmlns:bpmn="{_BPMN_NS}">
  <bpmn:process>
    <bpmn:task id="t0"/>
    <bpmn:task id="t1" name="Real Task"/>
  </bpmn:process>
</bpmn:definitions>"""
        path = tmp_path / "model.bpmn"
        path.write_text(bpmn)
        assert list_activities(path) == ["Real Task"]

    def test_empty_process_returns_empty_list(self, tmp_path):
        path = self._write_bpmn(tmp_path, [])
        assert list_activities(path) == []
