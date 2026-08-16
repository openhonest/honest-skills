#!/usr/bin/env python3
"""Catch a request for a decision that was not put as one.

Two events, because there is no third:

    PreToolUse on AskUserQuestion   a decision by construction, so this fires
                                    on every call and is exact
    Stop                            everything else, which is where the
                                    problem actually lives

There is no hook that fires when the model asks a question in prose. Stop is
the only place to stand, and it fires on every turn, so almost all of this file
is about not firing.

THE FIRST VERSION WAS BEST AT THE CASE THAT NEEDED IT LEAST

It looked for a question offering alternatives. A clean question is already
legible; nobody misses "Should I ship it?". The decision that gets past a reader
is the one settled inside a dense paragraph of qualifiers, and the specimen that
made this obvious carried no question mark anywhere. It disputed a ruling in
item 2 of a status update and announced an outward action in its closing line.
So there are three shapes now, and two of them never involve a question.

WHY THE BAR IS SO HIGH

The costs are not symmetric. Missing a buried decision costs nothing: the
conversation carries on exactly as it would have. Firing on an ordinary message
costs a wasted turn and teaches the reader to switch the hook off, and a hook
that is switched off catches nothing at all. Measured across 581 real messages,
the three shapes together fire on about 5 percent.

WHAT IT REFUSES TO DECIDE

Whether a message deserves a brief. That is intent, and intent is not readable
from text. All this sees is whether the words offer alternatives, announce an
outward action, or dispute a ruling. Each is narrower than "is this important"
and each is the only part that is decidable. decision.py takes the same line one
level down: it gates the form of a brief and reports every judgment about
content as unassessed.

Consequence, stated rather than discovered: a decision put in plain words with
no alternatives named, no outward verb and no contradiction passes straight
through. Density alone does not trigger anything, because a long paragraph is
not evidence that something is hidden in it. That is a miss, and it is the
direction the errors are meant to fall in.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import decision  # noqa: E402

# Only the last stretch of the transcript is read. It is a JSONL file that
# reaches tens of megabytes in a long session, and a hook that reads all of it
# on every turn is a hook that gets uninstalled for being slow.
TAIL_BYTES = 400_000

# THREE SHAPES, BECAUSE A BURIED DECISION IS NOT A QUESTION
#
# The first version looked only for a question offering alternatives, which
# made it best at the case that needed it least. A clean question is already
# legible. The one that hides is a decision settled inside a dense paragraph,
# and the specimen that showed this carried no question mark at all: it
# disputed a ruling in item 2 of a status update and announced an outward
# action in its closing line.
#
# So there are three, and each gets its own advice, because the fix differs.

# 1a. An explicit handoff. These say "you decide" in so many words and need no
# question mark to do it. A specimen ending "that is a change to signup code,
# your call, not mine" was missed entirely because the whole shape was gated on
# a question mark that a plain statement of handoff does not carry.
# A sitrep's own handoff line, and the commonest shape of all. It arrives
# hundreds of words in, names no options and prices nothing, and none of the
# other patterns touch it: "Needs you: whether to commit this now" holds no
# question, no outward verb and no dispute.
#
# The negative lookahead matters: "Needs you: nothing" is the line that says
# there is no decision, and firing on it would punish the correct answer.
NEEDS_YOU = r"^\s*[-*]?\s*\*{0,2}Needs you\*{0,2}\s*:\s*(?!nothing\b|none\b|n/a\b)\S"

HANDS_THE_DECISION_OVER = (
    # A rule rather than a list, after three specimens produced three
    # phrasings and the list missed all three in turn: "your call", then
    # "your call, not mine", then "that one is yours to call".
    #
    # The family is a second-person pronoun near a decision noun. It covers
    # every form seen so far and the obvious neighbours, which enumerating
    # never did.
    #
    # THIS IS STILL AN ENUMERATION AND WILL STILL MISS. "That one is yours"
    # carries no decision noun and passes straight through. That is the same
    # shape as the L1.18 defect recorded in the authority plan on this date:
    # a hand-maintained list of recognised forms that goes silent on anything
    # outside it. The difference is that this one leaves a trace, so what it
    # declined is countable instead of invisible.
    r"\b(?:your|yours)\b[^.!?\n]{0,24}\b(?:call|choice|decision|shout|to make)\b",
    r"\bup to you\b",
    r"\b(?:leave|leaving) (?:that|this|it|them) (?:one )?(?:to|with) you\b",
    r"\bnot mine to (?:make|call|decide)\b",
    # A sitrep's own handoff line, and the most common shape of all. It
    # arrives hundreds of words in, names no options and prices nothing,
    # and none of the other patterns touch it: "Needs you: whether to
    # commit this now" holds no question, no outward verb and no dispute.
    # The negative lookahead matters: "Needs you: nothing" is the line
    # that says there is no decision, and firing on it would punish the
    # correct answer.
    NEEDS_YOU,
    r"\bup to you\b",
    r"\bnot mine to (?:make|call|decide)\b",
)

# 1b. The reader is being offered alternatives, in words that do not also occur
# in an ordinary request for a fact. These do need a question mark, because
# without one they are ordinary prose: "you should ask whether" is not an ask.
# "Which file did you mean?" is deliberately not matched: it asks the reader to
# identify something, not to choose between courses of action.
OFFERS_A_CHOICE = (
    r"\bshould I\b",
    r"\bshall I\b",
    r"\bdo you want me to\b",
    r"\bwant me to\b",
    r"\bwould you like me to\b",
    r"\bok(?:ay)? to\b",
    r"\bshall we\b",
    r"\bproceed\?",
    r"\bwhich would you prefer\b",
    r"\bdo you approve\b",
)

# A message this long has room to bury its ask. Below it, the last line is
# still in view when the reader reaches the first.
LONG_ENOUGH_TO_BURY = 150     # words

# An ask past this point in a long message is one the reader had to read to.
BURIED_AFTER = 0.75

# 2. An action that reaches outside, announced rather than offered. Posting a
# comment, sending mail, pushing, merging: the reader finds out afterwards that
# a decision was taken. The negative lookahead is not decoration. Without it
# "I will not push" matched, which is the opposite statement.
ANNOUNCES_OUTWARD_ACTION = (
    r"\bI(?:'ll| will| am going to| plan to| intend to)\s+"
    r"(?!not\b|never\b)(?:\w+\s+){0,3}?"
    r"(?:post|comment|repl(?:y|ies)|send|email|publish|submit|merge|push|"
    r"deploy|release|file|close|assign|announce|share|upload|tweet)\b",
)

# 3. A prior instruction or ruling being contradicted, stated as a finding.
# Whose call wins is a decision, and reporting the disagreement is not the same
# as putting it to the person whose call it was.
CONTRADICTS_A_RULING = (
    r"\bI do(?: not|n't) confirm\b",
    r"\bI cannot confirm\b",
    r"\bdisagrees? with\b",
    r"\bthe .{0,30}premise (?:does not|doesn't) hold\b",
    r"\bcontrary to (?:the|your|his|her|their)\b",
    r"\bthat framing is wrong\b",
)

# Sections that mean the message is already in the form. Three of five is the
# bar rather than five, because chat is not a document and demanding the full
# shape of a brief inside a reply is the friction this is supposed to avoid.
ENOUGH_SECTIONS = 3


def trace(event: str, verdict: str, why: str) -> None:
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
            fh.write(json.dumps({"event": event, "verdict": verdict,
                                 "why": why}) + "\n")
    except OSError:
        pass


def read_tail(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - TAIL_BYTES))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def last_assistant_text(transcript: str) -> str:
    """The text of the most recent assistant message, or "".

    Thinking blocks are not text the reader saw, so they are skipped. An entry
    with no text block at all is mid-turn and is skipped too.
    """
    for line in reversed(transcript.splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue          # a truncated first line, from seeking into the file
        if entry.get("type") != "assistant":
            continue
        blocks = (entry.get("message") or {}).get("content") or []
        text = "\n".join(b.get("text", "") for b in blocks
                         if isinstance(b, dict) and b.get("type") == "text")
        if text.strip():
            return text
    return ""


# HANDS_THE_DECISION_OVER holds a line-anchored pattern, so every search over
# it carries MULTILINE. Without it "^" matched only the start of the whole
# message: the pattern passed a one-line test and missed every real sitrep,
# where the handoff sits on its own line hundreds of words down.
LINE = re.I | re.M


def offers_a_choice(text: str) -> bool:
    if any(re.search(p, text, LINE) for p in HANDS_THE_DECISION_OVER):
        return True
    if "?" not in text:
        return False
    return any(re.search(p, text, re.I) for p in OFFERS_A_CHOICE)


def buried_position(text: str) -> float | None:
    """Where the ask sits, as a fraction, or None when it is not buried.

    Returns nothing for a short message: there is nowhere to hide in four
    lines. In a long one, an ask in the closing quarter is an ask the reader
    had to read four hundred words to reach, which is the Army packaging rule
    broken in the one place it costs the most.
    """
    if len(text.split()) < LONG_ENOUGH_TO_BURY:
        return None
    spots = [m.start() for p in HANDS_THE_DECISION_OVER + OFFERS_A_CHOICE
             for m in re.finditer(p, text, LINE)]
    if not spots:
        return None
    where = min(spots) / len(text)
    return where if where >= BURIED_AFTER else None


def announces_outward_action(text: str) -> bool:
    return any(re.search(p, text, re.I) for p in ANNOUNCES_OUTWARD_ACTION)


def contradicts_a_ruling(text: str) -> bool:
    return any(re.search(p, text, re.I) for p in CONTRADICTS_A_RULING)


# The lead sentence of the advice, per shape. The five sections follow in every
# case; what changes is the reason the reader is being handed the decision.
SHAPES = (
    (offers_a_choice,
     "This is asking for a decision."),
    (announces_outward_action,
     "This announces an action that reaches outside this conversation. The "
     "reader finds out afterwards that a decision was taken, so it is theirs "
     "to make first."),
    (contradicts_a_ruling,
     "This disputes a ruling. Whose call wins is a decision, and reporting the "
     "disagreement is not the same as putting it to the person whose call it "
     "was."),
)


def shape_of(text: str) -> str:
    """Every shape that matches, not the first.

    A message can dispute a ruling and announce an outward action in the same
    breath, and the specimen that prompted this did exactly that. Reporting
    only the first would hand the reader a partial account of why they are
    being stopped, which is the same defect as a findings list that does not
    state its coverage.
    """
    return " ".join(lead for detect, lead in SHAPES if detect(text))


def already_in_form(text: str) -> bool:
    _, order = decision.split_sections(text)
    return len(order) >= ENOUGH_SECTIONS


def missing_sections(text: str) -> list[str]:
    _, order = decision.split_sections(text)
    return [decision.LABELS[k] for k, _ in decision.SECTIONS if k not in order]


def fired_before(session: str, text: str) -> bool:
    """True when this exact message has already been sent back once.

    Without this, a Stop hook that blocks produces a new turn, which ends, which
    fires Stop again. The key is the content rather than the turn, so a model
    that reformats gets through and a model that repeats itself verbatim does
    not loop.
    """
    key = hashlib.sha256(f"{session}\0{text}".encode()).hexdigest()[:32]
    marker = Path(tempfile.gettempdir()) / f"honest-decision-{key}.seen"
    if marker.exists():
        return True
    try:
        marker.touch()
    except OSError:
        return True           # cannot record it, so do not risk repeating it
    return False


def has_needs_you(text: str) -> bool:
    """Named rather than indexed. Reading HANDS_THE_DECISION_OVER[1] pointed
    at whatever sat second in the tuple, so reordering it silently repointed
    this check and the only symptom was the wrong advice."""
    return bool(re.search(NEEDS_YOU, text, LINE))


# Three advices, because three different things are wrong.
#
# A long report whose ask sits at the end already contains everything the
# reader needs. One line is in the wrong place. Telling its author that all
# five sections are missing is true of the section NAMES and false about the
# work required, and it fired that way on a real sitrep that had findings,
# evidence and a stated assessment.
#
# A bare question has nothing under it, and that is when the full shape helps.
# A sitrep with a "Needs you" line is not a broken sitrep. The report is doing
# its job; the ask inside it is the part that was never briefed. Telling its
# author that background and current situation are missing is false, because
# the whole report above the line is both.
BRIEF_THE_ASK = """This report is fine. The "Needs you" line inside it is not.

An item under "Needs you" is a decision, and it arrived as a bare ask: no
options, nothing priced, and the reader reaching it only after everything
above. They cannot answer it without holding the whole report in their head.

Brief that item where they meet it first. It needs three things it does not
have:

  Options               each with what it costs and what it buys
  Recommendation        one course of action, named
  Cost of no action     what happens if they do nothing, in figures

Two items means two briefs, or one with the choices numbered. The background
and the situation are already written above, so do not write them again."""

MOVE_IT = """{lead}

The ask sits {where:.0f} percent of the way in. To answer it the reader has to
hold everything above it in their head, and nobody can.

Everything needed to answer is already here. Move the ask to the top, ahead of
the evidence, and leave the rest where it is. That is the whole fix."""

ADVICE = """{lead}

This is about what the reader has to hold in their head, not about style. They
should be able to answer you without remembering anything. Right now they have
to carry the evidence forward and assemble the question themselves, and that is
work you are doing to them rather than for them.

So put the ask where they meet it first, and put underneath it only what they
need to answer:

  Background            what they need to know and do not
  Current situation     what is true now, and why it forces a choice
  Options               each with what it costs and what it buys
  Recommendation        one course of action, named
  Cost of no action     what happens if they do nothing, in figures

Missing here: {missing}.

Cost of no action is the one that matters most. Doing nothing needs no
decision, so it wins by default, and a request that does not price it has left
out the outcome most likely to occur."""


def advice_for(text: str, lead: str) -> str:
    """Proportionate to what is actually wrong.

    Position and absence are different defects with different fixes, and an
    earlier version answered both with the same wall of five section names.
    """
    if has_needs_you(text):
        return BRIEF_THE_ASK
    where = buried_position(text)
    if where is not None:
        return MOVE_IT.format(lead=lead, where=where * 100)
    return ADVICE.format(lead=lead, missing=", ".join(missing_sections(text)))


def on_stop(payload: dict) -> tuple[int, str]:
    text = last_assistant_text(read_tail(payload.get("transcript_path") or ""))
    if not text:
        trace("Stop", "declined", "no assistant text to read")
        return 0, ""
    if already_in_form(text):
        trace("Stop", "declined", "already in the form")
        return 0, ""
    lead = shape_of(text)
    if not lead:
        trace("Stop", "declined", "no shape matched")
        return 0, ""
    if fired_before(payload.get("session_id") or "", text):
        trace("Stop", "declined", "already sent back once")
        return 0, ""
    trace("Stop", "fired", lead)
    return 2, advice_for(text, lead)


def on_pre_tool_use(payload: dict) -> tuple[int, str]:
    """AskUserQuestion is a decision by construction: its schema holds options.

    The brief cannot live in the tool call, because the schema has nowhere to
    put a background or a cost. It belongs in the message before it, so that is
    what gets checked.
    """
    if payload.get("tool_name") != "AskUserQuestion":
        return 0, ""
    text = last_assistant_text(read_tail(payload.get("transcript_path") or ""))
    if already_in_form(text):
        return 0, ""
    if fired_before(payload.get("session_id") or "", text or "<no text>"):
        return 0, ""
    return 2, advice_for(text, SHAPES[0][1])


EVENTS = {"Stop": on_stop, "PreToolUse": on_pre_tool_use}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except (ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    handler = EVENTS.get(payload.get("hook_event_name") or "")
    if handler is None:
        return 0
    code, message = handler(payload)
    if code:
        print(message, file=sys.stderr)
    return code


# Exercised by tests/test_decision_check.py. In-process coverage cannot observe
# a child process, so the pragma records that the gap is in the instrument.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
