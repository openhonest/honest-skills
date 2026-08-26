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


def test_a_broken_advisory_does_not_take_the_findings_with_it(monkeypatch):
    """The freshness and version notes are advice about the tooling. The
    findings beside them are the hook's actual job.

    Called plainly, a fault in either propagated out of render and the hook
    reported nothing at all, so a note about whether the principles were
    current would have stopped a real finding reaching a writer. Found by
    breaking the module and watching a live finding vanish, not by reading the
    code."""
    edit_check = load("edit_check")
    def boom(*a, **k):
        raise RuntimeError("the advisory is broken")
    monkeypatch.setattr(edit_check, "principles_note", boom)
    monkeypatch.setattr(edit_check, "stale_note", boom)
    out = edit_check.render("x.py", [{"verdict": "OUT_OF_SPEC",
                                      "indicator": "L1.21",
                                      "detail": "a real finding",
                                      "action": "fix it"}])
    assert "a real finding" in out


def test_a_broken_advisory_is_recorded_rather_than_swallowed(monkeypatch, tmp_path):
    """Swallowed in the turn, recorded in the trace. A fault nobody can see is
    the defect this project exists to name; a fault that breaks the writer's
    turn is worse. The trace is where it can be counted without costing a turn."""
    edit_check = load("edit_check")
    trace_hook = load("trace_hook")
    log = tmp_path / "t.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    monkeypatch.setattr(edit_check, "trace", trace_hook.trace)
    trace_hook.FIRED = True
    monkeypatch.setattr(edit_check, "principles_note",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
    monkeypatch.setattr(edit_check, "stale_note", lambda: "")
    edit_check.advisories()
    rows = [__import__("json").loads(l) for l in log.read_text().splitlines()]
    assert any(r["event"] == "advisory" and "principles_note raised" in r["why"]
               for r in rows)


def test_an_advisory_broken_for_a_day_stops_being_hidden(monkeypatch, tmp_path):
    """Swallowing a fault once and tracing it is handling it. Swallowing it on
    every run for a day and tracing it every time is a module that has been
    dead since Tuesday with nothing saying so.

    A swallowed-and-traced fault looks identical whether it happened once or
    four hundred times, and only one of those is fine. Timed from the first
    failure rather than counted, because a count only rises while something is
    running often enough to fail."""
    edit_check = load("edit_check")
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path))
    monkeypatch.setattr(edit_check, "stale_note", lambda: "")
    monkeypatch.setattr(edit_check, "principles_note",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("dead")))
    now = 1_000_000.0
    assert edit_check.advisories(now) == [], "one failure is not a broken module"
    assert edit_check.advisories(now + 3600) == []
    late = edit_check.advisories(now + edit_check.ADVISORY_BROKEN_AFTER + 1)
    assert late and "has been failing since" in late[0]
    assert "hiding the fault" in late[0]


def test_a_recovered_advisory_clears_its_clock(monkeypatch, tmp_path):
    """Otherwise the hook reports a fault it has already recovered from, and a
    reader learns to skip the line."""
    edit_check = load("edit_check")
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path))
    monkeypatch.setattr(edit_check, "stale_note", lambda: "")
    now = 2_000_000.0
    monkeypatch.setattr(edit_check, "principles_note",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("dead")))
    edit_check.advisories(now)
    monkeypatch.setattr(edit_check, "principles_note", lambda *a: "")
    edit_check.advisories(now + edit_check.ADVISORY_BROKEN_AFTER + 1)
    monkeypatch.setattr(edit_check, "principles_note",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("again")))
    assert edit_check.advisories(now + edit_check.ADVISORY_BROKEN_AFTER + 2) == []


def test_the_health_record_failing_does_not_break_the_hook(monkeypatch, tmp_path):
    """The record of whether a thing works cannot be allowed to break the thing."""
    edit_check = load("edit_check")
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(edit_check.Path, "write_text",
                        lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
    assert edit_check.advisory_health("x", False, 1.0) == 0.0


def test_the_vendor_gate_is_backed_by_something_other_than_the_local_hook():
    """This passed by accident. The daily sync job runs vendor_check for its
    own reasons, which happens to mean deleting .git/hooks/pre-push is caught
    within a day rather than never.

    A property nobody intended is a property nothing preserves: the next person
    to touch that job has no reason to know it is holding up something else.
    Written down here so that removing it fails a test instead of quietly
    removing a gate."""
    root = Path(__file__).resolve().parent.parent
    workflow = (root / ".github/workflows/vendor-sync.yml").read_text()
    assert "vendor_check.py" in workflow.replace("--sync", ""), \
        "nothing but the local pre-push hook now checks the vendored copy"


def test_every_claim_kind_the_docstring_names_has_a_pattern():
    """The docstring listed four claim kinds and the table held three, so
    "It is safe to change the config format now" exited zero. It survived
    because every test was written from the table, and a test written from the
    table cannot see a gap in the table.

    Held here rather than beside CLAIMS for the reason this file exists: a test
    living next to the thing it guards is deleted in the same edit as the thing
    it guards. Adding a kind to the prose without adding it to the code fails
    here, in a file nobody editing the patterns would naturally open."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "claims", Path(__file__).resolve().parent.parent / "tools/claims.py")
    claims = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(claims)
    named = {"unqualified negative", "completion", "absolute", "safety"}
    assert named <= set(claims.CLAIMS), \
        f"named in the docstring, absent from CLAIMS: {named - set(claims.CLAIMS)}"
