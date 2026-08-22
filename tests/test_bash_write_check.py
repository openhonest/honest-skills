"""Tests for the Bash write hook.

It cannot say a command caused a change, only that the change happened around
it. Most of these pin what it refuses to claim.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "bash_write_check", ROOT / "hooks" / "bash_write_check.py")
bw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bw)
_pspec = importlib.util.spec_from_file_location(
    "pending", ROOT / "hooks" / "pending.py")
pending = importlib.util.module_from_spec(_pspec)
_pspec.loader.exec_module(pending)

DIRTY = "def charge(card, timeout=30):\n    try:\n        pass\n    except Exception:\n        pass\n"
CLEAN = "def add(a, b):\n    return a + b\n"


def payload(cwd, tool="Bash"):
    return json.dumps({"session_id": "s", "tool_name": tool, "cwd": str(cwd),
                       "tool_input": {"command": "echo hi"}})


@pytest.fixture(autouse=True)
def _isolated_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "pending"))


def run_hook(raw, monkeypatch):
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(sys, "stderr", err)
    return bw.main(), err.getvalue()


def test_it_finds_a_file_written_by_a_heredoc(tmp_path):
    """280 of one session's 376 Bash writes were Python heredocs, where the
    path lives inside the Python and no shell parsing can find it."""
    (tmp_path / "x.py").write_text(DIRTY)
    assert bw.recently_written(str(tmp_path), 120) == [str(tmp_path / "x.py")]


def test_a_file_written_long_ago_is_not_this_command(tmp_path):
    f = tmp_path / "old.py"; f.write_text(CLEAN)
    os.utime(f, (time.time() - 600, time.time() - 600))
    assert bw.recently_written(str(tmp_path), 120) == []


@pytest.mark.parametrize("d", [".git", "node_modules", ".venv", "__pycache__", "target"])
def test_generated_and_vendored_trees_are_skipped(tmp_path, d):
    """A checkout moves every file in .git and none of it is someone editing."""
    sub = tmp_path / d; sub.mkdir()
    (sub / "x.py").write_text(DIRTY)
    assert bw.recently_written(str(tmp_path), 120) == []


def test_a_file_type_it_does_not_check_is_not_collected(tmp_path):
    (tmp_path / "notes.md").write_text("hello")
    assert bw.recently_written(str(tmp_path), 120) == []


def test_a_build_reports_nothing(tmp_path, monkeypatch):
    """A hook that fires on `git checkout` is a hook nobody keeps."""
    for i in range(bw.TOO_MANY + 3):
        (tmp_path / f"f{i}.py").write_text(DIRTY)
    code, err = run_hook(payload(tmp_path), monkeypatch)
    assert (code, err) == (0, "")


def test_it_records_that_it_declined_on_a_build(tmp_path, monkeypatch):
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    for i in range(bw.TOO_MANY + 3):
        (tmp_path / f"f{i}.py").write_text(DIRTY)
    run_hook(payload(tmp_path), monkeypatch)
    assert "reads as a build" in json.loads(log.read_text().splitlines()[-1])["why"]


def test_a_dirty_file_written_by_a_script_surfaces_when_the_turn_ends(
        tmp_path, monkeypatch):
    """The whole path, end to end: a script writes the file, the Bash hook
    holds the path, and the settle reports it. 30 percent of one session's
    writes went through Bash and were invisible to the Write and Edit hooks."""
    (tmp_path / "x.py").write_text(DIRTY)
    monkeypatch.setattr(bw.edit_check, "honest_code_finding",
                        lambda p: {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
                                   "detail": "d", "action": "a"})
    assert run_hook(payload(tmp_path), monkeypatch) == (0, "")
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s"}'))
    monkeypatch.setattr(sys, "stderr", err)
    assert bw.edit_check.main() == 2 and "L1.21" in err.getvalue()


def test_a_clean_file_is_silent(tmp_path, monkeypatch):
    (tmp_path / "x.py").write_text(CLEAN)
    monkeypatch.setattr(bw.edit_check, "honest_code_finding", lambda p: None)
    assert run_hook(payload(tmp_path), monkeypatch) == (0, "")


def test_nothing_changed_is_silent_and_recorded(tmp_path, monkeypatch):
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    assert run_hook(payload(tmp_path), monkeypatch) == (0, "")
    assert json.loads(log.read_text())["why"] == "no source file changed"


def test_it_ignores_every_tool_but_bash(tmp_path, monkeypatch):
    """Write and Edit have their own hook. Running both would double-report."""
    (tmp_path / "x.py").write_text(DIRTY)
    assert run_hook(payload(tmp_path, tool="Write"), monkeypatch) == (0, "")


def test_malformed_input_does_nothing(monkeypatch):
    assert run_hook("not json", monkeypatch) == (0, "")


def test_a_json_value_that_is_not_an_object_does_nothing(monkeypatch):
    assert run_hook("[1,2,3]", monkeypatch) == (0, "")


def test_an_unreadable_file_is_skipped_not_raised(tmp_path, monkeypatch):
    """A file deleted between the walk and the read is normal, not an error."""
    (tmp_path / "x.py").write_text(DIRTY)
    real = Path.read_text
    def boom(self, *a, **k):
        if self.name == "x.py":
            raise OSError("gone")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", boom)
    assert run_hook(payload(tmp_path), monkeypatch) == (0, "")


def test_an_unwalkable_entry_does_not_stop_the_scan(tmp_path, monkeypatch):
    (tmp_path / "x.py").write_text(DIRTY)
    def boom(p):
        raise OSError("no")
    monkeypatch.setattr(bw.os.path, "getmtime", boom)
    assert bw.recently_written(str(tmp_path), 120) == []


def test_it_never_claims_the_command_caused_the_change():
    """It knows a file moved around the time a command ran. Nothing more, and
    the docstring says so rather than leaving it to be assumed."""
    src = (ROOT / "hooks" / "bash_write_check.py").read_text()
    assert "cannot say the command caused the change" in src


def test_a_bash_write_is_held_for_the_settle_rather_than_judged_here(
        tmp_path, monkeypatch):
    """It used to assess on the spot, which repeated a finding on every later
    Bash call while the mtime stayed inside the window. One session saw the
    identical block five times while working on something else. The paths now
    go to the same settle the Write and Edit hooks feed."""
    (tmp_path / "x.py").write_text(DIRTY)
    assert run_hook(payload(tmp_path), monkeypatch) == (0, "")
    held = pending.entries(pending.read_state("edit", "s"))
    assert [e["path"] for e in held] == [str(tmp_path / "x.py")]


def test_a_bash_write_also_reaches_the_stub_check(tmp_path, monkeypatch):
    """The stub check only ever saw Write and Edit, so a file a script wrote
    was never looked at for stubs at all."""
    (tmp_path / "x.py").write_text(DIRTY)
    run_hook(payload(tmp_path), monkeypatch)
    held = pending.entries(pending.read_state("stub", "s"))
    assert [e["path"] for e in held] == [str(tmp_path / "x.py")]


def test_a_build_is_still_refused_before_anything_is_held(tmp_path, monkeypatch):
    for i in range(bw.TOO_MANY + 1):
        (tmp_path / f"f{i}.py").write_text(CLEAN)
    assert run_hook(payload(tmp_path), monkeypatch) == (0, "")
    assert pending.entries(pending.read_state("edit", "s")) == []


def test_the_trace_records_whole_paths_for_bash_writes(tmp_path, monkeypatch):
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    (tmp_path / "x.py").write_text(DIRTY)
    run_hook(payload(tmp_path), monkeypatch)
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["files"] == [str(tmp_path / "x.py")]
