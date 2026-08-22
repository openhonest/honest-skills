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
import time
from pathlib import Path

# A write held longer than this, whose file has stopped moving, is not
# waiting for a turn to end. Nothing is coming for it.
STALE_AFTER = 600.0


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


def entries(state: dict) -> list[dict]:
    """The pending writes as {path, at} records.

    A bare string is what 0.22.0 and 0.23.0 wrote. It is read as held since the
    beginning of time, so anything stranded by those versions drains on the
    next write rather than sitting forever.
    """
    out = []
    for e in state["pending"]:
        if isinstance(e, str):
            out.append({"path": e, "at": 0.0})
        elif isinstance(e, dict) and isinstance(e.get("path"), str):
            out.append({"path": e["path"], "at": float(e.get("at") or 0.0)})
    return out


def stranded(kind: str, session: str) -> list[str]:
    """Held writes that no Stop firing is going to come back for.

    The Stop hook is registered when a session starts. A session whose
    registration predates the hook being added to Stop still runs the current
    scripts, so it defers every write and settles none of them, and the hook
    goes silently dead. Silence from a hook that is working and silence from a
    hook that is stranding everything are the same silence.

    A file still being edited is excluded: the wait is only over when the file
    has stopped moving too.
    """
    now = time.time()
    late = []
    for e in entries(read_state(kind, session)):
        if now - e["at"] < STALE_AFTER:
            continue
        try:
            if now - os.path.getmtime(e["path"]) < STALE_AFTER:
                continue
        except OSError:
            # The file is gone. Nothing to assess and nothing to say, but the
            # entry must still leave the list. Skipping it here meant only a
            # Stop firing could ever remove it, so a session that ended without
            # one left the path in the file for good. Assessing it returns
            # nothing, so this drains quietly.
            late.append(e["path"])
            continue
        late.append(e["path"])
    return late


def drop(kind: str, session: str, paths: list[str]) -> None:
    """Remove paths from the pending list, keeping the rest waiting."""
    state = read_state(kind, session)
    state["pending"] = [e for e in entries(state) if e["path"] not in paths]
    write_state(kind, session, state)


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
    held = entries(state)
    if not any(e["path"] == path for e in held):
        held.append({"path": path, "at": time.time()})
    state["pending"] = held
    write_state(kind, session, state)
