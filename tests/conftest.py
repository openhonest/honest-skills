"""Keep the suite out of the live trace and the live pending state.

Both are named by environment variables that a developer's shell is likely to
have set, and the hooks write wherever those point. On 2026-08-21 a single
`pytest` run put 223 rows into the trace being used to measure how the hooks
behaved in real sessions, and the busiest files in that measurement turned out
to be test fixtures. Every fire rate read off that file was wrong by an unknown
amount, and nothing in the numbers looked unusual.

A test that writes into the instrument measuring it is not a contained test.
"""
import pytest


@pytest.fixture(autouse=True)
def _never_touch_the_live_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(tmp_path / "trace.jsonl"))
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "pending"))
