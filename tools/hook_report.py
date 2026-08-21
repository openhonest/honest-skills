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
    out = [f"{len(rows)} events"]
    for event in sorted({r["event"] for r in rows}):
        got = [r for r in rows if r["event"] == event]
        fired = sum(1 for r in got if r["verdict"] == "fired")
        pct = fired / len(got) * 100
        out.append(f"\n{event}   {len(got)} runs, {fired} fired ({pct:.0f}%)")
        for why, n in Counter(r["why"] for r in got if r["verdict"] == "fired").most_common(5):
            out.append(f"    fired    {n:>4}  {why[:66]}")
        for why, n in Counter(r["why"] for r in got if r["verdict"] != "fired").most_common(5):
            out.append(f"    declined {n:>4}  {why[:66]}")
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
    rows = read(path)
    window = rows[-last:] if last else rows
    print(render(window))
    print(loop_closed(window))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
