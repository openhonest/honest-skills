#!/usr/bin/env python3
"""Record that a hook ran, when someone asks for the record.

One implementation, imported by every hook. decision_check.py held this
privately until stub_check.py needed it too, which is the moment a private
copy becomes two things under one name.
"""
from __future__ import annotations

import json
import os


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
            row = {"event": event, "verdict": verdict, "why": why}
            # Named fields rather than more prose in `why`. Whether a firing
            # led to a fix cannot be read out of a sentence, and that is the
            # only question that says the loop closed rather than merely
            # spoke.
            row.update({k: v for k, v in facts.items() if v is not None})
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


