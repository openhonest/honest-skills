#!/usr/bin/env python3
"""What the hooks actually did, read back from the trace.

    uv run tools/hook_report.py                  # the whole file
    uv run tools/hook_report.py --last 200       # the most recent 200 events

Reads HONEST_HOOK_TRACE, or the path given as an argument.

WHY THIS EXISTS

A hook that is working correctly is silent, and a hook that is not installed is
also silent. Firings are visible in the transcript; declines are not, and the
ratio between them is the only thing that says whether a hook is calibrated or
merely quiet. Every rate reported here was previously an assumption.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter


def read(path: str) -> list[dict]:
    """Every well-formed row. A truncated last line is normal on a live file
    and is skipped rather than raised on."""
    rows = []
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and "event" in row:
                    rows.append(row)
    except OSError:
        return []
    return rows


def render(rows: list[dict]) -> str:
    if not rows:
        return ("no trace found. Set HONEST_HOOK_TRACE to a file path, in the "
                "env block of ~/.claude/settings.json, and restart.")
    out = [f"{len(rows)} events", f"covering {span(rows)}"]
    for event in sorted({r["event"] for r in rows}):
        got = [r for r in rows if r["event"] == event]
        fired = sum(1 for r in got if r["verdict"] == "fired")
        held = sum(1 for r in got if r["verdict"] == "deferred")
        pct = fired / len(got) * 100
        # Held is its own verdict. Counting it as declined made a hook that
        # caught three files read as "0 fired (0%)", which is the display
        # saying nothing happened about the case the hook exists for.
        line = f"\n{event}   {len(got)} runs, {fired} fired ({pct:.0f}%)"
        out.append(line + (f", {held} held for the settle" if held else ""))
        for verdict in ("fired", "deferred", "declined"):
            for why, n in Counter(r["why"] for r in got
                                  if r["verdict"] == verdict).most_common(5):
                out.append(f"    {verdict:<8} {n:>4}  {why[:66]}")
    return "\n".join(out)


SCRATCH = ("/tmp/", "/private/tmp/", "/var/folders/")


def is_real_work(row: dict) -> bool:
    """False for a file under a scratch or temp tree.

    Classified by path rather than by name. A hand-written list of filenames to
    exclude went stale within an hour on 2026-08-21 and reported a measurement
    whose entire signal was the writer's own probe files. A rule that has to be
    updated by hand to stay correct will be wrong most of the time.
    """
    f = row.get("file") or ""
    return not any(f.startswith(s) for s in SCRATCH)


def span(rows: list[dict]) -> str:
    """The period the rows cover, so a count can become a rate.

    Rows written before 0.22.0 carry no timestamp and are excluded from this
    rather than guessed at.
    """
    stamped = sorted(r["ts"] for r in rows if r.get("ts"))
    if not stamped:
        return "no timestamped rows: this trace predates 0.22.0"
    if len(stamped) == 1:
        return f"one timestamped row, at {stamped[0]}"
    return f"{stamped[0]} to {stamped[-1]}, {len(stamped)} of {len(rows)} rows stamped"


def settled(rows: list[dict]) -> str:
    """What deferring bought, measured rather than asserted.

    Three denominators, each named where it is used, because reporting a rate
    without saying what it is a rate OF is how the same hook was described as
    firing on 53 percent, 7.7 percent and 0.8 percent of runs in one afternoon.
    """
    out = ["", "WHAT DEFERRING BOUGHT"]
    # A Bash deferral feeds both settles, so counting only the same-named
    # event reported "0 write(s) held, 14 assessed", and the collapse ratio
    # could never compute. Thirty percent of one session's writes went through
    # Bash, so this is most of them.
    from_bash = sum(int(m.group(1))
                    for r in rows if r["event"] == "PostToolUse:bash"
                    and r["verdict"] == "deferred"
                    for m in [re.match(r"(\d+) held", r["why"])] if m)
    for kind in ("edit", "stub"):
        held = [r for r in rows if r["event"] == f"PostToolUse:{kind}"
                and r["verdict"] == "deferred"]
        turns = [r for r in rows if r["event"] == f"Stop:{kind}"]
        fired = [r for r in turns if r["verdict"] == "fired"]
        repeats = [r for r in turns if "already reported" in r.get("why", "")]
        if not held and not from_bash and not turns:
            out.append(f"  {kind}: nothing yet")
            continue
        total_held = len(held) + from_bash
        out.append(f"  {kind}: {total_held} write(s) held "
                   f"({len(held)} from an edit, {from_bash} from a script), "
                   f"{len(turns)} assessed at a turn end, {len(fired)} reported")
        if turns:
            out.append(f"       {len(fired) / len(turns) * 100:.0f}% of assessed "
                       f"files had something to say (denominator: files assessed)")
        if total_held and fired:
            out.append(f"       {total_held / len(fired):.1f} write(s) per report, "
                       f"which is what the old shape reported separately")
        if repeats:
            out.append(f"       {len(repeats)} repeat(s) suppressed by the content guard")
    bash = [r for r in rows if r["event"] == "PostToolUse:bash"]
    if bash:
        deferred = sum(1 for r in bash if r["verdict"] == "deferred")
        out.append(f"  bash: {len(bash)} command(s) seen, {deferred} moved a source file")
    return "\n".join(out)


def loop_closed(rows: list[dict]) -> str:
    """Files that fired and later came back with fewer findings, or none.

    This is the only measurement that says the hook changed anything. A firing
    count says it spoke; a file going from findings to none says someone acted
    on what it said. Files still open at the end of the trace are counted
    separately rather than folded into either, because a file nobody has
    revisited is not a file that was ignored.
    """
    seen: dict[str, list[int]] = {}
    for r in rows:
        for name, hits in (r.get("findings") or {}).items():
            seen.setdefault(name, []).append(len(hits))
    fixed = [n for n, h in seen.items() if h[0] > 0 and h[-1] == 0]
    better = [n for n, h in seen.items() if h[-1] and h[-1] < h[0]]
    open_still = [n for n, h in seen.items() if h[-1] and h[-1] >= h[0]]
    once = [n for n, h in seen.items() if len(h) == 1 and h[0] > 0]
    out = [f"\nfiles judged more than once: {sum(1 for h in seen.values() if len(h) > 1)}",
           f"  went to zero findings   {len(fixed):>4}  {', '.join(sorted(fixed)[:6])}",
           f"  fewer than before       {len(better):>4}  {', '.join(sorted(better)[:6])}",
           f"  unchanged               {len(open_still):>4}  {', '.join(sorted(open_still)[:6])}",
           f"\nfired once and not seen again: {len(once)}",
           "",
           "UNCHANGED IS NOT IGNORED, and this report cannot tell them apart.",
           "A finding can be overruled with a reason, deferred with a ticket, or",
           "passed over. All three leave the file alone and read identically here.",
           "One session's three firings were one filed issue and two reasoned",
           "rejections: zero code changes, and nothing about that was ignoring it.",
           "A file seen once is evidence of nothing either way."]
    return "\n".join(out)


def main() -> int:
    argv = sys.argv[1:]
    last = 0
    if "--last" in argv:
        i = argv.index("--last")
        last = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    path = argv[0] if argv else os.environ.get("HONEST_HOOK_TRACE", "")
    if not path:
        print("no path given and HONEST_HOOK_TRACE is unset")
        return 2
    rows = [r for r in read(path) if is_real_work(r)]
    window = rows[-last:] if last else rows
    print(render(window))
    print(settled(window))
    print(loop_closed(window))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
