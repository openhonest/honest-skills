"""Keep the suite out of the live trace and the live pending state.

Both are named by environment variables that a developer's shell is likely to
have set, and the hooks write wherever those point. On 2026-08-21 a single
`pytest` run put 223 rows into the trace being used to measure how the hooks
behaved in real sessions, and the busiest files in that measurement turned out
to be test fixtures. Every fire rate read off that file was wrong by an unknown
amount, and nothing in the numbers looked unusual.

A test that writes into the instrument measuring it is not a contained test.
"""
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _never_touch_the_live_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(tmp_path / "trace.jsonl"))
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "pending"))
    # Disarmed for each test, because the flag is a module global and a test
    # that armed it would leave the next one writing rows it never asked for.
    # A test exercising trace() directly arms it and says so.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
    import trace_hook
    monkeypatch.setattr(trace_hook, "FIRED", False)
