"""Tell a session when a skill changed after it started reading that skill.

Hooks pick up new code the moment it lands on disk, because a hook is a
subprocess and the file is read every time it fires. Swapping the plugin
under a running session works, and it has worked here since 0.51.0.

Skills do not work that way. A session is handed the list of skills and their
descriptions when it starts, and the description is what decides when a skill
fires. Change the description and every running session keeps the old one. This
was verified rather than assumed: on 2026-08-28 sitrep's trigger was narrowed
from seven phrases to one, and the session that made the change was still
holding the seven-phrase description an hour later.

The body is read when the skill is invoked, so a session that invokes it after
the swap probably reads the new text. A session that already invoked it holds
the old text in its context, and nothing on disk reaches that.

So the swap cannot deliver a skill, and this says so. On the first hook firing
after a skill file changes, the session gets one line naming which skills moved
and telling it to re-read them. That is the whole of what is available: the hook
can see the disk and cannot see the session's context, so it can report the
mismatch and cannot repair it.

What it deliberately does not do. It does not fire on a fresh session, because
a session that has read nothing yet has nothing stale. It does not repeat once
it has been said for a given set of changes, because a line repeated on every
write is a line people learn to skip.
"""
import hashlib
import json
import os
import time
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"


def state_file() -> Path:
    """Where the last-seen skill fingerprints live.

    Beside the other hook state rather than in the plugin directory. A plugin
    directory is named for a version and replaced on update, so a record kept
    there would be discarded by the very swap it exists to report.
    """
    base = os.environ.get("HONEST_PENDING_DIR") or os.path.expanduser("~/.claude")
    return Path(base) / "honest-skill-drift.json"


def fingerprints(root: Path) -> dict:
    """A hash per skill, taken from the file on disk.

    Hashed rather than timestamped. A hot swap copies files in, so every
    mtime moves whether or not the text did, and a timestamp would report
    every skill as changed on every release.
    """
    out = {}
    for skill in sorted(root.glob("*/SKILL.md")):
        try:
            out[skill.parent.name] = hashlib.sha256(
                skill.read_bytes()).hexdigest()[:16]
        except OSError:
            continue
    return out


def read_state() -> dict:
    try:
        got = json.loads(state_file().read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    try:
        state_file().parent.mkdir(parents=True, exist_ok=True)
        state_file().write_text(json.dumps(state))
    except OSError:
        # The record of what changed cannot be allowed to break the hook that
        # reports it. A failed write means the same drift is reported again on
        # the next firing, which is noisy and honest.
        pass


def changed(session: str, now: float | None = None, root: Path = SKILLS) -> list[str]:
    """Skills whose text differs from what this session was last told about.

    Returns the names, or an empty list. The first call for a session records
    what is on disk and reports nothing: a session that has just started has
    read nothing yet, so nothing it holds can be stale.
    """
    now = time.time() if now is None else now
    here = fingerprints(root)
    if not here:
        return []
    state = read_state()
    seen = state.get(session)
    if not isinstance(seen, dict) or not seen.get("skills"):
        write_state({**state, session: {"skills": here, "at": now, "told": []}})
        return []
    before = seen["skills"]
    moved = sorted(n for n, h in here.items() if before.get(n) != h)
    if not moved:
        return []
    # Said once per set of changes. A session told about sitrep and then told
    # again about sitrep on every later write learns to skip the line, and the
    # next real change goes with it.
    if moved == sorted(seen.get("told") or []):
        return []
    write_state({**state, session: {"skills": before, "at": seen.get("at", now),
                                    "told": moved}})
    return moved


def note(session: str, now: float | None = None, root: Path = SKILLS) -> str:
    """One line naming the skills that moved, or "" when none did."""
    moved = changed(session, now, root)
    if not moved:
        return ""
    return (f"these skills changed on disk after this session started: "
            f"{', '.join(moved)}. A hook picks up new code immediately; a skill "
            f"does not, because its description was fixed when the session "
            f"started and its text is already in context. Re-read the file, or "
            f"restart, before relying on it.")


def forget(session: str) -> None:
    """Drop a session's record, so the next call treats it as new.

    Used when a session is known to have re-read its skills. Nothing calls this
    automatically, because the hook cannot see a session read a file.
    """
    state = read_state()
    if session in state:
        state.pop(session)
        write_state(state)
