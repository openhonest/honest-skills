"""Tests for the claims checker.

A checker that flags unearned claims and ships without tests is itself an
unearned claim. Each case asserts a value rather than asserting that nothing
raised, and the false-positive case is here because the limitation is real and
should fail loudly if someone silently "fixes" it.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("claims", ROOT / "tools" / "claims.py")
claims = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(claims)


def run(text: str, tmp_path: Path, json_out: bool = False) -> tuple[int, str]:
    f = tmp_path / "draft.md"
    f.write_text(text)
    argv = [str(f)] + (["--json"] if json_out else [])
    buf = io.StringIO()
    old = sys.argv
    sys.argv = ["claims.py"] + argv
    try:
        with redirect_stdout(buf):
            code = claims.main()
    finally:
        sys.argv = old
    return code, buf.getvalue()


@pytest.mark.parametrize("text,kind", [
    ("The parser is not found.", "unqualified negative"),
    ("There are no callers.", "unqualified negative"),
    ("Tests pass.", "completion"),
    ("It works now.", "completion"),
    ("Every module was checked.", "absolute"),
])
def test_bare_claim_is_flagged(text, kind, tmp_path):
    code, out = run(text, tmp_path)
    assert code == 1
    assert kind in out


@pytest.mark.parametrize("text", [
    "Not found under `crates/buzz-acp`.",              # path on the line
    "All tests pass, 118 of them.",                    # figure on the line
    "Tests pass:\n\n```\n42 passed\n```",              # block immediately after
])
def test_warranted_claim_passes(text, tmp_path):
    code, out = run(text, tmp_path)
    assert code == 0
    assert "nothing unearned" in out


def test_warrant_does_not_reach_backwards(tmp_path):
    """A block above an unrelated claim must not excuse it."""
    code, _ = run("```\n42 passed\n```\n\nEvery module was checked.", tmp_path)
    assert code == 1


def test_neighbouring_evidence_does_not_transfer(tmp_path):
    """One claim's warrant must not cover the claim beside it."""
    code, out = run("The parser is not found.\n\nNot found under `crates/`.", tmp_path)
    assert code == 1
    assert out.count("line ") == 1


def test_frontmatter_is_not_prose(tmp_path):
    code, _ = run("---\ndescription: flags 'not found' and 'tests pass'\n---\n\nFine.",
                  tmp_path)
    assert code == 0


def test_inline_code_is_a_mention_not_a_claim(tmp_path):
    code, _ = run("Triggers: `not found`, `tests pass`.", tmp_path)
    assert code == 0


def test_prose_about_claims_is_a_known_false_positive(tmp_path):
    """Use versus mention is not decided. If this ever passes, say so in the
    docstring instead of deleting the test."""
    code, _ = run("Every link is a verified fact, and not found means nothing.",
                  tmp_path)
    assert code == 1


def test_fenced_content_is_skipped(tmp_path):
    code, _ = run("```\nTests pass.\nNot found.\n```", tmp_path)
    assert code == 0


def test_unreadable_file_is_not_a_pass(tmp_path):
    sys.argv = ["claims.py", str(tmp_path / "missing.md")]
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = claims.main()
    assert code == 2
    assert "cannot read" in buf.getvalue()


def test_stdin_is_labelled_as_stdin():
    run_result = claims.analyse_paths([], "Tests pass.")
    assert run_result["files"][0]["source"] == "-"
    assert run_result["exit"] == 1


def test_json_output_carries_what_was_not_checked(tmp_path):
    code, out = run("Tests pass.", tmp_path, json_out=True)
    payload = json.loads(out)
    assert code == 1
    assert payload["schema"] == 2
    assert payload["verdict"] == "fail"
    assert len(payload["not_checked"]) == 4
    assert payload["files"][0]["findings"][0]["kind"] == "completion"


def test_unterminated_frontmatter_is_not_treated_as_metadata(tmp_path):
    """An opening --- with no closing one is a malformed document, not a
    licence to skip the whole file. Everything after it stays prose."""
    code, out = run("---\ndescription: x\n\nTests pass.", tmp_path)
    assert code == 1
    assert "completion" in out
