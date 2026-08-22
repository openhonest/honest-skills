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
NO_ANALYZER = {"indicator": "L1.21", "verdict": "NOT_RUN",
               "detail": "slop-audit-l1 is not on PATH",
               "action": "this file was not checked against the Honest Code clauses"}


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


def test_the_hook_runs_as_a_subprocess_and_exits_2_on_a_finding(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "pending"))
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    env = {**os.environ, "HONEST_PENDING_DIR": str(tmp_path / "pending")}
    hook = [sys.executable, str(ROOT / "hooks" / "edit_check.py")]
    subprocess.run(hook, input=payload(f), capture_output=True, text=True, env=env)
    p = subprocess.run(hook, input=json.dumps({"session_id": "s1"}),
                       capture_output=True, text=True, env=env)
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


# --- evidence that it ran ---------------------------------------------------

def test_a_clean_file_records_that_it_ran(tmp_path, monkeypatch):
    """Silence alone cannot tell "ran and found nothing" from "never ran"."""
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    no_delegates(monkeypatch)
    f = tmp_path / "ok.py"; f.write_text(CLEAN)
    run_hook(payload(f), monkeypatch)
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["verdict"] == "declined" and "3 of 3 ran" in row["why"]


def test_a_firing_records_which_indicators_hit(tmp_path, monkeypatch):
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    run_hook(payload(f), monkeypatch)
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["verdict"] == "fired" and "L1.17" in row["why"]


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
    f = edit_check.honest_code_finding("x.py")
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
    assert edit_check.honest_code_finding("x.py") is None


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
    assert edit_check.honest_code_finding("x.py") is None


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
    assert "new" in edit_check.honest_code_finding("x.py")["detail"]


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
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    assert _fire(payload(f), monkeypatch) == (0, "")


def test_a_violation_introduced_then_fixed_in_one_turn_is_never_reported(
        tmp_path, monkeypatch):
    """The whole reason for deferring. The turn's last word on the file is the
    only one worth an opinion."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    _fire(payload(f), monkeypatch)
    f.write_text(CLEAN)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")


def test_one_file_edited_twice_is_reported_once(tmp_path, monkeypatch):
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    _fire(payload(f), monkeypatch)
    _fire(payload(f), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert code == 2 and err.count("honest-code:") == 1


def test_two_files_each_get_their_own_report(tmp_path, monkeypatch):
    no_delegates(monkeypatch)
    for name in ("a.py", "b.py"):
        f = tmp_path / name; f.write_text("x = 1\n" * 1001)
        _fire(payload(f), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s1"}), monkeypatch)
    assert code == 2 and err.count("honest-code:") == 2


def test_the_same_finding_does_not_block_a_second_turn(tmp_path, monkeypatch):
    """A Stop hook that repeats itself is a Stop hook that never lets the turn
    end. Said once, then the choice not to act on it is the writer's."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")


def test_a_changed_file_is_reported_again(tmp_path, monkeypatch):
    """The guard is on the content, not the path. Editing the file and leaving
    a different violation is new news."""
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2
    f.write_text("y = 2\n" * 1002)
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch)[0] == 2


def test_a_file_deleted_before_the_turn_ends_is_not_a_finding(
        tmp_path, monkeypatch):
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    _fire(payload(f), monkeypatch)
    f.unlink()
    assert _fire(json.dumps({"session_id": "s1"}), monkeypatch) == (0, "")


def test_two_sessions_do_not_read_each_others_pending_writes(
        tmp_path, monkeypatch):
    no_delegates(monkeypatch)
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
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
    f = tmp_path / "big.py"; f.write_text("x = 1\n" * 1001)
    no_delegates(monkeypatch)
    report = edit_check.render(str(f), edit_check.findings_for(str(f), f.read_text()))
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
