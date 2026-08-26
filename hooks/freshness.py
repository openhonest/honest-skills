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

Four states, kept apart on purpose, because the last two are the ones that go
wrong. CURRENT says the copy matches. BEHIND names the commit it holds and the
one the source is at. UNVERIFIED says today's check got no answer, and carries
the date of the last one that did. UNMONITORED says nothing has succeeded for
long enough that the arrangement itself should be assumed broken.

The last two were one state until frame pointed out that they answer different
questions. Unverified is a gap in today's information and clears on its own. A
rate limit is gone within the hour. Unmonitored is the mechanism having
stopped: a renamed repository, a deleted one, one made private, a revoked
token, a URL that quietly 404s after a reorganisation. None of those clear, and
each produces the same message as the rate limit, forever. Collapsed together,
a copy nothing can ever check again reads exactly like one checked ninety
seconds ago during a busy minute.

Not having looked is not evidence of being up to date, and every measurement
defect found in this project has been the same shape: something unmeasured
landing in the numerator.
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
# After this long with no successful check, the copy stops being unverified and
# starts being unmonitored. A rate limit clears within the hour. A renamed
# repository, a deleted one, one made private, a revoked token or a URL that
# quietly 404s after a reorganisation never clears, and each produces the same
# message as the rate limit, forever. Without a clock on it, a copy nothing can
# ever check again reports what a copy checked ninety seconds ago reports.
UNMONITORED_AFTER = 7 * 24 * 60 * 60
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
    # Carries the previous answer forward. Written fresh, one failed check
    # erased the last known source commit and the date it was learned, so a
    # single bad minute would throw away the evidence that anything had ever
    # worked.
    state = dict(read_cache())
    state["checked_at"] = now
    state.pop("error", None)
    try:
        import urllib.request
        with urllib.request.urlopen(API_URL, timeout=TIMEOUT) as r:
            state["source_sha"] = json.load(r)["sha"]
        state["verified_at"] = now
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
    """One line naming which of the four states this copy is in, or "".

    Reads the cache and never the network, so this is free to call on every
    firing. When the cache is stale it starts a refresh and returns what it
    knows now, which may be nothing. The next firing after that has the answer.

    A failed check reports the date of the last successful one rather than a
    count of days, because a reader can act on "last verified on the 3rd" and
    cannot act on "stale".
    """
    now = time.time() if now is None else now
    mine = vendored_sha(skill)
    if not mine:
        return ""                       # nothing vendored here to be stale
    state = read_cache()
    if due(state, now):
        start_refresh()
    verified_at = float(state.get("verified_at") or 0)
    if state.get("error"):
        if not verified_at:
            return ("the Honest Code principles in this skill have never been "
                    f"checked against their source ({state['error']}). Whether "
                    f"they are current is unknown.")
        when = time.strftime("%Y-%m-%d", time.localtime(verified_at))
        if now - verified_at >= UNMONITORED_AFTER:
            # A finding rather than a caveat. Nothing here clears on its own.
            return (f"the Honest Code principles in this skill have not been "
                    f"verified since {when}. Treat this copy as unmonitored "
                    f"rather than current: the last error was {state['error']}")
        return ("the Honest Code principles in this skill could not be checked "
                f"against their source today ({state['error']}). Last verified "
                f"on {when}.")
    theirs = state.get("source_sha") or ""
    if not theirs:
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
