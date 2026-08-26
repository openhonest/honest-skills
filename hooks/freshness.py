"""Tell an installed session when the principles it holds have moved on.

The condition on vendoring is that a copy cannot go stale silently. Two links
of that chain are automation and neither of them reaches a person who installed
the plugin. A push to the principles repository notifies this repository, and
this repository syncs and releases. Then the text sits in a version-pinned
directory on someone's machine and stops following anything at all. A release is
a snapshot, and the source can move the next day.

So the copy says so itself. A hook reads a small cache and adds one line when
what it holds is behind the source. The cache is refreshed at most once a day by
a detached process, so no hook ever waits on the network: a check that costs a
session two seconds is a check someone turns off.

Three states, kept apart on purpose, because the third is the one that goes
wrong. CURRENT says the copy matches. BEHIND names the commit it holds and the
one the source is at. UNKNOWN says the check has not run or could not run, and
it reads as unknown rather than as current. Not having looked is not evidence of
being up to date, and every measurement defect found in this project has been
the same shape: something unmeasured landing in the numerator.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

API_URL = ("https://api.github.com/repos/openhonest/"
           "honest-code-principles/commits/main")
EVERY = 24 * 60 * 60          # a day; the text moves in commits, not in minutes
TIMEOUT = 10
BEGIN = "<!-- BEGIN VENDORED honest-code-principles.md"


def cache_file() -> Path:
    """Where the last answer is kept.

    Beside the other hook state rather than inside the plugin directory. A
    plugin directory is named for a version and replaced on update, so a cache
    written there would be thrown away exactly when it is most useful and every
    update would start from no answer at all.
    """
    base = os.environ.get("HONEST_PENDING_DIR") or os.path.expanduser("~/.claude")
    return Path(base) / "honest-principles-freshness.json"


def vendored_sha(skill: Path) -> str:
    """The commit recorded in the vendored block, or "" when there is none."""
    try:
        text = skill.read_text(errors="replace")
    except OSError:
        return ""
    at = text.find(BEGIN)
    if at < 0:
        return ""
    head = text[at + len(BEGIN):text.find("-->", at)].strip()
    return head[1:].strip() if head.startswith("@") else ""


def read_cache() -> dict:
    try:
        got = json.loads(cache_file().read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def refresh(now: float) -> dict:
    """Ask the source where it is, and record the answer or the failure.

    The failure is recorded rather than dropped. Without it a run that could
    not reach the network is indistinguishable from one that never ran, and
    both read as "no news", which is the reading that makes a stale copy
    invisible.
    """
    state = {"checked_at": now}
    try:
        import urllib.request
        with urllib.request.urlopen(API_URL, timeout=TIMEOUT) as r:
            state["source_sha"] = json.load(r)["sha"]
    except Exception as e:                        # noqa: BLE001
        # Every failure is the same fact here: no answer. Narrowing this to a
        # list of exception types means a type nobody listed escapes to the
        # caller, and the caller is a hook that must never break a turn.
        state["error"] = f"{type(e).__name__}: {e}"
    try:
        cache_file().parent.mkdir(parents=True, exist_ok=True)
        cache_file().write_text(json.dumps(state))
    except OSError:
        pass
    return state


def due(state: dict, now: float) -> bool:
    return now - float(state.get("checked_at") or 0) >= EVERY


def start_refresh() -> None:
    """Run the check in a process nobody waits for.

    Detached rather than inline. Inline, every hook firing on the day the cache
    expires pays the network, and the first thing anyone does with a hook that
    costs seconds is remove it.
    """
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--refresh"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def principles_note(skill: Path, now: float | None = None) -> str:
    """One line when the held principles are behind the source, else "".

    Reads the cache and never the network, so this is free to call on every
    firing. When the cache is stale it starts a refresh and returns what it
    knows now, which may be nothing. The next firing after that has the answer.
    """
    now = time.time() if now is None else now
    mine = vendored_sha(skill)
    if not mine:
        return ""                       # nothing vendored here to be stale
    state = read_cache()
    if due(state, now):
        start_refresh()
    theirs = state.get("source_sha") or ""
    if not theirs:
        if state.get("error"):
            return ("the Honest Code principles in this skill could not be "
                    f"checked against their source ({state['error']}). They "
                    f"may be current and that has not been established.")
        return ""                       # first run, refresh already started
    if theirs == mine:
        return ""
    return (f"the Honest Code principles in this skill are at {mine[:7]} and "
            f"the source is at {theirs[:7]}. Update the plugin to pick them "
            f"up, or read them at "
            f"https://github.com/openhonest/honest-code-principles")


if __name__ == "__main__":              # pragma: no cover
    if "--refresh" in sys.argv:
        refresh(time.time())
