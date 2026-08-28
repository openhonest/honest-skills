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
import trace_hook  # noqa: E402
from freshness import principles_note  # noqa: E402
from skill_drift import note as skill_drift_note  # noqa: E402
from trace_hook import note_session, stale_note, trace  # noqa: E402

# The vendored principles, beside this file in the installed plugin. Resolved
# from __file__ rather than from the working directory, because a hook runs
# wherever the session happens to be.
SKILL_FILE = Path(__file__).resolve().parent.parent / "skills/honest-code/SKILL.md"

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
KIND = "edit"
# A suppression is now whatever the analyzer says was withheld, never a
# decorator this hook spotted being added. Detecting the annotation counted 62
# on one package that excused nothing, and 10 of 11 on another. A signal wrong
# three times in four is worse than none when an honest source exists.
# How long a standing finding waits before it is raised again unprompted. An
# agent that walks away from a file does not make its defect go away, and a
# finding only re-checked when the file is touched can be escaped by never
# touching it. Adam's rule: nag on a timer until the cause is verified gone.
NAG_AFTER = 600.0

# A file with thirty violations produces a wall nobody reads. Show the first
# few and say how many were held back, because a truncated list that does not
# say it is truncated is the same lie as a findings list with no coverage.
MAX_CLAUSE_FINDINGS = 5


WRAP_MAX = 100          # a prose line shorter than this, with prose under it, is a wrap
MARKDOWN = {".md", ".markdown"}


def hard_wrap_finding(path: str, text: str) -> dict | None:
    """A line break inside a paragraph of a markdown file.

    One paragraph is one line, however long. The editor soft-wraps, so a hard
    wrap fights it, breaks reflow in every renderer, and turns a one-word edit
    into a whole-paragraph rewrap.

    This exists because saying it did not work. It is in the global
    instructions in capitals, it is in memory, and on 2026-08-25 Adam had to
    shout at me four times in a row: I wrapped four generated files at eighty
    columns, fixed them, and then wrapped the replies reporting the fix. A rule
    with no check behind it is advice, and advice is what gets lost.

    It was written that morning and deleted thirteen minutes later, inside a
    commit about how long the Bash hook took to walk the home tree. The commit
    message never mentioned it. Within the day another session hard-wrapped
    markdown twice, once in the first commit of a repository built to hold the
    rule. A check can be lost as quietly as a rule can, and riding out of the
    tree in an unrelated commit is how.

    Fenced code, tables, lists, quotes, headings and frontmatter all keep their
    own line breaks and are skipped.
    """
    if Path(path).suffix.lower() not in {".md", ".markdown"}:
        return None
    lines = text.split("\n")
    fence = front = False
    bullet = re.compile(r"^(\s*)([-+]|\*(?!\*)|\d+[.)])\s")
    wrapped = []
    for i, line in enumerate(lines[:-1]):
        s = line.strip()
        if i == 0 and s == "---":
            front = True
            continue
        if front:
            front = s != "---"
            continue
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
            continue
        if fence or not s:
            continue
        if s.startswith(("#", ">", "|")) or bullet.match(line) or line.startswith("    "):
            continue
        nxt = lines[i + 1].strip()
        if not nxt or nxt.startswith(("#", ">", "|", "```", "~~~")) or bullet.match(lines[i + 1]):
            continue
        if len(line) < WRAP_MAX:
            wrapped.append(i + 1)
    if not wrapped:
        return None
    return {"indicator": "WRAP", "verdict": "OUT_OF_SPEC",
            "detail": f"{len(wrapped)} line break(s) inside a paragraph, first at "
                      f"line {wrapped[0]}",
            "action": "join each paragraph onto one line, however long, and let "
                      "the editor wrap it"}


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
    """Removed. L1.17 has an owner and this was not it.

    This counted `len(text.splitlines())` against 1000. The analyzer's own
    L1.17 counts code lines, subtracting large data literals, because a file
    that is big because it holds a table is not the god-file smell the
    indicator is about.

    Same indicator name, same threshold, different measure, and they disagreed
    in the direction that reads as authoritative. `lang_spec.py` is a
    nine-language vocabulary table: 1113 raw lines, 336 code lines. The
    repository gate passes it and this hook reported it as over the limit, on
    2026-08-22, to the session that owns the file.

    Nothing replaces it here. The per-file response carries no line count, so
    asking for the right number is a change on the analyzer's side, and a
    second implementation of a measure is what produced the wrong report in the
    first place. Silence is the honest state until the authority can be asked.
    """
    return None


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

    Two more reasons joined the excused list on 2026-08-28, after the
    unmeasured count reached a quarter of everything written and the cause
    turned out to be the same two clauses on every Python file.

    "nothing to read" comes from One Gherkin Per Function on a file with no
    feature files beside it. "decided over the repository" comes from
    References Resolve Statically, which is a repository-level rule a
    single-file check cannot answer. Neither is a failure to look. Counted as
    gaps, they marked every Python file as not measured, including files at 100
    per cent conformity, and a file that reached 100 fell out of the fixed
    column at the moment it got there.

    The list is strings the analyzer chooses, so it will go stale the day audit
    adds a fourth reason, and it will go stale in the flattering direction by
    counting a real gap as excused. That is the wrong direction for this rule
    and it is why the list is short and named rather than pattern-matched.
    """
    excused = {"not applicable", "never", "nothing to read",
               "decided over the repository"}
    return sum(1 for c in clauses
               if not c.get("decided") and c.get("undecided") not in excused)


# The keys this hook reads out of the analyzer's per-file response. audit
# shipped 1.0.0 promising a stable JSON shape, then changed L1.21's shape twice
# in a day and put it outside that promise in the changelog. So the shape moves
# by declaration, and reading it with .get() everywhere means a field that goes
# away degrades to the flattering default: absent blocks read as no blocks,
# absent grade reads as no grade. That is the exact failure this hook exists to
# report, in the hook.
# Only the keys whose ABSENCE would be misread as good news. `clauses` gone
# means no findings, and `unexamined` gone means no embedded blocks; both read
# as a clean file. A missing `band` or `conformity` costs a grade in the record
# and cannot be mistaken for a pass, so it is not worth refusing over.
# One key. `clauses` gone means no findings, which reads as a clean file, and
# it has been in every version of this response. `unexamined` is hours old, so
# refusing on it would refuse every older analyzer for being older, and a
# missing `band` costs a grade in the record and cannot be mistaken for a pass.
NEEDED = ("clauses",)


def shape_complaint(data: dict) -> str:
    """What this hook expected from the analyzer and did not get.

    Empty when the response carries everything read here. A response missing a
    key is not a file with nothing to say about it.
    """
    missing = [k for k in NEEDED if k not in data]
    return ", ".join(missing)


def analyzer_says_all(paths: list[str]) -> dict[str, dict]:
    """One analyzer run for every file in the turn, keyed by path.

    The analysis itself costs nothing measurable: on a two-line file `--help`
    and a real run both take 71ms, so the whole bill is starting the process.
    Paid per file, a twenty-file turn spent about 2.6 seconds starting Python
    twenty times to do twenty milliseconds of work.

    A run that skipped a file it could not measure and reported the rest would
    claim a coverage it did not have, so an absent entry is treated as no
    result rather than as a clean one.
    """
    exe = shutil.which(ANALYZER)
    if exe is None or not paths:
        return {}
    try:
        r = subprocess.run([exe, "--honest-code", *paths, "--format", "json"],
                           capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    if isinstance(data, dict):
        data = [data]
    return {str(d.get("path")): d for d in data if isinstance(d, dict)}


def analyzer_says(path: str) -> tuple[dict | None, dict | None]:
    """One run of the analyzer, parsed once.

    Returns the response and, when it could not be had, the NOT_RUN finding
    that explains why. Split out so the finding and the grade come from a
    single run: reading them separately ran the analyzer twice per file, which
    on a twenty-file turn was nine seconds spent to learn the same thing.
    """
    exe = shutil.which(ANALYZER)
    if exe is None:
        return None, {"indicator": "L1.21", "verdict": "NOT_RUN",
                      "detail": f"{ANALYZER} is not on PATH",
                      "action": "this file was not checked against the Honest "
                                "Code clauses"}
    try:
        r = subprocess.run([exe, "--honest-code", path, "--format", "json"],
                           capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
        # One path returns an object and several return an array.
        # Reading only the object shape would treat an array as a
        # response with every key missing, which is a true statement
        # about a list and a wrong one about the file.
        if isinstance(data, list):
            data = data[0] if data else {}
        return data, None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, {"indicator": "L1.21", "verdict": "NOT_RUN",
                      "detail": "the analyzer ran and its output could not be read",
                      "action": "run it by hand on this file to see why"}


def honest_code_finding(path: str, data: dict) -> dict | None:
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
    missing = shape_complaint(data)
    if missing:
        return {"indicator": "L1.21", "verdict": "NOT_RUN",
                "detail": f"the analyzer's response is missing {missing}, so "
                          f"this hook could not read it",
                "action": "the analyzer's shape has moved; nothing here was "
                          "checked, which is not the same as clean"}
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
    # Both kinds of excuse, and only ones that actually withheld a finding.
    # `allowed` is an allow comment naming a clause. `declared` is a boundary
    # declaration, and it arrives only once audit's branch merges. Until then
    # the field is absent and this reads as zero, which is the honest value:
    # not "no declarations excused anything" but "nothing told me they did".
    #
    # This replaces counting markers, which counted 62 that excused nothing on
    # one package and 10 of 11 on another.
    # These two lists are separate in the analyzer's output on purpose and they
    # mean opposite things. Merged, a file was told it was "not conforming
    # code" for having said where its edges are.
    #
    # `allowed` is an author overriding a rule with a stated reason. That is a
    # suppression, declared out loud, which is why the reason is required.
    #
    # `declared` is a boundary decorator. Clause 4 asks whether I/O sits at an
    # edge and INFERS the edge from the call graph, because most projects say
    # nothing. The decorator is the project answering the question. Where a
    # declaration and an inference disagree, the declaration is the better
    # evidence, so a function under one is answering the rule rather than
    # escaping it.
    silenced = [a for c in clauses for a in (c.get("allowed") or [])]
    declared = [a for c in clauses for a in (c.get("declared") or [])]
    hits = [f for c in clauses for f in (c.get("findings") or [])]
    # A block of another language held in a string is checked now, not merely
    # noticed, so what comes back is findings rather than a label. They are
    # real violations in real code and they count as such.
    #
    # Files carrying such a block are no longer held out of the rate. audit's
    # answer to whether a block that IS the file's subject can be told from one
    # the file ships was no, not from the source alone, and excluding them
    # moved a number for a reason nobody reading it could see.
    embedded = [{**f, "embedded": b.get("language")}
                for b in (data.get("unexamined") or [])
                for f in (b.get("findings") or [])]
    hits = hits + embedded
    # Scoped only when there is something to scope. Asking git on every file
    # made the call unconditional, which is work nobody asked for on the
    # common path.
    mine = []
    if (silenced or declared) and not hits:
        touched_now = changed_lines(path)
        def on_changed(xs):
            return [a for a in xs
                    if touched_now is None or a.get("line") in touched_now]
        mine = on_changed(silenced)
        rests_on = on_changed(declared)
        if rests_on and not mine:
            # Not a mark against the file. What it says is where the clean
            # reading came from, so a reader can weigh the declaration rather
            # than trust it silently.
            first = rests_on[0]
            return {"indicator": "L1.21", "verdict": "DECLARED",
                    "detail": f"this file's clean reading rests on "
                              f"{len(rests_on)} boundary declaration(s); "
                              f"line {first.get('line')} states the edge that "
                              f"answers the rule",
                    "action": "no change needed; the declaration is the "
                              "project saying where its edges are"}
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
    lines = [f"{h.get('clause')} line {h.get('line')}"
             + (f" (in embedded {h['embedded']})" if h.get("embedded") else "")
             + f": {h.get('detail')}"
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


def findings_for(path: str, text: str,
                 said: dict | None = None) -> tuple[list[dict], dict]:
    """Every check's result, including the ones that did not run.

    Suppressing a NOT_RUN here would make the coverage count in render()
    impossible to compute, and the count is the whole of the honesty.
    """
    # `said` is this turn's single analyzer run, keyed by path. Absent, the
    # analyzer is run for this file alone, which is what a caller outside a
    # settle needs.
    if said is None:
        data, failed = analyzer_says(path)
    else:
        data = said.get(path)
        failed = None if data else {
            "indicator": "L1.21", "verdict": "NOT_RUN",
            "detail": "the analyzer returned no result for this file",
            "action": "nothing was checked, which is not the same as clean"}
    hc = failed if data is None else honest_code_finding(path, data)
    # decided_clauses travels with the conformity, always. 92.9 per cent over
    # nineteen readable clauses and 92.9 per cent over three are different
    # facts, and the share alone cannot tell them apart.
    # `unexamined` names content inside a readable file that no clause looked
    # at: JavaScript held in a Python string, for instance. The file can score
    # 100 per cent and be right about it, because every clause that read it
    # held. The share alone cannot say that most of the file was never read,
    # and decided_clauses does not help: it reads 14, which looks normal.
    grade = {} if data is None else {"conformity": data.get("conformity"),
                                     "band": data.get("band"),
                                     "decided": data.get("decided_clauses"),
                                     "unexamined": data.get("unexamined") or []}
    return ([f for f in (line_count_finding(text), whitespace_finding(text), hc)
             if f is not None], grade)


# An advisory broken this long has stopped degrading gracefully and started
# being a dead component wearing graceful degradation as a disguise. Shorter
# than the freshness threshold because these run many times a day rather than
# once, so a day of them is hundreds of failures rather than one missed poll.
ADVISORY_BROKEN_AFTER = 24 * 60 * 60


def advisory_health(name: str, ok: bool, now: float) -> float:
    """Record whether an advisory worked, and return how long it has been down.

    Returns 0.0 while it is working. A run of failures is timed from the first
    of them rather than counted, for the reason the freshness check is: a count
    only rises while something is running often enough to fail, and the age
    answers the question a reader has.

    Kept beside the other hook state rather than in the plugin directory, which
    is named for a version and replaced on update.
    """
    base = os.environ.get("HONEST_PENDING_DIR") or os.path.expanduser("~/.claude")
    f = Path(base) / "honest-advisory-health.json"
    try:
        book = json.loads(f.read_text())
        book = book if isinstance(book, dict) else {}
    except (OSError, ValueError):
        book = {}
    entry = book.get(name) if isinstance(book.get(name), dict) else {}
    if ok:
        entry = {"ok_at": now}
        down = 0.0
    else:
        entry.setdefault("since", now)
        down = now - float(entry["since"])
    book[name] = entry
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(book))
    except OSError:
        # The health record failing cannot be allowed to break the thing whose
        # health it records. Reported as working, which errs toward silence
        # rather than toward a warning nobody can act on.
        return 0.0
    return down


def advisories(now: float | None = None) -> list[str]:
    """The version and freshness notes, and never an exception.

    These are advice about the tooling. The findings beside them are the
    hook's actual job. Called plainly, a fault in either one propagates out of
    render and the hook reports nothing at all: a note about whether the
    principles are current would stop a real finding reaching a writer. Tested
    by breaking the freshness module and watching a live finding vanish.

    This is not the interior distrust the principles warn against. It is a
    boundary between the thing that must work and two things that only inform,
    and the direction of failure across it is the whole point.

    Swallowed in the turn, recorded in the trace. A fault nobody can see is
    the defect this project exists to name, and a fault that breaks the writer's
    turn is worse. The trace is where it can be counted without costing anyone
    a turn.
    """
    now = time.time() if now is None else now
    out = []
    for name, get in (("stale_note", stale_note),
                      ("principles_note", lambda: principles_note(SKILL_FILE)),
                      # trace_hook.SESSION rather than a value captured at
                      # import: note_session sets it when the hook fires, and
                      # an import-time read would always see the empty string.
                      ("skill_drift",
                       lambda: skill_drift_note(trace_hook.SESSION or ""))):
        try:
            note = get()
        except Exception as e:                    # noqa: BLE001
            trace("advisory", "fired", f"{name} raised: {type(e).__name__}: {e}")
            down = advisory_health(name, False, now)
            if down >= ADVISORY_BROKEN_AFTER:
                # Past here it is not an advisory degrading gracefully. A fault
                # swallowed once and traced is handled; swallowed on every run
                # for a day and traced every time is a module that has been
                # dead since Tuesday with nothing saying so.
                since = time.strftime("%Y-%m-%d",
                                      time.localtime(now - down))
                out.append(f"the {name.replace('_', ' ')} check has been "
                           f"failing since {since} and this hook has been "
                           f"hiding the fault. Its last error: "
                           f"{type(e).__name__}: {e}")
            continue
        advisory_health(name, True, now)
        if note:
            out.append(note)
    return out


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
    for note in advisories():
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


def assess(path: str, session: str = "",
           said: dict | None = None) -> tuple[str, str, bool] | None:
    """The report, the content it describes, and whether a defect is standing.

    Returns None when the file is gone, unreadable, or has nothing to say.
    The content hash travels with the report so a finding the model chose not
    to act on is not put a second time.

    The third element is False when everything reported is a boundary
    declaration, which is a note rather than a defect and so never joins the
    nag timer. It is computed here, from the findings, because the caller only
    has rendered text and reading a verdict back out of prose is a guess.
    """
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        # The file is gone or unreadable. That is not a finding about the
        # code, and a hook that reports it teaches the reader to ignore hooks.
        return None
    if Path(path).suffix.lower() in MARKDOWN:
        # Markdown reaches here only from the Bash sweep. Write and Edit answer
        # for it at the write, before anything is deferred.
        #
        # This path existed for code alone until 2026-08-25, when frame
        # reported hard-wrapping markdown twice on a day the check was live for
        # Write and Edit. It writes almost every file through a shell heredoc,
        # under an instruction to prefer the shell, so the rule had never once
        # been applied to the way that session actually writes. A check wired
        # to some of the ways a file can be written is not a check on the file.
        found = hard_wrap_finding(path, text)
        if not found:
            return None
        return (render(path, [found]),
                hashlib.sha256(text.encode()).hexdigest(), True)
    findings, grade = findings_for(path, text, said)
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
    # A declaration is not a broken rule, so it does not read as "fired". It
    # answers clause 4, and a file carrying only declarations is conforming
    # code that said where its edges are.
    verdict = ("suppressed"
               if hits and all(f["verdict"] in ("NOT_RUN", "SUPPRESSED")
                               for f in findings)
               else "declared"
               if hits and all(f["verdict"] in ("NOT_RUN", "DECLARED")
                               for f in findings)
               else "fired" if hits else "declined")
    trace("Stop:edit", verdict,
          f"{ran} of {CHECKS} ran, {Path(path).suffix or 'no suffix'}"
          + (f", {','.join(hits)}" if hits else ""),
          file=path, unit=unit, checks_ran=ran, checks=CHECKS,
          clauses=clauses or None,
          conformity=grade.get("conformity"), band=grade.get("band"),
          decided=grade.get("decided"),
          unexamined=grade.get("unexamined") or None)
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
                    hashlib.sha256(text.encode()).hexdigest(), False)
        # Nothing surfaced. A check that did not run is not an observation
        # about this file, and announcing it here would put the tool's own
        # limitation where a finding about the code belongs.
        return None
    standing_now = any(f["verdict"] not in ("NOT_RUN", "DECLARED")
                       for f in findings)
    return (render(path, findings),
            hashlib.sha256(text.encode()).hexdigest(), standing_now)


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
    held = entries(state)
    queued = [e["path"] for e in held]
    # Which of these this session is only believed to have written.
    guessed = {e["path"] for e in held if e.get("attributed")}
    said = analyzer_says_all([p for p in queued
                             if Path(p).suffix.lower() in SOURCE])
    for path in queued:
        looked_at.append(path)
        got = assess(path, session, said)
        if got is None:
            reported.pop(path, None)
            note_standing(session, path, False)   # clean now, stop nagging
            continue
        report, digest, outstanding = got
        # A declaration is a note, not a defect, so it is said once and never
        # put on the nag timer. On the timer it told one session four times
        # that a file was not conforming code, and the function it named had
        # a single read for a body.
        note_standing(session, path, outstanding)
        if reported.get(path) == digest:
            # Same file, same content, same finding, already put to this
            # session once. Repeating it cannot teach anything the first
            # firing did not, and a Stop hook that repeats itself is a Stop
            # hook that never lets the turn end.
            trace("Stop:edit", "declined", "already reported this content",
                  file=path)
            continue
        reported[path] = digest
        # A file found by timestamp under the working directory is not known to
        # be this session's. Saying so is the difference between a finding and
        # an accusation: one session was told about a file in another's working
        # copy, annotated by someone else, that it had never touched.
        reports.append(report + (
            "\n      attributed to this session because the file changed while "
            "a command ran here, not because an edit was seen. It may be "
            "another session's." if path in guessed else ""))
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
        if got is None or not got[2]:
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
    note_session(raw)
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
    if Path(path).suffix.lower() in {".md", ".markdown"}:
        # Markdown is not checked for code, but it is checked for this.
        try:
            body = Path(path).read_text(errors="replace")
        except OSError:
            return 0
        found = hard_wrap_finding(path, body)
        trace("PostToolUse:edit", "fired" if found else "declined",
              "hard wrap" if found else "no hard wrap", file=path)
        if not found:
            return 0
        print(f"honest-prose: {found['detail']} in {os.path.basename(path)}\n"
              f"      {found['action']}", file=sys.stderr)
        return 2
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
