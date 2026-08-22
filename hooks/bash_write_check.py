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
from pending import defer, session_key  # noqa: E402
from trace_hook import trace  # noqa: E402
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
        "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def recently_written(root: str, window: float) -> list[str]:
    """Source files under `root` whose mtime moved inside the window."""
    cutoff = time.time() - window
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith(".")]
        for name in filenames:
            if Path(name).suffix.lower() not in edit_check.SOURCE:
                continue
            p = os.path.join(dirpath, name)
            try:
                if os.path.getmtime(p) >= cutoff:
                    found.append(p)
            except OSError:
                continue
            if len(found) > TOO_MANY:
                return found
    return found


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    root = str(payload.get("cwd") or os.getcwd())

    written = recently_written(root, WINDOW)
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
    session = session_key(raw)
    for path in written:
        defer("edit", path, session)
        defer("stub", path, session)
    trace("PostToolUse:bash", "deferred", f"{len(written)} held until they settle",
          files=written)
    return 0                          # silence: the files may still be moving


# Exercised by tests/test_bash_write_check.py.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
