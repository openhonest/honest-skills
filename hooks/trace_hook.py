#!/usr/bin/env python3
"""Record that a hook ran, when someone asks for the record.

One implementation, imported by every hook. decision_check.py held this
privately until stub_check.py needed it too, which is the moment a private
copy becomes two things under one name.
"""
from __future__ import annotations

import json
import os
import re
import time


def running_version() -> str:
    """The version this hook is executing from, read out of its own path.

    A plugin is installed into a directory named for its version, so the file
    knows what it is. Nothing was reporting it, and a session executes whatever
    was registered when it launched, so a session could run a version several
    releases old with nothing saying so.
    """
    m = re.search(r"/honest-skills/(\d+\.\d+\.\d+)/", os.path.abspath(__file__))
    return m.group(1) if m else ""


def stale_note() -> str:
    """A line naming the running and registered versions when they differ.

    Empty when they match, when either is unknown, or when running from a
    source tree rather than an install. A hook that cannot tell says nothing
    rather than guessing it is current.
    """
    running = running_version()
    if not running:
        return ""
    try:
        with open(os.path.expanduser(
                "~/.claude/plugins/installed_plugins.json")) as fh:
            plugins = json.load(fh).get("plugins") or {}
    except (OSError, ValueError, AttributeError):
        return ""
    for name, entries in plugins.items():
        if "honest-skills" not in name or not entries:
            continue
        registered = entries[0].get("version") or ""
        if registered and registered != running:
            return (f"this session runs {running}, {registered} is installed. "
                    f"Restart to pick it up.")
    return ""


def trace(event: str, verdict: str, why: str, **facts: object) -> None:
    """Record that the hook ran, when someone asks for the record.

    A hook that stays silent leaves no way to tell "ran and correctly declined"
    from "never ran at all". That is the same defect as a check reporting a
    pass it did not perform, one level up, and it went unclosed for a day
    because the only evidence written was a marker for the firings.

    Off unless HONEST_HOOK_TRACE names a file, because a write on every turn
    is churn nobody asked for. A failure to write is swallowed on purpose:
    tracing must never be able to break the thing it observes.
    """
    path = os.environ.get("HONEST_HOOK_TRACE")
    if not path:
        return
    try:
        with open(path, "a") as fh:
            # The session and the version were added the same evening, after
            # a question the trace could not answer: whether a session that had
            # not restarted was running the new hooks. Rows from every session
            # share one file with nothing saying which wrote which, so the
            # answer had to come from an experiment instead of the record.
            #
            # The timestamp and the file were both absent until 2026-08-21,
            # when the first real question asked of this trace (does the edit
            # hook fire several times on one file in one turn) could not be
            # answered from it. An instrument that cannot say when or on what
            # records that something happened, which is not a measurement.
            row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "session": os.environ.get("CLAUDE_SESSION_ID", "")[:8],
                   "version": running_version(),
                   "event": event, "verdict": verdict, "why": why}
            # Named fields rather than more prose in `why`. Whether a firing
            # led to a fix cannot be read out of a sentence, and that is the
            # only question that says the loop closed rather than merely
            # spoke.
            row.update({k: v for k, v in facts.items() if v is not None})
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


