"""Tests for the clarity checker.

A measuring instrument published by a project whose thesis is that untested
instruments lie cannot itself be untested. These cover every branch in
syllables() and every reporting branch in main(), and each asserts a value
rather than merely asserting that nothing raised.
"""
from __future__ import annotations

import importlib.util
import io
import json
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


# --------------------------------------------------------- analyse() is pure
IN_BAND = ("Every crawler reached the homepage and stopped there, because the "
           "markup contained no links at all. I added twenty canonical links, "
           "and the deployment completed in eighty seconds.")


def test_analyse_returns_a_result_and_prints_nothing(capsys):
    r = clarity.analyse(IN_BAND, "draft.md")
    assert capsys.readouterr().out == ""
    assert r["verdict"] == "in_band"
    assert r["source"] == "draft.md"
    assert "schema" not in r, "schema belongs on the run, not on each file in it"


def test_analyse_is_deterministic():
    assert clarity.analyse(IN_BAND) == clarity.analyse(IN_BAND)


def test_every_check_is_present_even_when_it_passes():
    """Omitting a passing check costs a consumer the ability to tell 'passed'
    from 'never ran'. That distinction is the whole point of the format."""
    checks = clarity.analyse(IN_BAND)["checks"]
    expected = {"first_sentence", "headings", "long_sentences", "em_dashes",
                "hedges", "intensifiers", "tells", "banned_words"}
    assert set(checks) == expected
    assert all("verdict" in c for c in checks.values())


def test_first_sentence_is_unassessed_with_a_stated_reason():
    c = clarity.analyse(IN_BAND)["checks"]["first_sentence"]
    assert c["verdict"] == "unassessed"
    assert c["reason"]
    assert c["text"].startswith("Every crawler")


def test_exit_code_is_carried_in_the_payload():
    assert clarity.analyse(IN_BAND)["exit"] == 0
    assert clarity.analyse("It ran. It broke. I fixed it.")["exit"] == 1


def test_nothing_to_measure_is_a_verdict_not_an_error():
    r = clarity.analyse("\n\n")
    assert r["verdict"] == "nothing_to_measure"
    assert r["exit"] == 0
    assert r["index"] is None


def test_failing_checks_carry_what_was_found():
    r = clarity.analyse("It is clearly and obviously very good indeed today.")
    assert r["checks"]["hedges"]["verdict"] == "fail"
    assert "clearly" in r["checks"]["hedges"]["found"]
    assert r["checks"]["intensifiers"]["found"] == ["very"]


# ------------------------------------------------------------------- --json
def test_json_output_parses_and_matches_analyse(tmp_path):
    f = tmp_path / "d.md"
    f.write_text(IN_BAND)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "clarity.py"), "--json", str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["schema"] == 2
    assert payload["verdict"] == "pass"
    assert payload["files"] == [clarity.analyse(IN_BAND, str(f))]


def test_json_is_exclusive_of_the_human_report(tmp_path):
    """A hook parsing stdout must not have to skip a text report first."""
    f = tmp_path / "d.md"
    f.write_text(IN_BAND)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "clarity.py"), "--json", str(f)],
                       capture_output=True, text=True)
    assert "clarity index" not in r.stdout
    json.loads(r.stdout)


def test_json_exit_code_matches_the_payload(tmp_path):
    f = tmp_path / "bad.md"
    f.write_text("It ran. It broke. I fixed it. It runs.")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "clarity.py"), "--json", str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert json.loads(r.stdout)["exit"] == 1


# ------------------------------------------------------- unreadable sources
def test_unreadable_file_exits_two_not_one(tmp_path):
    """A hook must tell 'this draft is bad' from 'I could not read the draft'.
    Collapsing them hides a broken setup behind a writing complaint."""
    missing = tmp_path / "nope.md"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "clarity.py"), str(missing)],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "cannot read" in r.stdout


def test_unreadable_file_in_json_says_why(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "clarity.py"),
                        "--json", str(tmp_path / "nope.md")],
                       capture_output=True, text=True)
    assert r.returncode == 2
    payload = json.loads(r.stdout)
    assert payload["verdict"] == "unreadable"
    assert payload["exit"] == 2
    assert "FileNotFoundError" in payload["files"][0]["error"]


def test_flags_are_not_mistaken_for_paths():
    assert clarity.paths_from(["clarity.py", "--json"]) == []
    assert clarity.paths_from(["clarity.py", "--json", "a.md", "b.md"]) == ["a.md", "b.md"]


# The subprocess tests above prove the shell contract but run in a child that
# in-process coverage cannot observe. These exercise the same paths in-process
# so the error branch is measured rather than merely believed.
def test_read_one_reports_a_missing_file_without_raising(tmp_path):
    text, error = clarity.read_one(str(tmp_path / "gone.md"))
    assert text is None
    assert "FileNotFoundError" in error


def test_main_in_process_returns_two_for_an_unreadable_file(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "argv", ["clarity.py", str(tmp_path / "gone.md")])
    assert clarity.main() == 2
    assert "cannot read" in capsys.readouterr().out


def test_main_in_process_json_error_payload(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "argv", ["clarity.py", "--json", str(tmp_path / "gone.md")])
    assert clarity.main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "unreadable"
    assert payload["exit"] == 2


def test_main_in_process_json_success(monkeypatch, capsys, tmp_path):
    f = tmp_path / "d.md"
    f.write_text(IN_BAND)
    monkeypatch.setattr(sys, "argv", ["clarity.py", "--json", str(f)])
    assert clarity.main() == 0
    assert json.loads(capsys.readouterr().out)["files"][0]["verdict"] == "in_band"


# ------------------------------------------------------------ many files
# A pre-commit hook passes every staged file at once. Taking only the first
# would pass a commit on the strength of its tidiest file.
def write(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text)
    return str(f)


def test_one_file_still_arrives_as_a_list_of_one(tmp_path):
    """A consumer should never branch on how many arguments it passed."""
    run = clarity.analyse_paths([write(tmp_path, "a.md", IN_BAND)])
    assert run["schema"] == 2
    assert run["counts"]["files"] == 1
    assert isinstance(run["files"], list)


def test_every_path_is_measured_not_just_the_first(tmp_path):
    run = clarity.analyse_paths([
        write(tmp_path, "a.md", IN_BAND),
        write(tmp_path, "b.md", "It ran. It broke. I fixed it. It runs."),
    ])
    assert run["counts"] == {"files": 2, "passed": 1, "failed": 1, "unreadable": 0}
    assert [f["verdict"] for f in run["files"]] == ["in_band", "too_abrupt"]


def test_worst_result_wins(tmp_path):
    good = write(tmp_path, "a.md", IN_BAND)
    bad = write(tmp_path, "b.md", "It ran. It broke. I fixed it. It runs.")
    missing = str(tmp_path / "gone.md")
    assert clarity.analyse_paths([good])["exit"] == 0
    assert clarity.analyse_paths([good, bad])["exit"] == 1
    assert clarity.analyse_paths([good, missing])["exit"] == 2
    # An unreadable file outranks a merely out-of-band one: a run that could
    # not read half its input has not passed.
    assert clarity.analyse_paths([bad, missing])["exit"] == 2


def test_one_unreadable_file_does_not_stop_the_others(tmp_path):
    run = clarity.analyse_paths([str(tmp_path / "gone.md"),
                                 write(tmp_path, "a.md", IN_BAND)])
    assert run["counts"]["unreadable"] == 1
    assert run["counts"]["passed"] == 1
    assert run["files"][1]["verdict"] == "in_band"


def test_text_output_names_each_file_when_there_are_several(tmp_path):
    a = write(tmp_path, "a.md", IN_BAND)
    b = write(tmp_path, "b.md", IN_BAND)
    out = clarity.render_run(clarity.analyse_paths([a, b]))
    assert f"=== {a}" in out and f"=== {b}" in out
    assert "2 files: 2 in band, 0 out of band, 0 unreadable" in out


def test_text_output_does_not_name_a_single_file(tmp_path):
    out = clarity.render_run(clarity.analyse_paths([write(tmp_path, "a.md", IN_BAND)]))
    assert "===" not in out
    assert "1 files" not in out


def test_cli_measures_every_file_given(tmp_path):
    a = write(tmp_path, "a.md", IN_BAND)
    b = write(tmp_path, "b.md", "It ran. It broke. I fixed it. It runs.")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "clarity.py"), "--json", a, b],
                       capture_output=True, text=True)
    assert r.returncode == 1
    payload = json.loads(r.stdout)
    assert payload["counts"]["files"] == 2
    assert [f["source"] for f in payload["files"]] == [a, b]


def test_stdin_still_works_when_no_path_is_given(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["clarity.py", "--json"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(IN_BAND))
    assert clarity.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["files"] == 1
    assert payload["files"][0]["source"] == "-"


# --- gating -----------------------------------------------------------------
#
# Added after the checker was found reporting exit 0 on a draft that failed
# three word checks, because the exit code read only the clarity index. A gate
# that passes what it flagged is worse than no gate: it certifies the defect.

CLEAN = ("The daily report showed no traffic for two of the sites since Tuesday "
         "morning. A stale token in the collector caused it, and every request was "
         "rejected without a warning. I issued a replacement token and the counts "
         "recovered on the same afternoon.")
HEDGED = ("The result was clearly and obviously very significant indeed today, "
          "and the needle did move sharply.")


def test_word_failure_sets_exit_one_even_when_index_is_in_band():
    r = clarity.analyse(HEDGED)
    assert r["verdict"] == "in_band"
    assert r["gating_failures"], "in band but nothing gated, so nothing gates"
    assert r["exit"] == 1


def test_clean_prose_in_band_exits_zero():
    r = clarity.analyse(CLEAN)
    assert (r["verdict"], r["gating_failures"], r["exit"]) == ("in_band", [], 0)


def test_gating_failures_names_every_failing_gate_and_nothing_else():
    r = clarity.analyse(HEDGED)
    assert set(r["gating_failures"]) == {"hedges", "intensifiers", "banned_words"}
    assert all(r["checks"][k]["verdict"] == "fail" for k in r["gating_failures"])


def test_every_check_declares_whether_it_gates():
    checks = clarity.analyse(CLEAN)["checks"]
    assert all("gating" in c for c in checks.values())
    assert {k for k, c in checks.items() if c["gating"]} == set(clarity.GATING)


def test_judgement_calls_are_reported_and_never_gate():
    """headings, long sentences and the first line are reported, not enforced.

    A machine cannot tell a deliberate long sentence from a careless one. Gating
    on that teaches people to disable the hook, which costs the checks that can
    be judged.
    """
    for key in ("first_sentence", "headings", "long_sentences"):
        assert key not in clarity.GATING
    r = clarity.analyse("# A\n## B\n### C\n" + CLEAN)
    assert r["checks"]["headings"]["verdict"] == "fail"
    assert r["exit"] == 0


def test_hook_run_exits_one_on_hedges(tmp_path):
    code, out = run(HEDGED, tmp_path)
    assert code == 1
    assert "HEDGES" in out


def test_frontmatter_is_not_prose(tmp_path):
    """A skill file opens with its metadata. Scored, it becomes the first
    sentence, and the checker reports "name: sitrep" back as your lead."""
    _, out = run("---\nname: sitrep\ndescription: Report in brief format.\n---\n\n"
                 + CLEAN, tmp_path)
    assert "name: sitrep" not in out
    assert "FIRST SENTENCE  The daily report" in out


def test_frontmatter_is_only_stripped_at_the_top(tmp_path):
    """A horizontal rule mid-document is prose furniture, not metadata. Treating
    it as frontmatter would silently delete the body between two rules."""
    body = "\n\n---\nThe collector runs on a schedule of its own.\n---\n\n"
    with_rule = clarity.analyse(CLEAN + body + CLEAN)["counts"]["words"]
    without = clarity.analyse(CLEAN + "\n\n" + CLEAN)["counts"]["words"]
    assert with_rule - without == 9, "the text between mid-document rules vanished"
