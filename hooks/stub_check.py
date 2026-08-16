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
import json
import os
import re
import sys
from pathlib import Path

# The convention this enforces, in each language's own idiom. The message is
# the same everywhere so a grep across a polyglot repository finds every one.
MARKER = "CODE NOT WRITTEN"

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
        if {dotted(d) for d in node.decorator_list} & DECLARATION_DECORATORS:
            continue
        if body_is_empty(node.body):
            found.append((node.lineno, node.name))
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


def already_loud(source: str) -> bool:
    """The file already says CODE NOT WRITTEN somewhere, so it was told."""
    return MARKER in source


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
    if how == "matched":
        lines.append("      Matched by pattern rather than parsed, so this is "
                     "approximate. Python is the only language parsed here.")
    return "\n".join(lines)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        path = str((payload.get("tool_input") or {}).get("file_path") or "")
    except (ValueError, TypeError, AttributeError):
        return 0
    if not path or Path(path).suffix.lower() not in REMEDY:
        return 0
    try:
        source = Path(path).read_text(errors="replace")
    except OSError:
        return 0
    if already_loud(source):
        return 0

    how, stubs = findings_for(path, source)
    if not stubs:
        return 0
    print(render(path, how, stubs), file=sys.stderr)
    return 2


# Exercised by tests/test_stub_check.py. In-process coverage cannot observe a
# child process, so the pragma records that the gap is in the instrument.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
