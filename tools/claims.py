#!/usr/bin/env python3
"""Flag claims a draft has not earned.

    uv run tools/claims.py draft.md
    uv run tools/claims.py --json draft.md report.md   # any number of files

Four kinds of sentence can be false in a way an opinion cannot: something is
done, something passes, something does not exist, something is safe to change.
This finds the ones written without evidence beside them.

WHY AN UNQUALIFIED NEGATIVE IS THE WORST OF THE FOUR
"Not found" asserts something about everywhere you did not look. "Not found
under `crates/`" asserts something about one directory, which is what you
actually checked. The second is a finding and the first is a guess wearing a
finding's clothes, and the difference is four words.

WHAT COUNTS AS A WARRANT
A path or command in backticks, a fenced block touching the line, or a figure.
Crude on purpose: the check is whether the writer put anything checkable next
to the claim, not whether the thing they put there was any good.

WHAT THIS REFUSES TO JUDGE
Whether the evidence supports the claim. Whether the command was the right
command. Whether the scope named was the scope that mattered. Whether the
second opinion was independent. Those are the whole of the work, no checker
reaches them, and they print under every verdict rather than gating anything.

It also cannot tell a claim from a mention of one. Prose that *discusses* the
phrase "not found" reads to this as prose that asserts it. Backticks settle the
easy cases and a person settles the rest, which is why this checks a draft you
are about to send and not a document about drafts.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clarity  # noqa: E402

# Each entry: the shape to look for, and what the writer owes it.
CLAIMS = {
    "unqualified negative": (
        re.compile(
            r"\b(?:not found|no callers?|nothing (?:uses|calls|references)|"
            r"does(?:n't| not) exist|no (?:references?|occurrences?|matches|"
            r"instances?)|none (?:exist|found|remain))\b",
            re.I,
        ),
        "name where you looked",
    ),
    "completion": (
        re.compile(
            r"\b(?:tests? pass(?:es|ing)?|all tests?|suite passes|"
            r"it works|working now|now fixed|is fixed|verified|"
            r"confirmed working|deploy(?:ed|s) cleanly)\b",
            re.I,
        ),
        "show the command or its output",
    ),
    "absolute": (
        re.compile(
            r"\b(?:every (?:file|module|caller|agent|user|request|test)|"
            r"all (?:files|modules|callers|agents|users|requests|tests)|"
            r"never happens|always (?:works|passes|succeeds)|"
            r"nowhere (?:else|in))\b",
            re.I,
        ),
        "bound it to what you enumerated",
    ),
}

WARRANT = re.compile(r"`[^`]*[/.\-][^`]*`|\b\d[\d,.]*\b")
FENCE = re.compile(r"^\s*```")


def fenced_lines(lines: list[str]) -> set[int]:
    """Indices sitting inside a fenced block, plus the fence rows themselves."""
    inside: set[int] = set()
    open_at = None
    for i, line in enumerate(lines):
        if not FENCE.match(line):
            continue
        if open_at is None:
            open_at = i
        else:
            inside.update(range(open_at, i + 1))
            open_at = None
    return inside


def next_content(lines: list[str], i: int) -> int | None:
    """Index of the next non-blank line after `i`, or None at the end.

    Blank lines are skipped because a claim and the block proving it are
    separated by one in every Markdown document ever written.
    """
    k = i + 1
    while k < len(lines) and not lines[k].strip():
        k += 1
    return k if k < len(lines) else None


def warranted(lines: list[str], i: int, fenced: set[int]) -> bool:
    """Evidence sits on the claim's own line, or in a block that follows it.

    Deliberately one-directional. Accepting a block *above* the claim as well
    would let any paragraph following any code block pass, and a check that
    misses an unearned claim has failed at the only job it has. A false flag
    costs four words; a false pass costs the thing this exists to prevent.
    """
    if WARRANT.search(lines[i]):
        return True
    nxt = next_content(lines, i)
    return nxt is not None and nxt in fenced


INLINE_CODE = re.compile(r"`[^`]*`")


def frontmatter_lines(lines: list[str]) -> set[int]:
    """Indices of a leading YAML block. Metadata is not prose and cannot claim."""
    if not lines or lines[0].strip() != "---":
        return set()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return set(range(0, i + 1))
    return set()


def find(text: str) -> list[dict]:
    """Every unwarranted claim in the text, in reading order.

    Inline code is blanked before matching, so a document that *names* a claim
    phrase in backticks is not read as making it. That is the cheap half of
    use versus mention; the expensive half is left to a person, and said so in
    the module docstring.
    """
    lines = text.splitlines()
    fenced = fenced_lines(lines) | frontmatter_lines(lines)
    found = []
    for i, line in enumerate(lines):
        if i in fenced:
            continue
        prose = INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line)
        for kind, (pattern, owed) in CLAIMS.items():
            hit = pattern.search(prose)
            if hit and not warranted(lines, i, fenced):
                found.append({"line": i + 1, "kind": kind,
                              "quote": hit.group(0), "owed": owed,
                              "text": line.strip()[:90]})
    return found


NOT_CHECKED = [
    "Does the evidence support the claim?",
    "Was that the right command to run?",
    "Was the scope you named the scope that mattered?",
    "Was the second opinion independent?",
]


def analyse(raw: str, source: str) -> dict:
    """`source` has no default: a draft read from stdin and one whose caller
    never said where it came from must not look the same in the output."""
    found = find(raw)
    return {"source": source, "verdict": "fail" if found else "pass",
            "exit": 1 if found else 0, "findings": found}


def analyse_paths(paths: list[str], stdin_text: str | None) -> dict:
    if not paths:
        files = [analyse(stdin_text or "", "-")]
    else:
        files = [clarity.unreadable(p, err) if err else analyse(txt, p)
                 for p, (txt, err) in ((p, clarity.read_one(p)) for p in paths)]
    worst = max(f["exit"] for f in files)
    return {"schema": 2,
            "verdict": {0: "pass", 1: "fail", 2: "unreadable"}[worst],
            "exit": worst, "files": files, "not_checked": NOT_CHECKED}


def render(run: dict) -> str:
    out = []
    for f in run["files"]:
        if f["verdict"] == "unreadable":
            out.append(f"cannot read {f['source']}: {f['error']}")
            continue
        found = f["findings"]
        out.append(f"{f['source']}: {len(found)} unearned claim(s)"
                   if found else f"{f['source']}: nothing unearned")
        for c in found:
            out.append(f"  line {c['line']}  {c['kind']}: \"{c['quote']}\" "
                       f"— {c['owed']}")
            out.append(f"    {c['text']}")
    out.append("\n  NOT CHECKED, and these are the ones that matter:")
    out.extend(f"    {q}" for q in run["not_checked"])
    return "\n".join(out)


def main() -> int:
    argv = sys.argv
    paths = clarity.paths_from(argv)
    run = analyse_paths(paths, None if paths else sys.stdin.read())
    print(json.dumps(run, indent=2) if "--json" in argv[1:] else render(run))
    return run["exit"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
