"""Tests for the unwritten-function hook.

Half of these assert that it stays quiet. An empty body is correct far more
often than it is a stub, and a hook that fires on `@abstractmethod` is a hook
nobody keeps.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "stub_check", ROOT / "hooks" / "stub_check.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)


def payload(path):
    return json.dumps({"session_id": "s", "tool_input": {"file_path": str(path)}})


@pytest.fixture(autouse=True)
def _isolated_pending(tmp_path, monkeypatch):
    """Each test gets its own pending state, or one test's deferred write
    surfaces inside the next test's Stop."""
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "pending"))


def _fire(raw, monkeypatch):
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(sys, "stderr", err)
    return sc.main(), err.getvalue()


def run_hook(raw, monkeypatch):
    """One write, then the Stop that settles it, as Claude Code runs them.

    The write firing is silent by design since 0.22.0. A stub written and then
    filled in during the same turn is not a stub, and reporting it was the same
    defect the edit hook had.
    """
    _fire(raw, monkeypatch)
    try:
        session = json.loads(raw).get("session_id")
    except (ValueError, TypeError, AttributeError):
        session = None
    return _fire(json.dumps({"session_id": session}), monkeypatch)


# --- what a stub is ---------------------------------------------------------

@pytest.mark.parametrize("src", [
    "def charge(card, amount):\n    pass\n",
    "def charge(c, a):\n    ...\n",
    "def charge(c, a):\n    return\n",
    "def charge(c, a):\n    return None\n",
    'def charge(c, a):\n    """Charge the card."""\n',
    "async def charge(c):\n    pass\n",
    "class Gateway:\n    def charge(self, c):\n        pass\n",
])
def test_a_silently_unwritten_function_is_found(src):
    """Each of these returns None to a caller that cannot tell "not written"
    from "nothing to do"."""
    assert sc.python_stubs(src)


def test_a_docstring_alone_is_still_empty():
    """Describing what a function would do is not doing it, and it is the
    commonest way a stub gets written."""
    assert sc.python_stubs('def f():\n    """Does the thing."""\n')


# --- what an empty body is allowed to be ------------------------------------

@pytest.mark.parametrize("src", [
    "from abc import abstractmethod\n"
    "class G:\n    @abstractmethod\n    def charge(self, c): ...\n",
    "from typing import Protocol\n"
    "class G(Protocol):\n    def charge(self, c) -> None: ...\n",
    "from typing import overload\n"
    "@overload\ndef f(x: int) -> int: ...\ndef f(x): return x\n",
    "import abc\nclass G(abc.ABC):\n    def charge(self, c): ...\n",
    "import typing\nclass G:\n    @typing.overload\n    def f(self, x): ...\n",
])
def test_a_declaration_is_not_a_stub(src):
    """An empty body is the point in each of these. Firing on them makes the
    hook unusable inside a day."""
    assert sc.python_stubs(src) == []


def test_an_exception_class_is_not_a_stub():
    """`pass` is the whole definition."""
    assert sc.python_stubs("class ChargeFailed(Exception):\n    pass\n") == []


@pytest.mark.parametrize("src", [
    "def charge(c, a):\n    return c.debit(a)\n",
    "def charge(c, a):\n    return 0\n",
    "def charge(c, a):\n    return []\n",
    "def charge(c, a):\n    log(a)\n    return None\n",
])
def test_a_function_that_does_something_is_left_alone(src):
    """`return 0` is a decision someone made, and this cannot tell it from a
    placeholder, so it does not try."""
    assert sc.python_stubs(src) == []


def test_a_file_that_will_not_parse_says_so_rather_than_guessing():
    """A hook sees half-typed files constantly, and a partial reading of one
    is worth less than saying nothing."""
    assert sc.python_stubs("def f(:\n    pass") is None


def test_unparsed_produces_no_findings(tmp_path):
    how, stubs = sc.findings_for("x.py", "def f(:\n  pass")
    assert (how, stubs) == ("unparsed", [])


# --- the other languages, matched rather than parsed ------------------------

@pytest.mark.parametrize("src", [
    "function charge(card){}",
    "function charge(card){ // TODO\n}",
    "func Charge(c Card) error {}",
    "public void charge(Card c) {}",
    "private static int Charge(Card c) {}",
    "function charge(c){return null;}",
    "function charge(c){ return; }",
    "func Charge(c Card) error { return nil }",
])
def test_a_brace_language_stub_is_matched(src):
    assert sc.matched_stubs(src)


@pytest.mark.parametrize("src", [
    "function charge(c){ return c.debit(1); }",
    "function charge(c){ return 0; }",
    "const x = {};",
    "if (ok) {}",
    "for (;;) {}",
])
def test_a_brace_body_that_does_something_is_left_alone(src):
    """`if (ok) {}` is an empty branch, not an unwritten function, and there is
    no function header in front of it."""
    assert sc.matched_stubs(src) == []


def test_returning_null_is_the_same_shape_as_returning_none():
    """It caught `pass` in Python and let `return null;` through in JavaScript
    for the identical defect."""
    assert sc.matched_stubs("function charge(c){return null;}")
    assert sc.python_stubs("def charge(c):\n    return None\n")


# --- it says how it decided -------------------------------------------------

def test_python_is_reported_as_parsed():
    how, stubs = sc.findings_for("a.py", "def f():\n    pass\n")
    assert how == "parsed" and len(stubs) == 1


def test_another_language_is_reported_as_matched():
    how, stubs = sc.findings_for("a.js", "function f(){}")
    assert how == "matched" and len(stubs) == 1


def test_an_unsupported_extension_is_unchecked():
    assert sc.findings_for("a.md", "function f(){}") == ("unchecked", [])


def test_the_report_says_which_it_was():
    """A reader who cannot tell a parsed answer from a matched one cannot
    weigh it."""
    out = sc.render("a/x.js", "matched", [(1, "function f(){}")])
    assert "matched by pattern" in out and "approximate" in out
    out = sc.render("a/x.py", "parsed", [(1, "f")])
    assert "parsed" in out and "approximate" not in out


def test_the_report_gives_the_language_its_own_remedy():
    for name, expected in (("x.py", "NotImplementedError"),
                           ("x.js", "throw new Error"),
                           ("x.go", "panic"),
                           ("x.rs", "todo!"),
                           ("x.java", "UnsupportedOperationException"),
                           ("x.cs", "NotImplementedException"),
                           ("x.rb", "raise NotImplementedError")):
        out = sc.render(name, "parsed", [(1, "f")])
        assert expected in out and sc.MARKER in out


def test_the_report_says_why_it_matters():
    out = sc.render("x.py", "parsed", [(1, "f")])
    assert "cannot tell" in out and "arrives somewhere else" in out


def test_an_unknown_extension_still_renders_a_remedy():
    """render is reachable with a suffix that has no entry, and a finding with
    no action is a complaint."""
    out = sc.render("x.zig", "parsed", [(1, "f")])
    assert sc.MARKER in out


# --- run it the way Claude Code does ----------------------------------------

def test_a_stub_surfaces_on_stderr_with_exit_2(tmp_path, monkeypatch):
    f = tmp_path / "gw.py"; f.write_text("def charge(c, a):\n    pass\n")
    code, err = run_hook(payload(f), monkeypatch)
    assert code == 2
    assert "SILENT_STUB" in err and "NotImplementedError" in err


def test_a_function_that_raises_is_not_a_stub(tmp_path, monkeypatch):
    """A body containing a raise is not an empty body, so it is never flagged.
    That is true whatever the message says, which is why the wording is a
    suggestion rather than a test."""
    f = tmp_path / "gw.py"
    f.write_text('def charge(c, a):\n    raise NotImplementedError("CODE NOT WRITTEN")\n')
    assert run_hook(payload(f), monkeypatch) == (0, "")


@pytest.mark.parametrize("message", [
    '"CODE NOT WRITTEN"', '"INCOMPLETE CODE: charge cannot answer"', '"todo"', "",
])
def test_any_wording_satisfies_it(message):
    """One repository here was told to use INCOMPLETE CODE. A hook that
    insisted on its own string would fight that instruction."""
    assert sc.python_stubs(f"def charge(c):\n    raise NotImplementedError({message})\n") == []


def test_one_good_stub_does_not_silence_the_others(tmp_path, monkeypatch):
    """A file-level check for the marker suppressed the whole file, so two
    silent functions went unreported behind one that raised correctly."""
    f = tmp_path / "gw.py"
    f.write_text('def good(c):\n    raise NotImplementedError("CODE NOT WRITTEN")\n\n'
                 'def silent_one(c):\n    pass\n\ndef silent_two(c):\n    pass\n')
    code, err = run_hook(payload(f), monkeypatch)
    assert code == 2
    assert "silent_one" in err and "silent_two" in err and "good" not in err


def test_a_written_file_is_silent(tmp_path, monkeypatch):
    f = tmp_path / "gw.py"; f.write_text("def charge(c, a):\n    return c.debit(a)\n")
    assert run_hook(payload(f), monkeypatch) == (0, "")


def test_a_pyi_stub_file_is_silent(tmp_path, monkeypatch):
    """A .pyi is nothing but empty bodies, by design."""
    f = tmp_path / "gw.pyi"; f.write_text("def charge(c: int, a: int) -> None: ...\n")
    assert run_hook(payload(f), monkeypatch) == (0, "")


@pytest.mark.parametrize("name", ["notes.md", "data.json", "uv.lock"])
def test_a_file_this_does_not_check_is_silent(tmp_path, monkeypatch, name):
    f = tmp_path / name; f.write_text("function f(){}")
    assert run_hook(payload(f), monkeypatch) == (0, "")


def test_a_missing_file_is_not_a_finding(tmp_path, monkeypatch):
    assert run_hook(payload(tmp_path / "gone.py"), monkeypatch) == (0, "")


def test_malformed_input_does_nothing(monkeypatch):
    assert run_hook("not json", monkeypatch) == (0, "")


def test_no_file_path_does_nothing(monkeypatch):
    assert run_hook(json.dumps({"tool_input": {}}), monkeypatch) == (0, "")


def test_a_file_that_will_not_parse_is_silent(tmp_path, monkeypatch):
    f = tmp_path / "half.py"; f.write_text("def charge(:\n    pass")
    assert run_hook(payload(f), monkeypatch) == (0, "")


def test_it_runs_as_a_subprocess_the_way_claude_code_does(tmp_path):
    f = tmp_path / "gw.py"; f.write_text("def charge(c, a):\n    pass\n")
    env = {**os.environ, "HONEST_PENDING_DIR": str(tmp_path / "pending")}
    hook = [sys.executable, str(ROOT / "hooks" / "stub_check.py")]
    subprocess.run(hook, input=payload(f), capture_output=True, text=True, env=env)
    p = subprocess.run(hook, input=json.dumps({"session_id": "s"}),
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2 and "SILENT_STUB" in p.stderr and p.stdout == ""


def test_it_is_fast_enough_to_sit_in_an_edit_loop(tmp_path):
    import time
    f = tmp_path / "gw.py"; f.write_text("def charge(c, a):\n    return c.debit(a)\n")
    start = time.monotonic()
    subprocess.run([sys.executable, str(ROOT / "hooks" / "stub_check.py")],
                   input=payload(f), capture_output=True, text=True)
    assert time.monotonic() - start < 2.0


# --- the branches a first pass misses ---------------------------------------

def test_a_dotted_decorator_is_recognised():
    assert sc.dotted(__import__("ast").parse("@a.b.c\ndef f(): ...").body[0]
                     .decorator_list[0]) == "a.b.c"


def test_a_call_decorator_resolves_to_its_function():
    tree = __import__("ast").parse("@lru_cache()\ndef f(): pass")
    assert sc.dotted(tree.body[0].decorator_list[0]) == "lru_cache"


def test_a_decorator_this_cannot_name_is_not_an_exclusion():
    """A subscript decorator has no dotted name, and an unnameable decorator
    must not silently excuse a stub."""
    tree = __import__("ast").parse("@registry[0]\ndef f(): pass")
    assert sc.dotted(tree.body[0].decorator_list[0]) == ""
    assert sc.python_stubs("@registry[0]\ndef f(): pass")


def test_a_single_statement_that_does_work_is_not_empty():
    """The last branch of body_is_empty: one statement that is neither pass,
    nor ellipsis, nor a bare return."""
    assert sc.body_is_empty(__import__("ast").parse("def f():\n    log()").body[0].body) is False


def test_a_clean_file_records_that_it_ran(tmp_path, monkeypatch):
    """Silence alone cannot tell "ran and found nothing" from "never ran"."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    f = tmp_path / "gw.py"; f.write_text("def charge(c, a):\n    return c.debit(a)\n")
    run_hook(payload(f), monkeypatch)
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert any(r["verdict"] == "declined" and "parsed, 0 found" in r["why"]
               for r in rows)
    assert any("none had anything to say" in r["why"] for r in rows)


def test_a_firing_records_how_it_decided(tmp_path, monkeypatch):
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    f = tmp_path / "gw.js"; f.write_text("function charge(c){}")
    run_hook(payload(f), monkeypatch)
    row = json.loads(log.read_text().splitlines()[-1])
    assert row["verdict"] == "fired" and "matched, 1 found" in row["why"]


# --- a Then step that checks nothing ----------------------------------------

@pytest.mark.parametrize("body", [
    "    pass\n",
    '    result = ctx["result"]\n',
    "    ctx['n']\n",
])
def test_a_then_step_that_asserts_nothing_is_found(body):
    """Worse than a stub. A stub returns None and something downstream
    notices; this publishes a pass and the suite counts it."""
    src = f'from pytest_bdd import then\n@then("the count is 1000")\ndef _(ctx):\n{body}'
    assert sc.python_stubs(src)


@pytest.mark.parametrize("body", [
    '    assert ctx["n"] == 1000\n',
    '    self.assertEqual(ctx["n"], 1000)\n',
    "    with pytest.raises(ValueError):\n        go()\n",
    '    expect(ctx["n"]).to_equal(1000)\n',
    '    raise AssertionError("no")\n',
    "    self.fail('not yet')\n",
])
def test_a_then_step_that_can_fail_is_left_alone(body):
    src = f'from pytest_bdd import then\n@then("x")\ndef _(ctx):\n{body}'
    assert sc.python_stubs(src) == []


@pytest.mark.parametrize("step", ["given", "when"])
def test_given_and_when_may_assert_nothing(step):
    """They set things up. Only Then is the assertion."""
    src = (f'from pytest_bdd import {step}\n@{step}("a todo")\n'
           f'def _(ctx):\n    ctx["t"] = make()\n')
    assert sc.python_stubs(src) == []


def test_a_helper_that_asserts_internally_is_a_miss_not_an_alarm():
    """Calling a helper that asserts inside it is invisible here. The errors
    fall toward missing one, never toward blocking a real check."""
    src = ('from pytest_bdd import then\n@then("x")\n'
           'def _(ctx):\n    check_invariants(ctx)\n')
    assert sc.python_stubs(src)          # a miss, recorded rather than hidden


def test_the_report_says_why_a_then_step_is_worse():
    out = sc.render("x.py", "parsed", [(1, "_ (Then step, asserts nothing)")])
    assert "publishes a pass" in out and "Write the assertion" in out


def test_the_report_omits_that_line_for_an_ordinary_stub():
    out = sc.render("x.py", "parsed", [(1, "charge")])
    assert "publishes a pass" not in out


def test_a_with_block_that_is_not_an_assertion_does_not_count():
    """`with open(...)` is doing work, not checking it. Treating any context
    manager as an assertion would let every file-handling step through."""
    src = ('from pytest_bdd import then\n@then("x")\n'
           'def _(ctx):\n    with open(ctx["path"]) as fh:\n        ctx["text"] = fh.read()\n')
    assert sc.python_stubs(src)


def test_a_multi_item_with_is_searched_past_the_first():
    """`with open(p) as fh, pytest.raises(ValueError):` checks something, and
    the checking half is not the first item."""
    src = ('from pytest_bdd import then\n@then("x")\n'
           'def _(ctx):\n    with open(ctx["p"]) as fh, pytest.raises(ValueError):\n'
           '        go(fh)\n')
    assert sc.python_stubs(src) == []


# --- the settled file, not the file mid-edit --------------------------------

def test_a_write_says_nothing_until_the_turn_ends(tmp_path, monkeypatch):
    f = tmp_path / "gw.py"; f.write_text("def charge(c, a):\n    pass\n")
    assert _fire(payload(f), monkeypatch) == (0, "")


def test_a_stub_filled_in_before_the_turn_ends_is_never_reported(
        tmp_path, monkeypatch):
    """Writing the signature first and the body second is how code gets
    written. Reporting the intermediate state calls that a defect."""
    f = tmp_path / "gw.py"; f.write_text("def charge(c, a):\n    pass\n")
    _fire(payload(f), monkeypatch)
    f.write_text("def charge(c, a):\n    return c.debit(a)\n")
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s"}), monkeypatch) == (0, "")


def test_a_stub_left_standing_is_reported_once(tmp_path, monkeypatch):
    f = tmp_path / "gw.py"; f.write_text("def charge(c, a):\n    pass\n")
    _fire(payload(f), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s"}), monkeypatch)
    assert code == 2 and "SILENT_STUB" in err
    _fire(payload(f), monkeypatch)
    assert _fire(json.dumps({"session_id": "s"}), monkeypatch) == (0, "")


def test_a_file_deleted_before_the_turn_ends_is_not_a_finding(
        tmp_path, monkeypatch):
    f = tmp_path / "gw.py"; f.write_text("def charge(c, a):\n    pass\n")
    _fire(payload(f), monkeypatch)
    f.unlink()
    assert _fire(json.dumps({"session_id": "s"}), monkeypatch) == (0, "")


def test_two_files_each_get_their_own_report(tmp_path, monkeypatch):
    for name in ("a.py", "b.py"):
        f = tmp_path / name; f.write_text("def charge(c, a):\n    pass\n")
        _fire(payload(f), monkeypatch)
    code, err = _fire(json.dumps({"session_id": "s"}), monkeypatch)
    assert code == 2 and err.count("SILENT_STUB") == 2


def test_a_session_whose_stop_never_runs_gets_told_rather_than_going_silent(
        tmp_path, monkeypatch):
    """Same drain as the edit hook, for the same reason: a session whose Stop
    registration predates the hook being added there defers every write and
    settles none, and the check goes silently dead."""
    import os, time
    f = tmp_path / "stranded.py"; f.write_text("def charge(c, a):\n    pass\n")
    old = time.time() - 700
    os.utime(f, (old, old))
    sc.write_state("stub", "s", {"pending": [{"path": str(f), "at": old}],
                                 "reported": {}})
    other = tmp_path / "fresh.py"
    other.write_text("def ok(c):\n    return c\n")
    code, err = _fire(payload(other), monkeypatch)
    assert code == 2
    assert "the Stop hook is not running in this session" in err
    assert "stranded.py" in err and "SILENT_STUB" in err


def test_a_stranded_stub_that_was_filled_in_is_dropped_quietly(
        tmp_path, monkeypatch):
    import os, time
    f = tmp_path / "filled.py"; f.write_text("def charge(c, a):\n    return c\n")
    old = time.time() - 700
    os.utime(f, (old, old))
    sc.write_state("stub", "s", {"pending": [{"path": str(f), "at": old}],
                                 "reported": {}})
    other = tmp_path / "fresh.py"
    other.write_text("def ok(c):\n    return c\n")
    assert _fire(payload(other), monkeypatch) == (0, "")
    assert sc.stranded("stub", "s") == []


def test_the_remedy_names_the_case_where_raising_is_wrong(tmp_path, monkeypatch):
    """`raise NotImplementedError` is right for a Protocol method and wrong for
    the do-nothing half of a dispatch pair, which is the shape rule 1 produces
    every time a conditional becomes a table and only one branch does work. A
    session followed it verbatim there and every successful render would have
    raised."""
    f = tmp_path / "gw.py"; f.write_text("def do_nothing(c, a):\n    pass\n")
    code, err = run_hook(payload(f), monkeypatch)
    assert code == 2
    assert "do-nothing half of a dispatch pair" in err
    assert "do NOT raise" in err
