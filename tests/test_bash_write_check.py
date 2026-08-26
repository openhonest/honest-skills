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
    assert bw.recently_written(str(tmp_path), 120)[0] == [str(tmp_path / "x.py")]


def test_a_file_written_long_ago_is_not_this_command(tmp_path):
    f = tmp_path / "old.py"; f.write_text(CLEAN)
    os.utime(f, (time.time() - 600, time.time() - 600))
    assert bw.recently_written(str(tmp_path), 120)[0] == []


@pytest.mark.parametrize("d", [".git", "node_modules", ".venv", "__pycache__", "target"])
def test_generated_and_vendored_trees_are_skipped(tmp_path, d):
    """A checkout moves every file in .git and none of it is someone editing."""
    sub = tmp_path / d; sub.mkdir()
    (sub / "x.py").write_text(DIRTY)
    assert bw.recently_written(str(tmp_path), 120)[0] == []


def test_a_file_type_it_does_not_check_is_not_collected(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    assert bw.recently_written(str(tmp_path), 120)[0] == []


def test_markdown_written_by_a_script_is_collected(tmp_path):
    """It was not, until 2026-08-25. The wrap rule ran on Write and Edit only,
    and a session that writes its files through shell heredocs had never had it
    applied once. This test used to assert the opposite, which is why the gap
    survived a day of people looking straight at it."""
    (tmp_path / "notes.md").write_text("hello")
    assert bw.recently_written(str(tmp_path), 120)[0] == [str(tmp_path / "notes.md")]


def test_prose_is_not_handed_to_the_stub_check(tmp_path, monkeypatch):
    """The stub check reads code. Handed prose it finds nothing, and a check
    that runs on what it cannot read reports a pass it did not perform."""
    import pending
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "pending"))
    (tmp_path / "notes.md").write_text("hello")
    run_hook(json.dumps({"tool_name": "Bash", "cwd": str(tmp_path),
                         "session_id": "prose1"}), monkeypatch)
    held = [e["path"] for e in pending.entries(pending.read_state("edit", "prose1"))]
    assert str(tmp_path / "notes.md") in held
    assert pending.entries(pending.read_state("stub", "prose1")) == []


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
                        lambda p, d=None: {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
                                   "detail": "d", "action": "a"})
    assert run_hook(payload(tmp_path), monkeypatch) == (0, "")
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s"}'))
    monkeypatch.setattr(sys, "stderr", err)
    assert bw.edit_check.main() == 2 and "L1.21" in err.getvalue()


def test_a_clean_file_is_silent(tmp_path, monkeypatch):
    (tmp_path / "x.py").write_text(CLEAN)
    monkeypatch.setattr(bw.edit_check, "honest_code_finding", lambda p, d=None: None)
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
    assert bw.recently_written(str(tmp_path), 120)[0] == []


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


# --- what moved since the last look, not in a fixed window -------------------

def test_a_session_editing_the_same_files_is_not_read_as_a_build(
        tmp_path, monkeypatch):
    """A fixed window is cumulative. A session editing nine files over two
    minutes has all nine inside a 120-second window at once, so every Bash call
    it makes reads as a build and is discarded. That happened 31 times in one
    37-minute trace, always at exactly nine files, and that session was getting
    no coverage at all with nothing saying so."""
    for i in range(9):
        (tmp_path / f"f{i}.py").write_text(CLEAN)
    assert run_hook(payload(tmp_path), monkeypatch) == (0, "")   # first look
    held_first = len(pending.entries(pending.read_state("edit", "s")))
    # The nine were edited over the preceding minutes, which is what put them
    # all inside one fixed window and made the session look like a build.
    old = time.time() - 90
    for i in range(9):
        os.utime(tmp_path / f"f{i}.py", (old, old))
    (tmp_path / "f0.py").write_text(CLEAN + "# touched\n")       # one file moves
    run_hook(payload(tmp_path), monkeypatch)
    held = [e["path"] for e in pending.entries(pending.read_state("edit", "s"))]
    assert held_first == 0                    # nine at once still reads as a build
    assert held == [str(tmp_path / "f0.py")]  # one since the last look does not


def test_the_first_look_of_a_session_uses_the_plain_window(tmp_path, monkeypatch):
    """With nothing to compare against there is no since, and a session must
    not start blind."""
    assert bw.since_last_look("brand-new") == bw.WINDOW


def test_the_second_look_measures_from_the_first(tmp_path, monkeypatch):
    bw.since_last_look("s")
    got = bw.since_last_look("s")
    assert 1.0 <= got < bw.WINDOW


# --- a walk it cannot finish is not a shorter answer --------------------------

def test_a_tree_too_large_to_sweep_reports_nothing(tmp_path, monkeypatch):
    """A session whose working directory was the home tree made this hook walk
    everything on every Bash command: 26 seconds measured, against 2
    milliseconds from inside a repository."""
    monkeypatch.setattr(bw, "DIR_BUDGET", 2)
    for i in range(6):
        d = tmp_path / f"d{i}"; d.mkdir()
        (d / "x.py").write_text(DIRTY)
    found, finished = bw.recently_written(str(tmp_path), 120)
    assert not finished


def test_an_unfinished_sweep_says_nothing_rather_than_something(
        tmp_path, monkeypatch):
    """Returning what it found would report a partial sweep as a complete one,
    which is the defect this whole tool exists to report."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setattr(bw, "DIR_BUDGET", 1)
    for i in range(4):
        d = tmp_path / f"d{i}"; d.mkdir()
        (d / "x.py").write_text(DIRTY)
    assert run_hook(payload(tmp_path), monkeypatch) == (0, "")
    assert pending.entries(pending.read_state("edit", "s")) == []
    assert any("too large to sweep" in json.loads(l)["why"]
               for l in log.read_text().splitlines())


def test_a_walk_that_finishes_still_reports_normally(tmp_path, monkeypatch):
    (tmp_path / "x.py").write_text(DIRTY)
    found, finished = bw.recently_written(str(tmp_path), 120)
    assert finished and found == [str(tmp_path / "x.py")]


def test_the_trees_that_are_never_source_are_skipped(tmp_path):
    """Between them these were the reason a session rooted at the home
    directory took 26 seconds per Bash command. Library alone holds 134,860 of
    that tree's 166,779 directories; the whole of ~/dev is 12,863."""
    for name in ("Library", "go", "Applications", "Downloads"):
        d = tmp_path / name; d.mkdir()
        (d / "x.py").write_text(DIRTY)
    found, finished = bw.recently_written(str(tmp_path), 120)
    assert finished and found == []
