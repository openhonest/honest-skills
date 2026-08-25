#!/usr/bin/env python3
"""Check a commit message for the defects a machine can actually judge.

    uv run tools/commit_msg.py .git/COMMIT_EDITMSG
    uv run tools/commit_msg.py --json .git/COMMIT_EDITMSG

Run by pre-commit at the commit-msg stage, which passes the message file path.

Why this is not clarity.py with a different band. A commit subject is one line
of a dozen words, so the clarity index over it is arithmetic on a sample too
small to mean anything: a good subject and a bad one both land wherever the
syllables fall. Applying the index here would produce a number that looks like a
measurement and is not one.

What survives at this size is the word-level work, plus the subject-line length
that every git tool assumes. What does not survive is the structure: whether the
subject carries the change, and whether the body is ranked by what needs
attention. Those are reported and never gated, because a machine cannot tell a buried
lead from a deliberate one.

Existing tools cover the neighbouring ground. gitlint and commitizen check
syntax, prefix and imperative mood. Neither asks whether the subject says what
changed, which is the check nobody can automate and everybody needs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# The two checkers share the word lists and the file reader. Loading the sibling
# by hand (importlib.spec_from_file_location) made both names unresolvable to a
# static reader, so nothing downstream of them could be shown to have a finite
# set of values. Putting the directory on the path instead keeps `clarity` an
# ordinary import that any tool can follow.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import clarity  # noqa: E402

SUBJECT_LIMIT = 72


def strip_comments(raw: str) -> str:
    """Drop the commentary git appends to the template.

    Left in, the "# Please enter the commit message" block and the diff summary
    are scored as the author's prose, and the report describes git's words back
    to the author as though they were their own.
    """
    return "\n".join(l for l in raw.splitlines() if not l.startswith("#"))


def analyse_message(raw: str, source: str) -> dict:
    """`source` has no default: see the note in clarity.analyse. A default
    would make a message read from stdin indistinguishable from one whose
    caller never said."""
    text = strip_comments(raw).strip()
    lines = text.splitlines()
    subject = lines[0].strip() if lines else ""
    body = "\n".join(lines[1:]).strip()

    checks = {
        "subject_present": {
            "verdict": "pass" if subject else "fail",
            "gating": True, "text": subject,
        },
        "subject_length": {
            "verdict": "fail" if len(subject) > SUBJECT_LIMIT else "pass",
            "gating": True, "length": len(subject), "limit": SUBJECT_LIMIT,
        },
        "blank_line_after_subject": {
            # Every git tool that renders a log assumes it. Without it, the
            # whole message becomes the subject in half the tools you use.
            "verdict": "pass" if len(lines) < 2 or not lines[1].strip() else "fail",
            "gating": True,
        },
        "subject_carries_the_change": {
            "verdict": "unassessed",
            "gating": False,
            "text": subject,
            "reason": "a machine cannot tell a subject that says what changed "
                      "from one that merely names the area",
        },
        "bad_news_first": {
            "verdict": "unassessed",
            "gating": False,
            "reason": "a machine cannot tell which of two facts is the worse news",
        },
    }

    dashes = text.count("—")
    checks["em_dashes"] = {
        "verdict": "fail" if dashes % 2 else "pass", "gating": True,
        "count": dashes,
        "reason": ("odd count, so one is stray" if dashes % 2
                   else "even count, check they are paired"),
    }
    # Scan the prose, not the mentions. A commit that fixes a hyphenated -ly
    # adverb has to name the thing it fixed, and a checker that cannot tell a
    # mention from a use makes its own defects unreportable.
    #
    # Quoted phrases were missing from this until a commit describing the
    # "really" test was blocked for the word really. The rule was already
    # written here for code spans; it just was not applied to quotes.
    prose = clarity.strip_mentions(text)
    for key, pats in clarity.WORD_CLASSES:
        hits = [h for p in pats for h in clarity.scan(p, prose)]
        checks[key] = {"verdict": "fail" if hits else "pass", "gating": True,
                       "count": len(hits), "found": sorted(set(hits))}

    failed = [k for k, c in checks.items() if c["gating"] and c["verdict"] == "fail"]
    return {"source": source, "verdict": "fail" if failed else "pass",
            "exit": 1 if failed else 0, "gating_failures": failed,
            "subject": subject, "has_body": bool(body), "checks": checks}


def render(r: dict) -> str:
    out = []
    if r["verdict"] == "pass":
        out.append("commit message: ok")
    else:
        out.append(f"commit message: {len(r['gating_failures'])} defect(s)")
    c = r["checks"]
    if c["subject_present"]["verdict"] == "fail":
        out.append("  no subject line")
    if c["subject_length"]["verdict"] == "fail":
        out.append(f"  subject is {c['subject_length']['length']} characters, "
                   f"limit {SUBJECT_LIMIT}")
    if c["blank_line_after_subject"]["verdict"] == "fail":
        out.append("  no blank line after the subject, so tools will read the "
                   "whole message as the subject")
    if c["em_dashes"]["count"] and c["em_dashes"]["verdict"] == "fail":
        out.append(f"  {c['em_dashes']['count']} em dash(es), odd count so one is stray")
    for key, _ in clarity.WORD_CLASSES:
        if c[key]["verdict"] == "fail":
            out.append(f"  {clarity.LABELS[key].lower()}: {', '.join(c[key]['found'][:6])}")
    out.append(f"\n  SUBJECT  {r['subject'][:72]}")
    out.append("    Does it say what changed? Nothing here can check that for you.")
    if not r["has_body"]:
        out.append("    No body. If the change needs a why, it belongs here.")
    return "\n".join(out)


def main() -> int:
    argv = sys.argv
    as_json = "--json" in argv[1:]
    paths = clarity.paths_from(argv)
    if not paths:
        raw, source = sys.stdin.read(), "-"
    else:
        raw, error = clarity.read_one(paths[0])
        source = paths[0]
        if error:
            payload = {"source": source, "verdict": "unreadable", "exit": 2,
                       "error": error, "checks": {}}
            print(json.dumps(payload, indent=2) if as_json
                  else f"cannot read {source}: {error}")
            return 2
    result = analyse_message(raw, source)
    print(json.dumps(result, indent=2) if as_json else render(result))
    return result["exit"]


# Exercised by tests/test_commit_msg.py running this as a hook would. In-process
# coverage cannot observe a child process, so the pragma records that the gap is
# in the instrument rather than in the tests.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
