"""Tests for the clarity checker.

A measuring instrument published by a project whose thesis is that untested
instruments lie cannot itself be untested. These cover every branch in
syllables() and every reporting branch in main(), and each asserts a value
rather than merely asserting that nothing raised.
"""
from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("clarity", ROOT / "tools" / "clarity.py")
clarity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clarity)


def run(text: str, tmp_path: Path) -> tuple[int, str]:
    """Run the checker over `text` and return its exit code and output."""
    f = tmp_path / "draft.md"
    f.write_text(text)
    buf = io.StringIO()
    argv = sys.argv
    sys.argv = ["clarity.py", str(f)]
    try:
        with redirect_stdout(buf):
            code = clarity.main()
    finally:
        sys.argv = argv
    return code, buf.getvalue()


# --------------------------------------------------------------- syllables
@pytest.mark.parametrize(
    "word, expected",
    [
        ("a", 1),           # single vowel
        ("rhythm", 1),      # no a/e/i/o/u, y carries it
        ("the", 1),         # trailing e dropped, floor holds
        ("make", 1),        # trailing e dropped from 2
        ("bee", 1),         # vowel run counts once, then trailing e
        ("evidence", 3),
        ("readability", 5),
        ("strengths", 1),   # one vowel group in a long word
    ],
)
def test_syllables_counts_vowel_groups(word, expected):
    assert clarity.syllables(word) == expected


def test_syllables_never_returns_zero():
    """The floor matters: a zero would divide the long-word share by nothing."""
    assert clarity.syllables("shh") == 1
    assert clarity.syllables("e") == 1


# ---------------------------------------------------------- strip_furniture
def test_strip_furniture_drops_code_blocks():
    text = "Prose here.\n```\nsome_code(with_long_identifiers)\n```\nMore prose."
    out = clarity.strip_furniture(text)
    assert "some_code" not in out
    assert "Prose here." in out


def test_strip_furniture_drops_tables_urls_and_inline_code():
    text = "See | a | b |\n| 1 | 2 |\nat https://example.org/very/long/path and `inline_code`."
    out = clarity.strip_furniture(text)
    assert "https://example.org" not in out
    assert "inline_code" not in out
    assert "| 1 | 2 |" not in out


def test_furniture_is_excluded_from_the_score(tmp_path):
    """A report full of evidence must not score as unreadable for containing it."""
    prose = "The homepage had no links. A crawler arrived and left. I added twenty."
    with_code = prose + "\n\n```\n" + "\n".join(f"antidisestablishmentarianism_{i}()" for i in range(20)) + "\n```\n"
    _, plain = run(prose, tmp_path)
    _, fenced = run(with_code, tmp_path / "sub" if (tmp_path / "sub").mkdir() or True else tmp_path)
    index_of = lambda s: float(s.splitlines()[0].split()[2])
    assert index_of(plain) == index_of(fenced)


# ------------------------------------------------------------- sentences_of
def test_sentences_split_on_terminators_and_blank_lines():
    assert len(clarity.sentences_of("One. Two! Three?")) == 3
    assert len(clarity.sentences_of("One line\n\nAnother block")) == 2


def test_sentences_of_drops_fragments_with_no_words():
    assert clarity.sentences_of("   \n\n...\n\n") == []


# -------------------------------------------------------------------- main
def test_empty_input_says_so_and_succeeds(tmp_path):
    code, out = run("\n\n", tmp_path)
    assert code == 0
    assert "nothing to measure" in out


def test_in_band_text_exits_zero(tmp_path):
    text = ("Every crawler reached the homepage and stopped there, because the "
            "markup contained no links at all. I added twenty canonical links, "
            "and the deployment completed in eighty seconds.")
    code, out = run(text, tmp_path)
    assert code == 0
    assert "in band" in out


def test_too_abrupt_is_named_and_fails(tmp_path):
    code, out = run("It ran. It broke. I fixed it. It runs.", tmp_path)
    assert code == 1
    assert "TOO ABRUPT" in out


def test_too_hard_is_named_and_fails(tmp_path):
    text = ("The instrumentation infrastructure demonstrably necessitates "
            "comprehensive reconfiguration because organisational communication "
            "methodologies consistently underdetermine the operational "
            "requirements that subsequently characterise implementation.")
    code, out = run(text, tmp_path)
    assert code == 1
    assert "TOO HARD" in out


def test_first_sentence_is_printed_back(tmp_path):
    _, out = run("Fixed and live. The rest was cached copies of the old page.", tmp_path)
    assert "FIRST SENTENCE  Fixed and live." in out


def test_more_than_two_headings_is_flagged(tmp_path):
    text = "# One\ntext here.\n\n## Two\ntext here.\n\n## Three\ntext here.\n"
    _, out = run(text, tmp_path)
    assert "STRUCTURE  3 headings" in out


def test_two_headings_is_not_flagged(tmp_path):
    text = "# One\nSome prose that is long enough to measure properly here.\n\n## Two\nMore prose.\n"
    _, out = run(text, tmp_path)
    assert "STRUCTURE" not in out


def test_long_sentences_are_listed_with_their_length(tmp_path):
    long_one = " ".join(["word"] * 25) + "."
    _, out = run(f"Short one here. {long_one}", tmp_path)
    assert "OVER 20 WORDS  1" in out
    assert " 25  " in out


def test_odd_em_dash_count_reads_as_stray(tmp_path):
    _, out = run("The engine is not here — the app asks the server for it.", tmp_path)
    assert "EM DASHES  1" in out
    assert "stray, fix it" in out


def test_even_em_dash_count_asks_you_to_check_pairing(tmp_path):
    _, out = run("He claimed—no one denied it—that he had priority here.", tmp_path)
    assert "EM DASHES  2" in out
    assert "check they are paired" in out


def test_no_em_dash_section_when_there_are_none(tmp_path):
    _, out = run("A plain sentence with no dashes in it at all today.", tmp_path)
    assert "EM DASHES" not in out


@pytest.mark.parametrize(
    "text, label, needle",
    [
        ("This is clearly and obviously the correct answer to give.", "HEDGES", "clearly"),
        ("It was very significantly better than the previous attempt.", "INTENSIFIERS", "very"),
        ("Then comes the honest part, where the failure gets published.", "AI TELLS", "honest part"),
        ("The needle did not move at all under the sharper test today.", "BANNED WORDS", "move"),
    ],
)
def test_each_word_class_is_reported(tmp_path, text, label, needle):
    _, out = run(text, tmp_path)
    assert label in out
    assert needle in out


def test_clean_prose_reports_no_word_classes(tmp_path):
    text = ("The homepage carried no links. A crawler arrived and left again. "
            "I added twenty links to the canonical pages.")
    _, out = run(text, tmp_path)
    for label in ("HEDGES", "INTENSIFIERS", "AI TELLS", "BANNED WORDS"):
        assert label not in out


def test_reads_stdin_when_given_no_path(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["clarity.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("A short line of prose to measure here."))
    code = clarity.main()
    assert code in (0, 1)
    assert "clarity index" in capsys.readouterr().out


# ----------------------------------------------------------- the CLI itself
# Importing the module never executes the __main__ guard, so the exit code a
# shell or a pre-commit hook actually sees goes untested. These run the script
# the way a hook does.
def test_cli_exits_zero_on_in_band_prose(tmp_path):
    f = tmp_path / "ok.md"
    f.write_text("Every crawler reached the homepage and stopped there, because "
                 "the markup contained no links at all. I added twenty canonical "
                 "links, and the deployment completed in eighty seconds.")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "clarity.py"), str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "in band" in r.stdout


def test_cli_exits_one_out_of_band_so_a_hook_can_gate(tmp_path):
    f = tmp_path / "bad.md"
    f.write_text("It ran. It broke. I fixed it. It runs.")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "clarity.py"), str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "TOO ABRUPT" in r.stdout


def test_cli_reads_stdin_when_given_no_argument():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "clarity.py")],
                       input="Every crawler reached the homepage and stopped there, "
                             "because the markup contained no links at all. I added "
                             "twenty canonical links, and it deployed in eighty seconds.",
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "clarity index" in r.stdout


def test_headings_do_not_count_as_sentences(tmp_path):
    """A heading is furniture. Counted as prose it reads as a one-word sentence
    and drags the average down, so a well-written document with many headings
    scores as too abrupt."""
    prose = ("Every crawler reached the homepage and stopped there, because the "
             "markup contained no links at all. I added twenty canonical links, "
             "and the deployment completed in eighty seconds.")
    bare, _ = tmp_path / "a.md", None
    bare.write_text(prose)
    headed = tmp_path / "b.md"
    headed.write_text("## One\n\n" + prose + "\n\n## Two\n\n## Three\n")
    index = lambda f: float(run(f.read_text(), tmp_path)[1].splitlines()[0].split()[2])
    assert index(bare) == index(headed)
