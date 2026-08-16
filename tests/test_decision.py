"""Tests for the decision-brief checker.

The checker's value is that it gates the form and refuses to judge the content.
Most of these assert one or the other: that a structural defect fails, or that a
judgment call is reported as unassessed and never gated.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import decision  # noqa: E402

GOOD = """# Decision: ship the analyzer change today

Background. The classifier could not read three declaration kinds.

Current situation. Teaching it those kinds found 1,459 new pieces of state, and
seven tests that proved a refusal path now cannot fire.

Options.

| Option | Cost | Buys |
|---|---|---|
| Delete the six | An hour | A green tree |
| Skip with a reason | An hour | A standing reminder |

Recommendation: skip them with the reason, then rebuild next week.

Cost of no action. The gain sits uncommitted on one machine for 3 more days.
"""


def brief(**edits):
    """GOOD with one section replaced, so each test changes one thing."""
    text = GOOD
    for old, new in edits.items():
        text = text.replace(old.replace("_", " "), new)
    return text


# --- the form, which is gated -----------------------------------------------

def test_a_complete_brief_passes():
    r = decision.analyse_brief(GOOD, "t")
    assert r["verdict"] == "pass", r["gating_failures"]


@pytest.mark.parametrize("section", ["Background.", "Current situation.",
                                     "Options.", "Recommendation:",
                                     "Cost of no action."])
def test_every_missing_section_fails(section):
    text = "\n".join(l for l in GOOD.splitlines() if not l.startswith(section))
    r = decision.analyse_brief(text, "t")
    assert r["verdict"] == "fail"


def test_sections_out_of_order_fail():
    """The reader stops when they have what they need, so a recommendation
    below the options is one they had to work to reach.

    This used to open on the recommendation, which is now allowed: leading
    with the point is the rule working, not breaking. See
    test_leading_with_the_recommendation_is_not_out_of_order."""
    text = ("Background. Some history.\n\nOptions.\n\n- a costs an hour\n"
            "- b costs a day\n\nCurrent situation. It is bad.\n\n"
            "Recommendation: do the thing.\n\nCost of no action. 3 days lost.\n")
    r = decision.analyse_brief(text, "t")
    assert "sections_in_order" in r["gating_failures"]


def test_a_swamping_background_fails():
    text = GOOD.replace("The classifier could not read three declaration kinds.",
                        "history. " * 400)
    r = decision.analyse_brief(text, "t")
    assert "background_does_not_swamp" in r["gating_failures"]


def test_a_recommendation_that_needs_a_page_fails():
    """A recommendation that long is two recommendations or none."""
    text = GOOD.replace("skip them with the reason, then rebuild next week.",
                        "do the thing " * 30)
    r = decision.analyse_brief(text, "t")
    assert "recommendation_is_short" in r["gating_failures"]


def test_one_option_is_a_notification_not_a_decision():
    text = GOOD.replace("| Delete the six | An hour | A green tree |\n", "")
    r = decision.analyse_brief(text, "t")
    assert "offers_a_choice" in r["gating_failures"]
    assert r["checks"]["offers_a_choice"]["count"] == 1


def test_options_written_as_a_list_are_counted():
    text = GOOD.replace(
        "| Option | Cost | Buys |\n|---|---|---|\n"
        "| Delete the six | An hour | A green tree |\n"
        "| Skip with a reason | An hour | A standing reminder |",
        "- Delete the six, an hour\n- Skip with a reason, an hour")
    r = decision.analyse_brief(text, "t")
    assert r["checks"]["offers_a_choice"]["count"] == 2


def test_an_unpriced_cost_of_no_action_fails():
    """Doing nothing wins by default because it needs no decision. A cost with
    no quantity does not price the option most likely to be taken."""
    text = GOOD.replace("on one machine for 3 more days.", "on a laptop.")
    r = decision.analyse_brief(text, "t")
    assert "cost_of_no_action_is_priced" in r["gating_failures"]


def test_a_number_word_prices_it_too():
    text = GOOD.replace("on one machine for 3 more days.", "for another week.")
    r = decision.analyse_brief(text, "t")
    assert r["checks"]["cost_of_no_action_is_priced"]["verdict"] == "pass"


# --- the defect that produced this check ------------------------------------

def test_a_table_too_wide_for_a_terminal_fails():
    """A real brief on 2026-08-15 arrived with its cost column inside the wrong
    row, because the table was 85 columns."""
    wide = "│ " + "x" * 90 + " │"
    r = decision.analyse_brief(GOOD + "\n" + wide + "\n", "t")
    assert "tables_fit_the_page" in r["gating_failures"]
    assert r["checks"]["tables_fit_the_page"]["lines"]


def test_a_table_inside_the_width_is_silent():
    r = decision.analyse_brief(GOOD + "\n| a | b |\n", "t")
    assert r["checks"]["tables_fit_the_page"]["verdict"] == "pass"


def test_long_prose_is_not_a_table():
    """Only table rows are measured. Wrapping prose is the reader's problem and
    a checker that flags it fires on every brief."""
    r = decision.analyse_brief(GOOD + "\n" + "word " * 60 + "\n", "t")
    assert r["checks"]["tables_fit_the_page"]["verdict"] == "pass"


# --- both shapes of section heading -----------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("## Recommendation", "recommendation"),
    ("Recommendation.", "recommendation"),
    ("Recommendation:", "recommendation"),
    ("**Cost of no action**", "cost_of_no_action"),
    ("Recommendation: skip them", "recommendation"),
    ("The situation.", "situation"),
    ("If we do nothing, it rots", "cost_of_no_action"),
    ("Some ordinary sentence", ""),
    ("", ""),
])
def test_headings_are_recognised_in_either_shape(line, expected):
    assert decision.heading_key(line)[0] == expected


def test_a_leading_heading_keeps_its_own_sentence_as_body():
    """"Recommendation: skip them" carries the recommendation on the same line.
    An earlier version dropped it and reported the section missing."""
    key, rest = decision.heading_key("Recommendation: skip them today")
    assert key == "recommendation" and rest == "skip them today"


def test_text_before_any_heading_is_not_assigned_to_a_section():
    bodies, order = decision.split_sections("A title\n\nBackground. Some.\n")
    assert order == ["background"] and "Some." in bodies["background"]


# --- what it refuses to judge -----------------------------------------------

@pytest.mark.parametrize("key", [
    "recommendation_follows_from_the_situation",
    "options_are_the_real_ones",
    "the_cost_is_the_true_cost",
])
def test_the_judgment_calls_are_unassessed_and_never_gated(key):
    r = decision.analyse_brief(GOOD, "t")
    assert r["checks"][key]["verdict"] == "unassessed"
    assert r["checks"][key]["gating"] is False
    assert key not in r["gating_failures"]


def test_the_clarity_index_is_reported_and_not_gated():
    """A brief carries tables and figures that distort the index, so the band
    is guidance here rather than a gate."""
    c = decision.analyse_brief(GOOD, "t")["checks"]["clarity_index"]
    assert c["gating"] is False and isinstance(c["value"], float)


def test_the_word_rules_still_gate():
    r = decision.analyse_brief(GOOD.replace("seven tests", "Clearly very many tests"), "t")
    assert "hedges" in r["gating_failures"]
    assert "intensifiers" in r["gating_failures"]


def test_a_stray_em_dash_fails():
    r = decision.analyse_brief(GOOD.replace("cannot fire.", "cannot fire — truly."), "t")
    assert "em_dashes" in r["gating_failures"]


def test_paired_em_dashes_pass():
    r = decision.analyse_brief(
        GOOD.replace("cannot fire.", "cannot—no one denied it—fire."), "t")
    assert r["checks"]["em_dashes"]["verdict"] == "pass"


# --- the report -------------------------------------------------------------

def test_the_report_names_the_three_things_it_did_not_check():
    out = decision.render(decision.analyse_brief(GOOD, "t"))
    assert "NOT CHECKED" in out
    assert "real options" in out and "true cost" in out


def test_the_report_names_every_defect_it_found():
    text = GOOD.replace("Background. The classifier could not read three "
                        "declaration kinds.\n\n", "")
    out = decision.render(decision.analyse_brief(text, "t"))
    assert "missing: Background" in out


def test_the_report_says_ok_when_it_is():
    assert decision.render(decision.analyse_brief(GOOD, "t")).startswith(
        "decision brief: ok")


def test_every_gating_failure_reaches_the_reader():
    """A defect counted in the header and absent from the body is a defect the
    reader cannot act on."""
    text = ("Recommendation: " + "x " * 80 + "\n\nBackground. " + "h " * 500 +
            "\n\nCurrent situation. Clearly very bad — yes.\n\nOptions.\n\n"
            "- only one\n\nCost of no action. Nothing measurable.\n"
            "| " + "y" * 90 + " |\n")
    r = decision.analyse_brief(text, "t")
    out = decision.render(r)
    assert len(r["gating_failures"]) >= 6
    for line in out.splitlines():
        assert "\t" not in line


# --- run it as a person would -----------------------------------------------

def test_it_runs_as_a_subprocess_and_exits_1_on_a_defect(tmp_path):
    f = tmp_path / "b.md"; f.write_text("Background. Only this.\n")
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "decision.py"),
                        str(f)], capture_output=True, text=True)
    assert p.returncode == 1 and "missing" in p.stdout


def test_it_runs_as_a_subprocess_and_exits_0_on_a_good_brief(tmp_path):
    f = tmp_path / "b.md"; f.write_text(GOOD)
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "decision.py"),
                        str(f)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout


def test_json_output_carries_every_check(tmp_path):
    f = tmp_path / "b.md"; f.write_text(GOOD)
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "decision.py"),
                        "--json", str(f)], capture_output=True, text=True)
    d = json.loads(p.stdout)
    assert d["verdict"] == "pass"
    assert d["checks"]["the_cost_is_the_true_cost"]["verdict"] == "unassessed"


def test_stdin_is_read_when_no_path_is_given(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["decision.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(GOOD))
    assert decision.main() == 0
    assert "decision brief: ok" in capsys.readouterr().out


def test_an_unreadable_file_is_reported_rather_than_crashed(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["decision.py", "/no/such/brief.md"])
    assert decision.main() == 2
    assert "cannot read" in capsys.readouterr().out


def test_an_unreadable_file_reports_as_json_too(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["decision.py", "--json", "/no/such.md"])
    assert decision.main() == 2
    assert json.loads(capsys.readouterr().out)["verdict"] == "unreadable"


def test_source_has_no_default():
    """A default would make a brief read from stdin indistinguishable from one
    whose caller never said which file it came from."""
    with pytest.raises(TypeError):
        decision.analyse_brief(GOOD)


def test_a_readable_file_path_is_analysed_in_process(monkeypatch, capsys, tmp_path):
    """The subprocess tests exercise this path, but in-process coverage cannot
    observe a child, so the branch reads as untaken. This closes it here rather
    than marking it unreachable, because it is reachable."""
    f = tmp_path / "b.md"; f.write_text(GOOD)
    monkeypatch.setattr(sys, "argv", ["decision.py", str(f)])
    assert decision.main() == 0
    assert "decision brief: ok" in capsys.readouterr().out


def test_leading_with_the_recommendation_is_not_out_of_order():
    """The order exists so the reader meets the point early. Opening on it
    meets that better than position four does.

    An earlier version failed this shape, which put this checker in direct
    contradiction with the hook that tells a model to put the ask first."""
    text = ("Recommendation: delete the local copies.\n\n" +
            GOOD.replace("Recommendation: skip them with the reason, then "
                         "rebuild next week.\n\n", ""))
    r = decision.analyse_brief(text, "t")
    assert "sections_in_order" not in r["gating_failures"]
    assert r["checks"]["sections_in_order"]["leads_with_the_recommendation"]


def test_any_other_reordering_still_fails():
    """Only the recommendation may lead. Background after options is still a
    reader reconstructing the brief for themselves."""
    text = ("Options.\n\n- a costs an hour\n- b costs a day\n\n"
            "Background. Some history.\n\nCurrent situation. It is bad.\n\n"
            "Recommendation: do a.\n\nCost of no action. 3 days lost.\n")
    r = decision.analyse_brief(text, "t")
    assert "sections_in_order" in r["gating_failures"]


def test_the_report_names_the_order_it_actually_found():
    """The reader needs to see the order they wrote, not just that it was
    wrong. This line went uncovered when the only out-of-order test moved."""
    text = ("Background. Some.\n\nOptions.\n\n- a costs an hour\n- b costs a day"
            "\n\nCurrent situation. Bad.\n\nRecommendation: do a.\n\n"
            "Cost of no action. 3 days lost.\n")
    out = decision.render(decision.analyse_brief(text, "t"))
    assert "out of order: background then options then situation" in out


def test_an_option_that_buys_nothing_fails():
    """The really test, made mechanical for the one case a machine can see.
    A real brief carried "D. Leave it | nothing today | nothing" alongside a
    recommendation naming a different option."""
    text = GOOD.replace("| Skip with a reason | An hour | A standing reminder |",
                        "| Skip with a reason | An hour | A standing reminder |\n"
                        "| Leave it | nothing today | nothing |")
    r = decision.analyse_brief(text, "t")
    assert "no_scenery_options" in r["gating_failures"]
    assert r["checks"]["no_scenery_options"]["count"] == 1
    assert "Really?" in decision.render(r)


@pytest.mark.parametrize("buys", ["none", "n/a", "-", "--"])
def test_the_other_ways_of_writing_nothing_also_fail(buys):
    text = GOOD.replace("| Skip with a reason | An hour | A standing reminder |",
                        f"| Skip with a reason | An hour | A standing reminder |\n"
                        f"| Leave it | nothing | {buys} |")
    assert "no_scenery_options" in decision.analyse_brief(text, "t")["gating_failures"]


def test_an_option_that_buys_something_passes():
    """Doing nothing is a legitimate option when it buys something real, and
    the check must not fire on the word nothing appearing elsewhere."""
    text = GOOD.replace("| Skip with a reason | An hour | A standing reminder |",
                        "| Skip with a reason | An hour | A standing reminder |\n"
                        "| Wait a week | nothing today | the classifier lands first |")
    assert "no_scenery_options" not in decision.analyse_brief(text, "t")["gating_failures"]
