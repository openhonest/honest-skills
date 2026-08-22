"""What the trace records, and what the hook says about itself.

Both questions came from the same failure on 2026-08-21: the trace was asked
whether the edit hook fired several times on one file in one turn, and it could
answer neither when nor on what.
"""
import importlib.util
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
    trace_hook.trace("E", "fired", "why")
    row = json.loads(log.read_text())
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", row["ts"])
