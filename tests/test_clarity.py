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
    # Read the labelled line rather than a fixed position. This parsed
    # line 0 and broke when the not-measured block was prepended.
    def index_of(s):
        line = next(l for l in s.splitlines() if l.startswith("clarity index"))
        return float(line.split()[2])
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
        ("The badly-damaged file was recovered from last night's backup.", "AP PUNCTUATION", "badly-damaged"),
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
    for label in ("HEDGES", "INTENSIFIERS", "AI TELLS", "AP PUNCTUATION"):
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
    def index(f):
        out = run(f.read_text(), tmp_path)[1]
        line = next(l for l in out.splitlines() if l.startswith("clarity index"))
        return float(line.split()[2])
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
    assert clarity.analyse(IN_BAND, "-") == clarity.analyse(IN_BAND, "-")


def test_every_check_is_present_even_when_it_passes():
    """Omitting a passing check costs a consumer the ability to tell 'passed'
    from 'never ran'. That distinction is the whole point of the format."""
    checks = clarity.analyse(IN_BAND, "-")["checks"]
    expected = {"first_sentence", "headings", "long_sentences", "em_dashes",
                "hedges", "intensifiers", "tells", "ap_mechanics", "coinage"}
    assert set(checks) == expected
    assert all("verdict" in c for c in checks.values())


def test_first_sentence_is_unassessed_with_a_stated_reason():
    c = clarity.analyse(IN_BAND, "-")["checks"]["first_sentence"]
    assert c["verdict"] == "unassessed"
    assert c["reason"]
    assert c["text"].startswith("Every crawler")


def test_exit_code_is_carried_in_the_payload():
    assert clarity.analyse(IN_BAND, "-")["exit"] == 0
    assert clarity.analyse("It ran. It broke. I fixed it.", "-")["exit"] == 1


def test_nothing_to_measure_is_a_verdict_not_an_error():
    r = clarity.analyse("\n\n", "-")
    assert r["verdict"] == "nothing_to_measure"
    assert r["exit"] == 0
    assert r["index"] is None


def test_failing_checks_carry_what_was_found():
    r = clarity.analyse("It is clearly and obviously very good indeed today.", "-")
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
    run = clarity.analyse_paths([write(tmp_path, "a.md", IN_BAND)], None)
    assert run["schema"] == 2
    assert run["counts"]["files"] == 1
    assert isinstance(run["files"], list)


def test_every_path_is_measured_not_just_the_first(tmp_path):
    run = clarity.analyse_paths([
        write(tmp_path, "a.md", IN_BAND),
        write(tmp_path, "b.md", "It ran. It broke. I fixed it. It runs."),
    ], None)
    assert run["counts"] == {"files": 2, "passed": 1, "failed": 1, "unreadable": 0}
    assert [f["verdict"] for f in run["files"]] == ["in_band", "too_abrupt"]


def test_worst_result_wins(tmp_path):
    good = write(tmp_path, "a.md", IN_BAND)
    bad = write(tmp_path, "b.md", "It ran. It broke. I fixed it. It runs.")
    missing = str(tmp_path / "gone.md")
    assert clarity.analyse_paths([good], None)["exit"] == 0
    assert clarity.analyse_paths([good, bad], None)["exit"] == 1
    assert clarity.analyse_paths([good, missing], None)["exit"] == 2
    # An unreadable file outranks a merely out-of-band one: a run that could
    # not read half its input has not passed.
    assert clarity.analyse_paths([bad, missing], None)["exit"] == 2


def test_one_unreadable_file_does_not_stop_the_others(tmp_path):
    run = clarity.analyse_paths([str(tmp_path / "gone.md"),
                                 write(tmp_path, "a.md", IN_BAND)], None)
    assert run["counts"]["unreadable"] == 1
    assert run["counts"]["passed"] == 1
    assert run["files"][1]["verdict"] == "in_band"


def test_text_output_names_each_file_when_there_are_several(tmp_path):
    a = write(tmp_path, "a.md", IN_BAND)
    b = write(tmp_path, "b.md", IN_BAND)
    out = clarity.render_run(clarity.analyse_paths([a, b], None))
    assert f"=== {a}" in out and f"=== {b}" in out
    assert "2 files: 2 clean, 0 failed a gate, 0 unreadable" in out


def test_text_output_does_not_name_a_single_file(tmp_path):
    out = clarity.render_run(clarity.analyse_paths([write(tmp_path, "a.md", IN_BAND)], None))
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
          "and the reading did not budge at all.")


def test_word_failure_sets_exit_one_even_when_index_is_in_band():
    r = clarity.analyse(HEDGED, "-")
    assert r["verdict"] == "in_band"
    assert r["gating_failures"], "in band but nothing gated, so nothing gates"
    assert r["exit"] == 1


def test_clean_prose_in_band_exits_zero():
    r = clarity.analyse(CLEAN, "-")
    assert (r["verdict"], r["gating_failures"], r["exit"]) == ("in_band", [], 0)


def test_gating_failures_names_every_failing_gate_and_nothing_else():
    r = clarity.analyse(HEDGED, "-")
    assert set(r["gating_failures"]) == {"hedges", "intensifiers"}
    assert all(r["checks"][k]["verdict"] == "fail" for k in r["gating_failures"])


def test_every_check_declares_whether_it_gates():
    checks = clarity.analyse(CLEAN, "-")["checks"]
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
    r = clarity.analyse("# A\n## B\n### C\n" + CLEAN, "-")
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
    with_rule = clarity.analyse(CLEAN + body + CLEAN, "-")["counts"]["words"]
    without = clarity.analyse(CLEAN + "\n\n" + CLEAN, "-")["counts"]["words"]
    assert with_rule - without == 9, "the text between mid-document rules vanished"


# --- AP mechanical punctuation ----------------------------------------------
#
# AP Stylebook 1960, the first joint AP/UPI edition. Only rules a regular
# expression can settle outright are here; the two it cannot are asserted absent
# below, because a check that flags correct prose gets turned off, and it takes
# the checks that were worth having with it.

@pytest.mark.parametrize("text, found", [
    ("The badly-damaged file came back from last night's backup.", "badly-damaged"),
    ("The newly-chosen chair opened the meeting at eight this morning.", "newly-chosen"),
    ('He called the work "exacting", then filed the report away.', '",'),
    ('She read it aloud, said "that settles it". Then she left.', '".'),
    ("The contract named John Jones, Jr. as the sole buyer.", ", Jr."),
    ("The filing listed Smith, & Co. as the parent company.", ", & "),
    ("The week-end release reached a world-wide audience.", "week-end"),
])
def test_ap_defects_are_caught(tmp_path, text, found):
    code, out = run(text, tmp_path)
    assert code == 1
    assert "AP PUNCTUATION" in out and found in out


@pytest.mark.parametrize("text", [
    "The badly damaged file came back from last night's backup.",
    'He called the work "exacting," then filed the report away.',
    "The contract named John Jones Jr. as the sole buyer of the land.",
    "The filing listed Smith & Co. as the parent company of record.",
    "The weekend release reached a worldwide audience without incident.",
])
def test_correct_ap_forms_are_left_alone(tmp_path, text):
    _, out = run(text, tmp_path)
    assert "AP PUNCTUATION" not in out


def test_the_pronoun_I_after_a_comma_is_not_a_roman_numeral(tmp_path):
    """AP also bans the comma before a roman numeral suffix. That half is left
    out: these patterns ignore case, so "III" and ", I ran it" are the same
    string to the check. Flagging the commonest pronoun in English to catch
    "John Jones, III" is a trade no one would take."""
    _, out = run("The build broke, I ran the query again, and it came back clean.",
                 tmp_path)
    assert "AP PUNCTUATION" not in out


def test_the_serial_comma_rule_is_deliberately_absent(tmp_path):
    """AP bans the comma before the final "and" in a list, but keeps it where
    both halves are full clauses. Telling those apart needs to parse the
    sentence, so the rule is left to the writer rather than guessed at."""
    listed = "The report named the date, the host, and the failing check."
    clauses = "Fish abounded in the lake, and the shore was lined with deer."
    for text in (listed, clauses):
        assert "AP PUNCTUATION" not in run(text, tmp_path)[1]


def test_the_summary_names_the_gate_not_the_index(tmp_path):
    """"Out of band" named one of the two ways to fail, so a file scoring 26
    that failed four word checks was reported as unreadable prose."""
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text(IN_BAND)
    b.write_text(IN_BAND + " The result was clearly the right one to pick.")
    argv = sys.argv
    sys.argv = ["clarity.py", str(a), str(b)]
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            code = clarity.main()
    finally:
        sys.argv = argv
    out = buf.getvalue()
    assert code == 1
    assert "2 files: 1 clean, 1 failed a gate, 0 unreadable" in out
    assert "out of band" not in out


@pytest.mark.parametrize("text", [
    "The assembly-language routine ran inside the family-owned plant.",
    "It was a friendly-fire incident, logged in the weekly-updated record.",
    "The early-stage supply-chain review found no fault in the process.",
])
def test_ly_words_that_are_not_adverbs_may_take_a_hyphen(tmp_path, text):
    """AP's rule bans the hyphen after an ADVERB ending in -ly. Not every word
    ending in -ly is one, and flagging "assembly-language" is the kind of false
    positive that gets a hook switched off. Found by running the checker over a
    book manuscript, where it flagged assembly-language as a defect."""
    assert "AP PUNCTUATION" not in run(text, tmp_path)[1]


@pytest.mark.parametrize("found", [
    "badly-damaged", "federally-regulated", "nearly-deterministic",
    "fully-loaded", "frequently-accessed",
])
def test_real_ly_adverbs_are_still_caught(tmp_path, found):
    code, out = run(f"The report named a {found} case in the filing.", tmp_path)
    assert code == 1 and found in out


def test_the_exclusion_list_is_documented_as_incomplete():
    """The list cannot be complete, and saying so is the difference between a
    known limit and a silent one."""
    import inspect
    src = inspect.getsource(clarity)
    assert "incomplete" in src.lower()
    assert len(clarity.NOT_ADVERBS.split("|")) > 20


# --- calibration is not overclaim ---------------------------------------------

def test_almost_certainly_is_calibration_not_a_hedge(tmp_path):
    """"Certainly X" asserts a confidence the evidence has not earned.
    "Almost certainly X" says the opposite: I did not measure this. Flagging it
    pushes a writer toward the stronger claim, which inverts the rule."""
    _, out = run("The programmers were almost certainly competent in their own "
                 "codebases, and the tooling was adequate for the work.", tmp_path)
    assert "HEDGES" not in out


def test_the_bare_hedge_is_still_caught(tmp_path):
    code, out = run("The programmers were certainly competent in their own "
                    "codebases, and the tooling was adequate for the work.", tmp_path)
    assert code == 1 and "certainly" in out


def test_one_exemption_does_not_excuse_a_second_bare_hedge():
    """Exemptions are consumed one per phrase, not applied to the word
    everywhere. Otherwise a single calibrated use would license the rest."""
    r = clarity.analyse("It is almost certainly true, and it is certainly the "
                        "reason the whole run failed again this morning.", "-")
    assert r["checks"]["hedges"]["count"] == 1


def test_notably_naming_an_instance_is_not_a_hedge(tmp_path):
    """In "(notably XP and Scrum)" the word names an instance. It asserts no
    confidence about evidence, which is what the hedge rule is for."""
    _, out = run("The anti-waterfall patterns of the late 1990s (notably XP and "
                 "Scrum) reshaped how teams organized their delivery work.", tmp_path)
    assert "HEDGES" not in out


# --- coinage ----------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "This is what I'll call a loose parameter, roughly.",
    "Let us call it the bare container for now.",
    'By "container" I mean the region no test reaches.',
    "For want of a better word, a wrapper around the region.",
    "I am calling this a bare container.",
    "The term I use for it is a loose parameter.",
])
def test_announcing_a_coinage_fails(text):
    """A session wrote "loose parameter", then "bare container", then
    "container", for a thing Umbra already calls an unexercised input region.
    Each needed redefining and each redefinition was wrong."""
    assert "coinage" in clarity.analyse(text, "-")["gating_failures"]


@pytest.mark.parametrize("text", [
    "I will call the API twice and compare.",
    "They call it PostgreSQL for a reason.",
    "The unexercised input region is untested.",
    "Call the function with the region as its argument.",
])
def test_ordinary_use_of_call_is_not_a_coinage(text):
    """"call it X" is ordinary English. Only a first-person announcement of a
    name, or a stipulated private sense, is the act being banned."""
    assert "coinage" not in clarity.analyse(text, "-")["gating_failures"]


def test_a_coinage_inside_a_code_span_is_a_mention():
    """Writing about the rule has to be possible."""
    assert "coinage" not in clarity.analyse(
        'The checker matches `what I call`.', "-")["gating_failures"]


# --- the index is not a verdict on the writing ------------------------------

def test_every_report_opens_on_what_it_cannot_measure():
    """A session ran this on nearly every message, read "in band" as a pass,
    and shipped the writing its reader was rejecting. The index measures
    sentence length and syllables. It cannot see a buried lead, three findings
    where one mattered, or a correction that changes nothing for the reader,
    and those were the actual defects."""
    out = clarity.render_text(clarity.analyse(IN_BAND, "-"))
    assert out.startswith("NOT MEASURED")
    assert out.index("NOT MEASURED") < out.index("clarity index")


def test_it_says_in_band_is_not_a_pass():
    out = clarity.render_text(clarity.analyse(IN_BAND, "-"))
    assert "not a verdict on the writing" in out


def test_the_three_it_cannot_see_are_named():
    out = clarity.render_text(clarity.analyse(IN_BAND, "-"))
    for question in ("first sentence carry", "showing your work", "Cut what does not"):
        assert question in out, question


def test_a_failing_draft_carries_it_too():
    """It appears whether the draft passes or fails, because a failing report
    is read for what to fix and would otherwise imply the list is complete."""
    out = clarity.render_text(clarity.analyse("Clearly a very significant change.", "-"))
    assert out.startswith("NOT MEASURED")


# --- a quoted document is not this file's writing ----------------------------

VENDORED = """# A skill

This skill holds a document written by somebody else, so that a reader does not have to go and fetch it before the rules make sense. The prose in this paragraph belongs to the skill and is measured. The block below does not.

<!-- BEGIN VENDORED honest-code-principles.md @ a449b58 -->
## Their Heading
Their prose \u2014 with a stray dash, and a load-bearing tell.

## Another Heading
More of their prose, running past twenty words so that it would register as a long sentence if this tool were reading it at all.
<!-- END VENDORED -->

A closing sentence of the skill's own writing, long enough to be scored properly rather than dismissed as too abrupt to measure.
"""


def test_a_vendored_block_is_not_scored_as_this_file_s_prose(tmp_path):
    """The block has to match its source byte for byte or the push is refused,
    so the only way to make its score pass would be to edit the quotation. The
    author of the file cannot act on the finding, which makes reporting it
    noise."""
    f = tmp_path / "SKILL.md"; f.write_text(VENDORED)
    run = clarity.analyse_paths([str(f)], None)
    got = run["files"][0]
    assert got["exit"] == 0
    assert got["quoted_block_skipped"] is True


def test_skipping_a_quoted_block_is_reported_not_silent(tmp_path):
    """A tool that drops part of its input and says nothing has reported a
    score for a document it did not read."""
    f = tmp_path / "SKILL.md"; f.write_text(VENDORED)
    assert "quoted_block_skipped" in clarity.analyse_paths([str(f)], None)["files"][0]


def test_a_file_with_no_quoted_block_is_not_marked(tmp_path):
    f = tmp_path / "plain.md"; f.write_text("One sentence, on one line.\n")
    assert "quoted_block_skipped" not in clarity.analyse_paths([str(f)], None)["files"][0]


def test_the_skill_s_own_prose_is_still_scored(tmp_path):
    """Cutting the quotation must not cut the check. A file whose own writing
    breaks the rules still fails, quoted block or not."""
    bad = VENDORED.replace(
        "A closing sentence of the skill's own writing, long enough to be "
        "scored properly rather than dismissed as too abrupt to measure.",
        "This closing sentence is the author's own and it carries a stray "
        "dash \u2014 right here, which the tool must still refuse.")
    f = tmp_path / "SKILL.md"; f.write_text(bad)
    got = clarity.analyse_paths([str(f)], None)["files"][0]
    assert got["exit"] == 1


def test_line_numbers_still_point_at_the_real_file(tmp_path):
    """The quoted lines are blanked rather than removed, so everything after
    the block keeps its true line number. Deleted, every later finding would
    name a line the reader cannot find."""
    text = clarity.without_quoted(VENDORED)
    assert len(text.split("\n")) == len(VENDORED.split("\n"))
    assert "Their prose" not in text
    assert "A closing sentence" in text


def test_an_unterminated_quoted_block_skips_to_the_end(tmp_path):
    """Rather than resuming mid-quotation and scoring half of someone else's
    document. The vendor gate refuses to push an unpaired block, so this state
    is transient, and while it lasts silence beats a wrong number."""
    text = clarity.without_quoted("mine\n<!-- BEGIN VENDORED x @ a -->\ntheirs\nmore\n")
    assert "theirs" not in text and "more" not in text and "mine" in text


# --- the wrappers and self-labels Adam banned on 2026-08-28 -------------------

@pytest.mark.parametrize("text", [
    "That is the honest way to do it.",
    "That is the real thing here.",
    "The key insight is that it runs.",
    "The verdict is clear.",
    "Worth stating: the tests pass.",
    "Worth noting: it fails on Tuesdays.",
    "The important thing here is the timing.",
    "What matters here is the order.",
    "This is the load-bearing constraint.",
])
def test_a_wrapper_or_a_self_label_is_a_tell(text, tmp_path):
    """Each one wraps an outcome instead of stating it, or announces a sentence
    instead of writing it."""
    f = tmp_path / "d.md"; f.write_text(text + "\n")
    got = clarity.analyse_paths([str(f)], None)["files"][0]
    assert got["checks"]["tells"]["count"] >= 1, text


@pytest.mark.parametrize("text", [
    "The fastest way to check is to run it.",
    "That is the only way in.",
    "I found the thing that broke it.",
    "That is the right answer.",
    "The whole point of the gate is to refuse.",
])
def test_an_ordinary_sentence_about_ways_and_things_is_not_a_tell(text, tmp_path):
    """A checker that fires on the noun rather than the wrapper gets turned off.
    "The only way in" is a fact about the building. The adjective list is short
    on purpose: an exact answer over a subset beats a guess over everything."""
    f = tmp_path / "d.md"; f.write_text(text + "\n")
    got = clarity.analyse_paths([str(f)], None)["files"][0]
    assert got["checks"]["tells"]["count"] == 0, text


@pytest.mark.parametrize("text", [
    "We built it the Honest way.",
    "The Honest answer is in the spec.",
    "That is the Honest thing to do here.",
])
def test_the_capitalised_brand_is_not_a_tell(text, tmp_path):
    """Adam's methodology is called Honest, so "the Honest way" is a proper
    noun naming a method. "The honest way" is a verdict wearing a description.
    Everything else in this file is compared case-insensitively; this one word
    is not, which is what tells the two apart."""
    f = tmp_path / "d.md"; f.write_text(text + "\n")
    got = clarity.analyse_paths([str(f)], None)["files"][0]
    assert got["checks"]["tells"]["count"] == 0, text


def test_the_lowercase_wrapper_still_fires_beside_it(tmp_path):
    """The exemption must not swallow the rule it is an exemption to."""
    f = tmp_path / "d.md"
    f.write_text("We built it the Honest way, which is the honest way to work.\n")
    got = clarity.analyse_paths([str(f)], None)["files"][0]
    assert got["checks"]["tells"]["count"] == 1
