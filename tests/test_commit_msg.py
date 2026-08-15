"""Tests for the commit-message checker.

Each asserts a value rather than asserting that nothing raised. The checker
gates a commit, so a test that only proves it ran would certify nothing.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "commit_msg", ROOT / "tools" / "commit_msg.py")
commit_msg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(commit_msg)

GOOD = "Fix the stale token that emptied the traffic report\n\nThe collector held a token that expired on Tuesday.\n"


def run(text: str, tmp_path: Path, *flags: str) -> tuple[int, str]:
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(text)
    buf, argv = io.StringIO(), sys.argv
    sys.argv = ["commit_msg.py", *flags, str(f)]
    try:
        with redirect_stdout(buf):
            code = commit_msg.main()
    finally:
        sys.argv = argv
    return code, buf.getvalue()


# --- what passes ------------------------------------------------------------

def test_a_good_message_passes(tmp_path):
    code, out = run(GOOD, tmp_path)
    assert code == 0
    assert "commit message: ok" in out


def test_a_subject_with_no_body_passes_and_says_so(tmp_path):
    code, out = run("Fix the stale token in the collector\n", tmp_path)
    assert code == 0
    assert "No body." in out


def test_the_subject_is_printed_back_for_the_check_nothing_can_make(tmp_path):
    _, out = run(GOOD, tmp_path)
    assert "Fix the stale token that emptied the traffic report" in out
    assert "Does it say what changed?" in out


# --- what fails -------------------------------------------------------------

def test_an_over_long_subject_fails_with_its_length(tmp_path):
    subject = "Fix " + "the collector token problem " * 4
    code, out = run(subject + "\n", tmp_path)
    assert code == 1
    assert f"subject is {len(subject.strip())} characters" in out


def test_a_subject_at_the_limit_passes(tmp_path):
    r = commit_msg.analyse_message("x" * commit_msg.SUBJECT_LIMIT, "-")
    assert r["checks"]["subject_length"]["verdict"] == "pass"
    assert commit_msg.analyse_message(
        "x" * (commit_msg.SUBJECT_LIMIT + 1), "-")["checks"]["subject_length"]["verdict"] == "fail"


def test_a_missing_blank_line_after_the_subject_fails(tmp_path):
    code, out = run("Fix the token\nThe collector held a stale one.\n", tmp_path)
    assert code == 1
    assert "no blank line after the subject" in out


def test_an_empty_message_fails(tmp_path):
    code, out = run("\n\n", tmp_path)
    assert code == 1
    assert "no subject line" in out


def test_hedges_and_intensifiers_fail_with_the_words_found(tmp_path):
    code, out = run("Clearly fix the very significant token problem\n", tmp_path)
    assert code == 1
    assert "clearly" in out.lower() and "very" in out.lower()


def test_a_stray_em_dash_fails_and_a_pair_does_not(tmp_path):
    assert run("Fix the token — it was stale\n", tmp_path)[0] == 1
    assert run("Fix the token — the stale one — in the collector\n",
               tmp_path)[0] == 0


def test_an_ap_punctuation_defect_fails(tmp_path):
    code, out = run("Recover the badly-damaged token file\n", tmp_path)
    assert code == 1
    assert "badly-damaged" in out


# --- git's own template must not be scored ----------------------------------

def test_git_comment_lines_are_not_scored(tmp_path):
    """Left in, git's template is scored as the author's prose and the report
    describes git's words back to the author as though they were their own."""
    text = ("Fix the stale token in the collector\n"
            "# Please enter the commit message for your changes. Clearly this\n"
            "# is very significant — and it moves things.\n")
    code, out = run(text, tmp_path)
    assert code == 0, out
    assert "Please enter" not in out


def test_a_comment_line_does_not_count_as_the_blank_line(tmp_path):
    r = commit_msg.analyse_message("Fix the token\n# a comment\nA body line.\n", "-")
    assert r["checks"]["blank_line_after_subject"]["verdict"] == "fail"


# --- the checks it refuses to make ------------------------------------------

def test_the_structural_checks_are_reported_and_never_gate():
    checks = commit_msg.analyse_message(GOOD, "-")["checks"]
    for key in ("subject_carries_the_change", "bad_news_first"):
        assert checks[key]["verdict"] == "unassessed"
        assert checks[key]["gating"] is False
        assert checks[key]["reason"]


def test_the_clarity_index_is_not_applied():
    """A dozen-word subject is too small a sample for the index to mean
    anything, so no index appears rather than a number that looks measured."""
    assert "index" not in commit_msg.analyse_message(GOOD, "-")


def test_every_check_declares_whether_it_gates():
    assert all("gating" in c
               for c in commit_msg.analyse_message(GOOD, "-")["checks"].values())


# --- output shape -----------------------------------------------------------

def test_json_carries_every_check_whether_it_passed_or_failed(tmp_path):
    code, out = run("Clearly fix the token\n", tmp_path, "--json")
    r = json.loads(out)
    assert code == 1 and r["exit"] == 1
    assert r["gating_failures"] == ["hedges"]
    assert r["checks"]["intensifiers"]["verdict"] == "pass"
    assert r["checks"]["subject_length"]["length"] == len("Clearly fix the token")


def test_gating_failures_lists_only_gating_checks(tmp_path):
    r = commit_msg.analyse_message("Clearly fix the very significant token", "-")
    assert set(r["gating_failures"]) == {"hedges", "intensifiers"}
    assert all(r["checks"][k]["gating"] for k in r["gating_failures"])


def test_an_unreadable_path_exits_two_not_one(tmp_path):
    """A caller must be able to tell "this message is bad" from "I could not
    read the message"; collapsing them hides a broken hook setup."""
    argv = sys.argv
    sys.argv = ["commit_msg.py", str(tmp_path / "absent")]
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            code = commit_msg.main()
    finally:
        sys.argv = argv
    assert code == 2
    assert "cannot read" in buf.getvalue()


def test_an_unreadable_path_reports_the_error_in_json(tmp_path):
    argv = sys.argv
    sys.argv = ["commit_msg.py", "--json", str(tmp_path / "absent")]
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            code = commit_msg.main()
    finally:
        sys.argv = argv
    r = json.loads(buf.getvalue())
    assert (code, r["exit"], r["verdict"]) == (2, 2, "unreadable")
    assert "FileNotFoundError" in r["error"]


def test_stdin_is_read_when_no_path_is_given():
    argv, stdin = sys.argv, sys.stdin
    sys.argv, sys.stdin = ["commit_msg.py"], io.StringIO("Clearly fix it\n")
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            code = commit_msg.main()
    finally:
        sys.argv, sys.stdin = argv, stdin
    assert code == 1
    assert "hedges" in buf.getvalue().lower()


# --- run it the way a hook does ---------------------------------------------

def test_the_script_runs_as_a_hook_and_exits_nonzero(tmp_path):
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text("Clearly fix the token\n")
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "commit_msg.py"), str(f)],
                       capture_output=True, text=True)
    assert p.returncode == 1
    assert "hedges" in p.stdout.lower()


def test_the_script_runs_as_a_hook_and_exits_zero(tmp_path):
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(GOOD)
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "commit_msg.py"), str(f)],
                       capture_output=True, text=True)
    assert p.returncode == 0
    assert "commit message: ok" in p.stdout


def test_a_code_span_is_a_mention_not_a_use(tmp_path):
    """A commit that fixes a hyphenated -ly adverb has to name the thing it
    fixed. A checker that cannot tell a mention from a use makes its own
    defects unreportable."""
    code, out = run("Set `badly-damaged` solid, per AP\n", tmp_path)
    assert code == 0, out


def test_the_same_defect_outside_a_code_span_still_fails(tmp_path):
    assert run("Set badly-damaged solid, per AP\n", tmp_path)[0] == 1
