"""Holding a turn's writes until the files stop moving.

The state this module keeps must never be able to break the writes it serves,
so every failure to read or record it is a reason to do nothing rather than to
complain.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "pending", ROOT / "hooks" / "pending.py")
pending = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pending)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "pending"))


def test_a_session_id_that_is_not_given_falls_back_to_one_shared_list():
    assert pending.session_key('{"tool_input": {}}') == "shared"
    assert pending.session_key("not json") == "shared"
    assert pending.session_key('{"session_id": null}') == "shared"


def test_a_session_id_cannot_escape_the_state_directory():
    """The id names a file. Left unfiltered it could name any file."""
    assert pending.session_key('{"session_id": "../../etc/passwd"}') == "etcpasswd"
    assert pending.session_key('{"session_id": "///"}') == "shared"


def test_unreadable_state_is_treated_as_empty():
    pending.state_file("edit", "s").parent.mkdir(parents=True, exist_ok=True)
    pending.state_file("edit", "s").write_text("{not json")
    assert pending.read_state("edit", "s") == {"pending": [], "reported": {}, "said_of": []}


def test_absent_state_is_treated_as_empty():
    assert pending.read_state("edit", "never") == {"pending": [], "reported": {}, "said_of": []}


def test_state_of_the_wrong_shape_is_treated_as_empty():
    pending.state_file("edit", "s").parent.mkdir(parents=True, exist_ok=True)
    pending.state_file("edit", "s").write_text('{"pending": 3, "reported": "no"}')
    assert pending.read_state("edit", "s") == {"pending": [], "reported": {}, "said_of": []}


def test_a_path_deferred_twice_is_held_once():
    pending.defer("edit", "/a.py", "s")
    pending.defer("edit", "/a.py", "s")
    held = pending.entries(pending.read_state("edit", "s"))
    assert [e["path"] for e in held] == ["/a.py"]


def test_two_hooks_do_not_clear_each_others_pending_writes():
    """Whichever ran first at Stop would clear a shared list, and the second
    would find nothing to assess."""
    pending.defer("edit", "/a.py", "s")
    pending.defer("stub", "/a.py", "s")
    pending.write_state("edit", "s", {"pending": [], "reported": {}})
    held = pending.entries(pending.read_state("stub", "s"))
    assert [e["path"] for e in held] == ["/a.py"]


def test_an_unwritable_state_directory_does_not_raise(monkeypatch):
    monkeypatch.setenv("HONEST_PENDING_DIR", "/dev/null/nope")
    pending.defer("edit", "/a.py", "s")        # must not raise
    assert pending.read_state("edit", "s") == {"pending": [], "reported": {}, "said_of": []}


# --- writes nothing is coming back for ---------------------------------------

def test_a_write_from_an_older_version_is_read_as_held_since_forever():
    """0.22.0 and 0.23.0 wrote bare strings. Anything they stranded must drain
    on the next write rather than sit in the file for good."""
    pending.state_file("edit", "s").parent.mkdir(parents=True, exist_ok=True)
    pending.state_file("edit", "s").write_text(
        '{"pending": ["/a.py"], "reported": {}}')
    assert pending.entries(pending.read_state("edit", "s")) == [
        {"path": "/a.py", "at": 0.0}]


def test_an_entry_of_the_wrong_shape_is_dropped_rather_than_raised_on():
    pending.state_file("edit", "s").parent.mkdir(parents=True, exist_ok=True)
    pending.state_file("edit", "s").write_text(
        '{"pending": [3, {"at": 1}, {"path": "/ok.py"}], "reported": {}}')
    assert [e["path"] for e in
            pending.entries(pending.read_state("edit", "s"))] == ["/ok.py"]


def test_a_write_just_made_is_not_stranded(tmp_path):
    f = tmp_path / "a.py"; f.write_text("x = 1\n")
    pending.defer("edit", str(f), "s")
    assert pending.stranded("edit", "s") == []


def test_a_write_held_past_the_wait_is_stranded(tmp_path, monkeypatch):
    """The Stop hook is registered when a session starts. A session whose
    registration predates the hook being added to Stop still runs the current
    scripts, so it defers every write and settles none, and the hook goes
    silently dead."""
    f = tmp_path / "a.py"; f.write_text("x = 1\n")
    import os, time
    old = time.time() - pending.STALE_AFTER - 60
    os.utime(f, (old, old))
    pending.write_state("edit", "s", {"pending": [{"path": str(f), "at": old}],
                                      "reported": {}})
    assert pending.stranded("edit", "s") == [str(f)]


def test_a_file_still_being_edited_is_not_stranded(tmp_path):
    """The wait is only over when the file has stopped moving too. A long turn
    that keeps touching one file is still a long turn."""
    import time
    f = tmp_path / "a.py"; f.write_text("x = 1\n")          # mtime is now
    old = time.time() - pending.STALE_AFTER - 60
    pending.write_state("edit", "s", {"pending": [{"path": str(f), "at": old}],
                                      "reported": {}})
    assert pending.stranded("edit", "s") == []


def test_dropping_keeps_the_writes_that_are_still_waiting(tmp_path):
    pending.defer("edit", "/a.py", "s")
    pending.defer("edit", "/b.py", "s")
    pending.drop("edit", "s", ["/a.py"])
    assert [e["path"] for e in
            pending.entries(pending.read_state("edit", "s"))] == ["/b.py"]


def test_a_pending_file_that_is_gone_drains_rather_than_sitting_forever():
    """Skipping it meant only a Stop firing could remove it, so a session that
    ended without one left the path in the file for good. Ten such paths were
    sitting under the shared fallback key, which a live hook reads whenever no
    session id is given."""
    import time
    old = time.time() - pending.STALE_AFTER - 60
    pending.write_state("edit", "s", {"pending": [{"path": "/nope.py", "at": old}],
                                      "reported": {}})
    assert pending.stranded("edit", "s") == ["/nope.py"]
    pending.drop("edit", "s", ["/nope.py"])
    assert pending.entries(pending.read_state("edit", "s")) == []


def test_state_written_during_a_settle_is_not_overwritten_by_stale_state():
    """A settle captured said_of before its loop and wrote it back after, so a
    language announced during the turn was announced again on the next one.
    Read-modify-write across a loop that also writes."""
    pending.write_state("edit", "s", {"pending": [], "reported": {},
                                      "said_of": [".js"]})
    assert pending.read_state("edit", "s")["said_of"] == [".js"]


def test_every_read_returns_the_same_keys(tmp_path, monkeypatch):
    """Two return paths and one missing a key is how `said_of` reached some
    callers and not others within a minute of being added."""
    absent = pending.read_state("edit", "never-written")
    pending.state_file("edit", "bad").parent.mkdir(parents=True, exist_ok=True)
    pending.state_file("edit", "bad").write_text("{not json")
    pending.state_file("edit", "list").write_text("[1, 2]")
    pending.write_state("edit", "good", {"pending": [], "reported": {}})
    keys = {frozenset(pending.read_state("edit", k))
            for k in ("never-written", "bad", "list", "good")}
    assert keys == {frozenset(absent)}
