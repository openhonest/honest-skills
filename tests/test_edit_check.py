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
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolated_pending(tmp_path, monkeypatch):
    """Each test gets its own pending state. Shared state would let one test's
    deferred write surface inside the next test's Stop."""
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "pending"))
    (tmp_path / "pending").mkdir(exist_ok=True)
_spec = importlib.util.spec_from_file_location(
    "edit_check", ROOT / "hooks" / "edit_check.py")
edit_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(edit_check)

CLEAN = "def f(x):\n    return x + 1\n"
# Trips the whitespace check, which is this hook's own. The long-file
# trigger these tests used belonged to L1.17, which has an owner and it
# was not this hook.
MESSY = "x = 1  \ny = 2  \nz = 3  \n"
NO_ANALYZER = {"indicator": "L1.21", "verdict": "NOT_RUN",
               "detail": "slop-audit-l1 is not on PATH",
               "action": "this file was not checked against the Honest Code clauses"}


def hc(path):
    """The L1.21 finding for one file, running the analyzer as the hook does.

    The hook parses the analyzer's response once and reads both the finding and
    the file's grade from it, so a test that wants only the finding still goes
    through the same single call.
    """
    data, failed = edit_check.analyzer_says(path)
    return failed if data is None else edit_check.honest_code_finding(path, data)


def payload(path):
    return json.dumps({"session_id": "s1", "tool_name": "Write",
                       "tool_input": {"file_path": str(path)}})


def _fire(raw, monkeypatch):
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(sys, "stderr", err)
    return edit_check.main(), err.getvalue()


def run_hook(raw, monkeypatch):
    """One write, then the Stop that settles it, as Claude Code runs them.

    The write firing is silent by design since 0.22.0: it records the path and
    waits, because a file edited three times in one turn was reported three
    times, each report describing a state the next edit had already replaced.
    What the caller wants asserted is the verdict on the settled file, so that
    is what this returns.
    """
    _fire(raw, monkeypatch)
    try:
        session = json.loads(raw).get("session_id")
    except (ValueError, TypeError, AttributeError):
        session = None             # malformed input still gets its Stop
    return _fire(json.dumps({"session_id": session}), monkeypatch)


def no_analyzer(monkeypatch):
    """The state of every fresh install: the plugin is there, the binary is not."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: None)


def no_delegates(monkeypatch):
    """Silence the one subprocess check, for tests about the local two."""
    monkeypatch.setattr(edit_check, "honest_code_finding", lambda p, d=None: None)


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
    f = tmp_path / "big.py"; f.write_text(MESSY)
    code, err = run_hook(payload(f), monkeypatch)
    assert code == 2
    assert "L1.16" in err and "NOT_RUN" in err and "L1.21" in err


def test_every_report_states_its_coverage_before_its_content(tmp_path, monkeypatch):
    """A findings list with no coverage stated is a list claiming to be
    complete."""
    no_analyzer(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    first = run_hook(payload(f), monkeypatch)[1].splitlines()[0]
    assert first == "honest-code: 2 of 3 checks ran on big.py"


def test_coverage_counts_checks_that_ran_not_findings_that_fired():
    """A check that ran and passed leaves no finding, so counting the findings
    counted it as not having run. That reported "1 of 4" when three had."""
    out = edit_check.render("a/big.py", [
        {"indicator": "L1.16", "verdict": "OUT_OF_SPEC", "detail": "d",
         "action": "a"},
        dict(NO_ANALYZER)])
    assert out.splitlines()[0].startswith("honest-code: 2 of 3")


def test_full_coverage_says_three_of_three():
    out = edit_check.render("a/big.py", [
        {"indicator": "L1.16", "verdict": "OUT_OF_SPEC", "detail": "d",
         "action": "a"}])
    assert out.splitlines()[0].startswith("honest-code: 3 of 3")


def test_findings_for_keeps_the_checks_that_did_not_run(tmp_path, monkeypatch):
    """Suppressing them here would make the coverage count impossible, and the
    count is the whole of the honesty."""
    no_analyzer(monkeypatch)
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    got = edit_check.findings_for(str(f), CLEAN)[0]
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
        [{"indicator": "L1.16", "verdict": "OUT_OF_SPEC", "detail": "d",
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
                     [{"indicator": "L1.16", "verdict": "OUT_OF_SPEC",
                       "detail": "d", "action": "a"}]):
        assert edit_check.render("b.py", findings).startswith("honest-code: ")
        assert "checks ran on" in edit_check.render("b.py", findings)
def test_the_hook_runs_as_a_subprocess_and_is_silent_on_a_clean_file(tmp_path):
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    p = subprocess.run([sys.executable, str(ROOT / "hooks" / "edit_check.py")],
                       input=payload(f), capture_output=True, text=True)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


def test_the_hook_runs_as_a_subprocess_and_exits_2_on_a_finding(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "pending"))
    f = tmp_path / "big.py"; f.write_text(MESSY)
    env = {**os.environ, "HONEST_PENDING_DIR": str(tmp_path / "pending")}
    hook = [sys.executable, str(ROOT / "hooks" / "edit_check.py")]
    subprocess.run(hook, input=payload(f), capture_output=True, text=True, env=env)
    p = subprocess.run(hook, input=json.dumps({"session_id": "s1"}),
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2 and "L1.16" in p.stderr and p.stdout == ""


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
    """Stands in for both calls: the analyzer, and the `git diff` that decides
    which lines changed. returncode 1 means no baseline, so every finding is
    reported and the line filter stays out of these tests."""
    def run(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            return type("R", (), {"returncode": 1, "stdout": ""})()
        return type("R", (), {"returncode": 0, "stdout": json.dumps(payload)})()
    return run


def test_a_clean_file_produces_no_honest_code_finding(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [{"code": "L1.21.1", "decided": True, "findings": []}],
         "decided_clauses": 1, "unreadable_reason": ""}))
    assert hc("x.py") is None


def test_a_violation_carries_its_clause_line_and_remedy(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [{"code": "L1.21.14", "decided": True, "findings": [
            {"clause": "L1.21.14", "line": 5,
             "detail": "`timeout=30` absorbs the caller's omission",
             "instead": "make absence an explicit case of a bounded type"}]}],
         "decided_clauses": 14, "unreadable_reason": ""}))
    f = hc("x.py")
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
    f = hc("x.py")
    assert "14 of 19 clauses decided" in f["detail"]


def test_an_unreadable_file_is_not_a_clean_file(monkeypatch):
    """A file nobody could read is not a file with no violations."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [], "decided_clauses": 0,
         "unreadable_reason": "SyntaxError: unexpected EOF"}))
    f = hc("x.py")
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
    f = hc("x.py")
    assert "30 Honest Code finding(s)" in f["detail"]
    assert "and 25 more, not shown" in f["detail"]


def test_the_provisional_caveat_is_carried(monkeypatch):
    """The bands are expert judgment, not measured."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", fake_honest(
        {"clauses": [{"code": "L1.21.8", "decided": True, "findings": [
            {"clause": "L1.21.8", "line": 1, "detail": "d", "instead": "i"}]}],
         "decided_clauses": 14, "unreadable_reason": ""}))
    assert "expert judgment" in hc("x.py")["caveat"]


def test_a_missing_analyzer_leaves_l1_21_not_run(monkeypatch):
    no_analyzer(monkeypatch)
    f = hc("x.py")
    assert f["verdict"] == "NOT_RUN" and "not on PATH" in f["detail"]


def test_an_unreadable_response_leaves_l1_21_not_run(monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "not json"})())
    assert hc("x.py")["verdict"] == "NOT_RUN"


def test_an_analyzer_that_will_not_run_leaves_l1_21_not_run(monkeypatch):
    def boom(*a, **k):
        raise OSError("no")
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", boom)
    assert hc("x.py")["verdict"] == "NOT_RUN"


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


# --- evidence that it ran ---------------------------------------------------

def test_a_clean_file_records_that_it_ran(tmp_path, monkeypatch):
    """Silence alone cannot tell "ran and found nothing" from "never ran"."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    no_delegates(monkeypatch)
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    run_hook(payload(f), monkeypatch)
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert any(r["verdict"] == "declined" and "3 of 3 ran" in r["why"] for r in rows)
    assert any("none had anything to say" in r["why"] for r in rows)


def test_a_firing_records_which_indicators_hit(tmp_path, monkeypatch):
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    run_hook(payload(f), monkeypatch)
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["verdict"] == "fired" and "L1.16" in row["why"]


def test_an_unchecked_extension_is_recorded_rather_than_silent(tmp_path, monkeypatch):
    """The one place this hook's silence still cannot be told from a pass.
    It cannot report on a file it does not check, so it records instead."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    f = tmp_path / "notes.md"; f.write_text("hello")
    assert run_hook(payload(f), monkeypatch) == (0, "")
    row = json.loads(log.read_text().splitlines()[0])
    assert "not a checked extension: .md" in row["why"]


# --- only the lines this edit touched ---------------------------------------

def test_only_findings_on_changed_lines_are_reported(monkeypatch):
    """A one-line edit to a 500-line module returned all 45 of its findings,
    most of them years old, and the reader had to find the one they caused."""
    payload = {"clauses": [{"code": "L1.21.14", "decided": True, "findings": [
        {"clause": "L1.21.14", "line": 5, "detail": "yours", "instead": "fix"},
        {"clause": "L1.21.8", "line": 400, "detail": "ancient", "instead": "fix"}]}],
        "decided_clauses": 14, "unreadable_reason": ""}
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", lambda cmd, *a, **k:
        type("R", (), {"returncode": 0,
                       "stdout": "@@ -5,0 +5,1 @@\n" if cmd[0] == "git"
                                 else json.dumps(payload)})())
    f = hc("x.py")
    assert "yours" in f["detail"] and "ancient" not in f["detail"]
    assert "1 elsewhere in the file not shown" in f["detail"]


def test_a_file_whose_old_findings_are_untouched_is_silent(monkeypatch):
    """Editing a clean line of a dirty file is not an occasion to report the
    file's history back at you."""
    payload = {"clauses": [{"code": "L1.21.8", "decided": True, "findings": [
        {"clause": "L1.21.8", "line": 400, "detail": "ancient", "instead": "fix"}]}],
        "decided_clauses": 14, "unreadable_reason": ""}
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    monkeypatch.setattr(edit_check.subprocess, "run", lambda cmd, *a, **k:
        type("R", (), {"returncode": 0,
                       "stdout": "@@ -5,0 +5,1 @@\n" if cmd[0] == "git"
                                 else json.dumps(payload)})())
    assert hc("x.py") is None


def test_an_untracked_file_has_no_baseline_and_reports_everything(monkeypatch):
    """A file with no committed version has no old findings to separate from
    new ones, so filtering would hide real ones."""
    monkeypatch.setattr(edit_check.subprocess, "run", lambda *a, **k:
        type("R", (), {"returncode": 1, "stdout": ""})())
    assert edit_check.changed_lines("x.py") is None


def test_a_file_restored_to_its_committed_state_changed_nothing(monkeypatch):
    """`cp backup.py mutate.py` reported every finding in the file it had just
    restored. Tracked with an empty diff is the opposite of no baseline."""
    def run(cmd, *a, **k):
        rc = 0 if cmd[1] == "ls-files" else 0
        return type("R", (), {"returncode": rc, "stdout": ""})()
    monkeypatch.setattr(edit_check.subprocess, "run", run)
    assert edit_check.changed_lines("x.py") == set()


def test_git_being_absent_means_report_everything(monkeypatch):
    def boom(*a, **k):
        raise OSError("no git")
    monkeypatch.setattr(edit_check.subprocess, "run", boom)
    assert edit_check.changed_lines("x.py") is None


@pytest.mark.parametrize("hunk,expected", [
    ("@@ -1 +1 @@\n", {1}),
    ("@@ -5,0 +5,3 @@\n", {5, 6, 7}),
    ("@@ -1,2 +1,1 @@\n@@ -9,0 +20,2 @@\n", {1, 20, 21}),
])
def test_hunk_headers_are_read_in_both_forms(monkeypatch, hunk, expected):
    """`+5` and `+5,3` are both valid, and a header with no count means one."""
    monkeypatch.setattr(edit_check.subprocess, "run", lambda *a, **k:
        type("R", (), {"returncode": 0, "stdout": hunk})())
    assert edit_check.changed_lines("x.py") == expected


def test_a_diff_with_no_hunks_reports_everything(monkeypatch):
    monkeypatch.setattr(edit_check.subprocess, "run", lambda *a, **k:
        type("R", (), {"returncode": 0, "stdout": "diff --git a/x b/x\n"})())
    assert edit_check.changed_lines("x.py") is None


def test_a_restore_produces_no_finding_at_all(monkeypatch):
    """The whole point: the file is back to what was committed, so nothing in
    it is this edit's doing."""
    payload = {"clauses": [{"code": "L1.21.8", "decided": True, "findings": [
        {"clause": "L1.21.8", "line": 4, "detail": "old", "instead": "fix"}]}],
        "decided_clauses": 14, "unreadable_reason": ""}
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    def run(cmd, *a, **k):
        if cmd[0] == "git":
            return type("R", (), {"returncode": 0, "stdout": ""})()
        return type("R", (), {"returncode": 0, "stdout": json.dumps(payload)})()
    monkeypatch.setattr(edit_check.subprocess, "run", run)
    assert hc("x.py") is None


def test_a_stubbornly_untracked_file_still_reports(monkeypatch):
    """Not tracked is not the same as unchanged, and a new file's findings are
    all new."""
    payload = {"clauses": [{"code": "L1.21.8", "decided": True, "findings": [
        {"clause": "L1.21.8", "line": 4, "detail": "new", "instead": "fix"}]}],
        "decided_clauses": 14, "unreadable_reason": ""}
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/usr/bin/fake")
    def run(cmd, *a, **k):
        if cmd[0] == "git":
            return type("R", (), {"returncode": 1, "stdout": ""})()
        return type("R", (), {"returncode": 0, "stdout": json.dumps(payload)})()
    monkeypatch.setattr(edit_check.subprocess, "run", run)
    assert "new" in hc("x.py")["detail"]


def test_a_diff_that_errors_after_the_file_is_tracked_reports_everything(monkeypatch):
    """Tracked, but git could not produce a diff. That is a broken baseline
    rather than an unchanged file, and the two must not be confused again."""
    def run(cmd, *a, **k):
        rc = 0 if cmd[1] == "ls-files" else 128
        return type("R", (), {"returncode": rc, "stdout": ""})()
    monkeypatch.setattr(edit_check.subprocess, "run", run)
    assert edit_check.changed_lines("x.py") is None


# --- the settled file, not the file mid-edit --------------------------------

def test_a_write_says_nothing_until_the_turn_ends(tmp_path, monkeypatch):
    """The write firing is silent by construction. Adam reported on 2026-08-21
    that the hook looked like it was assessing the file before the change; the
    cause was PostToolUse firing once per tool call, so a file edited three
    times produced three reports and the model read one describing content two
    edits out of date."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    assert _fire(payload(f), monkeypatch) == (0, "")


def test_a_violation_introduced_then_fixed_in_one_turn_is_never_reported(
        tmp_path, monkeypatch):
    """The whole reason for deferring. The turn's last word on the file is the
    only one worth an opinion."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    f.write_text(CLEAN)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")


def test_one_file_edited_twice_is_reported_once(tmp_path, monkeypatch):
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    _fire(payload(f), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert code == 2 and err.count("honest-code:") == 1


def test_two_files_each_get_their_own_report(tmp_path, monkeypatch):
    no_delegates(monkeypatch)
    for name in ("a.py", "b.py"):
        f = tmp_path / name; f.write_text(MESSY)
        _fire(payload(f), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert code == 2 and err.count("honest-code:") == 2


def test_the_same_finding_does_not_block_a_second_turn(tmp_path, monkeypatch):
    """A Stop hook that repeats itself is a Stop hook that never lets the turn
    end. Said once, then the choice not to act on it is the writer's."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")


def test_a_changed_file_is_reported_again(tmp_path, monkeypatch):
    """The guard is on the content, not the path. Editing the file and leaving
    a different violation on the lines you touched is new news."""
    monkeypatch.setattr(edit_check, "honest_code_finding",
                        lambda p, d=None: {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
                                   "detail": "d", "action": "a"})
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    f.write_text(CLEAN + "# changed\n")
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2


def test_a_file_deleted_before_the_turn_ends_is_not_a_finding(
        tmp_path, monkeypatch):
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    f.unlink()
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")


def test_two_sessions_do_not_read_each_others_pending_writes(
        tmp_path, monkeypatch):
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(json.dumps({"session_id": "one",
                      "tool_input": {"file_path": str(f)}}), monkeypatch)
    assert _fire(json.dumps({"session_id": "two"}), monkeypatch) == (0, "")
    assert _fire(json.dumps({"session_id": "one"}), monkeypatch)[0] == 2


def test_an_unwritable_state_directory_does_not_break_the_write(
        tmp_path, monkeypatch):
    """Scratch state must never be able to break the thing it serves."""
    monkeypatch.setenv("HONEST_PENDING_DIR", "/dev/null/nope")
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    assert _fire(payload(f), monkeypatch) == (0, "")


def test_a_stale_session_is_told_so_alongside_the_finding(tmp_path, monkeypatch):
    """The note rides on output the hook was already producing. Staleness only
    hurts when the hook fires, because the stale versions' defect is the noise
    in exactly that output, and a version line on every clean write would be
    the same noise by another name."""
    monkeypatch.setattr(edit_check, "stale_note",
                        lambda: "this session runs 0.13.1, 0.22.0 is installed.")
    f = tmp_path / "big.py"; f.write_text(MESSY)
    no_delegates(monkeypatch)
    report = edit_check.render(str(f), edit_check.findings_for(str(f), f.read_text())[0])
    assert "0.13.1" in report.splitlines()[1]


# --- which kind of undecided ------------------------------------------------

def test_a_rule_that_cannot_apply_is_not_a_gap_in_coverage():
    """"14 of 19 decided" put a browser rule that cannot apply to a Python file
    in the same bucket as a file nobody could parse. Only the second is a
    failure to look, and counting both overstated what went unchecked on every
    Python file ever measured."""
    clauses = [{"decided": False, "undecided": "not applicable"},
               {"decided": False, "undecided": "never"},
               {"decided": True}]
    assert edit_check.coverage_gap(clauses) == 0


def test_a_clause_nobody_could_read_is_a_gap():
    assert edit_check.coverage_gap([{"decided": False, "undecided": "unreadable"}]) == 1


def test_an_undecided_clause_with_no_kind_counts_as_a_gap():
    """A reader that cannot tell says it did not look, rather than assuming it
    did. An older analyzer emits no kind at all."""
    assert edit_check.coverage_gap([{"decided": False}]) == 1


def test_the_trace_records_the_whole_path_not_just_the_name(tmp_path, monkeypatch):
    """It held the basename until 2026-08-21, so nothing reading the trace
    could tell a scratch file from real work. Every consumer kept its own
    hand-written list of filenames to exclude, and one went stale within the
    hour and reported a measurement whose entire signal was probe files."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    no_delegates(monkeypatch)
    f = tmp_path / "sub" / "deep.py"
    f.parent.mkdir(); f.write_text(CLEAN)
    run_hook(payload(f), monkeypatch)
    files = [json.loads(l).get("file") for l in log.read_text().splitlines()]
    assert str(f) in files and "deep.py" not in files


def test_a_session_whose_stop_never_runs_gets_told_rather_than_going_silent(
        tmp_path, monkeypatch):
    """The hook going silently dead is the failure this drain exists to stop.
    Silence from a hook that is working and silence from a hook that is
    stranding every write are the same silence."""
    import os, time
    no_delegates(monkeypatch)
    old_file = tmp_path / "stranded.py"
    old_file.write_text(MESSY)
    old = time.time() - 700
    os.utime(old_file, (old, old))
    edit_check.write_state("edit", "s1", {
        "pending": [{"path": str(old_file), "at": old}], "reported": {}})
    new = tmp_path / "fresh.py"; new.write_text(CLEAN)
    code, err = _fire(payload(new), monkeypatch)
    assert code == 2
    assert "the Stop hook is not running in this session" in err
    assert "stranded.py" in err and "L1.16" in err


def test_the_drained_write_is_not_reported_a_second_time(tmp_path, monkeypatch):
    import os, time
    no_delegates(monkeypatch)
    f = tmp_path / "stranded.py"; f.write_text(MESSY)
    old = time.time() - 700
    os.utime(f, (old, old))
    edit_check.write_state("edit", "s1", {
        "pending": [{"path": str(f), "at": old}], "reported": {}})
    other = tmp_path / "fresh.py"; other.write_text(CLEAN)
    assert _fire(payload(other), monkeypatch)[0] == 2
    assert _fire(payload(other), monkeypatch) == (0, "")


def test_a_stranded_write_with_nothing_to_say_is_dropped_quietly(
        tmp_path, monkeypatch):
    """A held write that turned out clean is not news, and announcing the
    wiring fault with no finding under it would be the tool reporting on
    itself where a finding about the code belongs."""
    import os, time
    no_delegates(monkeypatch)
    f = tmp_path / "clean.py"; f.write_text(CLEAN)
    old = time.time() - 700
    os.utime(f, (old, old))
    edit_check.write_state("edit", "s1", {
        "pending": [{"path": str(f), "at": old}], "reported": {}})
    other = tmp_path / "fresh.py"; other.write_text(CLEAN)
    assert _fire(payload(other), monkeypatch) == (0, "")
    assert edit_check.stranded("edit", "s1") == []


def test_a_turn_that_settled_nothing_still_leaves_a_row(tmp_path, monkeypatch):
    """Without it, a Stop that ran and found nothing reads identically to a
    Stop that never ran. That cost a wrong diagnosis on 2026-08-21: two
    sessions holding writes with no settle recorded looked like stranding, and
    the missing row was the whole of the evidence."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    _fire(json.dumps({"session_id": "empty"}), monkeypatch)
    row = json.loads(log.read_text())
    assert row["event"] == "Stop:edit"
    assert "0 file(s) assessed" in row["why"]


def test_the_row_says_how_many_files_were_looked_at(tmp_path, monkeypatch):
    """Assessed four and they were clean is a different fact from there was
    nothing to assess, and the count is what separates them."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    no_delegates(monkeypatch)
    for name in ("a.py", "b.py"):
        f = tmp_path / name; f.write_text(CLEAN)
        _fire(payload(f), monkeypatch)
    _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert any("2 file(s) assessed, none had anything to say" in r["why"]
               for r in rows)


def test_a_file_the_reader_cannot_read_is_not_reported_as_clean(
        tmp_path, monkeypatch):
    """A Python parser over a JavaScript file returns an empty tree, and every
    clause that walks the tree finds nothing in it and counts as holding. A
    JavaScript file scored 87.5 percent that way, on clauses that never read
    it. Silence here would publish the same thing."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    payload_json = json.dumps({"clauses":
        [{"code": f"L1.21.{i}", "decided": False, "undecided": "unreadable",
          "findings": []} for i in range(16)]
        + [{"code": "L1.21.17", "decided": True, "findings": []}],
        "decided_clauses": 1})
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": payload_json})())
    f = tmp_path / "app.js"; f.write_text("class A extends B {}\n")
    got = hc(str(f))
    assert got["verdict"] == "NOT_RUN"
    assert "16 of 17 clauses could not read this file" in got["detail"]


def test_a_python_file_with_no_findings_stays_silent(tmp_path, monkeypatch):
    """The clauses that do not apply to a Python file are not a coverage gap,
    so a clean Python file must not start announcing one."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    payload_json = json.dumps({"clauses":
        [{"code": "L1.21.6", "decided": False, "undecided": "not applicable",
          "findings": []},
         {"code": "L1.21.17", "decided": False, "undecided": "never",
          "findings": []},
         {"code": "L1.21.1", "decided": True, "findings": []}],
        "decided_clauses": 1})
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": payload_json})())
    f = tmp_path / "app.py"; f.write_text(CLEAN)
    assert hc(str(f)) is None


def test_the_coverage_gap_is_announced_once_per_language_per_session(
        tmp_path, monkeypatch):
    """Never is a false clean bill on every JavaScript file. Every write is
    noise to anyone writing JavaScript all day."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    unreadable = json.dumps({"clauses": [
        {"code": "L1.21.1", "decided": False, "undecided": "unreadable",
         "findings": []}], "decided_clauses": 0})
    monkeypatch.setattr(
        edit_check.subprocess, "run",
        lambda *a, **k: type("R", (), {"stdout": json.dumps(
            [{**json.loads(unreadable), "path": p}
             for p in a[0][2:-2]])})())
    a = tmp_path / "a.js"; a.write_text("class A {}\n")
    b = tmp_path / "b.js"; b.write_text("class B {}\n")
    code, err = run_hook(payload(a), monkeypatch)
    assert code == 2 and "could not read this file" in err
    assert run_hook(payload(b), monkeypatch) == (0, "")


def test_a_second_language_is_announced_on_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    unreadable = json.dumps({"clauses": [
        {"code": "L1.21.1", "decided": False, "undecided": "unreadable",
         "findings": []}], "decided_clauses": 0})
    monkeypatch.setattr(
        edit_check.subprocess, "run",
        lambda *a, **k: type("R", (), {"stdout": json.dumps(
            [{**json.loads(unreadable), "path": p}
             for p in a[0][2:-2]])})())
    js = tmp_path / "a.js"; js.write_text("class A {}\n")
    rs = tmp_path / "a.rs"; rs.write_text("fn main() {}\n")
    assert run_hook(payload(js), monkeypatch)[0] == 2
    assert run_hook(payload(rs), monkeypatch)[0] == 2


def test_the_announcement_survives_the_turn_ending(tmp_path, monkeypatch):
    """Rebuilding the state each turn would reset it, turning once per session
    into once per turn."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    unreadable = json.dumps({"clauses": [
        {"code": "L1.21.1", "decided": False, "undecided": "unreadable",
         "findings": []}], "decided_clauses": 0})
    monkeypatch.setattr(
        edit_check.subprocess, "run",
        lambda *a, **k: type("R", (), {"stdout": json.dumps(
            [{**json.loads(unreadable), "path": p}
             for p in a[0][2:-2]])})())
    a = tmp_path / "a.js"; a.write_text("class A {}\n")
    assert run_hook(payload(a), monkeypatch)[0] == 2
    b = tmp_path / "b.js"; b.write_text("class B {}\n")
    assert run_hook(payload(b), monkeypatch) == (0, "")


# --- silenced is not the same as fixed --------------------------------------

def _analyzer(monkeypatch, payload):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": json.dumps(payload)})())


def test_a_silenced_finding_is_reported_as_silenced_not_as_clean(
        tmp_path, monkeypatch):
    """An annotation that makes a finding disappear was indistinguishable from
    writing conforming code. Anything scoring an agent on conformance paid it
    the same either way, and silencing is the cheaper of the two."""
    _analyzer(monkeypatch, {"clauses": [
        {"code": "L1.21.8", "decided": True, "findings": [],
         "allowed": [{"line": 4, "reason": "legacy caller needs None"}]}],
        "decided_clauses": 1})
    monkeypatch.setattr(edit_check, "changed_lines", lambda p: None)
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    got = hc(str(f))
    assert got["verdict"] == "SUPPRESSED"
    assert "silenced on lines you changed, not fixed" in got["detail"]
    assert "legacy caller needs None" in got["detail"]


def test_the_reason_travels_with_the_suppression(tmp_path, monkeypatch):
    """A suppression is a decision someone should be able to see."""
    _analyzer(monkeypatch, {"clauses": [
        {"code": "L1.21.8", "decided": True, "findings": [],
         "allowed": [{"line": 9}]}], "decided_clauses": 1})
    monkeypatch.setattr(edit_check, "changed_lines", lambda p: None)
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    assert "no reason given" in hc(str(f))["detail"]


def test_a_suppression_on_a_line_this_edit_did_not_touch_is_not_reported(
        tmp_path, monkeypatch):
    """Someone else's earlier decision is not this writer's business, the same
    rule the findings already follow."""
    _analyzer(monkeypatch, {"clauses": [
        {"code": "L1.21.8", "decided": True, "findings": [],
         "allowed": [{"line": 400, "reason": "old"}]}], "decided_clauses": 1})
    monkeypatch.setattr(edit_check, "changed_lines", lambda p: {7, 8})
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    assert hc(str(f)) is None


def test_a_real_finding_outranks_a_suppression(tmp_path, monkeypatch):
    """Something still broken is the more useful thing to say."""
    _analyzer(monkeypatch, {"clauses": [
        {"code": "L1.21.8", "decided": True,
         "findings": [{"clause": "L1.21.8", "line": 4, "detail": "d",
                       "instead": "i"}],
         "allowed": [{"line": 9, "reason": "r"}]}], "decided_clauses": 1})
    monkeypatch.setattr(edit_check, "changed_lines", lambda p: None)
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    assert hc(str(f))["verdict"] == "OUT_OF_SPEC"


def test_the_record_calls_a_suppression_neither_fired_nor_clean(
        tmp_path, monkeypatch):
    """Left as fired it counts against the writer like a real finding. Left as
    declined it counts as conforming code, which is the reading that makes
    silencing the cheap route to a good score."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setattr(edit_check, "honest_code_finding",
                        lambda p, d=None: {"indicator": "L1.21", "verdict": "SUPPRESSED",
                                   "detail": "1 finding(s) silenced", "action": "a"})
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    run_hook(payload(f), monkeypatch)
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert any(r["verdict"] == "suppressed" for r in rows
               if r["event"] == "Stop:edit")


def test_the_record_names_which_clause_fired(tmp_path, monkeypatch):
    """"L1.21 fired" says a rule was broken. The clause says which habit
    produced it, and that is the thing a series of writes can show moving."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setattr(edit_check, "honest_code_finding",
                        lambda p, d=None: {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
                                   "detail": "d", "action": "a",
                                   "clauses": ["L1.21.14", "L1.21.4"]})
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    run_hook(payload(f), monkeypatch)
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    fired = [r for r in rows if r.get("verdict") == "fired"]
    assert fired and fired[0]["clauses"] == ["L1.21.4", "L1.21.14"]  # numeric


def test_a_finding_with_no_clause_leaves_the_field_out(tmp_path, monkeypatch):
    """L1.17 and L1.16 are not clause-shaped, and an empty list in the record
    would read as "asked and found none"."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    run_hook(payload(f), monkeypatch)
    fired = [json.loads(l) for l in log.read_text().splitlines()
             if json.loads(l).get("verdict") == "fired"]
    assert fired and "clauses" not in fired[0]


def test_clauses_are_ordered_by_number_not_as_text(tmp_path, monkeypatch):
    """As text "L1.21.14" comes before "L1.21.4", which reads as a mistake to
    anyone who knows the clauses."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setattr(edit_check, "honest_code_finding",
                        lambda p, d=None: {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
                                   "detail": "d", "action": "a",
                                   "clauses": ["L1.21.14", "L1.21.2", "L1.21.4"]})
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    run_hook(payload(f), monkeypatch)
    fired = [json.loads(l) for l in log.read_text().splitlines()
             if json.loads(l).get("verdict") == "fired"]
    assert fired[0]["clauses"] == ["L1.21.2", "L1.21.4", "L1.21.14"]


# --- every write is a unit, and its state is recorded ------------------------

def _unit(tmp_path, monkeypatch, finding, ran_all=True):
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setattr(edit_check, "honest_code_finding", lambda p, d=None: finding)
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    run_hook(payload(f), monkeypatch)
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    return next(r for r in rows if r["event"] == "Stop:edit" and "unit" in r)


def test_a_silent_pass_is_recorded_as_a_measurement(tmp_path, monkeypatch):
    """A conforming write is a data point. Left unrecorded there is no
    denominator, and a chart of defects alone has no rate in it."""
    row = _unit(tmp_path, monkeypatch, None)
    assert row["unit"] == "conformed"
    assert row["checks_ran"] == row["checks"] == edit_check.CHECKS


def test_a_file_the_checks_could_not_read_is_not_a_conforming_unit(
        tmp_path, monkeypatch):
    """A JavaScript file that half the instrument cannot read used to record
    identically to a clean one. That inflates the rate by exactly the amount
    the instrument could not see."""
    row = _unit(tmp_path, monkeypatch,
                {"indicator": "L1.21", "verdict": "NOT_RUN",
                 "detail": "d", "action": "a"})
    assert row["unit"] == "not_measured"
    assert row["checks_ran"] < row["checks"]


def test_a_finding_makes_the_unit_nonconforming(tmp_path, monkeypatch):
    row = _unit(tmp_path, monkeypatch,
                {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
                 "detail": "d", "action": "a"})
    assert row["unit"] == "nonconforming"


def test_a_silenced_check_makes_the_unit_suppressed_not_conforming(
        tmp_path, monkeypatch):
    row = _unit(tmp_path, monkeypatch,
                {"indicator": "L1.21", "verdict": "SUPPRESSED",
                 "detail": "d", "action": "a"})
    assert row["unit"] == "suppressed"


def test_a_suppression_outranks_a_finding_in_the_unit_state(
        tmp_path, monkeypatch):
    """Silencing is the fact worth surfacing: it is the cheap route, and a
    reader needs to see it was taken even when something else also fired."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setattr(edit_check, "honest_code_finding",
                        lambda p, d=None: {"indicator": "L1.21", "verdict": "SUPPRESSED",
                                   "detail": "1 silenced", "action": "a"})
    f = tmp_path / "big.py"; f.write_text(MESSY)   # also trips L1.17
    run_hook(payload(f), monkeypatch)
    row = next(json.loads(l) for l in log.read_text().splitlines()
               if json.loads(l).get("event") == "Stop:edit"
               and "unit" in json.loads(l))
    assert row["unit"] == "suppressed"


# --- a whole-file finding is said once, not on every edit --------------------

def test_a_standing_finding_keeps_being_reported(tmp_path, monkeypatch):
    """An agent is not worn down the way a person is, and a finding that stops
    being said stops being visible. Adam overruled the suppression that used to
    live here: the file still trips the check and the report should keep saying
    so until it does not."""
    no_delegates(monkeypatch)
    f = tmp_path / "messy.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    f.write_text(MESSY + "w = 4  \\n")   # edited again, still messy
    _fire(payload(f), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert code == 2 and "L1.16" in err


def test_a_repeat_says_how_long_it_has_been_standing(tmp_path, monkeypatch):
    """The repeat carries its count so a reader can tell what is new in this
    report from what has stood all session. A file that fixed one of its two
    findings got a report that looked identical to the two before it."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    _, first = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert "still standing" not in first
    f.write_text(MESSY + "w = 4  \\n")   # edited again, still messy
    _fire(payload(f), monkeypatch)
    _, second = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert "still standing, told 2 times" in second


def test_another_file_over_the_limit_is_still_reported(tmp_path, monkeypatch):
    """Said once per file, not once per session. A second long file is news
    about a different file."""
    no_delegates(monkeypatch)
    a = tmp_path / "a.py"; a.write_text(MESSY)
    _fire(payload(a), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    b = tmp_path / "b.py"; b.write_text(MESSY.replace("x", "q"))
    _fire(payload(b), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2


def test_a_line_scoped_finding_still_repeats_on_new_content(
        tmp_path, monkeypatch):
    """Only whole-file findings are held back. A finding about the lines just
    written is new news every time those lines change."""
    monkeypatch.setattr(edit_check, "honest_code_finding",
                        lambda p, d=None: {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
                                   "detail": "d", "action": "a"})
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    f.write_text(CLEAN + "# more\n")
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2


def test_unchanged_content_is_not_reported_twice(tmp_path, monkeypatch):
    """The content guard, reached with a line-scoped finding. Said once, then
    the choice not to act on it is the writer's. A Stop hook that repeats
    itself is a Stop hook that never lets the turn end."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setattr(edit_check, "honest_code_finding",
                        lambda p, d=None: {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
                                   "detail": "d", "action": "a"})
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    _fire(payload(f), monkeypatch)                    # same content, untouched
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")
    assert any("already reported this content" in json.loads(l)["why"]
               for l in log.read_text().splitlines())


# --- a standing finding is raised again on a timer ---------------------------

def test_a_finding_is_raised_again_after_the_wait_even_with_no_new_write(
        tmp_path, monkeypatch):
    """An agent that walks away from a file does not make its defect go away.
    A finding only re-checked when the file is written can be escaped by never
    writing to it again."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    # The agent moves on. Nothing touches big.py again.
    state = edit_check.read_state("edit", "s1")
    state["standing"] = {str(f): 0.0}          # the wait has elapsed
    edit_check.write_state("edit", "s1", state)
    other = tmp_path / "ok.py"; other.write_text(CLEAN)
    _fire(payload(other), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert code == 2 and "big.py" in err


def test_a_finding_fixed_while_working_elsewhere_is_never_raised(
        tmp_path, monkeypatch):
    """Verified, not remembered. The file is re-assessed before anything is
    said, so a fix made in passing closes the entry in silence."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    f.write_text(CLEAN)                        # fixed, without the hook seeing it
    state = edit_check.read_state("edit", "s1")
    state["standing"] = {str(f): 0.0}
    edit_check.write_state("edit", "s1", state)
    other = tmp_path / "ok.py"; other.write_text(CLEAN)
    _fire(payload(other), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")
    assert edit_check.read_state("edit", "s1")["standing"] == {}


def test_the_wait_has_to_elapse_before_it_is_raised_again(
        tmp_path, monkeypatch):
    """Nagging on a timer, not on every turn. A finding raised again seconds
    later is repetition without information."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    other = tmp_path / "ok.py"; other.write_text(CLEAN)
    _fire(payload(other), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")


def test_a_file_that_went_away_closes_its_entry(tmp_path, monkeypatch):
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    f.unlink()
    state = edit_check.read_state("edit", "s1")
    state["standing"] = {str(f): 0.0}
    edit_check.write_state("edit", "s1", state)
    other = tmp_path / "ok.py"; other.write_text(CLEAN)
    _fire(payload(other), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")
    assert edit_check.read_state("edit", "s1")["standing"] == {}


def test_a_standing_file_written_this_turn_is_not_raised_twice(
        tmp_path, monkeypatch):
    """The turn already assessed it, so raising it again from the standing
    book would put the same finding in the same report twice."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    state = edit_check.read_state("edit", "s1")
    state["standing"] = {str(f): 0.0}          # due, and written again below
    edit_check.write_state("edit", "s1", state)
    f.write_text(MESSY + "w = 4  \\n")   # edited again, still messy
    _fire(payload(f), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert code == 2 and err.count("honest-code:") == 1


def test_a_boundary_declaration_that_withheld_a_finding_counts(
        tmp_path, monkeypatch):
    """Reported by the analyzer rather than inferred from a decorator. Counting
    markers found 62 that excused nothing on one package, and 10 of 11 on
    another."""
    _analyzer(monkeypatch, {"clauses": [
        {"code": "L1.21.4", "decided": True, "findings": [],
         "declared": [{"line": 12, "reason": "declared boundary withheld it"}]}],
        "decided_clauses": 1})
    monkeypatch.setattr(edit_check, "changed_lines", lambda p: None)
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    got = hc(str(f))
    assert got["verdict"] == "SUPPRESSED" and "line 12" in got["detail"]


def test_an_analyzer_that_does_not_report_declarations_reads_as_none(
        tmp_path, monkeypatch):
    """The field is absent until audit's branch merges. Absent reads as zero,
    which is honest: not "no declaration excused anything" but "nothing told me
    one did"."""
    _analyzer(monkeypatch, {"clauses": [
        {"code": "L1.21.4", "decided": True, "findings": []}], "decided_clauses": 1})
    monkeypatch.setattr(edit_check, "changed_lines", lambda p: None)
    f = tmp_path / "a.py"; f.write_text(CLEAN)
    assert hc(str(f)) is None


# --- one analyzer run for the whole turn --------------------------------------

def test_the_turn_runs_the_analyzer_once_for_every_file(tmp_path, monkeypatch):
    """The analysis costs nothing measurable: on a small file --help and a real
    run both take 71ms, so the whole bill is starting the process. Paid per
    file, a twenty-file turn spent 2.5 seconds starting Python twenty times to
    do twenty milliseconds of work."""
    runs = []
    def spy(*a, **k):
        runs.append(a[0])
        paths = [x for x in a[0] if str(x).endswith(".py")]
        return type("R", (), {"stdout": json.dumps(
            [{"path": p, "clauses": [], "decided_clauses": 14,
              "conformity": 100.0, "band": "Healthy"} for p in paths])})()
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    monkeypatch.setattr(edit_check.subprocess, "run", spy)
    for i in range(5):
        f = tmp_path / f"m{i}.py"; f.write_text(CLEAN)
        _fire(payload(f), monkeypatch)
    runs.clear()
    _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    analyzer = [r for r in runs if "--honest-code" in r]
    assert len(analyzer) == 1
    assert sum(1 for x in analyzer[0] if str(x).endswith(".py")) == 5


def test_a_file_the_batch_returned_nothing_for_is_not_called_clean(
        tmp_path, monkeypatch):
    """A run that skipped a file it could not measure and reported the rest
    would claim a coverage it did not have."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": "[]"})())
    f = tmp_path / "m.py"; f.write_text(CLEAN)
    _fire(payload(f), monkeypatch)
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    row = next(json.loads(l) for l in log.read_text().splitlines()
               if json.loads(l).get("event") == "Stop:edit" and "unit" in json.loads(l))
    assert row["unit"] == "not_measured"


def test_the_conformity_carries_how_many_clauses_could_be_read(
        tmp_path, monkeypatch):
    """92.9 per cent over nineteen readable clauses and 92.9 per cent over
    three are different facts, and the share alone cannot tell them apart."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": json.dumps(
                            [{"path": p, "clauses": [], "decided_clauses": 3,
                              "conformity": 92.9, "band": "Not Healthy"}
                             for p in a[0] if str(p).endswith(".py")])})())
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    f = tmp_path / "m.py"; f.write_text(CLEAN)
    run_hook(payload(f), monkeypatch)
    row = next(json.loads(l) for l in log.read_text().splitlines()
               if json.loads(l).get("event") == "Stop:edit" and "band" in json.loads(l))
    assert row["decided"] == 3 and row["conformity"] == 92.9


# --- content inside a readable file that no clause examined -------------------

def _with_unexamined(monkeypatch, unexamined):
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": json.dumps(
                            [{"path": p, "clauses": [], "decided_clauses": 14,
                              "conformity": 100.0, "band": "Healthy",
                              "unexamined": unexamined}
                             for p in a[0] if str(p).endswith(".py")])})())


def test_a_finding_inside_an_embedded_block_is_a_finding(tmp_path, monkeypatch):
    """A block of another language held in a string is checked now, not merely
    noticed, so what comes back is findings rather than a label. They are real
    violations in real code and they count as such."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    _with_unexamined(monkeypatch, [
        {"language": "javascript", "line": 2, "lines": 9,
         "also_accepted_by": ["typescript"],
         "findings": [{"clause": "L1.21.5", "line": 3,
                       "detail": "inherits from Base", "instead": "compose"}]}])
    monkeypatch.setattr(edit_check, "changed_lines", lambda p: None)
    f = tmp_path / "m.py"; f.write_text(CLEAN)
    code, err = run_hook(payload(f), monkeypatch)
    assert code == 2
    assert "in embedded javascript" in err and "L1.21.5" in err
    row = next(json.loads(l) for l in log.read_text().splitlines()
               if json.loads(l).get("event") == "Stop:edit" and "unit" in json.loads(l))
    assert row["unit"] == "nonconforming"


def test_a_block_that_fires_nothing_is_not_held_against_the_file(
        tmp_path, monkeypatch):
    """A SQL query in a database driver used to pull its file out of the rate.
    audit's answer to whether a block that IS the file's subject can be told
    from one the file ships was no, not from the source alone, and excluding
    them moved a number for a reason nobody reading it could see."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    _with_unexamined(monkeypatch, [
        {"language": "ruby", "line": 4, "lines": 12, "findings": []}])
    monkeypatch.setattr(edit_check, "changed_lines", lambda p: None)
    f = tmp_path / "m.py"; f.write_text(CLEAN)
    assert run_hook(payload(f), monkeypatch) == (0, "")
    row = next(json.loads(l) for l in log.read_text().splitlines()
               if json.loads(l).get("event") == "Stop:edit" and "unit" in json.loads(l))
    assert row["unit"] == "conformed"


def test_a_file_with_nothing_unexamined_is_unaffected(tmp_path, monkeypatch):
    _with_unexamined(monkeypatch, [])
    f = tmp_path / "m.py"; f.write_text(CLEAN)
    assert run_hook(payload(f), monkeypatch) == (0, "")


# --- the analyzer's shape is declared unstable, so notice when it moves ------

def test_a_response_missing_its_findings_key_is_not_a_clean_file(monkeypatch):
    """audit shipped 1.0.0 promising a stable JSON shape, then changed L1.21's
    shape twice in a day and put it outside that promise. Read with .get()
    throughout, a key that goes away degrades to the flattering default: no
    clauses means no findings means clean."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": json.dumps(
                            {"path": "x.py", "conformity": 100.0,
                             "band": "Healthy"})})())
    got = hc("x.py")
    assert got["verdict"] == "NOT_RUN"
    assert "missing clauses" in got["detail"]


def test_a_response_carrying_findings_is_read_normally(monkeypatch):
    """Only the key whose absence reads as good news is refused. A missing
    grade costs a record field and cannot be mistaken for a pass."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": json.dumps(
                            {"clauses": [], "decided_clauses": 14})})())
    assert hc("x.py") is None


def test_an_array_response_for_one_path_is_read_as_that_file(monkeypatch):
    """One path returns an object and several return an array. Reading only the
    object shape would treat an array as a response with every key missing,
    which is a true statement about a list and a wrong one about the file."""
    monkeypatch.setattr(edit_check.shutil, "which", lambda n: "/bin/true")
    monkeypatch.setattr(edit_check.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": json.dumps(
                            [{"clauses": [], "decided_clauses": 14}])})())
    assert hc("x.py") is None


# --- believed, not observed --------------------------------------------------

def test_a_file_found_by_timestamp_says_it_may_be_another_session_s(
        tmp_path, monkeypatch):
    """The Bash hook lists files whose timestamp moved under the working
    directory; it cannot see which command wrote them. On 2026-08-24 a session
    was told about a file in another session's working copy, annotated by
    someone else, that it had never touched."""
    no_delegates(monkeypatch)
    f = tmp_path / "other.py"; f.write_text(MESSY)
    edit_check.defer("edit", str(f), "s1", attributed=True)
    code, err = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert code == 2
    assert "may be another session's" in err
    assert "not because an edit was seen" in err


def test_a_file_this_session_edited_carries_no_such_caveat(
        tmp_path, monkeypatch):
    """An observed edit is known, and hedging a known thing is its own kind of
    dishonesty."""
    no_delegates(monkeypatch)
    f = tmp_path / "mine.py"; f.write_text(MESSY)
    _fire(payload(f), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert code == 2 and "another session" not in err
