#!/usr/bin/env python3
"""An MCP server exposing the writing checkers to any client that speaks MCP.

The hook reaches Claude Code and nothing else. This reaches Cursor, Codex and
anything else with an MCP client, and it serves the deliberate case: check this
before I send it, rather than check everything as it is written.

WHY THIS IS STDLIB ONLY
It ships inside a plugin that installs on machines we do not control. Every
dependency is a thing that can be missing, pinned wrong, or absent from a
sandbox, and a checker that will not start is worse than no checker because the
silence reads as a pass. JSON-RPC over stdio is a hundred lines. The SDK is
convenience, and convenience is not worth an install failure here.

WHY IT WRAPS RATHER THAN REIMPLEMENTS
Every verdict comes from clarity.py, commit_msg.py and decision.py, called
directly. A second implementation under the same name is how two tools come to
disagree while both claiming the standard, so there is no analysis in this file
at all: it is transport.

STDOUT IS THE PROTOCOL
Nothing may print to stdout except a JSON-RPC message. Anything diagnostic goes
to stderr. A stray print here corrupts the stream and the client sees a parse
error rather than the thing that was actually wrong.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import clarity      # noqa: E402
import commit_msg   # noqa: E402
import decision     # noqa: E402

SERVER_NAME = "honest-writing"
SERVER_VERSION = "0.5.0"

# The version answered when a client does not state one. A client that does
# state one gets its own echoed back, because refusing a version we can in fact
# speak would fail the connection over a string rather than a capability.
FALLBACK_PROTOCOL = "2025-06-18"

# JSON-RPC 2.0 error codes, from the specification.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603

TEXT_INPUT = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "The text to check."},
    },
    "required": ["text"],
}

TOOLS = (
    {
        "name": "check_decision_brief",
        "description":
            "Check a request for a decision. Gates the form: five sections "
            "present and in order (background, current situation, options, "
            "recommendation, cost of no action), background under 40 percent, "
            "at least two options, recommendation under 60 words, a cost of no "
            "action carrying an actual quantity, and tables under 80 columns. "
            "Reports and never gates the three judgments no checker reaches: "
            "whether the recommendation follows, whether these are the real "
            "options, and whether that is the true cost.",
        "inputSchema": TEXT_INPUT,
    },
    {
        "name": "check_prose",
        "description":
            "Check a draft for readability and for the tells that make writing "
            "read as machine-written. Reports the clarity index (average "
            "sentence length plus the share of long words, band 20 to 40) and "
            "gates stray em dashes, hedging adverbs, intensifiers, and AP "
            "mechanical punctuation. Code, tables, headings and URLs are "
            "excluded from the score.",
        "inputSchema": TEXT_INPUT,
    },
    {
        "name": "check_commit_message",
        "description":
            "Check a commit message. Gates subject length, the blank line "
            "after the subject, stray em dashes, hedges, intensifiers and AP "
            "punctuation. Deliberately does not apply the clarity index, "
            "because a dozen words is too small a sample for it to mean "
            "anything. Reports as unassessed whether the subject says what "
            "changed and whether bad news sits above good news.",
        "inputSchema": TEXT_INPUT,
    },
)


def run_check(analyse, text: str, label: str) -> dict:
    """Call one checker and shape its result for a client.

    `verdict`, `gating_failures` and `report` are the three things a caller
    acts on. `checks` carries everything else, including every check that was
    NOT assessed, so a client can show what the verdict did not cover.
    """
    result = analyse(text, "mcp")
    return {"tool": label, **result}


def verdict_line(payload: dict) -> str:
    """One line, first, saying whether it passed and what failed.

    Without this, check_prose opened with "clarity index 20.0, in band" on a
    draft carrying three gating failures, because the index and the gates are
    different questions and the renderer leads with the index. A model reading
    the first line would have called it clean. The finding goes first.
    """
    failures = payload.get("gating_failures") or []
    if payload.get("verdict") == "unreadable":
        return "UNREADABLE. Nothing was checked, which is not the same as clean."
    if not failures:
        return "PASS. Every gated check passed. See the unassessed ones below."
    return f"FAIL. {len(failures)} gated check(s): {', '.join(failures)}"


def render_for_model(payload: dict, render) -> str:
    """The verdict, then the report, then the machine-readable result.

    All three, not one. The verdict is what a model acts on, the report is what
    a person reads, and the JSON is what a client filters and counts. Sending
    only the report would make the unassessed checks invisible to anything
    programmatic, which is the exact thing they exist to prevent.
    """
    return (verdict_line(payload) + "\n\n" + render(payload)
            + "\n\n" + json.dumps(payload, indent=2))


def call_tool(name: str, args: dict) -> dict:
    text = args.get("text")
    if not isinstance(text, str):
        return {"content": [{"type": "text",
                             "text": "This tool needs a 'text' string. Nothing "
                                     "was checked, which is not the same as "
                                     "nothing being wrong."}],
                "isError": True}
    if name == "check_decision_brief":
        payload = run_check(decision.analyse_brief, text, name)
        body = render_for_model(payload, decision.render)
    elif name == "check_prose":
        payload = run_check(clarity.analyse, text, name)
        body = render_for_model(payload, clarity.render_text)
    elif name == "check_commit_message":
        payload = run_check(commit_msg.analyse_message, text, name)
        body = render_for_model(payload, commit_msg.render)
    else:
        return {"content": [{"type": "text", "text": f"No tool named {name}."}],
                "isError": True}
    return {"content": [{"type": "text", "text": body}],
            "isError": payload.get("verdict") == "unreadable"}


def on_initialize(params: dict) -> dict:
    return {
        "protocolVersion": params.get("protocolVersion") or FALLBACK_PROTOCOL,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def on_tools_list(params: dict) -> dict:
    return {"tools": list(TOOLS)}


def on_tools_call(params: dict) -> dict:
    return call_tool(params.get("name") or "", params.get("arguments") or {})


def on_ping(params: dict) -> dict:
    return {}


# Dispatch by lookup rather than by a chain of tests, so the set of methods this
# server answers is one readable list rather than something to be reconstructed
# from control flow.
METHODS = {
    "initialize": on_initialize,
    "tools/list": on_tools_list,
    "tools/call": on_tools_call,
    "ping": on_ping,
}


def handle(message: dict) -> dict | None:
    """Return the response to one message, or None when none is owed.

    A notification has no id and gets no reply, ever. Replying to one is a
    protocol error that some clients tolerate and others drop the connection
    over, so the distinction is load-bearing and is made here once.
    """
    mid = message.get("id")
    method = message.get("method")

    if mid is None:
        return None

    if not isinstance(method, str):
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": INVALID_REQUEST, "message": "no method"}}

    fn = METHODS.get(method)
    if fn is None:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": METHOD_NOT_FOUND,
                          "message": f"unknown method {method}"}}
    try:
        return {"jsonrpc": "2.0", "id": mid,
                "result": fn(message.get("params") or {})}
    except Exception as exc:                      # noqa: BLE001
        # The checker raised. Report it as a failed call rather than dying,
        # because a server that exits takes every later check with it, and say
        # what happened rather than returning an empty result that reads clean.
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": INTERNAL_ERROR,
                          "message": f"{type(exc).__name__}: {exc}"}}


def serve(stdin, stdout) -> int:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": PARSE_ERROR, "message": "not JSON"}}) + "\n")
            stdout.flush()
            continue
        if not isinstance(message, dict):
            stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": INVALID_REQUEST,
                          "message": "not a JSON-RPC object"}}) + "\n")
            stdout.flush()
            continue
        response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0


# Exercised by tests/test_mcp_server.py, which drives serve() with real
# JSON-RPC. In-process coverage cannot observe a child process, so the pragma
# records that the gap is in the instrument rather than in the tests.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(serve(sys.stdin, sys.stdout))
