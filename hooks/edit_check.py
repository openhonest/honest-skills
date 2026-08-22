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

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pending import (defer, drop, entries, read_state,  # noqa: E402
                     session_key, stranded, write_state)
from trace_hook import stale_note, trace  # noqa: E402

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
CHECKS = 4
KIND = "edit"
# How long a standing finding waits before it is raised again unprompted. An
# agent that walks away from a file does not make its defect go away, and a
# finding only re-checked when the file is touched can be escaped by never
# touching it. Adam's rule: nag on a timer until the cause is verified gone.
NAG_AFTER = 600.0

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


# Findings that describe the whole file rather than the lines just written.
# The content guard cannot hold these back: any edit changes the content, so
# the guard sees new content and reports again. A file over the line limit
# therefore said so on every single edit until it was split, which is the
# nagging that gets a tool uninstalled. Said once per file per session instead.
WHOLE_FILE = {"L1.17", "L1.16"}


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


# The two ways an edit can make a check go quiet without changing behaviour.
# `honest-code-allow:` names a clause outright. A boundary decorator tells the
# reader this function is an edge, which stops clause 4 asking why it does its
# own I/O.
ANNOTATION = re.compile(
    r"honest-code-allow:\s*L1\.21\.\d+"
    r"|@\s*(?:[\w.]+\.)?(?:boundary|boundary_in|boundary_out|edge|entrypoint|entry_point)\b")


def annotations_added(path: str, text: str) -> list[int]:
    """Lines this edit added that silence a check.

    A declaration already in the file is architecture and is left alone. One
    written in the same edit that would otherwise have reported is the cheap
    route to a clean score: one comment against a rewrite. This does not prove
    the annotation caused the silence, and it does not claim to. It reports
    that the edit added one, which is the thing a reader should see.
    """
    lines = text.splitlines()
    present = [n for n, line in enumerate(lines, 1) if ANNOTATION.search(line)]
    if not present:
        return []                 # nothing to place, so do not ask git
    touched = changed_lines(path)
    if touched == set():
        return []                 # the file matches its committed version
    return present if touched is None else [n for n in present if n in touched]


def coverage_gap(clauses: list[dict]) -> int:
    """Undecided clauses that represent a failure to look, not a rule that
    does not apply.

    The analyzer separated these on 2026-08-21. Before that, "14 of 19 decided"
    put a browser rule that cannot apply to a Python file in the same bucket as
    a file the reader could not parse. Only the second is a gap in coverage,
    and reporting both as one number overstates what went unchecked on every
    Python file ever measured.

    An undecided clause with no kind is counted as a gap. A reader that cannot
    tell should say it did not look rather than assume it did.
    """
    return sum(1 for c in clauses
               if not c.get("decided") and c.get("undecided") != "not applicable"
               and c.get("undecided") != "never")


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
    gaps = coverage_gap(clauses)
    # What this edit silenced rather than fixed. The analyzer has always
    # reported it and this hook threw it away, so an annotation that made a
    # finding disappear was indistinguishable from writing conforming code.
    # Anything scoring an agent on conformance would have paid it the same
    # either way, and silencing is the cheaper of the two.
    silenced = [a for c in clauses for a in (c.get("allowed") or [])]
    hits = [f for c in clauses for f in (c.get("findings") or [])]
    # Scoped only when there is something to scope. Asking git on every file
    # made the call unconditional, which is work nobody asked for on the
    # common path.
    mine = []
    if silenced and not hits:
        touched_now = changed_lines(path)
        mine = [a for a in silenced
                if touched_now is None or a.get("line") in touched_now]
    if mine:
        # Silenced on the lines this edit touched, with nothing left to report.
        # Said plainly, because a suppression is a decision someone should be
        # able to see, and the reason travels with it.
        first = mine[0]
        return {"indicator": "L1.21", "verdict": "SUPPRESSED",
                "detail": f"{len(mine)} finding(s) silenced on lines you "
                          f"changed, not fixed; line {first.get('line')}: "
                          f"{first.get('reason') or 'no reason given'}",
                "action": "this counts as a suppression, not as conforming code"}
    if not hits and gaps:
        # No findings and a coverage gap is not a clean file, it is a file the
        # reader could not read. A Python parser over a JavaScript file returns
        # an empty tree, and every clause that walks the tree finds nothing in
        # it and counts as holding. Staying silent here publishes that as a
        # pass. Adam's hook checks fifteen non-Python extensions.
        return {"indicator": "L1.21", "verdict": "NOT_RUN",
                "detail": f"{gaps} of {len(clauses)} clauses could not read this "
                          f"file, and {decided} were decided",
                "action": "the clauses that could not be read are unchecked, "
                          "which is not the same as clean"}
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

    codes = sorted({h.get("clause") for h in hits if h.get("clause")},
                   key=lambda c: [int(n) if n.isdigit() else 0
                                  for n in c.replace("L", "").split(".")])
    shown = hits[:MAX_CLAUSE_FINDINGS]
    lines = [f"{h.get('clause')} line {h.get('line')}: {h.get('detail')}"
             for h in shown]
    if len(hits) > len(shown):
        lines.append(f"and {len(hits) - len(shown)} more, not shown")
    return {"indicator": "L1.21", "verdict": "OUT_OF_SPEC",
            "detail": f"{len(hits)} Honest Code finding(s) on lines you changed, "
                      f"{decided} of {len(clauses)} clauses decided"
                      + (f" ({gaps} could not be read, the rest do not apply "
                         f"to this file)" if gaps else "")
                      + (f", {older} elsewhere in the file not shown" if older else "")
                      + "; " + "; ".join(lines),
            "clauses": codes,
            "action": shown[0].get("instead") or "see the clause detail",
            "caveat": "these bands are expert judgment, not measured, and the "
                      "clauses this file could not decide are outside the score"}


def annotation_finding(path: str, text: str) -> dict | None:
    """An edit that added a silencer says so, whatever else it did."""
    added = annotations_added(path, text)
    if not added:
        return None
    return {"indicator": "L1.21", "verdict": "SUPPRESSED",
            "detail": f"this edit added {len(added)} annotation(s) that silence "
                      f"a check, at line(s) {', '.join(map(str, added[:4]))}",
            "action": "an annotation is not a fix, and does not count as "
                      "conforming code"}


def findings_for(path: str, text: str) -> list[dict]:
    """Every check's result, including the ones that did not run.

    Suppressing a NOT_RUN here would make the coverage count in render()
    impossible to compute, and the count is the whole of the honesty.
    """
    return [f for f in (line_count_finding(text), whitespace_finding(text),
                        annotation_finding(path, text),
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
    note = stale_note()
    if note:
        lines.append(f"  {note}")
    for f in findings:
        lines.append(f"  {f['verdict']}  {f['indicator']}  {f['detail']}")
        lines.append(f"      {f['action']}")
        if f.get("caveat"):
            lines.append(f"      note: {f['caveat']}")
    return "\n".join(lines)


def _with_repeat_count(finding: dict, path: str, session: str) -> dict:
    """Mark a finding this session has already put about this file.

    Counted per file and per indicator, so "still standing" is readable
    without the reader holding the earlier reports in their head.
    """
    state = read_state(KIND, session)
    seen = dict(state.get("told") or {})
    key = f"{finding['indicator']}:{path}"
    seen[key] = n = int(seen.get(key, 0)) + 1
    state["told"] = seen
    write_state(KIND, session, state)
    if n == 1:
        return finding
    return {**finding,
            "detail": f"{finding['detail']} [still standing, told {n} times]"}


def said_before(session: str, key: str) -> bool:
    """True the first time this session meets `key`, false after.

    Backs both the once-per-language coverage notice and the once-per-file
    whole-file findings. Kept in the pending state, so it lasts the session and
    no longer.
    """
    state = read_state(KIND, session)
    said = state.get("said_of") or []
    if key in said:
        return False
    state["said_of"] = said + [key]
    write_state(KIND, session, state)
    return True


def announce_once(session: str, suffix: str) -> bool:
    """True the first time this session meets a language the reader cannot read.

    Kept in the same state file as the pending writes, so it lasts the session
    and no longer.
    """
    return said_before(session, suffix)


def assess(path: str, session: str = "") -> tuple[str, str] | None:
    """The report for one settled file, with the content it describes.

    Returns None when the file is gone, unreadable, or has nothing to say.
    The content hash travels with the report so a finding the model chose not
    to act on is not put a second time.
    """
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        # The file is gone or unreadable. That is not a finding about the
        # code, and a hook that reports it teaches the reader to ignore hooks.
        return None
    findings = findings_for(path, text)
    # An unresolved finding keeps being reported until it is resolved. It was
    # briefly suppressed after the first telling, on the reasoning that
    # repetition trains skimming. Adam overruled that and he was right twice
    # over: an agent is not worn down the way a person is, and suppressing a
    # finding that is still true makes an unresolved problem invisible, which
    # is the failure this whole thing exists to prevent.
    #
    # What the earlier evidence actually showed was a session skimming a
    # finding it had ALREADY FIXED, nine times, because of a stale binary.
    # That is repetition of stale news and a different fault entirely.
    #
    # So the repeat carries its count instead of being dropped. A reader can
    # then tell what is new in this report from what has been standing all
    # session, which is what went wrong at 11:56 when a file was told the same
    # two things after fixing one of them.
    findings = [_with_repeat_count(f, path, session) for f in findings]
    # The coverage and the indicators are recorded here, per file, because
    # this is where the checks actually run. Tracing only at the turn level
    # would say a turn fired without saying on what or against how many
    # checks, which is a count of events rather than a measurement.
    ran = CHECKS - sum(1 for f in findings if f["verdict"] == "NOT_RUN")
    hits = [f["indicator"] for f in findings if f["verdict"] != "NOT_RUN"]
    # What the hook did, and what the code was, are two different facts and
    # the record keeps them apart. `verdict` is the tool's action. `unit` is
    # the state of the thing written, which is what a control chart plots.
    #
    # A silent pass is a measurement, not an absence of one, so it is recorded
    # rather than left to be inferred from the lack of a row. And a file the
    # checks could not fully read is NOT a conforming unit: it is a missing
    # measurement, and counting it as good inflates the rate by exactly the
    # amount the instrument could not see.
    if any(f["verdict"] == "SUPPRESSED" for f in findings):
        unit = "suppressed"
    elif any(f["verdict"] == "OUT_OF_SPEC" for f in findings):
        unit = "nonconforming"
    elif ran < CHECKS:
        unit = "not_measured"
    else:
        unit = "conformed"
    # The clause is what teaches. "L1.21 fired" says a rule was broken; the
    # clause says which habit produced it, and that is the thing a series of
    # writes can show moving.
    # Sorted by number, not as text. As text "L1.21.14" comes before
    # "L1.21.4", which reads as a mistake to anyone who knows the clauses.
    clauses = sorted({c for f in findings for c in (f.get("clauses") or [])},
                     key=lambda c: [int(n) if n.isdigit() else 0
                                    for n in c.replace("L", "").split(".")])
    # A suppression is its own verdict in the record. Left as "fired" it would
    # count against the writer like a real finding; left as "declined" it would
    # count as conforming code, which is the reading that makes silencing the
    # cheap way to a good score.
    verdict = ("suppressed"
               if hits and all(f["verdict"] in ("NOT_RUN", "SUPPRESSED")
                               for f in findings)
               else "fired" if hits else "declined")
    trace("Stop:edit", verdict,
          f"{ran} of {CHECKS} ran, {Path(path).suffix or 'no suffix'}"
          + (f", {','.join(hits)}" if hits else ""),
          file=path, unit=unit, checks_ran=ran, checks=CHECKS,
          clauses=clauses or None)
    if not any(f["verdict"] != "NOT_RUN" for f in findings):
        # A coverage gap on THIS file is an observation about this file, unlike
        # a missing binary, which says nothing about it. A Python parser over a
        # JavaScript file returns an empty tree, every clause that walks the
        # tree finds nothing in it and counts as holding, and silence here
        # publishes that as a pass. Fifteen of the extensions this hook checks
        # are not Python.
        #
        # Said once per language per session: never is a false clean bill on
        # every JavaScript file, and every write is noise to someone writing
        # JavaScript all day.
        gap = next((f for f in findings if f["verdict"] == "NOT_RUN"
                    and "could not read this file" in f["detail"]), None)
        if gap and announce_once(session, Path(path).suffix.lower()):
            return (render(path, [gap]),
                    hashlib.sha256(text.encode()).hexdigest())
        # Nothing surfaced. A check that did not run is not an observation
        # about this file, and announcing it here would put the tool's own
        # limitation where a finding about the code belongs.
        return None
    return render(path, findings), hashlib.sha256(text.encode()).hexdigest()


def standing(session: str) -> list[str]:
    """Files with a finding outstanding, due to be raised again.

    Verified rather than remembered. The caller re-assesses each one, so a
    finding fixed while the agent worked elsewhere is dropped in silence and
    never raised. Nothing is reported from memory.
    """
    book = read_state(KIND, session).get("standing") or {}
    now = time.time()
    return [p for p, at in book.items() if now - float(at or 0) >= NAG_AFTER]


def note_standing(session: str, path: str, outstanding: bool) -> None:
    """Open or close a file's entry in the standing book."""
    state = read_state(KIND, session)
    book = dict(state.get("standing") or {})
    if outstanding:
        book.setdefault(path, time.time())
    else:
        book.pop(path, None)
    state["standing"] = book
    write_state(KIND, session, state)


def settle(session: str) -> str:
    """Assess every file this turn wrote, once each, at its final state.

    Returns the report and how many files were looked at, because a caller
    that only gets an empty string cannot tell "assessed four and they were
    clean" from "there was nothing to assess".

    Clears the pending list whether or not anything is reported, so a file
    that was fixed before the turn ended leaves no residue for the next one.
    """
    state = read_state(KIND, session)
    reported = state["reported"]
    reports, looked_at = [], []
    for path in [e["path"] for e in entries(state)]:
        looked_at.append(path)
        got = assess(path, session)
        if got is None:
            reported.pop(path, None)
            note_standing(session, path, False)   # clean now, stop nagging
            continue
        note_standing(session, path, True)
        report, digest = got
        if reported.get(path) == digest:
            # Same file, same content, same finding, already put to this
            # session once. Repeating it cannot teach anything the first
            # firing did not, and a Stop hook that repeats itself is a Stop
            # hook that never lets the turn end.
            trace("Stop:edit", "declined", "already reported this content",
                  file=path)
            continue
        reported[path] = digest
        reports.append(report)
    # said_of is re-read here rather than carried from the top. assess() can
    # add to it while this loop runs, and writing back the value captured
    # before the loop put the stale one on disk, so a language announced
    # during a turn was announced again on the next one.
    # Re-read rather than carried from the top: assess() writes to this state
    # while the loop runs, and writing back the value captured before the loop
    # put the stale one on disk. Every field added here has hit that once.
    # Anything standing past the timer is re-checked here, even if this turn
    # never touched it. An agent that walks away from a file does not make its
    # defect go away, and a finding only re-checked on write can be escaped by
    # never writing again.
    for path in standing(session):
        if path in looked_at:
            continue
        got = assess(path, session)
        if got is None:
            note_standing(session, path, False)
            continue
        reports.append(got[0])
        note_standing(session, path, False)       # restart the clock
        note_standing(session, path, True)
    live = read_state(KIND, session)
    write_state(KIND, session, {"pending": [], "reported": reported,
                                "said_of": live["said_of"], "told": live["told"],
                                "standing": live.get("standing") or {}})
    return "\n".join(reports), len(looked_at)


def main() -> int:
    raw = sys.stdin.read()
    session = session_key(raw)
    path = hook_input(raw)
    if not path:
        # No file path means this is the Stop firing, where the writes have
        # settled and the assessment is finally about the file that exists.
        report, looked = settle(session)
        if not report:
            # Recorded even with nothing to say. Without this row a Stop that
            # ran and found nothing reads identically to a Stop that never
            # ran, and on 2026-08-21 that cost a wrong diagnosis: two sessions
            # holding writes with no settle recorded looked like stranding,
            # and the missing row was the whole of the evidence.
            trace("Stop:edit", "declined",
                  f"{looked} file(s) assessed, none had anything to say")
            return 0
        print(report, file=sys.stderr)
        return 2                      # exit 2 puts stderr in front of the model
    if Path(path).suffix.lower() not in SOURCE:
        trace("PostToolUse:edit", "declined",
              f"not a checked extension: {Path(path).suffix or 'none'}",
              file=path)
        return 0
    late = stranded(KIND, session)
    if late:
        # The Stop hook is not running in this session, so these were held and
        # nothing came for them. Reporting late beats the hook going silently
        # dead, and saying why beats reporting them as if this were normal.
        reports = [r for r in (assess(p, session) for p in late) if r]
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
    trace("PostToolUse:edit", "deferred", "held until the writes settle",
          file=path)
    return 0                          # silence: the file may still be moving


# Exercised by tests/test_edit_check.py, which runs this as Claude Code does.
# In-process coverage cannot observe a child process, so the pragma records
# that the gap is in the instrument rather than in the tests.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
