"""What the trace records, and what the hook says about itself.

Both questions came from the same failure on 2026-08-21: the trace was asked
whether the edit hook fired several times on one file in one turn, and it could
answer neither when nor on what.
"""
import importlib.util
import os
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "trace_hook", ROOT / "hooks" / "trace_hook.py")
trace_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trace_hook)




# --- the hook says which version it is ---------------------------------------

def test_a_source_tree_says_nothing_about_its_version(monkeypatch):
    """Run from a checkout there is no version to name, and a hook that cannot
    tell says nothing rather than guessing it is current."""
    monkeypatch.setattr(trace_hook, "__file__", "/src/honest-skills/hooks/x.py")
    assert trace_hook.running_version() == ""
    assert trace_hook.stale_note() == ""


def test_an_installed_hook_reads_its_version_out_of_its_own_path(monkeypatch):
    monkeypatch.setattr(
        trace_hook, "__file__",
        "/c/honest-skills/honest-skills/0.13.1/hooks/trace_hook.py")
    assert trace_hook.running_version() == "0.13.1"


def test_a_stale_session_is_told_which_version_it_is_missing(tmp_path, monkeypatch):
    """A session runs whatever was registered when it launched, so it can run a
    version several releases old with nothing saying so. Adam asked on
    2026-08-21 why the hook did not simply report this."""
    home = tmp_path / "home"; (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"honest-skills@m": [{"version": "0.22.0"}]}}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        trace_hook, "__file__",
        "/c/honest-skills/honest-skills/0.13.1/hooks/trace_hook.py")
    note = trace_hook.stale_note()
    assert "0.13.1" in note and "0.22.0" in note and "Restart" in note


def test_a_current_session_is_told_nothing(tmp_path, monkeypatch):
    home = tmp_path / "home"; (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"honest-skills@m": [{"version": "0.22.0"}]}}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        trace_hook, "__file__",
        "/c/honest-skills/honest-skills/0.22.0/hooks/trace_hook.py")
    assert trace_hook.stale_note() == ""


def test_an_unreadable_registry_says_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "empty"))
    monkeypatch.setattr(
        trace_hook, "__file__",
        "/c/honest-skills/honest-skills/0.13.1/hooks/trace_hook.py")
    assert trace_hook.stale_note() == ""


def test_a_registry_naming_no_version_says_nothing(tmp_path, monkeypatch):
    home = tmp_path / "home"; (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"honest-skills@m": [{}], "other@m": []}}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        trace_hook, "__file__",
        "/c/honest-skills/honest-skills/0.13.1/hooks/trace_hook.py")
    assert trace_hook.stale_note() == ""


def test_every_row_carries_the_time_it_was_written(tmp_path, monkeypatch):
    """Without it the trace cannot answer when, which is the question it was
    first asked and could not answer on 2026-08-21."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    armed_trace("E", "fired", "why")
    row = json.loads(log.read_text())
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", row["ts"])


def test_every_row_says_which_session_and_version_wrote_it(tmp_path, monkeypatch):
    """Rows from every session share one file. Without these two fields there
    was no way to tell whether a session that had not restarted was running the
    new hooks, and the answer had to come from an experiment.

    The session comes from the hook's own input. It used to be read from
    CLAUDE_SESSION_ID, which is never set, so every row said "" while the state
    file read the same fact from the input and worked."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    trace_hook.note_session(json.dumps({"session_id": "abcdef1234567890"}))
    monkeypatch.setattr(
        trace_hook, "__file__",
        "/c/honest-skills/honest-skills/0.23.0/hooks/trace_hook.py")
    armed_trace("E", "fired", "why")
    row = json.loads(log.read_text())
    assert row["session"] == "abcdef12" and row["version"] == "0.23.0"


def test_a_row_written_outside_a_session_still_records(tmp_path, monkeypatch):
    """Run by hand there is no session id, and an empty field is better than a
    refusal to write."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    trace_hook.note_session("{}")
    armed_trace("E", "fired", "why")
    assert json.loads(log.read_text())["session"] == ""


def test_a_run_with_no_session_in_its_input_records_none(tmp_path, monkeypatch):
    """Run by hand there is no session, and an empty field is honest where a
    guess would not be."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    trace_hook.note_session("not json at all")
    armed_trace("E", "fired", "why")
    assert json.loads(log.read_text())["session"] == ""


def test_the_session_is_not_read_from_the_environment(tmp_path, monkeypatch):
    """CLAUDE_SESSION_ID is never set for a hook. Reading it there is what made
    every row since the field was added say nothing."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "from-the-environment")
    trace_hook.note_session(json.dumps({"session_id": "from-the-input"}))
    armed_trace("E", "fired", "why")
    assert json.loads(log.read_text())["session"] == "from-the"


def test_one_file_is_one_key_whatever_the_working_directory(tmp_path, monkeypatch):
    """The same file arrived as a relative path and as an absolute one within
    two hours, and every consumer keys on the string. One file read as two, and
    a rule standing on one file read as standing on two."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    target = tmp_path / "sub" / "a.py"
    target.parent.mkdir()
    target.write_text("x = 1\n")
    monkeypatch.chdir(tmp_path)
    armed_trace("Stop:edit", "declined", "clean", file="sub/a.py")
    armed_trace("Stop:edit", "declined", "clean", file=str(target))
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert rows[0]["file"] == rows[1]["file"] == os.path.realpath(str(target))


def armed_trace(*a, **kw):
    """trace() as a hook calls it: with the record armed by a firing.

    The trace holds hook firings. Calling trace() without one writes nothing,
    which is what stopped a hand-run probe from inflating a standing count in
    the live file. Arms the flag alone and leaves SESSION as the test set it.
    """
    trace_hook.FIRED = True
    return trace_hook.trace(*a, **kw)


def test_a_call_outside_a_hook_firing_writes_nothing(tmp_path, monkeypatch):
    """The trace is a record of hook firings, and it used to record anything at
    all that called trace(). The test suite wrote 223 rows per run and every
    fire rate read off the file for a day was contaminated; that was patched by
    redirecting the trace in conftest, which fixed the tests and left the shape
    alone. Four days later a probe run by hand put its own rows in the live file
    and inflated a standing count. Twice is the architecture."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setattr(trace_hook, "FIRED", False)
    trace_hook.trace("Stop:edit", "fired", "a probe, not a firing")
    assert not log.exists()
    trace_hook.note_session('{"session_id": "abcdefgh"}')
    trace_hook.trace("Stop:edit", "fired", "a firing")
    assert json.loads(log.read_text())["why"] == "a firing"
