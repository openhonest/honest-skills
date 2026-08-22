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
    assert pending.read_state("edit", "s") == {"pending": [], "reported": {}}


def test_absent_state_is_treated_as_empty():
    assert pending.read_state("edit", "never") == {"pending": [], "reported": {}}


def test_state_of_the_wrong_shape_is_treated_as_empty():
    pending.state_file("edit", "s").parent.mkdir(parents=True, exist_ok=True)
    pending.state_file("edit", "s").write_text('{"pending": 3, "reported": "no"}')
    assert pending.read_state("edit", "s") == {"pending": [], "reported": {}}


def test_a_path_deferred_twice_is_held_once():
    pending.defer("edit", "/a.py", "s")
    pending.defer("edit", "/a.py", "s")
    assert pending.read_state("edit", "s")["pending"] == ["/a.py"]


def test_two_hooks_do_not_clear_each_others_pending_writes():
    """Whichever ran first at Stop would clear a shared list, and the second
    would find nothing to assess."""
    pending.defer("edit", "/a.py", "s")
    pending.defer("stub", "/a.py", "s")
    pending.write_state("edit", "s", {"pending": [], "reported": {}})
    assert pending.read_state("stub", "s")["pending"] == ["/a.py"]


def test_an_unwritable_state_directory_does_not_raise(monkeypatch):
    monkeypatch.setenv("HONEST_PENDING_DIR", "/dev/null/nope")
    pending.defer("edit", "/a.py", "s")        # must not raise
    assert pending.read_state("edit", "s") == {"pending": [], "reported": {}}
