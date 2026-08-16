"""Tests for the unwritten-function hook.

Half of these assert that it stays quiet. An empty body is correct far more
often than it is a stub, and a hook that fires on `@abstractmethod` is a hook
nobody keeps.
"""
from __future__ import annotations

import importlib.util
import io
import json
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


def run_hook(raw, monkeypatch):
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(sys, "stderr", err)
    return sc.main(), err.getvalue()


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
    p = subprocess.run([sys.executable, str(ROOT / "hooks" / "stub_check.py")],
                       input=payload(f), capture_output=True, text=True)
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
    row = json.loads(log.read_text())
    assert row["verdict"] == "declined" and "parsed, 0 found" in row["why"]


def test_a_firing_records_how_it_decided(tmp_path, monkeypatch):
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    f = tmp_path / "gw.js"; f.write_text("function charge(c){}")
    run_hook(payload(f), monkeypatch)
    row = json.loads(log.read_text())
    assert row["verdict"] == "fired" and "matched, 1 found" in row["why"]
