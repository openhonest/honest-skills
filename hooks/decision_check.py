#!/usr/bin/env python3
"""Catch a request for a decision that was not put as one.

Two events, because there is no third:

    PreToolUse on AskUserQuestion   a decision by construction, so this fires
                                    on every call and is exact
    Stop                            the model asked in prose, which is where
                                    most questions actually live

There is no hook that fires when the model asks a question in prose. Stop is
the only place to stand, and it fires on every turn, so almost all of this file
is about not firing.

WHY THE BAR IS SO HIGH

The costs are not symmetric. Missing a decision question costs nothing: the
conversation carries on exactly as it would have. Blocking an ordinary question
costs a wasted turn and teaches the reader to switch the hook off, and a hook
that is switched off catches nothing at all. So this fires only when the text is
unambiguously offering a choice, and it fires at most once for any one message.

WHAT IT REFUSES TO DECIDE

Whether a question deserves a brief. That is intent, and intent is not readable
from text. All this can see is whether the words present the reader with
alternatives, which is narrower than "is this important" and is the only part
that is decidable. decision.py takes the same line one level down: it gates the
form of a brief and reports every judgment about content as unassessed.

Consequence, stated rather than discovered: a genuine decision put in plain
words with no alternatives named will pass straight through. That is a miss and
it is the direction the errors are meant to fall in.
"""
from __future__ import annotations

import hashlib
import json
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

# The reader is being offered alternatives. Each of these says so in words that
# do not also occur in an ordinary request for a fact. "Which file did you
# mean?" is deliberately not matched: it asks the reader to identify something,
# not to choose between courses of action.
OFFERS_A_CHOICE = (
    r"\bshould I\b",
    r"\bshall I\b",
    r"\bdo you want me to\b",
    r"\bwant me to\b",
    r"\bwould you like me to\b",
    r"\bok(?:ay)? to\b",
    r"\bshall we\b",
    r"\bproceed\?",
    r"\byour call\b",
    r"\bwhich would you prefer\b",
    r"\bdo you approve\b",
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


def offers_a_choice(text: str) -> bool:
    if "?" not in text:
        return False
    return any(re.search(p, text, re.I) for p in OFFERS_A_CHOICE)


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


ADVICE = """This is asking for a decision. Put it in the five sections so the
reader can decide from the message rather than reconstruct it:

  Background            what they need to know and do not
  Current situation     what is true now, and why it forces a choice
  Options               each with what it costs and what it buys
  Recommendation        one course of action, named
  Cost of no action     what happens if they do nothing, in figures

Missing here: {missing}.

Cost of no action is the one that matters most. Doing nothing needs no
decision, so it wins by default, and a request that does not price it has left
out the outcome most likely to occur."""


def advice_for(text: str) -> str:
    return ADVICE.format(missing=", ".join(missing_sections(text)))


def on_stop(payload: dict) -> tuple[int, str]:
    text = last_assistant_text(read_tail(payload.get("transcript_path") or ""))
    if not text or not offers_a_choice(text) or already_in_form(text):
        return 0, ""
    if fired_before(payload.get("session_id") or "", text):
        return 0, ""
    return 2, advice_for(text)


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
    return 2, advice_for(text)


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
