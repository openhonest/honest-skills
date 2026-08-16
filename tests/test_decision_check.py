"""Tests for the decision-question hook.

This hook fires on Stop, which happens every turn, so almost every test here
asserts that it does NOT fire. The costs are not symmetric: missing a decision
question costs nothing, and blocking an ordinary one costs a wasted turn and
teaches the reader to switch the hook off.

The loop test is the one that matters most. A Stop hook that blocks produces a
new turn, which ends, which fires Stop again.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "decision_check", ROOT / "hooks" / "decision_check.py")
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)

BRIEF = ("Background. A thing happened.\n\nCurrent situation. It forces a "
         "choice.\n\nOptions.\n\n- delete them, an hour\n- skip them, an hour\n\n"
         "Recommendation: skip them.\n\nCost of no action. 3 days lost.\n"
         "Should I proceed?")


def transcript(tmp_path, *texts):
    """A JSONL transcript whose last assistant message carries `texts[-1]`."""
    p = tmp_path / "t.jsonl"
    lines = []
    for t in texts:
        lines.append(json.dumps({"type": "assistant", "message": {
            "content": [{"type": "text", "text": t}]}}))
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def stop(tmp_path, text, session=None):
    return dc.on_stop({"hook_event_name": "Stop",
                       "transcript_path": transcript(tmp_path, text),
                       "session_id": session or str(uuid.uuid4())})


# --- the cases where firing would be wrong ----------------------------------

@pytest.mark.parametrize("text", [
    "What port is your server on?",
    "Which file did you mean?",
    "The tests pass. 226 of them.",
    "I fixed it in a083037.",
    "Here is what I found: three defects, all in the parser.",
    "Do you have the API key handy?",
    "That failed. The error was a missing import.",
    "",
])
def test_an_ordinary_message_does_not_fire(tmp_path, text):
    """"Which file did you mean" asks the reader to identify something, not to
    choose between courses of action."""
    assert stop(tmp_path, text) == (0, "")


def test_a_statement_with_no_question_mark_never_fires(tmp_path):
    assert stop(tmp_path, "You should probably proceed with the refactor.") == (0, "")


def test_a_message_already_in_the_form_does_not_fire(tmp_path):
    """The point is the form, so a message that has it is done."""
    assert stop(tmp_path, BRIEF) == (0, "")


def test_a_missing_transcript_does_not_fire(tmp_path):
    assert dc.on_stop({"transcript_path": str(tmp_path / "gone.jsonl"),
                       "session_id": "s"}) == (0, "")


def test_a_transcript_with_no_assistant_text_does_not_fire(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"content": []}}) + "\n")
    assert dc.on_stop({"transcript_path": str(p), "session_id": "s"}) == (0, "")


def test_a_thinking_only_message_is_not_text_the_reader_saw(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {
        "content": [{"type": "thinking", "thinking": "Should I proceed?"}]}}) + "\n")
    assert dc.on_stop({"transcript_path": str(p), "session_id": "s"}) == (0, "")


def test_a_truncated_line_from_seeking_is_skipped(tmp_path):
    """The tail read starts mid-file, so the first line is usually half a
    record. It is not an error and must not stop the scan."""
    p = tmp_path / "t.jsonl"
    p.write_text('ent":"half a record"}\n' + json.dumps(
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Should I ship it?"}]}}) + "\n")
    code, _ = dc.on_stop({"transcript_path": str(p), "session_id": str(uuid.uuid4())})
    assert code == 2


# --- the cases where firing is right ----------------------------------------

@pytest.mark.parametrize("text", [
    "Should I delete the six tests or skip them?",
    "Do you want me to submit it now?",
    "Shall I proceed with the rename?",
    "Ready to push. Ok to proceed?",
    "It is your call. Which would you prefer?",
    "Do you approve the release?",
])
def test_a_question_offering_a_choice_fires(tmp_path, text):
    code, message = stop(tmp_path, text)
    assert code == 2
    assert "five sections" in message


def test_the_message_names_what_is_missing(tmp_path):
    _, message = stop(tmp_path, "Should I ship it?")
    for section in ("Background", "Current situation", "Options",
                    "Recommendation", "Cost of no action"):
        assert section in message


def test_a_partial_brief_is_told_only_what_it_lacks(tmp_path):
    text = ("Current situation. The tree is red.\n\nOptions.\n\n- a\n- b\n\n"
            "Should I proceed?")
    _, message = stop(tmp_path, text)
    assert "Missing here: Background, Recommendation, Cost of no action" in message
    assert "Missing here: Background, Current situation" not in message


def test_the_advice_leads_on_the_section_that_changes_behaviour(tmp_path):
    """Doing nothing needs no decision, so it wins by default."""
    _, message = stop(tmp_path, "Should I ship it?")
    assert "wins by default" in message


# --- the loop, which is the dangerous failure -------------------------------

def test_it_fires_once_and_never_again_for_the_same_message(tmp_path):
    """A Stop hook that blocks produces a new turn, which ends, which fires
    Stop again. Without this the session cannot end."""
    session = str(uuid.uuid4())
    text = "Should I ship it?"
    assert stop(tmp_path, text, session)[0] == 2
    for _ in range(5):
        assert stop(tmp_path, text, session) == (0, "")


def test_a_reformatted_message_is_judged_afresh(tmp_path):
    """The guard keys on content, not on the turn, so fixing the message is
    what gets you through rather than merely trying again."""
    session = str(uuid.uuid4())
    assert stop(tmp_path, "Should I ship it?", session)[0] == 2
    assert stop(tmp_path, BRIEF, session) == (0, "")


def test_a_different_question_in_the_same_session_still_fires(tmp_path):
    session = str(uuid.uuid4())
    assert stop(tmp_path, "Should I ship it?", session)[0] == 2
    assert stop(tmp_path, "Shall I delete the branch?", session)[0] == 2


def test_an_unwritable_marker_suppresses_rather_than_risks_a_loop(monkeypatch):
    """If the firing cannot be recorded, it must not fire. A hook that cannot
    remember is a hook that repeats, and repeating here is a loop."""
    def boom(*a, **k):
        raise OSError("read-only")
    monkeypatch.setattr(dc.Path, "exists", lambda self: False)
    monkeypatch.setattr(dc.Path, "touch", boom)
    assert dc.fired_before("s", "Should I ship it?") is True


# --- AskUserQuestion, a decision by construction -----------------------------

def test_ask_user_question_fires_when_the_lead_up_is_not_a_brief(tmp_path):
    code, message = dc.on_pre_tool_use({
        "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
        "transcript_path": transcript(tmp_path, "Here are some options."),
        "session_id": str(uuid.uuid4())})
    assert code == 2 and "Options" in message


def test_ask_user_question_is_silent_when_the_lead_up_is_a_brief(tmp_path):
    assert dc.on_pre_tool_use({
        "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
        "transcript_path": transcript(tmp_path, BRIEF),
        "session_id": str(uuid.uuid4())}) == (0, "")


def test_no_other_tool_is_touched(tmp_path):
    for tool in ("Bash", "Write", "Edit", "Read"):
        assert dc.on_pre_tool_use({
            "hook_event_name": "PreToolUse", "tool_name": tool,
            "transcript_path": transcript(tmp_path, "Should I ship it?"),
            "session_id": "s"}) == (0, "")


def test_ask_user_question_with_no_transcript_text_still_fires_once(tmp_path):
    """The tool call itself is the decision, so an empty lead-up is the worst
    case rather than a reason to stay quiet."""
    p = tmp_path / "t.jsonl"; p.write_text("")
    code, _ = dc.on_pre_tool_use({
        "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
        "transcript_path": str(p), "session_id": str(uuid.uuid4())})
    assert code == 2


# --- run it the way Claude Code does ----------------------------------------

def run(raw, monkeypatch):
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    monkeypatch.setattr(sys, "stderr", err)
    return dc.main(), err.getvalue()


def test_malformed_input_does_nothing(monkeypatch):
    assert run("not json", monkeypatch) == (0, "")


def test_a_json_value_that_is_not_an_object_does_nothing(monkeypatch):
    assert run("[1,2,3]", monkeypatch) == (0, "")


def test_an_event_this_hook_does_not_handle_does_nothing(monkeypatch):
    assert run(json.dumps({"hook_event_name": "SessionStart"}), monkeypatch) == (0, "")


def test_a_missing_event_name_does_nothing(monkeypatch):
    assert run(json.dumps({"transcript_path": "/nope"}), monkeypatch) == (0, "")


def test_main_writes_the_advice_to_stderr_and_exits_2(tmp_path, monkeypatch):
    payload = json.dumps({
        "hook_event_name": "Stop",
        "transcript_path": transcript(tmp_path, "Should I ship it?"),
        "session_id": str(uuid.uuid4())})
    code, err = run(payload, monkeypatch)
    assert code == 2 and "five sections" in err


def test_it_runs_as_a_subprocess_and_is_silent_on_an_ordinary_turn(tmp_path):
    payload = json.dumps({
        "hook_event_name": "Stop",
        "transcript_path": transcript(tmp_path, "The tests pass."),
        "session_id": str(uuid.uuid4())})
    p = subprocess.run([sys.executable, str(ROOT / "hooks" / "decision_check.py")],
                       input=payload, capture_output=True, text=True)
    assert (p.returncode, p.stdout, p.stderr) == (0, "", "")


def test_it_is_fast_enough_to_run_on_every_turn(tmp_path):
    """It fires on Stop, so it runs once per turn for the life of the session."""
    import time
    payload = json.dumps({
        "hook_event_name": "Stop",
        "transcript_path": transcript(tmp_path, "The tests pass."),
        "session_id": str(uuid.uuid4())})
    start = time.monotonic()
    subprocess.run([sys.executable, str(ROOT / "hooks" / "decision_check.py")],
                   input=payload, capture_output=True, text=True)
    assert time.monotonic() - start < 2.0


def test_only_the_tail_of_a_large_transcript_is_read(tmp_path):
    """A session transcript reaches tens of megabytes. A hook that reads all of
    it on every turn is a hook that gets uninstalled for being slow."""
    p = tmp_path / "big.jsonl"
    filler = json.dumps({"type": "user", "message": {"content": []}}) + "\n"
    with open(p, "w") as fh:
        fh.write(filler * 40_000)
        fh.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Should I ship it?"}]}}) + "\n")
    assert p.stat().st_size > dc.TAIL_BYTES
    code, _ = dc.on_stop({"transcript_path": str(p),
                          "session_id": str(uuid.uuid4())})
    assert code == 2
    assert len(dc.read_tail(str(p))) <= dc.TAIL_BYTES


def test_a_malformed_line_after_the_last_message_is_skipped(tmp_path):
    """The scan runs backwards from the end of the file, so the line that has
    to be tolerated is the one written after the message, not before it. The
    first version of this test put the bad line first, where the scan never
    reached it."""
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Should I ship it?"}]}}) + "\n"
        + "{half a record\n")
    code, _ = dc.on_stop({"transcript_path": str(p),
                          "session_id": str(uuid.uuid4())})
    assert code == 2


def test_ask_user_question_also_fires_only_once(tmp_path):
    """Blocking the same tool call twice would stall the turn as surely as a
    Stop loop would."""
    session = str(uuid.uuid4())
    payload = {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
               "transcript_path": transcript(tmp_path, "Here are options."),
               "session_id": session}
    assert dc.on_pre_tool_use(payload)[0] == 2
    assert dc.on_pre_tool_use(payload) == (0, "")


def test_main_prints_nothing_when_the_handler_declines(tmp_path, monkeypatch):
    """The silent path through main(), which is the one it takes on almost
    every turn."""
    payload = json.dumps({
        "hook_event_name": "Stop",
        "transcript_path": transcript(tmp_path, "The tests pass."),
        "session_id": str(uuid.uuid4())})
    assert run(payload, monkeypatch) == (0, "")
