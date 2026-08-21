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
    assert "Put the\nask first" in message or "hold anything in their head" in message


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
    assert "wins by\ndefault" in message or "wins by default" in message


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

def test_ask_user_question_never_blocks(tmp_path):
    """It used to block when the preceding message was not a brief. It could
    not do that: a model writes the brief and calls the tool in ONE turn, so
    the brief is not a completed message yet and the hook read the turn before
    it. Doing the right thing produced the same rejection as doing the wrong
    thing, twice, with no path through, and a live session abandoned the widget
    and asked in plain text instead."""
    assert dc.on_pre_tool_use({
        "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
        "transcript_path": transcript(tmp_path, "Here are some options."),
        "session_id": str(uuid.uuid4())}) == (0, "")


def test_ask_user_question_is_recorded_even_though_it_passes(tmp_path, monkeypatch):
    """Silence would make "ran and let it through" look like "never ran"."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    dc.on_pre_tool_use({
        "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
        "transcript_path": transcript(tmp_path, "Options."),
        "session_id": "s"})
    row = json.loads(log.read_text())
    assert row["event"] == "PreToolUse" and "cannot see the current turn" in row["why"]


def test_a_brief_written_in_the_same_turn_is_caught_at_stop(tmp_path):
    """Nothing is lost by not blocking. When the turn ends the brief IS in the
    transcript, and Stop reads it there."""
    brief = ("Background. A.\n\nCurrent situation. B.\n\nOptions.\n\n"
             "- a, an hour\n- b, a day\n\nRecommendation: a.\n\n"
             "Cost of no action. 3 days lost.")
    assert stop(tmp_path, brief) == (0, "")


def test_no_other_tool_is_touched(tmp_path):
    for tool in ("Bash", "Write", "Edit", "Read"):
        assert dc.on_pre_tool_use({
            "hook_event_name": "PreToolUse", "tool_name": tool,
            "transcript_path": transcript(tmp_path, "Should I ship it?"),
            "session_id": "s"}) == (0, "")


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
    assert code == 2 and "ask first" in err


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


def test_no_other_tool_is_touched(tmp_path):
    for tool in ("Bash", "Write", "Edit", "Read"):
        assert dc.on_pre_tool_use({
            "hook_event_name": "PreToolUse", "tool_name": tool,
            "transcript_path": transcript(tmp_path, "Should I ship it?"),
            "session_id": "s"}) == (0, "")
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
    assert code == 2 and "ask first" in err


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
def test_main_prints_nothing_when_the_handler_declines(tmp_path, monkeypatch):
    """The silent path through main(), which is the one it takes on almost
    every turn."""
    payload = json.dumps({
        "hook_event_name": "Stop",
        "transcript_path": transcript(tmp_path, "The tests pass."),
        "session_id": str(uuid.uuid4())})
    assert run(payload, monkeypatch) == (0, "")


# --- the buried shapes, which carry no question mark ------------------------
#
# Every fixture here is written from scratch. The message that showed this gap
# was client work, so its wording stays out of a public repository; what is
# reused is the shape, not the text.

@pytest.mark.parametrize("text", [
    "I'll post the finding on the ticket. Status and owner unchanged.",
    "I will push the branch once the suite is green.",
    "Traced it to the annualised return. I am going to comment on the issue.",
    "I plan to send the summary to the list this afternoon.",
    "I'll merge it after lunch.",
])
def test_an_outward_action_announced_rather_than_offered_fires(tmp_path, text):
    """The reader finds out afterwards that a decision was taken."""
    code, message = stop(tmp_path, text)
    assert code == 2
    assert "reaches outside this conversation" in message


@pytest.mark.parametrize("text", [
    "I will not push anything until you say so.",
    "I will never send that without your sign-off.",
])
def test_a_negated_outward_action_does_not_fire(tmp_path, text):
    """"I will not push" is the opposite statement. An earlier pattern let the
    qualifier gap swallow the "not" and matched it anyway."""
    assert stop(tmp_path, text) == (0, "")


@pytest.mark.parametrize("text", [
    "I do NOT confirm a computation bug. The arithmetic is correct.",
    "I cannot confirm the reading. The evidence points the other way.",
    "My evidence disagrees with the bug framing.",
    "Contrary to your ruling, the value is arithmetically right.",
])
def test_disputing_a_ruling_fires(tmp_path, text):
    """Whose call wins is a decision, and reporting the disagreement is not the
    same as putting it to the person whose call it was."""
    code, message = stop(tmp_path, text)
    assert code == 2 and "disputes a ruling" in message


def test_a_buried_decision_inside_a_dense_paragraph_is_caught(tmp_path):
    """The case this was rebuilt for: no question mark anywhere, the dispute in
    the middle, the outward action in the closing line."""
    text = (
        "Two answers here, one confirmed and one where the framing does not "
        "survive contact with the numbers. First, the sub-score reads the "
        "three-year terms only, and no one-year term exists anywhere in the "
        "rules, so there is nothing to remove. Second, I do NOT confirm a "
        "computation bug: the value is a simple excess return, and a fund "
        "benchmarked to the index it tracks lands at roughly zero by "
        "arithmetic. I will post both findings on the ticket. Status and "
        "owner unchanged.")
    assert "?" not in text
    code, message = stop(tmp_path, text)
    assert code == 2
    # It does both, and the reader is told both.
    assert "disputes a ruling" in message
    assert "reaches outside this conversation" in message


def test_density_alone_does_not_fire(tmp_path):
    """A long hedged paragraph is not evidence that something is hidden in it,
    and firing on length would fire on most technical writing."""
    text = ("The classifier may be somewhat premature here, and it could "
            "arguably be that the numbers shift again, though it seems "
            "reasonably likely that the broad shape holds. Generally the "
            "readings tend to move together, more or less, and the earlier "
            "figures were possibly optimistic in a way that probably matters "
            "rather less than it appears.")
    assert stop(tmp_path, text) == (0, "")


def test_a_message_doing_two_things_at_once_is_told_both(tmp_path):
    """Naming one when two apply hands the reader a partial account of why
    they are being stopped."""
    text = "Should I proceed? I will push it either way."
    _, message = stop(tmp_path, text)
    assert message.startswith("This is asking for a decision.")
    assert "reaches outside this conversation" in message


# --- the handoff that carries no question mark ------------------------------

@pytest.mark.parametrize("text", [
    "That is a change to signup code, your call, not mine.",
    "Up to you.",
    "The numbers are in. Your decision.",
    "That is not mine to call.",
])
def test_an_explicit_handoff_fires_without_a_question_mark(tmp_path, text):
    """A specimen ending "your call, not mine" was missed entirely, because the
    whole shape was gated on a question mark a plain handoff does not carry."""
    assert "?" not in text
    assert stop(tmp_path, text)[0] == 2


def test_an_ask_at_the_end_of_a_long_message_is_named_as_buried(tmp_path):
    """The case that prompted this: four hundred words of evidence, then one
    closing clause handing over the decision."""
    text = "Measured this turn, the pool holds the correct remote. " * 40 + \
           "That is a change to signup code, your call, not mine."
    _, message = stop(tmp_path, text)
    assert "percent of the way in" in message
    assert "Move it to the top" in message
    # The substance is already there. Do not tell them to add five sections.
    assert "Missing here" not in message
    assert "Move it to the top" in message


def test_a_short_message_is_never_called_buried(tmp_path):
    """There is nowhere to hide in four lines, and calling it buried would be
    a complaint about brevity."""
    _, message = stop(tmp_path, "Ready to go. Your call.")
    assert "percent of the way in" not in message


def test_an_ask_at_the_top_of_a_long_message_is_not_buried(tmp_path):
    """This is the shape being asked for, so it must not be flagged."""
    text = "Your call: ship it or wait. " + \
           "Measured this turn, the pool holds the correct remote. " * 40
    _, message = stop(tmp_path, text)
    assert "percent of the way in" not in message


def test_a_long_message_with_no_ask_at_all_is_not_measured_for_burial():
    """The outward-action and dispute shapes fire with no ask phrase anywhere,
    so the position check has to cope with having nothing to locate."""
    text = "I will push the branch once the suite is green. " * 40
    assert dc.buried_position(text) is None


def test_a_bare_question_still_gets_the_full_shape(tmp_path):
    """Nothing under it, so the five sections are the fix rather than noise."""
    _, message = stop(tmp_path, "Should I ship it?")
    assert "Missing here" in message
    assert "Move it to the top" not in message


def test_the_two_advices_are_never_both_given(tmp_path):
    """Position and absence are different defects. Answering both at once is
    what made the advice a wall on a report that needed one line moved."""
    long_buried = ("Measured this turn, the pool holds the correct remote. " * 40
                   + "That is your call, not mine.")
    for text in (long_buried, "Should I ship it?"):
        _, message = stop(tmp_path, text)
        assert ("Missing here" in message) != ("Move it to the top" in message)


# --- the sitrep handoff, which is the commonest shape of all ----------------

@pytest.mark.parametrize("text", [
    "- Needs you: whether to commit this now.",
    "**Needs you:** two things. Whether to commit, and whether the draft belongs here.",
    "Needs you: a decision on the corpus re-run.",
])
def test_a_sitrep_needs_you_line_fires(tmp_path, text):
    """The commonest shape and the one every other pattern missed. It holds no
    question, no outward verb and no dispute."""
    assert stop(tmp_path, text)[0] == 2


@pytest.mark.parametrize("text", [
    "- Needs you: nothing",
    "- Needs you: none",
    "- Needs you: nothing, and that is the point.",
])
def test_needs_you_nothing_is_the_correct_answer_and_does_not_fire(tmp_path, text):
    """Firing here would punish the report that has no decision in it."""
    assert stop(tmp_path, text) == (0, "")


def test_prose_that_merely_mentions_needing_someone_does_not_fire(tmp_path):
    """The pattern is anchored to the line, not floating in the sentence."""
    assert stop(tmp_path, "The report needs your review of the numbers.") == (0, "")


def test_a_real_sitrep_is_told_to_brief_the_ask_not_to_rewrite_itself(tmp_path):
    """The shape from a live session: a sound report whose two decisions arrive
    500 words in, unpriced.

    The report is not broken. Telling its author that background and current
    situation are missing is false, because everything above the line is both."""
    text = ("FINDINGS. " + "The suite passes and the gate exits zero. " * 40 +
            "\n- Needs you: whether to commit this now.")
    _, message = stop(tmp_path, text)
    assert "This report is fine" in message
    assert "Missing here" not in message
    assert "Move it to the top" not in message


def test_the_three_advices_are_mutually_exclusive(tmp_path):
    """Each names a different defect with a different fix, and giving two at
    once is what made the advice a wall."""
    cases = {
        "needs_you": "FINDINGS. Fine. \n- Needs you: whether to commit now.",
        "buried": ("Measured this turn, the pool holds the remote. " * 40
                   + "That is your call, not mine."),
        "bare": "Should I ship it?",
    }
    seen = []
    for text in cases.values():
        _, m = stop(tmp_path, text)
        seen.append(("This report is fine" in m, "Move it to the top" in m,
                     "Missing here" in m))
    for flags in seen:
        assert sum(flags) == 1, flags
    assert len(set(seen)) == 3


# --- evidence that it ran, not only that it fired ---------------------------

def test_a_declining_turn_leaves_a_trace_when_asked(tmp_path, monkeypatch):
    """Without this there is no way to tell "ran and correctly declined" from
    "never ran at all", which is the same defect as a reported pass that was
    never performed."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    stop(tmp_path, "The tests pass. 304 of them.")
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert rows == [{"event": "Stop", "verdict": "declined",
                     "why": "no shape matched"}]


def test_a_firing_turn_records_why_it_fired(tmp_path, monkeypatch):
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    stop(tmp_path, "Should I ship it?")
    row = json.loads(log.read_text().splitlines()[0])
    assert row["verdict"] == "fired" and "asking for a decision" in row["why"]


@pytest.mark.parametrize("text,why", [
    ("Background. A.\n\nCurrent situation. B.\n\nOptions.\n\n- a\n- b\n\n"
     "Recommendation: a.\n\nCost of no action. 3 days.\n\nYour call.",
     "already in the form"),
    ("The tests pass.", "no shape matched"),
])
def test_each_decline_says_which_one_it_was(tmp_path, monkeypatch, text, why):
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    stop(tmp_path, text)
    assert json.loads(log.read_text().splitlines()[0])["why"] == why


def test_no_trace_is_written_unless_asked(tmp_path, monkeypatch):
    """A write on every turn is churn nobody asked for.

    Named explicitly rather than globbed: the first version globbed for any
    .jsonl and found the transcript fixture it had just written itself."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.delenv("HONEST_HOOK_TRACE", raising=False)
    stop(tmp_path, "Should I ship it?")
    assert not log.exists()


def test_an_unwritable_trace_never_breaks_the_hook(tmp_path, monkeypatch):
    """Tracing must not be able to break the thing it observes."""
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(tmp_path / "no" / "such" / "t"))
    assert stop(tmp_path, "Should I ship it?")[0] == 2


def test_an_empty_transcript_is_recorded_as_a_decline(tmp_path, monkeypatch):
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    p = tmp_path / "t.jsonl"; p.write_text("")
    dc.on_stop({"transcript_path": str(p), "session_id": "s"})
    assert json.loads(log.read_text())["why"] == "no assistant text to read"


# --- the handoff family, after enumeration missed three specimens in a row ---

@pytest.mark.parametrize("text", [
    "That one is yours to call.",
    "That is your call.",
    "That is a change to signup code, your call, not mine.",
    "Up to you.",
    "Your decision.",
    "I leave that one to you.",
    "Your shout.",
])
def test_the_handoff_family_is_caught_by_rule_not_by_list(tmp_path, text):
    """Three live specimens produced three phrasings and the phrase list
    missed each in turn. The family is a second-person pronoun near a decision
    noun, which covers every form seen and the obvious neighbours."""
    assert stop(tmp_path, text)[0] == 2


@pytest.mark.parametrize("text", [
    "Your tests pass and your build is green.",
    "I called your function twice.",
    "The decision was made last week and your name is on it.",
])
def test_a_second_person_pronoun_alone_is_not_a_handoff(tmp_path, text):
    """"your" is one of the commonest words in a report. Without a decision
    noun beside it this fires on every second message."""
    assert stop(tmp_path, text) == (0, "")


def test_the_rule_still_misses_and_the_miss_is_recorded(tmp_path, monkeypatch):
    """"That one is yours" carries no decision noun and passes through.

    This is asserted rather than fixed. The hook recognises a family of forms
    and goes quiet outside it, which is the same shape as the L1.18 defect in
    the authority plan of this date. The difference is that the decline is
    written to the trace, so the blind spot is countable instead of invisible.
    """
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("HONEST_HOOK_TRACE", str(log))
    assert stop(tmp_path, "That one is yours.") == (0, "")
    assert json.loads(log.read_text())["why"] == "no shape matched"


def test_the_declaro_specimen_is_caught(tmp_path):
    """From a live session: a sound report whose one decision arrives in the
    last line as "that one is yours to call"."""
    text = ("Thirty-four other test files sit outside the fast suite the same "
            "way. They hold 551 tests and take 20 seconds. Adding them takes "
            "the fast suite from 11 seconds to 31, and your own note sets the "
            "ceiling at 30. That one is yours to call.")
    assert stop(tmp_path, text)[0] == 2


def test_the_needs_you_check_does_not_depend_on_tuple_order(monkeypatch):
    """It read HANDS_THE_DECISION_OVER[1] once, so reordering the tuple
    silently repointed it at another pattern and the only symptom was the
    wrong advice on the commonest shape of all."""
    monkeypatch.setattr(dc, "HANDS_THE_DECISION_OVER",
                        tuple(reversed(dc.HANDS_THE_DECISION_OVER)))
    assert dc.has_needs_you("- Needs you: whether to commit now.") is True
    assert dc.has_needs_you("- Needs you: nothing") is False


# --- a mention is not a use -------------------------------------------------

@pytest.mark.parametrize("text", [
    'My list only had "your call". Three specimens produced "your call, not mine".',
    'The phrase `your call` is what it matches.',
    'It fired on "Needs you: whether to commit now" as an example.',
    'Adding a fourth string like "up to you" buys one specimen.',
])
def test_a_quoted_or_code_span_phrase_does_not_fire(tmp_path, text):
    """It fired on a message whose only match was the phrase it matches, quoted
    as an example. commit_msg.py already made this argument and acted on it: a
    checker that cannot tell a mention from a use makes its own defects
    unreportable."""
    assert stop(tmp_path, text) == (0, "")


@pytest.mark.parametrize("text", [
    "That one is yours to call.",
    "That is your call.",
    "- Needs you: whether to commit now.",
])
def test_the_same_words_unquoted_still_fire(tmp_path, text):
    """Stripping mentions must not strip uses."""
    assert stop(tmp_path, text)[0] == 2


def test_a_report_about_this_hook_does_not_trip_it(tmp_path):
    """The live false positive, kept as a fixture. This message asks for
    nothing and every match in it is a quoted example."""
    text = ('The declaro session\'s ask was missed because it said "yours to '
            'call" and my list only had "your call". Three specimens produced '
            '"your call", "your call, not mine", and "that one is yours to '
            'call", and the list missed each in turn. 324 tests, 100 percent '
            'branch coverage. Needs a restart.')
    assert stop(tmp_path, text) == (0, "")


# --- the exit, so the hook cannot corner a model into ceremony ---------------

@pytest.mark.parametrize("text", [
    "Should I ship it?",
    "FINDINGS. Fine.\n- Needs you: whether to commit now.",
    "Measured this turn, the pool holds the remote. " * 40 + "That is your call.",
])
def test_every_advice_offers_the_exit_first(tmp_path, text):
    """A session was pushed into writing four options for a decision that had
    one answer, three of them scenery. "Stop it with this empty ritual. There
    is only one answer and you know what it is."

    An advice that only says how to fill in the shape is an advice that makes
    the shape compulsory."""
    _, message = stop(tmp_path, text)
    assert "FIRST, THE EXIT" in message
    assert "do not\nask" in message
    # First means first: before anything telling you how to fill the shape in.
    # The move-it advice names no sections at all, so there is nothing to
    # order against there.
    for later in ("Options", "Move the ask", "three things"):
        if later in message:
            assert message.index("THE EXIT") < message.index(later)


def test_the_exit_names_the_test_for_a_real_fork(tmp_path):
    """"Can I name three courses" is not the test. Anyone can."""
    _, message = stop(tmp_path, "Should I ship it?")
    assert "same way whatever the answer" in message
    assert "do not\nask" in message


# --- the binomial split: down into action, or up to the standard ------------

def test_a_message_that_already_answered_is_pushed_down_into_action(tmp_path):
    """The specimen wrote "Recommendation. A." and then asked "Which do you
    want: A, B, C, or D?" It had the answer, wrote the answer, and asked
    anyway, because something upstream said to check before acting."""
    text = ("Background. A thing.\n\nCurrent situation. It forces a choice.\n\n"
            "Options.\n\n- A, a day\n- B, an hour\n\n"
            "Recommendation. A. If I am wrong the cost is small.\n\n"
            "Cost of no action. 3 days lost.\n\n"
            "Which do you want: A, B, C, or D?")
    _, message = stop(tmp_path, text)
    assert message.startswith("You named a recommendation")
    assert "any universe" in message
    assert "Missing here" not in message


def test_a_message_with_no_recommendation_is_pushed_up_to_the_standard(tmp_path):
    """The other half of the split. A bare ask still gets the shape."""
    _, message = stop(tmp_path, "Should I ship it?")
    assert not message.startswith("You named a recommendation")
    assert "Missing here" in message


def test_the_down_advice_names_the_cost_of_asking(tmp_path):
    """"Asking costs one turn too, and buys nothing" is the whole argument."""
    text = ("Recommendation. Ship it.\n\nBackground. A.\n\n"
            "Current situation. B.\n\nOptions.\n\n- a\n- b\n\n"
            "Cost of no action. 3 days.\n\nWhich do you want?")
    _, message = stop(tmp_path, text)
    assert "buys\nnothing" in message
    assert "any universe" in message


# --- the manufactured blocker -----------------------------------------------

def test_effort_priced_as_a_blocker_is_named(tmp_path):
    """An agent reported "rebuilding them honestly means driving a real
    database, slower per scenario, say real or double." Asked why that blocked
    it: "It isn't. I already stood one up three times today in four lines
    each." Its own report had named the answer two paragraphs earlier."""
    text = ("FINDINGS. 29 of 94 scenarios fail.\n"
            "- Needs you: rebuilding them honestly means driving a real "
            "SQLite. Slower per scenario. Say real or double.")
    _, message = stop(tmp_path, text)
    assert "effort is not a\ncost to the reader" in message
    assert "cannot do" in message


@pytest.mark.parametrize("text", [
    "FINDINGS. Ready.\n- Needs you: whether to push this to the public remote.",
    "FINDINGS. Done.\n- Needs you: the ROR login, which I do not have.",
])
def test_a_genuine_blocker_is_not_accused_of_manufacturing_one(tmp_path, text):
    """Permission and capability are the two that survive. Adding the note to
    them would teach the reader to skip it."""
    _, message = stop(tmp_path, text)
    assert "effort is not a\ncost to the reader" not in message


def test_the_effort_words_are_read_as_prose_not_as_mentions(tmp_path):
    """A report quoting the word slower must not trip it."""
    text = ('FINDINGS. Fixed.\n- Needs you: the login. I removed the phrase '
            '"slower per scenario" from the draft.')
    _, message = stop(tmp_path, text)
    assert "effort is not a\ncost to the reader" not in message


# --- asking permission to continue ------------------------------------------

@pytest.mark.parametrize("text", [
    "Two swallows left. Want me to keep going on it?",
    "Shall I continue with the rest?",
    "That group is done. Keep going?",
    "Should I carry on with the others?",
    "Do you want me to go on?",
])
def test_asking_permission_to_continue_is_told_to_carry_on(tmp_path, text):
    """The ritual in its purest form: the answer was given before the question
    was asked, usually more than once. A session asked "want me to keep going
    on it?" then said it itself: "You said keep going twice. Asking again was
    the ritual." """
    _, message = stop(tmp_path, text)
    assert message.startswith("You are asking permission to continue")
    assert "Missing here" not in message


@pytest.mark.parametrize("text", [
    "Ready to push to the public remote. Ok to proceed?",
    "- Needs you: the ROR login, which I do not have.",
])
def test_a_real_ask_is_not_treated_as_a_continuation(tmp_path, text):
    """Permission to reach outside is a genuine fork. Telling someone to carry
    on there would be telling them to act without consent."""
    _, message = stop(tmp_path, text)
    assert not message.startswith("You are asking permission to continue")


def test_a_plain_report_still_says_nothing(tmp_path):
    assert stop(tmp_path, "Fixed a real bug. 1,023 tests passing.") == (0, "")


def test_the_carry_on_advice_says_when_stopping_is_right(tmp_path):
    """An advice that only says "do not stop" would be wrong the one time
    stopping matters."""
    _, message = stop(tmp_path, "Want me to keep going?")
    assert "genuinely cannot proceed" in message
    assert "cannot proceed" in message


# --- a recommendation stated in prose, not under a heading -------------------

def test_a_prose_recommendation_with_a_menu_is_pushed_down(tmp_path):
    """The section test alone missed this. Most real messages recommend in a
    sentence; only a formal brief uses a labelled section."""
    text = ("Which do you want me to act on? Item 2 is the one I would fix "
            "first: it is a factual contradiction in shipped text, and the "
            "correction makes the credential stronger.")
    _, message = stop(tmp_path, text)
    assert message.startswith("You named a recommendation")


@pytest.mark.parametrize("phrase", [
    "My recommendation is A.", "I recommend A.", "I would go with A.",
    "I'd pick A.", "If it were me, A.", "A is the one I would take.",
])
def test_every_way_of_recommending_in_prose_counts(tmp_path, phrase):
    _, message = stop(tmp_path, f"{phrase} Which do you want?")
    assert message.startswith("You named a recommendation")


def test_a_menu_with_no_recommendation_still_gets_the_shape(tmp_path):
    """Nothing has been answered, so there is nothing to push down."""
    _, message = stop(tmp_path, "Which do you want: A, B, or C?")
    assert "Missing here" in message


def test_a_recommendation_with_no_menu_gets_the_shape_not_the_push(tmp_path):
    """Handing over after recommending is the normal shape, not the ritual.
    What is missing is what the reader needs to weigh it against."""
    _, message = stop(tmp_path, "I would fix item 2 first. Your call.")
    assert not message.startswith("You named a recommendation")
    assert "Missing here" in message


def test_prose_that_merely_mentions_a_preference_is_silent(tmp_path):
    """No ask at all, so nothing fires however it is phrased."""
    assert stop(tmp_path, "I would not touch item 3. It needs a lawyer.") == (0, "")


# --- complying must not earn a fresh complaint ------------------------------

COMPLIED = (
    "One decision, up front: should I fix the code now, or leave it "
    "catalogued and move on?\n\n"
    "I'd do it only on your say-so, because it changes three production reads "
    "and you have been in cataloging mode, not code mode. The fix itself is "
    "small and low-risk: read the score change from full_data, exactly as the "
    "PDF already does, with a test that the field shows the score change. No "
    "pipeline work, since the data is already synced.\n\n"
    "Say fix it and I branch; say next and I take the following row.")


def test_a_message_that_moved_its_ask_to_the_top_is_left_alone(tmp_path):
    """A session was told to move its ask to the top and that this was the
    whole fix. It moved the ask to the top, and the next firing demanded five
    labelled sections it had not asked for the turn before. Doing the right
    thing produced a different rejection."""
    assert stop(tmp_path, COMPLIED) == (0, "")


def test_the_move_it_advice_no_longer_promises_more_than_it_delivers(tmp_path):
    """It said "That is the whole fix" and then the next turn asked for
    headings. Either the promise or the follow-up had to go."""
    text = "Evidence here. " * 160 + "That is your call."
    _, message = stop(tmp_path, text)
    assert "Moving it is enough" in message
    assert "nothing here asks for headings" in message


def test_a_bare_ask_put_first_is_still_a_bare_ask(tmp_path):
    """The floor was missing at first, and "Should I ship it?" qualified as
    well packaged. Putting a question first does not give it substance."""
    assert not dc.ask_is_up_front("Should I ship it?")
    assert stop(tmp_path, "Should I ship it?")[0] == 2


def test_a_long_report_cannot_claim_the_up_front_exemption(tmp_path):
    """Past the burial threshold the question is where the ask sits, and a
    long message is exactly what that measures."""
    assert not dc.ask_is_up_front("Should I fix it? " + "Evidence. " * 200)


def test_the_exemption_needs_the_ask_near_the_start(tmp_path):
    """Substance alone is not packaging. The reader has to meet the ask
    before the evidence, not after it."""
    late = ("Here is a long stretch of reasoning that runs on for a while and "
            "covers the measurement, the trace, and what it implies for the "
            "next step in some detail. " * 2) + "Should I proceed?"
    assert not dc.ask_is_up_front(late)


def test_a_ritual_message_cannot_hide_behind_the_exemption(tmp_path):
    """already_answered is checked first, so putting a menu re-offer at the
    top buys nothing."""
    text = ("Which do you want: A, B, or C? My recommendation is A, because "
            "it is the only one that keeps the tree green and it costs an "
            "hour of work rather than a day of it, which matters here.")
    _, message = stop(tmp_path, text)
    assert message.startswith("You named a recommendation")


# --- a description of two things differing is not a dispute -----------------

@pytest.mark.parametrize("text", [
    "The dispute detector is aimed at disputes with the reader, not at a "
    "finding that code disagrees with a spec.",
    "SQLite disagrees with PostgreSQL on how it reads that wildcard.",
    "The docstring disagrees with the SQL underneath it.",
])
def test_the_ordinary_verb_is_not_a_dispute(tmp_path, text):
    """"disagrees with" on its own matched a sentence about code and a spec,
    which disputes nobody. It fired on a report that asked for nothing."""
    assert not dc.contradicts_a_ruling(text)
    assert stop(tmp_path, text) == (0, "")


@pytest.mark.parametrize("text", [
    "My evidence disagrees with the bug framing.",
    "I disagree with your ruling on this.",
    "That disagrees with your definition of the metric.",
    "I do NOT confirm a computation bug.",
    "Contrary to your instruction, the value is arithmetically right.",
])
def test_a_real_dispute_still_fires(tmp_path, text):
    """Narrowing must not lose the case. Whose call wins is a decision."""
    assert dc.contradicts_a_ruling(text)


def test_the_narrowing_needs_a_subject_or_an_object():
    """Either a first-person subject, or a ruling as the object. The bare verb
    is neither and is why this fired on ordinary prose."""
    assert not dc.contradicts_a_ruling("A disagrees with B.")
    assert dc.contradicts_a_ruling("I disagree with A.")
    assert dc.contradicts_a_ruling("A disagrees with your call.")


def test_the_needs_you_advice_asks_for_all_five_sections(tmp_path):
    """It used to ask for three and say the background was already written
    above. A session followed that literally and produced a brief opening
    straight into a table of options, which was rejected for having no
    background. The reader answers from the brief, not from the report."""
    _, message = stop(tmp_path, "FINDINGS. Fine.\n- Needs you: whether to commit now.")
    for section in ("Background", "Current situation", "Options",
                    "Recommendation", "Cost of no action"):
        assert section in message, section


def test_it_no_longer_tells_you_to_omit_the_background(tmp_path):
    _, message = stop(tmp_path, "FINDINGS. Fine.\n- Needs you: whether to commit now.")
    assert "do not write them again" not in message
    assert "stands on its own" in message
    assert "Compressed is not omitted" in message
