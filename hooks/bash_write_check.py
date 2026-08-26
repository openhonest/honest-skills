#!/usr/bin/env python3
"""Check source files a Bash command wrote, which the Write hook cannot see.

A PostToolUse hook on Bash.

WHY THIS EXISTS

The write-time hook matches `Write|Edit`. Measured across one real session,
30 percent of file writes went through Bash instead: 376 against 889. Auto mode
makes it worse by instruction, telling the model to prefer sed and heredocs over
the file tools. A check watching the wrong door catches the minority.

WHY TIMESTAMPS RATHER THAN PARSING THE COMMAND

Of those 376 Bash writes, 280 were Python heredocs. The path being written lives
inside the Python, not in the shell command, so no amount of shell parsing finds
it. What every one of them has in common is that a file's mtime moved.

So this looks for source files modified since the command started. That is not
free of error and the errors are stated here rather than discovered:

  - A build, a checkout or a formatter moves many files at once. Past a
    threshold this reports nothing, because a hook that fires on `git checkout`
    is a hook nobody keeps.
  - A file touched by a command that did not mean to write it still counts.
  - A write completed more than WINDOW seconds ago is missed.

It cannot say the command caused the change, only that the change happened
around it. That is weaker than the Write hook and it is what is available.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pending import (defer, read_state, session_key,  # noqa: E402
                     write_state)
from trace_hook import note_session, trace  # noqa: E402
import edit_check  # noqa: E402

# How far back to look. Long enough for a slow command, short enough that the
# previous command's writes have aged out.
WINDOW = 120.0

# More than this many and it was a build, not an edit.
TOO_MANY = 8

# Say a given file's findings once, not on every command that follows.
#
# A file's mtime stays inside the window for two minutes, so every subsequent
# Bash call re-read it and re-reported the same findings. One real session saw
# the identical block five times while working on something else. The key is
# the file's content, so a fix is reported on and an unchanged file is not.
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "target",
        "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        # Never where anyone edits source, and between them the reason a
        # session rooted at the home directory took 26 seconds per command:
        # Library alone holds 134,860 of that tree's 166,779 directories and
        # the module cache another 12,313. The whole of ~/dev is 12,863.
        "Library", "Applications", "Movies", "Music", "Pictures", "go",
        "Downloads"}


def since_last_look(session: str) -> float:
    """Seconds since this session last ran this hook, capped at the window.

    A fixed window is cumulative, and that is what broke it. A session editing
    nine files over two minutes has all nine inside a 120-second window at
    once, so every Bash call it makes reads as a build and is discarded. On
    2026-08-21 that happened 31 times in one 37-minute trace, always at exactly
    nine files, which is a working session and not a build: a build's count
    varies. That session was getting no coverage at all and nothing said so.

    Asking what moved since the last look separates the two. A build moves many
    files between two adjacent calls; a session moves one or two.
    """
    state = read_state("bash", session)
    last = state.get("last_look") or 0.0
    state["last_look"] = time.time()
    write_state("bash", session, state)
    if not last:
        return WINDOW
    return max(1.0, min(WINDOW, time.time() - float(last)))


# How many directories the walk may visit before it gives up. A session whose
# working directory is the home tree made this hook walk everything on every
# Bash command: 26 seconds measured, against 2 milliseconds from inside a
# repository. A hook that costs 26 seconds a command is worse than no hook.
#
# The budget fails loudly. A walk cut short has not seen the files it did not
# reach, and returning what it found would report a partial sweep as a complete
# one, which is the defect this whole tool exists to report.
# Set above the largest tree anyone here actually works in. ~/dev is 12,863
# directories and finishes in 0.7 seconds; the budget exists for the tree
# nobody anticipated, not to trim the ones we know about.
DIR_BUDGET = 20000


def recently_written(root: str, window: float) -> tuple[list[str], bool]:
    """Source files under `root` whose mtime moved inside the window.

    Returns the files and whether the walk finished. An unfinished walk is not
    a shorter list of changed files, it is no answer at all.
    """
    cutoff = time.time() - window
    found = []
    visited = 0
    for dirpath, dirnames, filenames in os.walk(root):
        visited += 1
        if visited > DIR_BUDGET:
            return found, False
        dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith(".")]
        for name in filenames:
            # Markdown as well as code. The wrap rule was wired to Write and
            # Edit alone, so a session that writes its files through shell
            # heredocs had never had it applied once. That is most of one
            # session's markdown, and both of the hard wraps reported on
            # 2026-08-25 went in that way.
            if Path(name).suffix.lower() not in (edit_check.SOURCE
                                                 | edit_check.MARKDOWN):
                continue
            p = os.path.join(dirpath, name)
            try:
                if os.path.getmtime(p) >= cutoff:
                    found.append(p)
            except OSError:
                continue
            if len(found) > TOO_MANY:
                return found, True
    return found, True


def main() -> int:
    raw = sys.stdin.read()
    note_session(raw)
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    root = str(payload.get("cwd") or os.getcwd())

    session = session_key(raw)
    written, finished = recently_written(root, since_last_look(session))
    if not finished:
        # Say nothing about files rather than something about some of them.
        trace("PostToolUse:bash", "declined",
              f"the tree under {os.path.basename(root) or root} is too large to "
              f"sweep, so no file here was checked")
        return 0
    if len(written) > TOO_MANY:
        trace("PostToolUse:bash", "declined",
              f"{len(written)} files moved, reads as a build not an edit")
        return 0
    if not written:
        trace("PostToolUse:bash", "declined", "no source file changed")
        return 0

    # Hand the paths to the same settle the Write and Edit hooks feed, rather
    # than assessing here. Two things follow. A file a script writes and a
    # later command fixes inside the same turn is judged once, at the state it
    # ends in, which is the defect Adam reported on 2026-08-21. And a file
    # written by a script now gets the stub check too, which only ever saw
    # Write and Edit.
    for path in written:
        # Marked as attributed rather than observed. This hook lists source
        # files whose timestamp moved under the session's working directory; it
        # cannot see which command wrote them. Another session editing under
        # the same tree lands here, and on 2026-08-24 one did: a session was
        # told about a file in someone else's working copy, annotated by
        # someone else, that it had never touched.
        defer("edit", path, session, attributed=True)
        if Path(path).suffix.lower() not in edit_check.MARKDOWN:
            # The stub check reads code. Handed prose it finds nothing, and a
            # check that runs on what it cannot read reports a pass it did not
            # perform.
            defer("stub", path, session, attributed=True)
    trace("PostToolUse:bash", "deferred", f"{len(written)} held until they settle",
          files=written)
    return 0                          # silence: the files may still be moving


# Exercised by tests/test_bash_write_check.py.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
