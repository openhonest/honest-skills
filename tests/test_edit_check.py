"""Tests for the PostToolUse hook.

The hook's whole value is that it says nothing when a file is fine. That
property is the one most likely to break silently, so most of these assert
silence rather than output.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "edit_check", ROOT / "hooks" / "edit_check.py")
edit_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(edit_check)

CLEAN = "def f(x):\n    return x + 1\n"


def payload(path, session="s1"):
    return json.dumps({"session_id": session, "tool_name": "Write",
                       "tool_input": {"file_path": str(path)}})


def run_hook(raw, monkeypatch):
    """Run main() with stdin replaced, returning (exit_code, stderr)."""
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(sys, "stderr", err)
    code = edit_check.main()
    return code, err.getvalue()


# --- silence, which is the point --------------------------------------------

def test_a_clean_file_produces_no_output_at_all(tmp_path, monkeypatch):
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    monkeypatch.setattr(edit_check, "analyzer_finding", lambda p, s: None)
    code, err = run_hook(payload(f), monkeypatch)
    assert (code, err) == (0, "")


def test_exit_zero_is_the_silent_path(tmp_path, monkeypatch):
    """Exit 0 sends stdout to the debug log and shows it to nobody, so the
    hook must return 0 and print nothing rather than printing a tick."""
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    monkeypatch.setattr(edit_check, "analyzer_finding", lambda p, s: None)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload(f)))
    with redirect_stdout(out):
        code = edit_check.main()
    assert code == 0 and out.getvalue() == ""


@pytest.mark.parametrize("name", ["notes.md", "data.json", "uv.lock", "x.yaml"])
def test_non_source_files_are_not_checked(tmp_path, monkeypatch, name):
    """A hook that fires on lock files and prose fires constantly."""
    f = tmp_path / name; f.write_text("trailing   \n" * 50)
    code, err = run_hook(payload(f), monkeypatch)
    assert (code, err) == (0, "")


def test_an_unreadable_path_is_not_a_finding(tmp_path, monkeypatch):
    """The file being gone says nothing about the code, and a hook that
    complains about it teaches the reader to ignore hooks."""
    code, err = run_hook(payload(tmp_path / "absent.py"), monkeypatch)
    assert (code, err) == (0, "")


def test_malformed_hook_input_does_nothing(monkeypatch):
    code, err = run_hook("not json at all", monkeypatch)
    assert (code, err) == (0, "")


def test_missing_file_path_does_nothing(monkeypatch):
    code, err = run_hook(json.dumps({"tool_input": {}}), monkeypatch)
    assert (code, err) == (0, "")


# --- what does surface ------------------------------------------------------

def test_an_over_long_file_surfaces_on_stderr_with_exit_2(tmp_path, monkeypatch):
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    monkeypatch.setattr(edit_check, "analyzer_finding", lambda p, s: None)
    code, err = run_hook(payload(f), monkeypatch)
    assert code == 2
    assert "L1.17" in err and "1001 lines" in err


def test_a_file_at_the_limit_is_silent(tmp_path, monkeypatch):
    f = tmp_path / "edge.py"; f.write_text("x = 1\n" * 1000)
    monkeypatch.setattr(edit_check, "analyzer_finding", lambda p, s: None)
    assert run_hook(payload(f), monkeypatch) == (0, "")


def test_trailing_whitespace_over_the_band_surfaces(tmp_path, monkeypatch):
    lines = ["x = 1   "] * 10 + ["y = 2"] * 90
    f = tmp_path / "ws.py"; f.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(edit_check, "analyzer_finding", lambda p, s: None)
    code, err = run_hook(payload(f), monkeypatch)
    assert code == 2 and "L1.16" in err and "10.0%" in err


def test_trailing_whitespace_inside_the_band_is_silent(tmp_path, monkeypatch):
    lines = ["x = 1   "] * 2 + ["y = 2"] * 98
    f = tmp_path / "ws.py"; f.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(edit_check, "analyzer_finding", lambda p, s: None)
    assert run_hook(payload(f), monkeypatch) == (0, "")


def test_every_finding_carries_an_action(tmp_path, monkeypatch):
    """A verdict the reader cannot act on is a complaint."""
    f = tmp_path / "big.py"; f.write_text("x = 1   \n" * 1001)
    monkeypatch.setattr(edit_check, "analyzer_finding", lambda p, s: None)
    for finding in edit_check.findings_for(str(f), f.read_text(), "s"):
        assert finding["action"]


# --- the delegated indicator ------------------------------------------------

def test_a_missing_analyzer_is_unmeasured_not_a_pass(tmp_path, monkeypatch):
    """"Not checked" must never read as "passed"."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: None)
    monkeypatch.setattr(edit_check, "already_told", lambda s: False)
    f = edit_check.analyzer_finding(str(tmp_path / "x.py"), "fresh")
    assert f["verdict"] == "UNMEASURED" and "not on PATH" in f["detail"]


def test_the_missing_analyzer_is_reported_once_per_session(tmp_path, monkeypatch):
    """Repeating a fact the reader cannot act on differently is how an alarm
    becomes wallpaper."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: None)
    session = "once-" + tempfile.mktemp(prefix="", dir="").replace("/", "")
    first = edit_check.analyzer_finding(str(tmp_path / "x.py"), session)
    second = edit_check.analyzer_finding(str(tmp_path / "y.py"), session)
    assert first is not None and second is None


def test_the_hook_never_reimplements_the_mutable_state_ratio():
    """The authoritative definition lives in the Honest Framework with its
    bound-literal amendment. A second implementation under the same name is
    how two tools come to disagree while both claiming the standard."""
    src = (ROOT / "hooks" / "edit_check.py").read_text()
    assert "import ast" not in src
    assert edit_check.ANALYZER in src


def test_a_healthy_band_from_the_analyzer_is_silent(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", lambda *a, **k: type(
        "R", (), {"stdout": json.dumps({"results": {"L1.18": {"band": "Healthy", "value": 3.0}}})})())
    assert edit_check.analyzer_finding("x.py", "s") is None


def test_a_slop_band_from_the_analyzer_surfaces_with_its_caveat(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", lambda *a, **k: type(
        "R", (), {"stdout": json.dumps({"results": {"L1.18": {"band": "Slop", "value": 66.7}}})})())
    f = edit_check.analyzer_finding("x.py", "s")
    assert f["verdict"] == "OUT_OF_SPEC" and "66.7" in f["detail"]
    assert "provisional" in f["caveat"]


def test_an_unparseable_analyzer_response_is_unmeasured(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", lambda *a, **k: type(
        "R", (), {"stdout": "not json"})())
    assert edit_check.analyzer_finding("x.py", "s")["verdict"] == "UNMEASURED"


def test_an_analyzer_with_no_verdict_is_unmeasured(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", lambda *a, **k: type(
        "R", (), {"stdout": json.dumps({"results": {}})})())
    assert edit_check.analyzer_finding("x.py", "s")["verdict"] == "UNMEASURED"


def test_an_analyzer_that_will_not_run_is_unmeasured(monkeypatch):
    def boom(*a, **k):
        raise OSError("no")
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", boom)
    assert edit_check.analyzer_finding("x.py", "s")["verdict"] == "UNMEASURED"


# --- run it the way Claude Code does ----------------------------------------

def test_the_hook_runs_as_a_subprocess_and_is_silent_on_a_clean_file(tmp_path):
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    p = subprocess.run([sys.executable, str(ROOT / "hooks" / "edit_check.py")],
                       input=payload(f), capture_output=True, text=True)
    assert p.returncode in (0, 2)      # 2 only if the analyzer is absent this session
    if p.returncode == 0:
        assert p.stdout == "" and p.stderr == ""


def test_the_hook_runs_as_a_subprocess_and_exits_2_on_a_finding(tmp_path):
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    p = subprocess.run([sys.executable, str(ROOT / "hooks" / "edit_check.py")],
                       input=payload(f), capture_output=True, text=True)
    assert p.returncode == 2
    assert "L1.17" in p.stderr
    assert p.stdout == ""


def test_the_hook_is_fast_enough_to_sit_in_an_edit_loop(tmp_path):
    """Slow is the same as absent for a tool that runs on every write."""
    import time
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    start = time.monotonic()
    subprocess.run([sys.executable, str(ROOT / "hooks" / "edit_check.py")],
                   input=payload(f), capture_output=True, text=True)
    assert time.monotonic() - start < 2.0


# --- the branches the first pass missed --------------------------------------

def test_an_empty_file_has_no_whitespace_finding(tmp_path):
    """Dividing by zero lines is the obvious way this crashes on a new file."""
    assert edit_check.whitespace_finding("") is None


def test_no_session_id_suppresses_the_once_per_session_notice():
    """Without a session there is nowhere to record that we already said it,
    so saying nothing beats saying it on every write."""
    assert edit_check.already_told("") is True


def test_an_unwritable_marker_directory_suppresses_the_notice(monkeypatch):
    def boom(*a, **k):
        raise OSError("read-only")
    monkeypatch.setattr(edit_check.Path, "exists", lambda self: False)
    monkeypatch.setattr(edit_check.Path, "touch", boom)
    assert edit_check.already_told("s2") is True


def test_the_caveat_is_rendered_when_present():
    """The provisional-threshold note is the honest part of an L1.18 finding
    and it must reach the reader, not just the dict."""
    out = edit_check.render("a/b.py", [{
        "indicator": "L1.18", "verdict": "OUT_OF_SPEC",
        "detail": "ratio 66.7", "action": "move it",
        "caveat": "this threshold is provisional"}])
    assert "note: this threshold is provisional" in out
    assert "b.py" in out and "a/b.py" not in out
