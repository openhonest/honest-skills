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
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import clarity   # noqa: E402
import decision  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_hook import trace  # noqa: E402

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

# Re-offering the menu: "Which do you want: A, B, C, or D?" after naming one.
RE_OFFERS_THE_MENU = (
    r"\bwhich (?:do you want|one|option)\b",
    r"\b[A-D](?:\s*,\s*[A-D]){1,3}\s*,?\s*or\s+[A-D]\b",
    r"\bpick one\b",
)

# Asking permission to continue work already authorised. This is the ritual in
# its purest form: the answer was given before the question was asked, and
# usually more than once. A live session asked "want me to keep going on it?"
# and then said it itself: "You said keep going twice. Asking again was the
# ritual."
#
# Continuing is not a fork. If the work was authorised, doing it is the work,
# and stopping to ask converts one turn of progress into two turns of nothing.
ASKS_TO_CONTINUE = (
    r"\b(?:want|do you want) me to (?:keep|carry on|continue|go on)\b",
    r"\bshall I (?:keep|carry on|continue|go on)\b",
    r"\bshould I (?:keep|carry on|continue|go on)\b",
    r"\b(?:keep|carry on) going\?",
    r"\bcontinue\?",
    r"\bshall I proceed with the (?:rest|remainder|others)\b",
)

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
) + RE_OFFERS_THE_MENU + ASKS_TO_CONTINUE
# Reciting the menu is an ask, and it was not recognised as one. "Which do you
# want: A, B, C, or D?" declined as no-shape-matched, so the down-path it
# exists to trigger was unreachable from the specimen that produced it.

# A message this long has room to bury its ask. Below it, the last line is
# still in view when the reader reaches the first.
LONG_ENOUGH_TO_BURY = 150     # words

# An ask past this point in a long message is one the reader had to read to.
BURIED_AFTER = 0.75

# An ask this early has already been packaged: the reader meets it before the
# evidence, which is the whole of what the format is for.
UP_FRONT_BEFORE = 0.15

# ...but only if there is something under it. A bare question put first is
# still a bare question, and that is the case the shape exists for. The floor
# was missing at first, and "Should I ship it?" qualified as well packaged.
ENOUGH_UNDER_THE_ASK = 40    # words

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
    # "disagrees with" on its own is the ordinary English verb and matched
    # "a finding that code disagrees with a spec", which disputes nobody. It
    # needs a first-person subject or a ruling as its object to be a dispute
    # with the reader rather than a description of two things differing.
    r"\bI disagree with\b",
    r"\bmy (?:\w+ ){0,2}(?:evidence|reading|measurement|finding)s? "
    r"disagrees? with\b",
    r"\bdisagrees? with (?:your|his|her|their|the) "
    r"(?:ruling|call|instruction|framing|premise|definition|conclusion)\b",
    r"\bthe .{0,30}premise (?:does not|doesn't) hold\b",
    r"\bcontrary to (?:the|your|his|her|their)\b",
    r"\bthat framing is wrong\b",
)

# Sections that mean the message is already in the form. Three of five is the
# bar rather than five, because chat is not a document and demanding the full
# shape of a brief inside a reply is the friction this is supposed to avoid.
ENOUGH_SECTIONS = 3


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


def usable(text: str) -> str:
    """The text with mentions removed, so a report about this hook does not
    trip it. clarity.strip_mentions is the one implementation; this had a
    private copy of the same regex until commit_msg needed it too."""
    return clarity.strip_mentions(text)


def offers_a_choice(text: str) -> bool:
    if any(re.search(p, text, LINE) for p in HANDS_THE_DECISION_OVER):
        return True
    if "?" not in text:
        return False
    return any(re.search(p, text, re.I) for p in OFFERS_A_CHOICE)


def ask_is_up_front(text: str) -> bool:
    """True when the ask arrives before the reasoning.

    This exists because complying with the advice earned a fresh complaint. A
    session was told to move its ask to the top and that this "is the whole
    fix". It moved the ask to the top, and the next firing demanded five
    labelled sections it had not asked for the turn before. Doing the right
    thing produced a different rejection, which is the same failure as the
    AskUserQuestion block.

    An ask in the opening sentence, in a short message, is already packaged.
    Demanding headings from it reads labels instead of substance, and the
    substance is there: the reader meets the question before the evidence.
    """
    clean = usable(text)
    words = len(clean.split())
    if not clean or words > LONG_ENOUGH_TO_BURY or words < ENOUGH_UNDER_THE_ASK:
        return False
    spots = [m.start() for p in HANDS_THE_DECISION_OVER + OFFERS_A_CHOICE
             for m in re.finditer(p, clean, LINE)]
    return bool(spots) and min(spots) / len(clean) <= UP_FRONT_BEFORE


def buried_position(text: str) -> float | None:
    """Where the ask sits, as a fraction, or None when it is not buried.

    Returns nothing for a short message: there is nowhere to hide in four
    lines. In a long one, an ask in the closing quarter is an ask the reader
    had to read four hundred words to reach, which is the Army packaging rule
    broken in the one place it costs the most.
    """
    if len(text.split()) < LONG_ENOUGH_TO_BURY:
        return None
    clean = usable(text)
    spots = [m.start() for p in HANDS_THE_DECISION_OVER + OFFERS_A_CHOICE
             for m in re.finditer(p, clean, LINE)]
    if not spots:
        return None
    where = min(spots) / len(clean)
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


def matched_patterns(text: str) -> list[str]:
    """Which patterns actually matched, for the trace.

    The lead sentence alone said a shape fired without saying why, so three
    attempts to find which pattern carried the volume each used a different
    denominator and produced a different answer. Recording the pattern turns a
    rate into a diagnosis.
    """
    clean = usable(text)
    return [p for p in HANDS_THE_DECISION_OVER + OFFERS_A_CHOICE
            + ASKS_TO_CONTINUE + CONTRADICTS_A_RULING
            + ANNOUNCES_OUTWARD_ACTION
            if re.search(p, clean, LINE)]


def shape_of(text: str) -> str:
    """Every shape that matches, not the first.

    A message can dispute a ruling and announce an outward action in the same
    breath, and the specimen that prompted this did exactly that. Reporting
    only the first would hand the reader a partial account of why they are
    being stopped, which is the same defect as a findings list that does not
    state its coverage.
    """
    clean = usable(text)
    return " ".join(lead for detect, lead in SHAPES if detect(clean))


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




# A recommendation stated in prose rather than under a heading. The section
# test alone missed "Which do you want me to act on? Item 2 is the one I would
# fix first", which names the answer and then asks anyway. Most real messages
# recommend in a sentence; only a formal brief uses a labelled section.
RECOMMENDS_IN_PROSE = (
    r"\bI would (?:fix|start|do|pick|choose|take|go with|say)\b",
    r"\bthe one I would\b",
    r"\bI'?d (?:fix|start|pick|choose|go with)\b",
    r"\bmy recommendation\b",
    r"\bI recommend\b",
    r"\bif it were me\b",
)


def already_answered(text: str) -> bool:
    """True when the message names a recommendation and then re-offers the menu.

    The ritual question, and it is decidable. The specimen wrote
    "Recommendation. A. If I am wrong, the cost is..." and closed with "Which
    do you want: A, B, C, or D?" It had the answer, wrote the answer, and
    asked anyway, because something upstream said to check before acting.

    NOT merely "has a recommendation". The first version tested that and fired
    on every correct brief, because the format requires a recommendation and
    a brief exists in order to ask. Handing the decision over after
    recommending is the normal shape. Reciting the menu back after
    recommending is the ritual: it asks the reader to redo the comparison the
    writer has already done and published.
    """
    clean = usable(text)
    bodies, _ = decision.split_sections(clean)
    named = bool((bodies.get("recommendation") or "").strip()) or any(
        re.search(p, clean, re.I) for p in RECOMMENDS_IN_PROSE)
    if not named:
        return False
    return any(re.search(p, clean, re.I) for p in RE_OFFERS_THE_MENU)


# Effort priced as though it were the reader's cost. "Slower per scenario" is
# not a reason for anyone to decide anything; it is a description of work.
PRICES_ITS_OWN_EFFORT = (
    r"\bslow(?:er|ly)?\b", r"\btakes? longer\b", r"\bmore work\b",
    r"\btime[- ]consuming\b", r"\btedious\b", r"\bper scenario\b",
    r"\ba lot of work\b", r"\bmany hours\b",
)

MANUFACTURED_BLOCKER = """
Check it is a blocker at all. This prices your own effort, and effort is not a
cost to the reader. A "Needs you" item is something you cannot do, may not do
without their say-so, or would build differently depending on their answer.
Work is none of those.
"""


CARRY_ON = """You are asking permission to continue work you were already told
to do. Carry on, and report what changed when you are done.

Stop only when you genuinely cannot proceed. That will be obvious."""


def asks_to_continue(text: str) -> bool:
    return any(re.search(p, usable(text), re.I) for p in ASKS_TO_CONTINUE)


def prices_its_own_effort(text: str) -> bool:
    return any(re.search(p, usable(text), re.I) for p in PRICES_ITS_OWN_EFFORT)


def has_needs_you(text: str) -> bool:
    """Named rather than indexed. Reading HANDS_THE_DECISION_OVER[1] pointed
    at whatever sat second in the tuple, so reordering it silently repointed
    this check and the only symptom was the wrong advice."""
    return bool(re.search(NEEDS_YOU, usable(text), LINE))


# The hook pushes in two directions rather than one.
#
# Everything used to go up: every ask got the five sections. That made the
# ritual question worse, because a question nobody needed to answer arrived
# dressed as a formal decision. The two populations want opposite treatment.
#
# DOWN: you already know the answer. Act, and report what you did.
# UP: this is a real fork. Give the reader what they need to take it.
ACT_ON_IT = """You named a recommendation and then recited the menu back.

Is there any universe in which they pick B? If not, B is scenery. Do the thing
and report it. Being wrong costs one turn; asking costs one turn and buys
nothing."""


# Three advices for the questions that survive that test, because three
# different things are wrong with them.
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

FIRST, THE EXIT. If you would proceed the same way whatever the answer, do not
ask. Say what you found, say what you are doing, and do it.

That item is a decision and arrived unpriced. Brief it where they meet it
first, all five sections:

  Background / Current situation / Options (cost and buys each) /
  Recommendation (one, named) / Cost of no action (in figures)

The brief stands on its own. Draw background and situation from what you wrote
above, compressed to a sentence or two each. Compressed is not omitted: the
reader answers from the brief, not by scrolling up.

Two items means two briefs."""

MOVE_IT = """{lead}

FIRST, THE EXIT. If you would proceed the same way whatever the answer, do not
ask. Say what you found, say what you are doing, and do it.

The ask sits {where:.0f} percent of the way in. Move it to the top and leave the
rest where it is. Moving it is enough; nothing here asks for headings."""

ADVICE = """{lead}

FIRST, THE EXIT. If you would proceed the same way whatever the answer, do not
ask. Say what you found, say what you are doing, and do it.

They should be able to answer without holding anything in their head. Put the
ask first, and under it only what they need to answer:

  Background / Current situation / Options (cost and buys each) /
  Recommendation (one, named) / Cost of no action (in figures)

Missing here: {missing}.

Cost of no action matters most: doing nothing needs no decision, so it wins by
default."""


def advice_for(text: str, lead: str) -> str:
    """Proportionate to what is actually wrong.

    Position and absence are different defects with different fixes, and an
    earlier version answered both with the same wall of five section names.
    """
    if asks_to_continue(text):
        return CARRY_ON
    if already_answered(text):
        return ACT_ON_IT
    if has_needs_you(text):
        return BRIEF_THE_ASK + (
            MANUFACTURED_BLOCKER if prices_its_own_effort(text) else "")
    where = buried_position(text)
    if where is not None:
        return MOVE_IT.format(lead=lead, where=where * 100)
    return ADVICE.format(lead=lead, missing=", ".join(missing_sections(text)))


def on_stop(payload: dict) -> tuple[int, str]:
    text = last_assistant_text(read_tail(payload.get("transcript_path") or ""))
    if not text:
        trace("Stop", "declined", "no assistant text to read")
        return 0, ""
    lead = shape_of(text)
    if not lead:
        trace("Stop", "declined", "no shape matched")
        return 0, ""
    # The order matters, and getting it wrong let the worst case through. A
    # message that answered itself and asked anyway is usually a COMPLETE
    # brief, so testing "already in the form" first declined on exactly the
    # thing the down-path exists for. Answered-and-asking is checked first;
    # being well-formed is no defence against not needing to ask.
    if not already_answered(text) and already_in_form(text):
        trace("Stop", "declined", "already in the form")
        return 0, ""
    if not already_answered(text) and ask_is_up_front(text):
        # Short, and the ask arrives before the reasoning. That is the
        # packaging rule already satisfied, and there is nothing left to say
        # that would not be a demand for headings.
        trace("Stop", "declined", "ask is already up front")
        return 0, ""
    if fired_before(payload.get("session_id") or "", text):
        trace("Stop", "declined", "already sent back once")
        return 0, ""
    trace("Stop", "fired", " | ".join(matched_patterns(text)) or lead)
    return 2, advice_for(text, lead)


def on_pre_tool_use(payload: dict) -> tuple[int, str]:
    """Never blocks. Records that the call happened, and gets out of the way.

    WHY THIS WAS GUTTED RATHER THAN FIXED

    It used to block AskUserQuestion when the preceding message was not a
    brief. It could not do that, and the way it failed was the worst available
    to a hook.

    A model that writes the brief and then calls the tool writes both in ONE
    turn. The brief is not a completed assistant message yet, so it is not in
    the transcript, so the hook read the turn before it and saw no brief.
    Doing the right thing produced the same rejection as doing the wrong
    thing, twice, with no path through. A live session gave up on the widget
    and asked in plain text instead, which is a hook making a tool unusable.

    The rule it broke: judge only what you can see. The hook cannot see the
    current turn, so it cannot know whether a brief was written, and blocking
    on a fact it has no access to is worse than not checking at all. The
    schema already requires two or more options, which is the only thing in
    the tool call itself worth checking, so nothing is lost by stopping.

    Stop still covers the case. When the turn ends, the brief IS in the
    transcript, and the Stop hook reads it there.
    """
    if payload.get("tool_name") == "AskUserQuestion":
        trace("PreToolUse", "declined", "cannot see the current turn, never blocks")
    return 0, ""


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
