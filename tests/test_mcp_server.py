"""Tests for the MCP server.

The server is transport and nothing else, so most of these check that it speaks
the protocol correctly and that it never invents a verdict of its own. The two
that matter most assert the things a broken server gets silently wrong: that a
notification draws no reply, and that a failing check leads with the failure.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp"))
import server  # noqa: E402

BRIEF = ("Background. A thing happened.\n\nCurrent situation. It forces a "
         "choice.\n\nOptions.\n\n- delete them, an hour\n- skip them, an hour\n\n"
         "Recommendation: skip them.\n\nCost of no action. 3 days lost.\n")


def session(*messages):
    """Drive serve() with real JSON-RPC and return the parsed replies."""
    raw = "\n".join(json.dumps(m) for m in messages) + "\n"
    out = io.StringIO()
    server.serve(io.StringIO(raw), out)
    return [json.loads(l) for l in out.getvalue().strip().splitlines() if l]


def req(mid, method, **params):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}


def call(mid, name, text):
    return req(mid, "tools/call", name=name, arguments={"text": text})


# --- the protocol -----------------------------------------------------------

def test_initialize_echoes_the_client_version():
    """Refusing a version we can in fact speak would fail the connection over a
    string rather than over a capability."""
    r = session(req(1, "initialize", protocolVersion="2024-11-05"))[0]
    assert r["result"]["protocolVersion"] == "2024-11-05"
    assert r["result"]["serverInfo"]["name"] == "honest-writing"
    assert "tools" in r["result"]["capabilities"]


def test_initialize_without_a_version_answers_with_the_fallback():
    r = session(req(1, "initialize"))[0]
    assert r["result"]["protocolVersion"] == server.FALLBACK_PROTOCOL


def test_a_notification_draws_no_reply_at_all():
    """A notification has no id. Replying to one is a protocol error that some
    clients tolerate and others drop the connection over."""
    assert session({"jsonrpc": "2.0", "method": "notifications/initialized"}) == []


def test_a_notification_for_a_known_method_also_draws_no_reply():
    assert session({"jsonrpc": "2.0", "method": "ping", "params": {}}) == []


def test_tools_list_names_all_three():
    r = session(req(1, "tools/list"))[0]
    assert {t["name"] for t in r["result"]["tools"]} == {
        "check_decision_brief", "check_prose", "check_commit_message"}


def test_every_tool_declares_an_input_schema():
    for t in session(req(1, "tools/list"))[0]["result"]["tools"]:
        assert t["inputSchema"]["required"] == ["text"]
        assert t["description"]


def test_an_unknown_method_is_an_error_not_a_crash():
    e = session(req(1, "no/such/method"))[0]["error"]
    assert e["code"] == server.METHOD_NOT_FOUND


def test_a_message_with_no_method_is_an_invalid_request():
    e = session({"jsonrpc": "2.0", "id": 1})[0]["error"]
    assert e["code"] == server.INVALID_REQUEST


def test_ping_answers_empty():
    assert session(req(1, "ping"))[0]["result"] == {}


def test_a_line_that_is_not_json_is_reported_and_the_server_continues():
    out = io.StringIO()
    server.serve(io.StringIO("{not json\n" + json.dumps(req(2, "ping")) + "\n"), out)
    replies = [json.loads(l) for l in out.getvalue().strip().splitlines()]
    assert replies[0]["error"]["code"] == server.PARSE_ERROR
    assert replies[1]["result"] == {}       # it kept serving


def test_a_json_value_that_is_not_an_object_is_an_invalid_request():
    out = io.StringIO()
    server.serve(io.StringIO("[1,2,3]\n"), out)
    assert json.loads(out.getvalue())["error"]["code"] == server.INVALID_REQUEST


def test_blank_lines_are_skipped():
    out = io.StringIO()
    server.serve(io.StringIO("\n\n" + json.dumps(req(1, "ping")) + "\n"), out)
    assert len(out.getvalue().strip().splitlines()) == 1


def test_a_checker_that_raises_becomes_an_error_not_an_exit(monkeypatch):
    """A server that dies takes every later check with it."""
    def boom(*a, **k):
        raise RuntimeError("the checker broke")
    monkeypatch.setattr(server.decision, "analyse_brief", boom)
    e = session(call(1, "check_decision_brief", BRIEF))[0]["error"]
    assert e["code"] == server.INTERNAL_ERROR and "the checker broke" in e["message"]


# --- the verdict a model reads ----------------------------------------------

def test_a_failing_check_leads_with_the_failure():
    """check_prose once opened with "clarity index 20.0, in band" on a draft
    carrying three gating failures, because the index and the gates are
    different questions. A model reading the first line would have called it
    clean."""
    r = session(call(1, "check_prose", "Clearly this is a very significant change."))[0]
    first = r["result"]["content"][0]["text"].splitlines()[0]
    assert first.startswith("FAIL")
    assert "hedges" in first and "intensifiers" in first


def test_a_passing_check_says_so_and_points_at_what_it_did_not_assess():
    r = session(call(1, "check_decision_brief", BRIEF))[0]
    first = r["result"]["content"][0]["text"].splitlines()[0]
    assert first.startswith("PASS") and "unassessed" in first


@pytest.mark.parametrize("name,text", [
    ("check_prose", "A short clean line about the work."),
    ("check_commit_message", "Fix the widget\n\nA body that explains why."),
    ("check_decision_brief", BRIEF),
])
def test_every_tool_returns_the_report_and_the_json(name, text):
    body = session(call(1, name, text))[0]["result"]["content"][0]["text"]
    payload = json.loads(body[body.index("{"):])
    assert payload["tool"] == name
    assert "checks" in payload and payload["source"] == "mcp"


def test_the_unassessed_checks_survive_into_the_json():
    """They exist so nothing reads a green verdict as a complete one, which
    only works if a client can see them."""
    body = session(call(1, "check_decision_brief", BRIEF))[0]["result"]["content"][0]["text"]
    payload = json.loads(body[body.index("{"):])
    assert payload["checks"]["the_cost_is_the_true_cost"]["verdict"] == "unassessed"


def test_a_missing_text_argument_says_nothing_was_checked():
    """"Not checked" must never read as "passed"."""
    r = session(req(1, "tools/call", name="check_prose", arguments={}))[0]
    assert r["result"]["isError"] is True
    assert "not the same as" in r["result"]["content"][0]["text"]


def test_a_non_string_text_argument_is_refused_too():
    r = session(call(1, "check_prose", 42))[0]
    assert r["result"]["isError"] is True


def test_an_unknown_tool_name_is_an_error_result_not_a_protocol_error():
    r = session(call(1, "check_the_vibes", "hello"))[0]
    assert r["result"]["isError"] is True
    assert "No tool named" in r["result"]["content"][0]["text"]


def test_the_unreadable_verdict_line_says_nothing_was_checked():
    assert "not the same as clean" in server.verdict_line({"verdict": "unreadable"})


# --- it never analyses anything itself --------------------------------------

def test_the_server_holds_no_analysis_of_its_own():
    """Every verdict comes from the three checkers. A second implementation
    under the same name is how two tools come to disagree while both claiming
    the standard."""
    src = (ROOT / "mcp" / "server.py").read_text()
    for banned in ("re.compile", "def analyse", "splitlines()", "syllable"):
        assert banned not in src, banned


def test_stdout_carries_nothing_but_protocol(tmp_path):
    """A stray print corrupts the stream and the client sees a parse error
    rather than the thing that was actually wrong."""
    msgs = "\n".join(json.dumps(m) for m in [
        req(1, "initialize"), req(2, "tools/list"),
        call(3, "check_prose", "A clean short line.")]) + "\n"
    p = subprocess.run([sys.executable, str(ROOT / "mcp" / "server.py")],
                       input=msgs, capture_output=True, text=True)
    assert p.returncode == 0
    for line in p.stdout.strip().splitlines():
        assert json.loads(line)["jsonrpc"] == "2.0"
