"""Tests for the trace reader."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import hook_report  # noqa: E402


def write(tmp_path, rows):
    p = tmp_path / "t.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(p)


ROWS = [{"event": "Stop", "verdict": "fired", "why": "asking for a decision"},
        {"event": "Stop", "verdict": "declined", "why": "no shape matched"},
        {"event": "Stop", "verdict": "declined", "why": "no shape matched"},
        {"event": "PostToolUse:edit", "verdict": "fired", "why": "3 of 3 ran, .py"}]


def test_it_reports_the_rate_per_event(tmp_path):
    """A firing is visible in the transcript; a decline is not, and the ratio
    is the only thing that says whether a hook is calibrated or merely quiet."""
    out = hook_report.render(hook_report.read(write(tmp_path, ROWS)))
    assert "Stop   3 runs, 1 fired (33%)" in out
    assert "PostToolUse:edit   1 runs, 1 fired (100%)" in out


def test_it_names_the_commonest_reasons_both_ways(tmp_path):
    out = hook_report.render(hook_report.read(write(tmp_path, ROWS)))
    assert "fired       1  asking for a decision" in out
    assert "declined    2  no shape matched" in out


def test_a_truncated_last_line_is_skipped(tmp_path):
    """Normal on a file being written to while it is read."""
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps(ROWS[0]) + "\n" + '{"event": "Stop", "verd')
    assert len(hook_report.read(str(p))) == 1


def test_a_row_without_an_event_is_not_a_trace_row(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"unrelated": True}) + "\n")
    assert hook_report.read(str(p)) == []


def test_a_missing_file_reads_as_empty(tmp_path):
    assert hook_report.read(str(tmp_path / "gone.jsonl")) == []


def test_an_empty_trace_says_how_to_turn_it_on(tmp_path):
    """The commonest reason for no data is that nobody set the variable."""
    out = hook_report.render([])
    assert "HONEST_HOOK_TRACE" in out and "restart" in out


def test_last_n_limits_the_window(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hook_report.py", "--last", "1",
                                      write(tmp_path, ROWS)])
    assert hook_report.main() == 0
    out = capsys.readouterr().out
    assert "1 events" in out


def test_it_falls_back_to_the_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HONEST_HOOK_TRACE", write(tmp_path, ROWS))
    monkeypatch.setattr(sys, "argv", ["hook_report.py"])
    assert hook_report.main() == 0
    assert "4 events" in capsys.readouterr().out


def test_no_path_anywhere_is_an_error_not_a_guess(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HONEST_HOOK_TRACE", raising=False)
    monkeypatch.setattr(sys, "argv", ["hook_report.py"])
    assert hook_report.main() == 2
    assert "unset" in capsys.readouterr().out


# --- did a firing lead to a fix ---------------------------------------------

def test_a_file_that_went_to_zero_is_counted_as_fixed(tmp_path):
    """The only measurement that says the hook changed anything. A firing
    count says it spoke."""
    rows = [{"event": "PostToolUse:bash", "verdict": "fired", "why": "x",
             "findings": {"a.py": ["L1.21", "L1.21"]}},
            {"event": "PostToolUse:bash", "verdict": "declined", "why": "x",
             "findings": {"a.py": []}}]
    out = hook_report.loop_closed(rows)
    assert "went to zero findings      1  a.py" in out


def test_a_file_with_fewer_findings_is_counted_separately(tmp_path):
    rows = [{"event": "e", "verdict": "fired", "why": "x",
             "findings": {"b.py": ["L1.21", "L1.21", "L1.21"]}},
            {"event": "e", "verdict": "fired", "why": "x",
             "findings": {"b.py": ["L1.21"]}}]
    assert "fewer than before          1  b.py" in hook_report.loop_closed(rows)


def test_the_report_says_it_cannot_tell_ignored_from_overruled(tmp_path):
    """One session's three firings were one filed issue and two reasoned
    rejections. Zero code changes, and nothing about that was ignoring it."""
    rows = [{"event": "e", "verdict": "fired", "why": "x", "findings": {"c.py": ["L1.21"]}},
            {"event": "e", "verdict": "fired", "why": "x", "findings": {"c.py": ["L1.21"]}}]
    out = hook_report.loop_closed(rows)
    assert "UNCHANGED IS NOT IGNORED" in out
    assert "overruled with a reason" in out and "deferred with a ticket" in out


def test_a_file_that_did_not_improve_is_not_counted_as_progress(tmp_path):
    rows = [{"event": "e", "verdict": "fired", "why": "x", "findings": {"c.py": ["L1.21"]}},
            {"event": "e", "verdict": "fired", "why": "x", "findings": {"c.py": ["L1.21"]}}]
    out = hook_report.loop_closed(rows)
    assert "unchanged                  1  c.py" in out


def test_a_file_seen_once_is_evidence_of_nothing(tmp_path):
    """A file nobody revisited is not a file that was ignored."""
    rows = [{"event": "e", "verdict": "fired", "why": "x", "findings": {"d.py": ["L1.21"]}}]
    out = hook_report.loop_closed(rows)
    assert "fired once and not seen again: 1" in out
    assert "evidence of nothing either way" in out


def test_rows_without_findings_are_ignored_rather_than_counted(tmp_path):
    """Older trace lines carry no findings field, and absent is not zero."""
    assert "judged more than once: 0" in hook_report.loop_closed(
        [{"event": "e", "verdict": "fired", "why": "x"}])


# --- what deferring bought ---------------------------------------------------

def test_the_span_says_it_cannot_date_rows_from_before_0_22_0():
    """A count without a period is not a rate, and older rows carry no time."""
    assert "predates" in hook_report.span([{"event": "E", "verdict": "fired", "why": ""}])


def test_the_span_reports_the_period_the_rows_cover():
    rows = [{"event": "E", "verdict": "fired", "why": "", "ts": "2026-08-21T10:00:00"},
            {"event": "E", "verdict": "fired", "why": "", "ts": "2026-08-21T11:00:00"}]
    got = hook_report.span(rows)
    assert "10:00:00 to 2026-08-21T11:00:00" in got and "2 of 2" in got


def test_a_single_stamped_row_is_not_called_a_period():
    rows = [{"event": "E", "verdict": "fired", "why": "", "ts": "2026-08-21T10:00:00"}]
    assert "one timestamped row" in hook_report.span(rows)


def test_the_collapse_ratio_is_the_writes_held_per_report():
    """Three writes to one file that report once is the whole fix, stated as a
    number rather than asserted."""
    rows = ([{"event": "PostToolUse:edit", "verdict": "deferred", "why": ""}] * 3
            + [{"event": "Stop:edit", "verdict": "fired", "why": "1 of 3"}])
    got = hook_report.settled(rows)
    assert "3 write(s) held" in got and "3.0 write(s) per report" in got


def test_every_rate_names_its_denominator():
    """The same hook was described as firing on 53, 7.7 and 0.8 percent of runs
    in one afternoon, because each number counted a different thing."""
    rows = [{"event": "Stop:edit", "verdict": "fired", "why": ""},
            {"event": "Stop:edit", "verdict": "declined", "why": ""}]
    assert "denominator: files assessed" in hook_report.settled(rows)


def test_suppressed_repeats_are_counted_rather_than_invisible():
    rows = [{"event": "Stop:edit", "verdict": "declined",
             "why": "already reported this content"}]
    assert "1 repeat(s) suppressed" in hook_report.settled(rows)


def test_a_kind_with_no_traffic_says_so_rather_than_showing_zero_percent():
    assert "edit: nothing yet" in hook_report.settled([])


def test_writes_held_with_nothing_to_report_give_no_ratio():
    """Dividing by zero reports is not a collapse ratio, and printing 0.0 would
    read as the fix having bought nothing rather than as nothing having fired."""
    rows = ([{"event": "PostToolUse:edit", "verdict": "deferred", "why": ""}] * 3
            + [{"event": "Stop:edit", "verdict": "declined", "why": ""}])
    got = hook_report.settled(rows)
    assert "3 write(s) held" in got and "per report" not in got


def test_bash_traffic_is_counted_separately():
    rows = [{"event": "PostToolUse:bash", "verdict": "deferred", "why": ""},
            {"event": "PostToolUse:bash", "verdict": "declined", "why": ""}]
    assert "bash: 2 command(s) seen, 1 moved a source file" in hook_report.settled(rows)


def test_writes_held_before_any_turn_has_ended_report_no_rate():
    """The state mid-turn: writes are held and nothing has been assessed yet.
    A rate over zero assessed files is not a rate."""
    rows = [{"event": "PostToolUse:edit", "verdict": "deferred", "why": ""}]
    got = hook_report.settled(rows)
    assert "1 write(s) held" in got and "denominator" not in got
