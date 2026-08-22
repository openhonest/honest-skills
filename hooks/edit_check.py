#!/usr/bin/env python3
"""Check a file at the moment it is written, and say nothing when it is fine.

A PostToolUse hook. Claude Code runs it after every Write and Edit, passing the
tool call as JSON on stdin.

WHY A HOOK RATHER THAN A TOOL THE AGENT CALLS

An agent has no appetite for quality; it emits the most probable continuation.
An instruction to run a check is advice, and advice degrades over a long session
and is skipped when inconvenient. Worse, an agent that stops calling produces no
output, so the silence reads as health.

A hook fires whether or not the agent cooperates. That is the whole point: it
turns the check from something the agent may remember into a step in the loop.

SILENCE IS THE DESIGN, NOT AN OVERSIGHT

Exit 0 sends stdout to Claude Code's debug log and shows it to nobody. So a
clean file produces no output at all: not a tick, not a summary, nothing. A
check that speaks on every write is noise, and noise gets uninstalled inside a
day, which is a worse outcome than never being installed.

When something is wrong, exit 2 puts stderr in front of the model, which is the
one path that reaches the thing doing the writing.

The andon cord does not display a score to the worker. It is silent, and then
it is not.

WHAT THIS DOES NOT DO, STATED HERE RATHER THAN DISCOVERED

It is not the Slop Audit. It runs two checks that need no parser and no
judgement, and it delegates the mutable-state ratio to the real analyzer when
that analyzer is installed. It never reimplements it. The authoritative
definition lives in the Honest Framework's L1.18 with its bound-literal
amendment, and a second implementation under the same name is how two tools
come to disagree while both claiming the standard.

AN ABSENCE IS NOT A FINDING ABOUT YOUR FILE

The first version announced the missing analyzer as a finding, so a clean file
produced "1 finding(s) in t.py" when there was nothing in t.py at all. It was
reporting on itself and labelling the report as an observation of the file.
That is the category error this project exists to name, and every new install
met it on the first write, because nobody has the analyzer.

The rule that replaced it: an absence is only worth saying alongside a
presence. A findings list that does not declare its coverage is claiming to be
complete, so every report leads with how many checks ran out of how many. When
there is nothing to report, there is no list to be incomplete about, and the
hook is silent.

SILENCE IS NOT A PASS, AND NEVER CLAIMS TO BE

Nothing here ever prints a tick, a score, or the word clean. Silence means
nothing surfaced. The coverage line on every real report is what keeps that
honest, because it is impossible to read a finding from this tool without also
reading what it did not examine.
"""
from __future__ import annotations

import json
import os
import re
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_hook import trace  # noqa: E402

# L1.17 at file scope. The published band is a percentage of files in a
# repository, which is meaningless for one file. The question underneath it,
# whether this file has grown past the point anyone reads it whole, is exactly
# file-scoped.
LINE_LIMIT = 1000

# L1.16. The published Slop band.
WHITESPACE_SLOP = 3.0

# Text formats worth checking at all. A hook that fires on lock files and
# generated output is a hook that fires constantly.
SOURCE = {".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".rb",
          ".c", ".h", ".cpp", ".hpp", ".cs", ".sh", ".sql"}

ANALYZER = "slop-audit-l1"

# How many checks this hook has to offer. Reported on every finding, so the
# reader learns the coverage at the same moment as the content.
#
# L1.18 WAS HERE AND COULD NEVER HAVE WORKED. It takes a repository root and
# refuses a single file: "point me at a directory (a repo root), not a single
# file". The hook had always passed it one file, so the call always failed and
# always reported NOT_RUN. Nobody noticed, because the binary was absent from
# this machine for a different reason and the two failures looked identical.
# Installing the binary is what exposed it.
#
# Pointing it at the file's parent instead would answer a different question:
# measured on a directory holding that one file it returns 100.0 and band Slop,
# which is a statement about the directory, not the file that was just written.
# A check that answers a question nobody asked is worse than one that is absent.
#
# L1.21 replaces it and is why audit called it the one indicator built for this
# path rather than adapted to it.
CHECKS = 3

# A file with thirty violations produces a wall nobody reads. Show the first
# few and say how many were held back, because a truncated list that does not
# say it is truncated is the same lie as a findings list with no coverage.
MAX_CLAUSE_FINDINGS = 5


def hook_input(raw: str) -> str:
    """Return the file path, or "" when there is not one.

    A hook that raises on unexpected input turns every write into an error
    notice. Absent fields are a reason to do nothing, not to complain.
    """
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return ""
    return str((d.get("tool_input") or {}).get("file_path") or "")


def line_count_finding(text: str) -> dict | None:
    n = len(text.splitlines())
    if n <= LINE_LIMIT:
        return None
    return {"indicator": "L1.17", "verdict": "OUT_OF_SPEC",
            "detail": f"{n} lines, over the {LINE_LIMIT}-line threshold",
            "action": "split it, or accept it deliberately"}


def whitespace_finding(text: str) -> dict | None:
    lines = text.splitlines()
    if not lines:
        return None
    trailing = sum(1 for l in lines if l != l.rstrip())
    pct = trailing / len(lines) * 100
    if pct <= WHITESPACE_SLOP:
        return None
    return {"indicator": "L1.16", "verdict": "OUT_OF_SPEC",
            "detail": f"{pct:.1f}% of lines end in whitespace, band is under {WHITESPACE_SLOP}%",
            "action": "run the formatter this project already has"}


def changed_lines(path: str) -> set[int] | None:
    """Line numbers this file gained or altered against its committed version.

    None when there is nothing to compare against: not a repository, not
    tracked, or git unavailable. None means report everything, because a file
    with no baseline has no old findings to separate from new ones.

    An EMPTY set is a different answer and means the file now matches its
    committed version. Nothing was changed, so nothing is this edit's doing.
    Conflating the two made `cp backup.py mutate.py` report every finding in
    the file it had just restored.

    This exists because the hook was reporting the whole file. A one-line edit
    to a 500-line module returned all 45 of its findings, most of them years
    old, and the reader had to find the one they had just caused. Reporting a
    file's history back at someone who changed one line is the load this
    project exists to remove.
    """
    try:
        here = os.path.dirname(path) or "."
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", path],
                                 capture_output=True, text=True, timeout=10, cwd=here)
        if tracked.returncode != 0:
            return None                       # not tracked: no baseline
        r = subprocess.run(["git", "diff", "-U0", "--", path],
                           capture_output=True, text=True, timeout=10, cwd=here)
        if r.returncode != 0:
            return None
        if not r.stdout.strip():
            return set()                      # tracked and identical to HEAD
    except (OSError, subprocess.SubprocessError):
        return None
    lines: set[int] = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", r.stdout, re.M):
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        lines.update(range(start, start + count))
    return lines or None


def honest_code_finding(path: str) -> dict | None:
    """L1.21, the Honest Code clauses, measured on this one file.

    Delegated like L1.18 and for the same reason. It is the one indicator
    designed for a single file: no git history, no CI, no test run, no
    repository, no network. It parses the file and runs nineteen pure
    functions over the tree.

    The clause count is read from the response, never assumed. Some clauses
    cannot be decided for a given language: two ask about a browser, one asks
    how work was sequenced over weeks and no file carries that. A Python file
    decided 14 of 19 when measured, which is not the number that was quoted to
    me, so the field is the authority and the memory is not.
    """
    exe = shutil.which(ANALYZER)
    if exe is None:
        return {"indicator": "L1.21", "verdict": "NOT_RUN",
                "detail": f"{ANALYZER} is not on PATH",
                "action": "this file was not checked against the Honest Code clauses"}
    try:
        r = subprocess.run([exe, "--honest-code", path, "--format", "json"],
                           capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"indicator": "L1.21", "verdict": "NOT_RUN",
                "detail": "the analyzer ran and its output could not be read",
                "action": "run it by hand on this file to see why"}

    if data.get("unreadable_reason"):
        # A file nobody could read is not a file with no violations.
        return {"indicator": "L1.21", "verdict": "NOT_RUN",
                "detail": f"could not read the file: {data['unreadable_reason']}",
                "action": "nothing was checked, which is not the same as clean"}

    clauses = data.get("clauses") or []
    decided = data.get("decided_clauses")
    hits = [f for c in clauses for f in (c.get("findings") or [])]
    if not hits:
        return None

    # Only what this edit touched, when there is a baseline to compare against.
    # The rest of the file's findings are real and are not this person's
    # business right now.
    touched = changed_lines(path)
    older = 0
    if touched == set():
        # The file matches its committed version. A restore is not an edit.
        return None
    if touched is not None:
        mine = [f for f in hits if f.get("line") in touched]
        older = len(hits) - len(mine)
        if not mine:
            return None
        hits = mine

    shown = hits[:MAX_CLAUSE_FINDINGS]
    lines = [f"{h.get('clause')} line {h.get('line')}: {h.get('detail')}"
             for h in shown]
    if len(hits) > len(shown):
        lines.append(f"and {len(hits) - len(shown)} more, not shown")
    return {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
            "detail": f"{len(hits)} Honest Code finding(s) on lines you changed, "
                      f"{decided} of {len(clauses)} clauses decided"
                      + (f", {older} elsewhere in the file not shown" if older else "")
                      + "; " + "; ".join(lines),
            "action": shown[0].get("instead") or "see the clause detail",
            "caveat": "these bands are expert judgment, not measured, and the "
                      "clauses this file could not decide are outside the score"}


def findings_for(path: str, text: str) -> list[dict]:
    """Every check's result, including the ones that did not run.

    Suppressing a NOT_RUN here would make the coverage count in render()
    impossible to compute, and the count is the whole of the honesty.
    """
    return [f for f in (line_count_finding(text), whitespace_finding(text),
                        honest_code_finding(path)) if f is not None]


def render(path: str, findings: list[dict]) -> str:
    """The coverage first, then the findings.

    "2 of 3 checks ran" before any content, because a list of findings with no
    coverage stated is a list claiming to be complete.
    """
    name = os.path.basename(path)
    # Count what did NOT run and subtract. Counting the findings instead
    # counts the checks that FIRED, so a check that ran and passed vanished
    # from the coverage: a file with a real finding and a clean whitespace
    # check reported "1 of 3 ran" when two had. Under-reporting coverage is a
    # smaller lie than over-reporting it and it is still a lie.
    not_run = sum(1 for f in findings if f["verdict"] == "NOT_RUN")
    lines = [f"honest-code: {CHECKS - not_run} of {CHECKS} checks ran on {name}"]
    for f in findings:
        lines.append(f"  {f['verdict']}  {f['indicator']}  {f['detail']}")
        lines.append(f"      {f['action']}")
        if f.get("caveat"):
            lines.append(f"      note: {f['caveat']}")
    return "\n".join(lines)


def main() -> int:
    path = hook_input(sys.stdin.read())
    if not path or Path(path).suffix.lower() not in SOURCE:
        trace("PostToolUse:edit", "declined",
              f"not a checked extension: {Path(path).suffix or 'none'}")
        return 0
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        # The file is gone or unreadable. That is not a finding about the code,
        # and a hook that reports it teaches the reader to ignore hooks.
        return 0

    findings = findings_for(path, text)
    ran = CHECKS - sum(1 for f in findings if f["verdict"] == "NOT_RUN")
    hits = [f["indicator"] for f in findings if f["verdict"] != "NOT_RUN"]
    trace("PostToolUse:edit", "fired" if hits else "declined",
          f"{ran} of {CHECKS} ran, {Path(path).suffix or 'no suffix'}"
          + (f", {','.join(hits)}" if hits else ""))
    if not any(f["verdict"] != "NOT_RUN" for f in findings):
        # Nothing surfaced. A check that did not run is not an observation
        # about this file, and announcing it here would put the tool's own
        # limitation where a finding about the code belongs.
        return 0                      # silence: exit 0 shows stdout to nobody

    print(render(path, findings), file=sys.stderr)
    return 2                          # exit 2 puts stderr in front of the model


# Exercised by tests/test_edit_check.py, which runs this as Claude Code does.
# In-process coverage cannot observe a child process, so the pragma records
# that the gap is in the instrument rather than in the tests.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
