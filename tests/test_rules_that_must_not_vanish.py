"""Rules that must still be enforced, tested away from the code enforcing them.

This file exists because of one commit on 2026-08-25. The hard-wrap check
shipped at 08:48 and was gone by 09:01, removed inside a commit whose subject
was how long the Bash hook took to walk the home tree. The commit message never
mentioned removing it.

Deleting the check alone would have failed the suite. The same commit rewrote
the test that would have caught it, so that it asserted markdown is not a
checked extension. Check and evidence travelled together, the suite passed, and
afterwards nothing anywhere disagreed with the deletion. Six hours later
another session hard-wrapped markdown twice, the second time in the first commit
of a repository built to hold the rule.

A test that lives beside the thing it guards can be deleted in the same edit as
the thing it guards. So these live apart from it, they name the rule rather than
the implementation, and they say what it cost when the rule went missing. They
are deliberately few. A file that grew to cover everything would be a second
test suite, and nobody would notice a deletion from it either.

Adding one here is a judgment that a rule has been lost once and must not be
lost silently again.
"""
import importlib.util
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WRAPPED = ("This is a paragraph that someone has broken across two\n"
           "lines at about eighty columns, which is the thing.\n")


def test_a_hard_wrap_is_still_a_finding():
    """Adam's instruction has been in capitals for months and prose alone never
    held it. On 2026-08-25 he said it four times in one morning: four generated
    files wrapped at eighty columns, fixed, and then the replies reporting the
    fix were wrapped too."""
    edit_check = load("edit_check")
    assert edit_check.hard_wrap_finding("n.md", WRAPPED) is not None


def test_markdown_is_still_a_type_the_bash_sweep_collects(tmp_path):
    """The rule was wired to Write and Edit for a day while one session wrote
    almost every markdown file through a shell heredoc. It had never once been
    applied to the way that session writes, so both hard wraps that day went in
    under a check that was live and looking elsewhere.

    A check wired to some of the ways a file can be written is not a check on
    the file."""
    bw = load("bash_write_check")
    (tmp_path / "notes.md").write_text("hello")
    found, finished = bw.recently_written(str(tmp_path), 120)
    assert finished and found == [str(tmp_path / "notes.md")]


def test_a_paragraph_on_one_line_is_still_silent():
    """The other half of the rule. A check that fires on correct prose gets
    turned off, and then the rule is gone by a different route."""
    edit_check = load("edit_check")
    long_line = ("This is a paragraph on a single line, however long it runs, "
                 "and the editor is left to wrap it where it likes.\n")
    assert edit_check.hard_wrap_finding("n.md", long_line) is None


def test_a_boundary_declaration_is_still_not_a_suppression(tmp_path, monkeypatch):
    """Merging the analyzer's two lists told a writer four times in one day
    that its file was not conforming code for having said where its edges are.
    The function it named had a single read of a corpus file for a body.

    An author overriding a rule is a suppression. A project stating where its
    I/O sits is answering the rule that asks. Kept here because the two lists
    look interchangeable to anyone who has not been told otherwise."""
    edit_check = load("edit_check")
    monkeypatch.setattr(edit_check, "changed_lines", lambda p: None)
    f = tmp_path / "edge.py"
    f.write_text("def read():\n    return open('x').read()\n")
    got = edit_check.honest_code_finding(str(f), {
        "clauses": [{"code": "L1.21.4", "decided": True, "findings": [],
                     "declared": [{"line": 1, "reason": "reads the corpus"}]}],
        "decided_clauses": 1})
    assert got is not None, "a declaration now reports nothing at all"
    assert got["verdict"] == "DECLARED", \
        f"a declaration reads as {got['verdict']}; it is not a suppression"


def test_the_trace_still_records_only_hook_firings():
    """Anything that called trace() used to be recorded. A test run put 223 rows
    in the live file and every fire rate read off it for a day was contaminated;
    four days later a probe run by hand inflated a standing count. The gate is
    the only thing keeping the measurement free of the people measuring."""
    trace_hook = load("trace_hook")
    assert hasattr(trace_hook, "FIRED"), \
        "the firing gate has gone; anything calling trace() is recorded again"
    assert trace_hook.FIRED is False, "the gate must start closed"
