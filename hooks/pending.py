#!/usr/bin/env python3
"""Hold a turn's writes until the files stop moving.

PostToolUse fires once per tool call, so a hook that assessed the file there
was assessing a state the next edit might already have replaced. A turn that
edits one file three times produced three reports, and the model read one
describing content two edits out of date. Adam reported exactly that on
2026-08-21: the hook looked like it was reading the file before the change.

The settled file is the only state worth an opinion, so the write firing
records the path and says nothing, and the Stop firing assesses what is
actually there.

Every hook that defers keeps its own state under its own `kind`, because two
hooks sharing one pending list would race: whichever ran first at Stop would
clear the list and the second would find nothing to assess.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def session_key(raw: str) -> str:
    """The session this write belongs to, or "shared" when none is given.

    Two sessions editing at once must not read each other's pending list. When
    Claude Code names no session the fallback is a single shared list, which
    can interleave; that is worse than isolation and better than losing writes.

    The id names a file, so anything that is not a plain name is stripped.
    """
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return "shared"
    key = str(d.get("session_id") or "shared")
    return "".join(c for c in key if c.isalnum() or c in "-_") or "shared"


def state_file(kind: str, session: str) -> Path:
    """Where this session's pending writes are held.

    HONEST_PENDING_DIR overrides the location. Without it the state could only
    live in the real home directory, so a test of the deferral would have had
    to write there, and a test that mutates the machine it runs on is a test
    nobody trusts twice.
    """
    base = os.environ.get("HONEST_PENDING_DIR") or os.path.expanduser("~/.claude")
    return Path(base) / f"honest-pending-{kind}-{session}.json"


def read_state(kind: str, session: str) -> dict:
    """The pending writes and the findings already put to this session.

    Unreadable or wrongly shaped state is treated as empty. A hook that raises
    on its own scratch file turns every write into an error notice.
    """
    try:
        d = json.loads(state_file(kind, session).read_text())
    except (OSError, ValueError):
        return {"pending": [], "reported": {}}
    pending = d.get("pending")
    reported = d.get("reported")
    return {"pending": pending if isinstance(pending, list) else [],
            "reported": reported if isinstance(reported, dict) else {}}


def write_state(kind: str, session: str, state: dict) -> None:
    """Record the state, or fail silently.

    Scratch state must never be able to break the thing it serves.
    """
    try:
        state_file(kind, session).parent.mkdir(parents=True, exist_ok=True)
        state_file(kind, session).write_text(json.dumps(state))
    except OSError:
        pass


def defer(kind: str, path: str, session: str) -> None:
    """Record the write and say nothing until the file stops moving."""
    state = read_state(kind, session)
    if path not in state["pending"]:
        state["pending"].append(path)
    write_state(kind, session, state)
