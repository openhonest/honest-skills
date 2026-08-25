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


SESSION = ""            # set once per run by the hook, from its own input
# Whether a hook actually fired this run. Armed by note_session(), which only
# the three hook entry points call.
#
# The trace is a record of hook firings, and until now it recorded anything at
# all that called trace(). The test suite wrote 223 rows per run, and every
# fire rate reported off this file for a day was contaminated. That was patched
# by redirecting the trace in conftest, which fixed the tests and left the shape
# alone; four days later a one-off probe run by hand put its own rows in the
# live file and inflated a standing count. The same class twice means the
# shape is the defect, so the gate now lives here rather than in each caller
# remembering to redirect.
FIRED = False


def note_session(raw: str) -> None:
    """Record which session this hook run belongs to.

    Read from the hook's input, which carries it, rather than from
    CLAUDE_SESSION_ID, which is never set. The state file keyed itself off the
    input all along and worked; only the trace read the environment, so every
    row since the field was added has said "". One fact, two sources, and the
    wrong one was the one people read.
    """
    global SESSION, FIRED
    FIRED = True
    try:
        SESSION = str((json.loads(raw) or {}).get("session_id") or "")[:8]
    except (ValueError, TypeError, AttributeError):
        SESSION = ""


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
    if not path or not FIRED:
        return
    try:
        with open(path, "a") as fh:
            # `file` carries the whole path. It held the basename until
            # 2026-08-21, which meant nothing reading the trace could tell a
            # scratch file from real work, so every consumer kept its own
            # hand-written list of filenames to exclude. One such list went
            # stale within the hour and reported a measurement whose entire
            # signal was the writer's own probe files.
            #
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
                   "session": SESSION,
                   "version": running_version(),
                   "event": event, "verdict": verdict, "why": why}
            # Named fields rather than more prose in `why`. Whether a firing
            # led to a fix cannot be read out of a sentence, and that is the
            # only question that says the loop closed rather than merely
            # spoke.
            row.update({k: v for k, v in facts.items() if v is not None})
            # Resolved, so one file is one key. The same file arrived as
            # "hooks/edit_check.py" and as its absolute path within two hours,
            # and every consumer keyed on the string: one file read as two, and
            # a rule standing on one file read as standing on two. Whatever the
            # caller's working directory was, the file is the same file.
            if row.get("file"):
                row["file"] = os.path.realpath(str(row["file"]))
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


