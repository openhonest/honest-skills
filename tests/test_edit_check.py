"""Tests for the PostToolUse hook.

The hook's whole value is that it says nothing when there is nothing to say.
That property is the one most likely to break silently, so most of these assert
silence rather than output.

The second group asserts the rule that replaced the first design: an absence is
not a finding about your file, and a findings list that does not state its
coverage is claiming to be complete.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "edit_check", ROOT / "hooks" / "edit_check.py")
edit_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(edit_check)

CLEAN = "def f(x):\n    return x + 1\n"
NO_ANALYZER = {"indicator": "L1.21", "verdict": "NOT_RUN",
               "detail": "slop-audit-l1 is not on PATH",
               "action": "this file was not checked against the Honest Code clauses"}


def payload(path):
    return json.dumps({"session_id": "s1", "tool_name": "Write",
                       "tool_input": {"file_path": str(path)}})


def run_hook(raw, monkeypatch):
    """Run main() with stdin replaced, returning (exit_code, stderr)."""
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(sys, "stderr", err)
    return edit_check.main(), err.getvalue()


def no_analyzer(monkeypatch):
    """The state of every fresh install: the plugin is there, the binary is not."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: None)


def no_delegates(monkeypatch):
    """Silence the one subprocess check, for tests about the local two."""
    monkeypatch.setattr(edit_check, "honest_code_finding", lambda p: None)


# --- silence, which is the point --------------------------------------------

def test_a_clean_file_produces_no_output_at_all(tmp_path, monkeypatch):
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    no_delegates(monkeypatch)
    assert run_hook(payload(f), monkeypatch) == (0, "")


def test_a_fresh_install_is_silent_on_its_first_write(tmp_path, monkeypatch):
    """The defect this replaced. A user installed the plugin, edited a file,
    and the first thing the tool said was that a check it wanted was missing.
    It was reporting on itself and labelling it a finding about the file."""
    no_analyzer(monkeypatch)
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    assert run_hook(payload(f), monkeypatch) == (0, "")


def test_it_stays_silent_however_many_times_you_write(tmp_path, monkeypatch):
    """The old design fired once per session and kept a marker file to enforce
    it. The notice should not have been firing at all, so both are gone."""
    no_analyzer(monkeypatch)
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    for _ in range(5):
        assert run_hook(payload(f), monkeypatch) == (0, "")


def test_exit_zero_is_the_silent_path(tmp_path, monkeypatch):
    """Exit 0 sends stdout to the debug log and shows it to nobody, so the
    hook must return 0 and print nothing rather than printing a tick."""
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    no_delegates(monkeypatch)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload(f)))
    with redirect_stdout(out):
        code = edit_check.main()
    assert code == 0 and out.getvalue() == ""


@pytest.mark.parametrize("name", ["notes.md", "data.json", "uv.lock", "x.yaml"])
def test_non_source_files_are_not_checked(tmp_path, monkeypatch, name):
    """A hook that fires on lock files and prose fires constantly."""
    f = tmp_path / name; f.write_text("trailing   \n" * 50)
    assert run_hook(payload(f), monkeypatch) == (0, "")


def test_an_unreadable_path_is_not_a_finding(tmp_path, monkeypatch):
    """The file being gone says nothing about the code, and a hook that
    complains about it teaches the reader to ignore hooks."""
    assert run_hook(payload(tmp_path / "absent.py"), monkeypatch) == (0, "")


def test_malformed_hook_input_does_nothing(monkeypatch):
    assert run_hook("not json at all", monkeypatch) == (0, "")


def test_missing_file_path_does_nothing(monkeypatch):
    assert run_hook(json.dumps({"tool_input": {}}), monkeypatch) == (0, "")


# --- an absence is only worth saying alongside a presence -------------------

def test_a_real_finding_carries_the_absence_with_it(tmp_path, monkeypatch):
    """Silent alone, reported alongside. The reader is about to act on a list,
    so the list has to say what it did not look at."""
    no_analyzer(monkeypatch)
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    code, err = run_hook(payload(f), monkeypatch)
    assert code == 2
    assert "L1.17" in err and "NOT_RUN" in err and "L1.21" in err


def test_every_report_states_its_coverage_before_its_content(tmp_path, monkeypatch):
    """A findings list with no coverage stated is a list claiming to be
    complete."""
    no_analyzer(monkeypatch)
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    first = run_hook(payload(f), monkeypatch)[1].splitlines()[0]
    assert first == "honest-code: 2 of 3 checks ran on big.py"


def test_coverage_counts_checks_that_ran_not_findings_that_fired():
    """A check that ran and passed leaves no finding, so counting the findings
    counted it as not having run. That reported "1 of 3" when two had."""
    out = edit_check.render("a/big.py", [
        {"indicator": "L1.17", "verdict": "OUT_OF_SPEC", "detail": "d",
         "action": "a"},
        dict(NO_ANALYZER)])
    assert out.splitlines()[0].startswith("honest-code: 2 of 3")


def test_full_coverage_says_three_of_three():
    out = edit_check.render("a/big.py", [
        {"indicator": "L1.17", "verdict": "OUT_OF_SPEC", "detail": "d",
         "action": "a"}])
    assert out.splitlines()[0].startswith("honest-code: 3 of 3")


def test_findings_for_keeps_the_checks_that_did_not_run(tmp_path, monkeypatch):
    """Suppressing them here would make the coverage count impossible, and the
    count is the whole of the honesty."""
    no_analyzer(monkeypatch)
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    got = edit_check.findings_for(str(f), CLEAN)
    assert [g["verdict"] for g in got] == ["NOT_RUN"]
    assert {g["indicator"] for g in got} == {"L1.21"}


def test_no_report_ever_claims_the_file_passed():
    """Silence means nothing surfaced. A tick would mean checked and passed,
    and a hook running 3 of 20 indicators is not in a position to say that.

    Scanned in the output rather than the source, because "clean" appears in
    the source as a band name the analyzer returns, which the first version of
    this test could not tell from a claim the hook was making."""
    shapes = [
        [dict(NO_ANALYZER)],
        [{"indicator": "L1.17", "verdict": "OUT_OF_SPEC", "detail": "d",
          "action": "a"}],
        [{"indicator": "L1.16", "verdict": "OUT_OF_SPEC", "detail": "d",
          "action": "a"}, dict(NO_ANALYZER)],
    ]
    for findings in shapes:
        out = edit_check.render("a/b.py", findings).lower()
        for claim in ("clean", "passed", "✓", "all good", "no issues"):
            assert claim not in out, (claim, out)


def test_every_report_opens_on_coverage_not_on_a_verdict():
    """The reader learns what was examined before what was found, so the list
    can never be taken for a complete one."""
    for findings in ([dict(NO_ANALYZER)],
                     [{"indicator": "L1.17", "verdict": "OUT_OF_SPEC",
                       "detail": "d", "action": "a"}]):
        assert edit_check.render("b.py", findings).startswith("honest-code: ")
        assert "checks ran on" in edit_check.render("b.py", findings)
def test_the_hook_runs_as_a_subprocess_and_is_silent_on_a_clean_file(tmp_path):
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    p = subprocess.run([sys.executable, str(ROOT / "hooks" / "edit_check.py")],
                       input=payload(f), capture_output=True, text=True)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


def test_the_hook_runs_as_a_subprocess_and_exits_2_on_a_finding(tmp_path):
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    p = subprocess.run([sys.executable, str(ROOT / "hooks" / "edit_check.py")],
                       input=payload(f), capture_output=True, text=True)
    assert p.returncode == 2 and "L1.17" in p.stderr and p.stdout == ""


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


def test_the_caveat_is_rendered_when_present():
    """The provisional-threshold note is the honest half of an L1.18 finding
    and it must reach the reader, not just the dict."""
    out = edit_check.render("a/b.py", [{
        "indicator": "L1.18", "verdict": "OUT_OF_SPEC",
        "detail": "ratio 66.7", "action": "move it",
        "caveat": "this threshold is provisional"}])
    assert "note: this threshold is provisional" in out
    assert "b.py" in out and "a/b.py" not in out


# --- L1.21, the Honest Code clauses -----------------------------------------

def fake_honest(payload):
    return lambda *a, **k: type("R", (), {"stdout": json.dumps(payload)})()


def test_a_clean_file_produces_no_honest_code_finding(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [{"code": "L1.21.1", "decided": True, "findings": []}],
         "decided_clauses": 1, "unreadable_reason": ""}))
    assert edit_check.honest_code_finding("x.py") is None


def test_a_violation_carries_its_clause_line_and_remedy(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [{"code": "L1.21.14", "decided": True, "findings": [
            {"clause": "L1.21.14", "line": 5,
             "detail": "`timeout=30` absorbs the caller's omission",
             "instead": "make absence an explicit case of a bounded type"}]}],
         "decided_clauses": 14, "unreadable_reason": ""}))
    f = edit_check.honest_code_finding("x.py")
    assert f["verdict"] == "OUT_OF_SPEC"
    assert "L1.21.14" in f["detail"] and "line 5" in f["detail"]
    assert "bounded type" in f["action"]


def test_the_clause_coverage_is_read_not_assumed(monkeypatch):
    """A Python file decided 14 of 19 when measured, which is not the number
    that was quoted to me. The field is the authority and the memory is not."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [{"code": f"L1.21.{i}", "decided": i <= 14,
                      "findings": [{"clause": "L1.21.1", "line": 1,
                                    "detail": "d", "instead": "i"}] if i == 1 else []}
                     for i in range(1, 20)],
         "decided_clauses": 14, "unreadable_reason": ""}))
    f = edit_check.honest_code_finding("x.py")
    assert "14 of 19 clauses decided" in f["detail"]


def test_an_unreadable_file_is_not_a_clean_file(monkeypatch):
    """A file nobody could read is not a file with no violations."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [], "decided_clauses": 0,
         "unreadable_reason": "SyntaxError: unexpected EOF"}))
    f = edit_check.honest_code_finding("x.py")
    assert f["verdict"] == "NOT_RUN"
    assert "not the same as clean" in f["action"]


def test_a_wall_of_findings_is_truncated_and_says_so(monkeypatch):
    """A truncated list that does not say it is truncated is the same lie as a
    findings list with no coverage."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [{"code": "L1.21.8", "decided": True, "findings": [
            {"clause": "L1.21.8", "line": n, "detail": "d", "instead": "i"}
            for n in range(30)]}],
         "decided_clauses": 14, "unreadable_reason": ""}))
    f = edit_check.honest_code_finding("x.py")
    assert "30 Honest Code finding(s)" in f["detail"]
    assert "and 25 more, not shown" in f["detail"]


def test_the_provisional_caveat_is_carried(monkeypatch):
    """The bands are expert judgment, not measured."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [{"code": "L1.21.8", "decided": True, "findings": [
            {"clause": "L1.21.8", "line": 1, "detail": "d", "instead": "i"}]}],
         "decided_clauses": 14, "unreadable_reason": ""}))
    assert "expert judgment" in edit_check.honest_code_finding("x.py")["caveat"]


def test_a_missing_analyzer_leaves_l1_21_not_run(monkeypatch):
    no_analyzer(monkeypatch)
    f = edit_check.honest_code_finding("x.py")
    assert f["verdict"] == "NOT_RUN" and "not on PATH" in f["detail"]


def test_an_unreadable_response_leaves_l1_21_not_run(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "not json"})())
    assert edit_check.honest_code_finding("x.py")["verdict"] == "NOT_RUN"


def test_an_analyzer_that_will_not_run_leaves_l1_21_not_run(monkeypatch):
    def boom(*a, **k):
        raise OSError("no")
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", boom)
    assert edit_check.honest_code_finding("x.py")["verdict"] == "NOT_RUN"


def test_the_hook_never_reimplements_the_honest_code_clauses():
    """Nineteen clauses, one implementation. A second under the same name is
    how two tools come to disagree while both claim the standard."""
    src = (ROOT / "hooks" / "edit_check.py").read_text()
    assert "--honest-code" in src
    assert "import ast" not in src


def test_l1_18_is_not_delegated_because_it_cannot_read_one_file():
    """It takes a repository root and refuses a single file: "point me at a
    directory (a repo root), not a single file". The hook always passed it one
    file, so the call always failed and always reported NOT_RUN, and the
    binary's absence made that look like the same failure.

    Pointing it at the parent instead answers a different question: on a
    directory holding that one file it returns 100.0 and band Slop, which
    describes the directory rather than the file just written."""
    src = (ROOT / "hooks" / "edit_check.py").read_text()
    assert "--indicators" not in src
    assert "analyzer_finding" not in src
    assert not hasattr(edit_check, "analyzer_finding")


def test_trailing_whitespace_over_the_band_surfaces(tmp_path, monkeypatch):
    """Removed by accident while deleting the L1.18 tests, which left L1.16's
    finding branch uncovered and the gap invisible until coverage said so."""
    lines = ["x = 1   "] * 10 + ["y = 2"] * 90
    f = tmp_path / "ws.py"; f.write_text("\n".join(lines) + "\n")
    no_delegates(monkeypatch)
    code, err = run_hook(payload(f), monkeypatch)
    assert code == 2 and "L1.16" in err and "10.0%" in err
