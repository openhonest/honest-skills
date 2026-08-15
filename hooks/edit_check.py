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

Where the analyzer is absent, the answer is UNMEASURED and it says so once.
"Not checked" is not "passed".
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

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


def hook_input(raw: str) -> tuple[str, str]:
    """Return (file_path, session_id). Empty strings when absent.

    A hook that raises on unexpected input turns every write into an error
    notice. Absent fields are a reason to do nothing, not to complain.
    """
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return "", ""
    tool_input = d.get("tool_input") or {}
    return str(tool_input.get("file_path") or ""), str(d.get("session_id") or "")


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


def already_told(session: str) -> bool:
    """One notice per session about a missing analyzer, not one per write.

    Repeating a fact the reader cannot act on differently the second time is
    how an alarm becomes wallpaper.
    """
    if not session:
        return True
    marker = Path(tempfile.gettempdir()) / f"honest-edit-check-{session}.told"
    if marker.exists():
        return True
    try:
        marker.touch()
    except OSError:
        return True
    return False


def analyzer_finding(path: str, session: str) -> dict | None:
    """Delegate the mutable-state ratio. Never reimplement it."""
    exe = shutil.which(ANALYZER)
    if exe is None:
        if already_told(session):
            return None
        return {"indicator": "L1.18", "verdict": "UNMEASURED",
                "detail": f"{ANALYZER} is not on PATH, so mutable-state ratio "
                          f"was not evaluated on this file or any other this session",
                "action": "install the Slop Audit analyzer, or accept that this "
                          "check is not running"}
    try:
        r = subprocess.run([exe, path, "--indicators", "18", "--no-exec", "--format", "json"],
                           capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"indicator": "L1.18", "verdict": "UNMEASURED",
                "detail": "the analyzer ran and its output could not be read",
                "action": "run it by hand on this file to see why"}
    band = ((data.get("results") or {}).get("L1.18") or {}).get("band")
    value = ((data.get("results") or {}).get("L1.18") or {}).get("value")
    if band is None:
        return {"indicator": "L1.18", "verdict": "UNMEASURED",
                "detail": "the analyzer returned no verdict for this file",
                "action": "this is a gap in the analyzer, not in the file"}
    if str(band).lower() in ("healthy", "clean"):
        return None
    return {"indicator": "L1.18", "verdict": "OUT_OF_SPEC",
            "detail": f"mutable-state ratio {value}, band {band}",
            "action": "move the state into the parameter list, or to the boundary",
            "caveat": "this threshold is provisional and was set by expert judgment"}


def findings_for(path: str, text: str, session: str) -> list[dict]:
    out = []
    for f in (line_count_finding(text), whitespace_finding(text),
              analyzer_finding(path, session)):
        if f is not None:
            out.append(f)
    return out


def render(path: str, findings: list[dict]) -> str:
    name = os.path.basename(path)
    lines = [f"honest-code: {len(findings)} finding(s) in {name}"]
    for f in findings:
        lines.append(f"  {f['verdict']}  {f['indicator']}  {f['detail']}")
        lines.append(f"      {f['action']}")
        if f.get("caveat"):
            lines.append(f"      note: {f['caveat']}")
    return "\n".join(lines)


def main() -> int:
    path, session = hook_input(sys.stdin.read())
    if not path or Path(path).suffix.lower() not in SOURCE:
        return 0
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        # The file is gone or unreadable. That is not a finding about the code,
        # and a hook that reports it teaches the reader to ignore hooks.
        return 0

    findings = findings_for(path, text, session)
    if not findings:
        return 0                      # silence: exit 0 shows stdout to nobody

    print(render(path, findings), file=sys.stderr)
    return 2                          # exit 2 puts stderr in front of the model


# Exercised by tests/test_edit_check.py, which runs this as Claude Code does.
# In-process coverage cannot observe a child process, so the pragma records
# that the gap is in the instrument rather than in the tests.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
