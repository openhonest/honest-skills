#!/usr/bin/env python3
"""Make an unwritten function say so, instead of returning nothing quietly.

A PostToolUse hook on Write and Edit.

WHY A STUB IS A SILENT FAILURE

    def charge(card, amount):
        pass

That function is indistinguishable, from the caller's side, from one that ran
and had nothing to do. It returns None, the caller carries on, and the first
evidence that the payment never happened arrives somewhere else entirely. The
same shape returns null, an empty list, or zero in every other language.

The fix is one line and it converts an invisible gap into a loud one:

    def charge(card, amount):
        raise NotImplementedError("CODE NOT WRITTEN")

Nothing is lost by raising. Code that was never written cannot work, so the
only thing the quiet version buys is a later, more confusing failure somewhere
that has no idea why its input is wrong.

WHAT AN EMPTY BODY IS ALLOWED TO BE, WHICH IS MOST OF THE HARD PART

An empty body is correct far more often than it is a stub, and firing on those
would make this unusable within a day:

  - `@abstractmethod`, which exists to have no body
  - a `Protocol` or `typing.Protocol` member, which is a type declaration
  - an `@overload` signature, which is a type declaration with a sibling
  - an exception class, where `pass` is the whole definition
  - a `.pyi` stub file, which is nothing but empty bodies by design. This one
    needs no code: `.pyi` is not in the extension list, so the file is never
    opened. A guard for it was written anyway and was unreachable.
  - a deliberately empty handler with `# noqa` or an explanatory comment

Each of those is excluded by name below. Anything this cannot tell apart is
left alone: the errors fall toward missing a stub, never toward blocking a
correct empty body.

PYTHON IS PARSED, THE REST ARE MATCHED, AND IT SAYS WHICH

Python goes through `ast`, so the answer is exact and a syntax error is an
honest UNPARSED rather than a guess. The other languages get a narrow pattern
over a function header followed by an empty body, which is approximate. The
report names which of the two you got, because a reader who cannot tell a
parsed answer from a matched one cannot weigh it.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pending import (defer, drop, entries, read_state,  # noqa: E402
                     session_key, stranded, write_state)
from trace_hook import trace  # noqa: E402

# A suggested wording, not a test. What this requires is that the function
# RAISE; the words are a project's own choice, and one repository here settled
# on "INCOMPLETE CODE" by instruction. A body containing any raise is not an
# empty body, so it is never flagged, whatever it says.
#
# There was a file-level check for this marker too, and it was worse than
# useless: one correctly raising stub silenced every other stub in the same
# file. Two silent functions went unreported behind one good one.
MARKER = "CODE NOT WRITTEN"
KIND = "stub"

REMEDY = {
    ".py": f'raise NotImplementedError("{MARKER}")',
    ".js": f'throw new Error("{MARKER}");',
    ".jsx": f'throw new Error("{MARKER}");',
    ".ts": f'throw new Error("{MARKER}");',
    ".tsx": f'throw new Error("{MARKER}");',
    ".go": f'panic("{MARKER}")',
    ".rs": f'todo!("{MARKER}")',
    ".java": f'throw new UnsupportedOperationException("{MARKER}");',
    ".cs": f'throw new NotImplementedException("{MARKER}");',
    ".rb": f'raise NotImplementedError, "{MARKER}"',
}

# A Then step, in pytest-bdd and in behave. Given and When set things up and
# are allowed to assert nothing; Then is the assertion, and one that asserts
# nothing does not merely fail to check, it publishes a pass.
THEN_DECORATORS = frozenset({"then", "pytest_bdd.then", "behave.then"})

# What counts as actually checking something.
ASSERTING_CALLS = re.compile(
    r"^(?:assert|expect|should|verify|fail|raises)|"
    r"(?:\.assert|\.expect|\.should|\.fail|\.raises)", re.I)


def asserts_something(node: ast.AST) -> bool:
    """True when the body can fail.

    A bare `assert`, a `raise`, a `with pytest.raises(...)`, or a call whose
    name says it checks: assertEqual, expect_that, should_be, self.fail.
    Calling a helper that asserts internally is invisible here, which is a
    miss rather than a false alarm.
    """
    for sub_node in ast.walk(node):
        if isinstance(sub_node, (ast.Assert, ast.Raise)):
            return True
        if isinstance(sub_node, ast.Call) and ASSERTING_CALLS.search(dotted(sub_node)):
            return True
        if isinstance(sub_node, (ast.With, ast.AsyncWith)):
            for item in sub_node.items:
                if ASSERTING_CALLS.search(dotted(item.context_expr)):
                    return True
    return False


# Decorators that mean the empty body is the point.
DECLARATION_DECORATORS = frozenset({
    "abstractmethod", "abstractproperty", "overload",
    "abc.abstractmethod", "typing.overload",
})

# Base classes whose members are declarations rather than implementations.
DECLARATION_BASES = frozenset({"Protocol", "typing.Protocol", "ABC", "abc.ABC"})


def dotted(node: ast.AST) -> str:
    """`typing.overload` from an Attribute, `overload` from a Name, else ""."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted(node.value)}.{node.attr}" if dotted(node.value) else node.attr
    if isinstance(node, ast.Call):
        return dotted(node.func)
    return ""


def body_is_empty(body: list[ast.stmt]) -> bool:
    """True when the body does nothing at all.

    A lone docstring counts as empty: describing what a function would do is
    not doing it, and that is the commonest way a stub gets written.
    """
    statements = [s for s in body
                  if not (isinstance(s, ast.Expr)
                          and isinstance(s.value, ast.Constant)
                          and isinstance(s.value.value, str))]
    if not statements:
        return True                       # docstring only, or nothing
    if len(statements) > 1:
        return False
    only = statements[0]
    if isinstance(only, ast.Pass):
        return True
    if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant):
        return only.value.value is Ellipsis
    if isinstance(only, ast.Return):
        # `return`, `return None`. A `return 0` or `return []` is a decision
        # someone made and this cannot tell it from a placeholder.
        return only.value is None or (
            isinstance(only.value, ast.Constant) and only.value.value is None)
    return False


def python_stubs(source: str) -> list[tuple[int, str]] | None:
    """(line, name) for each function that is silently unwritten.

    None when the file will not parse. A hook sees half-typed files constantly
    and a partial reading of one is worth less than saying so.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    declaration_classes: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = {dotted(b) for b in node.bases}
            if bases & DECLARATION_BASES:
                declaration_classes.update(ast.walk(node))

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node in declaration_classes:
            continue
        decorators = {dotted(d) for d in node.decorator_list}
        if decorators & DECLARATION_DECORATORS:
            continue
        if body_is_empty(node.body):
            found.append((node.lineno, node.name))
        elif decorators & THEN_DECORATORS and not asserts_something(node):
            # It does work and checks nothing, so it cannot fail. That is
            # worse than an empty stub: a stub returns None and something
            # downstream notices, while this publishes a pass.
            found.append((node.lineno, f"{node.name} (Then step, asserts nothing)"))
    return found


# A function header followed immediately by a closing brace, with only
# whitespace or a comment between. Deliberately narrow: anything with a
# statement in it is somebody's decision, not a placeholder.
BRACE_STUB = re.compile(
    r"^[^\n]*\b(?:function|func|fn|def|public|private|protected|static)\b"
    r"[^\n{;]*\{\s*(?://[^\n]*\s*)?"
    # An empty body, or one that returns the language's own nothing. The
    # second was missing at first, which caught `pass` in Python and let
    # `return null;` through in JavaScript for the identical shape.
    r"(?:return\s*(?:null|undefined|nil)?\s*;?\s*)?\}",
    re.M)


def matched_stubs(source: str) -> list[tuple[int, str]]:
    """Approximate, for languages this does not parse."""
    return [(source[:m.start()].count("\n") + 1, m.group(0).strip()[:48])
            for m in BRACE_STUB.finditer(source)]


def findings_for(path: str, source: str) -> tuple[str, list[tuple[int, str]]]:
    """(how it was decided, the stubs). how is "parsed", "matched" or "unparsed"."""
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        found = python_stubs(source)
        return ("unparsed", []) if found is None else ("parsed", found)
    if suffix in REMEDY:
        return "matched", matched_stubs(source)
    return "unchecked", []


def render(path: str, how: str, stubs: list[tuple[int, str]]) -> str:
    name = os.path.basename(path)
    remedy = REMEDY.get(Path(path).suffix.lower(), f'raise an error saying "{MARKER}"')
    lines = [f"honest-code: {len(stubs)} unwritten function(s) in {name}, "
             f"{'parsed' if how == 'parsed' else 'matched by pattern'}"]
    for line, what in stubs:
        lines.append(f"  SILENT_STUB  {name}:{line}  {what}")
    lines.append(f"      make it say so: {remedy}")
    lines.append("      An empty body returns None to a caller that cannot tell "
                 "'not written' from 'nothing to do', so the first evidence "
                 "arrives somewhere else.")
    if any("asserts nothing" in what for _, what in stubs):
        lines.append("      A Then step that checks nothing does not merely "
                     "fail to check. It publishes a pass, and the suite counts "
                     "it. Write the assertion, or raise until you do.")
    if how == "matched":
        lines.append("      Matched by pattern rather than parsed, so this is "
                     "approximate. Python is the only language parsed here.")
    return "\n".join(lines)


def assess(path: str) -> tuple[str, str] | None:
    """The report for one settled file, with the content it describes."""
    try:
        source = Path(path).read_text(errors="replace")
    except OSError:
        return None
    how, stubs = findings_for(path, source)
    trace("Stop:stub", "fired" if stubs else "declined",
          f"{how}, {len(stubs)} found", file=path)
    if not stubs:
        return None
    return (render(path, how, stubs),
            hashlib.sha256(source.encode()).hexdigest())


def settle(session: str) -> str:
    """Assess every file this turn wrote, once each, at its final state.

    A stub written and then filled in during the same turn is not a stub, and
    reporting it was the same defect the edit hook had: PostToolUse fires once
    per tool call, so the report described a state the next edit replaced.
    """
    state = read_state(KIND, session)
    reported = state["reported"]
    reports = []
    for path in [e["path"] for e in entries(state)]:
        got = assess(path)
        if got is None:
            reported.pop(path, None)
            continue
        report, digest = got
        if reported.get(path) == digest:
            # Said once. A Stop hook that repeats itself is a Stop hook that
            # never lets the turn end, and leaving the stub is the writer's
            # call to make once they have been told.
            continue
        reported[path] = digest
        reports.append(report)
    write_state(KIND, session, {"pending": [], "reported": reported})
    return "\n".join(reports)


def main() -> int:
    raw = sys.stdin.read()
    session = session_key(raw)
    try:
        path = str((json.loads(raw).get("tool_input") or {}).get("file_path") or "")
    except (ValueError, TypeError, AttributeError):
        path = ""
    if not path:
        # No file path means this is the Stop firing, where the writes have
        # settled and the assessment is finally about the file that exists.
        report = settle(session)
        if not report:
            return 0
        print(report, file=sys.stderr)
        return 2
    if Path(path).suffix.lower() not in REMEDY:
        return 0
    late = stranded(KIND, session)
    if late:
        # The Stop hook is not running in this session, so these were held and
        # nothing came for them. Reporting late beats the hook going silently
        # dead, and saying why beats reporting them as if this were normal.
        reports = [r for r in (assess(p) for p in late) if r]
        drop(KIND, session, late)
        trace(f"PostToolUse:{KIND}", "fired",
              f"{len(late)} write(s) held past the wait with no Stop firing")
        if reports:
            print(f"honest-code: the Stop hook is not running in this session, so "
                  f"{len(late)} earlier write(s) were never assessed. Reporting "
                  f"them now, late. Restart to fix the wiring.\n"
                  + "\n".join(r[0] for r in reports), file=sys.stderr)
            defer(KIND, path, session)
            return 2
    defer(KIND, path, session)
    trace("PostToolUse:stub", "deferred", "held until the writes settle",
          file=path)
    return 0                          # silence: the file may still be moving


# Exercised by tests/test_stub_check.py. In-process coverage cannot observe a
# child process, so the pragma records that the gap is in the instrument.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
