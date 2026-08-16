#!/usr/bin/env python3
"""Check a decision brief for the defects a machine can actually judge.

    uv run tools/decision.py brief.md
    uv run tools/decision.py --json brief.md

A decision brief asks someone to decide. It has five sections and they are in
this order for a reason:

    Background            what the reader needs to know and does not
    Current situation     what is true now, and why it forces a choice
    Options               each with what it costs and what it buys
    Recommendation        one course of action, named
    Cost of no action     what happens if the reader does nothing

WHY THE ORDER IS PART OF THE FORM
The reader stops when they have what they need. A recommendation at the bottom
is a recommendation nobody read. The rule is not that background comes first
because it is background; it is that background earns at most the space needed
to make the situation legible, and the situation exists to force the choice.

WHY "COST OF NO ACTION" IS A SECTION AND NOT A SENTENCE
Doing nothing is always an option and it is the one that wins by default,
because it needs no decision. A brief that does not price it has quietly
excluded the option most likely to be taken.

WHAT THIS REFUSES TO JUDGE
Whether the recommendation follows from the situation. Whether the options are
the real ones. Whether the cost is the true cost. Those are the whole of the
work and no checker reaches them, so they are reported and never gated.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clarity  # noqa: E402

# The five sections, in required order, each with the openings people actually
# write. Matching is on the start of a line, so "The situation." and
# "## Current situation" and "**Situation**" all land.
SECTIONS = (
    ("background", ("background", "context", "how we got here")),
    ("situation", ("current situation", "the situation", "situation",
                   "where we are", "what is true now")),
    ("options", ("options", "the options", "alternatives", "courses of action")),
    ("recommendation", ("recommendation", "recommended", "i recommend",
                        "recommend")),
    ("cost_of_no_action", ("cost of no action", "cost of inaction",
                           "if we do nothing", "doing nothing",
                           "cost of doing nothing")),
)

LABELS = {
    "background": "Background",
    "situation": "Current situation",
    "options": "Options",
    "recommendation": "Recommendation",
    "cost_of_no_action": "Cost of no action",
}

# A brief is read in a terminal, in a chat window, and in a mail client. Past
# this width a box-drawing table wraps and the cells interleave into nonsense.
#
# 80 is not a nostalgic number. It is the default terminal width, the width a
# chat pane leaves after its own chrome, and the point at which a quoted mail
# reply starts breaking. Measured against a real brief on 2026-08-15 whose
# options table was 85 columns and arrived shredded, with cost text landing
# inside the wrong column and one row losing its cell boundaries entirely.
TABLE_WIDTH = 80

# Anything that reads as a table row.
TABLE_LINE = re.compile(r"^\s*[|│┌├└┬┼┴╔╠╚]")

# A quantity: a figure, a currency, a share, a span of time, or a count of
# occurrences.
#
# Bare number words are deliberately absent. An earlier version accepted them
# and passed "sitting uncommitted on one machine" as a priced cost, because
# "one" is an article there and not a quantity. The words kept below cannot be
# used that way: "once today" and "three days" are measurements, "one machine"
# is a noun with a number in front of it.
QUANTITY = re.compile(
    r"\d|[$\u00a3\u20ac%]|"
    r"\b(once|twice|minutes?|hours?|days?|weeks?|months?|quarters?|years?)\b",
    re.I)


def heading_key(line: str) -> tuple[str, str]:
    """Return (section this line opens, the rest of the line).

    Two shapes are equally common and both have to work. A section name can sit
    alone on its own line, as a markdown heading or a bare sentence:

        ## Recommendation
        Recommendation.

    or it can lead the sentence it introduces, which is how people write
    briefs when they are not thinking about markdown:

        Recommendation: skip them with the reason, then rebuild.

    The first version of this function handled only the first shape, and threw
    away three of the five sections of the first real brief it was given.
    """
    s = line.strip().lstrip("#*->_ ").strip()
    s = re.sub(r"[*_`]", "", s).strip()
    low = s.lower()
    for key, openings in SECTIONS:
        for o in openings:
            if low == o or low == o + ":" or low == o + ".":
                return key, ""
            # A section name can be followed by a colon, a full stop, a
            # dash, a comma, or nothing but a space.
            for sep in (": ", ". ", ", ", " - ", " "):
                if low.startswith(o + sep):
                    return key, s[len(o) + len(sep.rstrip()):].lstrip(" -")
    return "", ""


def split_sections(text: str) -> tuple[dict, list]:
    """Return ({key: body}, [keys in the order they appeared])."""
    bodies: dict[str, list[str]] = {}
    order: list[str] = []
    current = ""
    for line in text.splitlines():
        key, rest = heading_key(line)
        if key and key not in bodies:
            bodies[key] = [rest] if rest else []
            order.append(key)
            current = key
            continue
        if current:
            bodies[current].append(line)
    return {k: "\n".join(v).strip() for k, v in bodies.items()}, order


def wide_table_lines(text: str) -> list[int]:
    """1-indexed line numbers of table rows too wide to survive a terminal."""
    return [i for i, l in enumerate(text.splitlines(), 1)
            if TABLE_LINE.match(l) and len(l) > TABLE_WIDTH]


def option_count(body: str) -> int:
    """How many options the Options section offers.

    Counts table rows that carry content, then falls back to list items. A
    single option is not a choice, and the reader is being asked to make one.
    """
    rows = [l for l in body.splitlines()
            if TABLE_LINE.match(l) and re.search(r"[A-Za-z]{3}", l)]
    if rows:
        # Drop the header row, which names the columns rather than an option.
        return max(0, len(rows) - 1)
    return len([l for l in body.splitlines()
                if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+\S", l)])


# An option that says in its own cell that it buys nothing. A real brief
# carried "D. Leave it | nothing today | nothing" on 2026-08-16, alongside a
# recommendation naming a different option. Its author had already rejected it
# and offered it anyway, to have something to count.
BUYS_NOTHING = re.compile(
    r"[|│]\s*(?:nothing|none|n/?a|-{1,2})\s*[|│]?\s*$", re.I | re.M)


def scenery_options(body: str) -> int:
    """Options that admit they buy nothing.

    The really test, made mechanical for the one case a machine can see. Is
    there any universe in which the reader picks the row whose own cell says
    it buys nothing? Offering it spends their attention on a course already
    rejected, and it inflates the option count so the brief looks like a
    choice.
    """
    return len(BUYS_NOTHING.findall(body))


def analyse_brief(raw: str, source: str) -> dict:
    """`source` has no default: see the note in clarity.analyse. A default
    would make a brief read from stdin indistinguishable from one whose caller
    never said which file it came from."""
    text = raw.strip()
    bodies, order = split_sections(text)
    prose = clarity.strip_furniture(text)

    checks: dict[str, dict] = {}

    for key, _ in SECTIONS:
        present = key in bodies and bool(bodies[key].strip())
        checks[f"has_{key}"] = {
            "verdict": "pass" if present else "fail", "gating": True,
            "words": len(bodies.get(key, "").split()),
        }

    expected = [k for k, _ in SECTIONS]
    seen = [k for k in order if k in expected]
    # A recommendation in first position is not out of order, it is the rule
    # working. The order exists so the reader meets the point early; opening on
    # it and supporting it underneath meets that better than position four
    # does. An earlier version failed this shape, which put this checker in
    # direct contradiction with the hook that tells a model to put the ask
    # first. Two of our own tools disagreeing about the same rule is the defect
    # this project exists to name, so the checker yielded.
    rest = seen[1:] if seen[:1] == ["recommendation"] else seen
    in_order = rest == sorted(rest, key=expected.index)
    checks["sections_in_order"] = {
        "verdict": "pass" if in_order else "fail", "gating": True,
        "found": seen, "expected": expected,
        "leads_with_the_recommendation": seen[:1] == ["recommendation"],
        "reason": "the reader stops when they have what they need, so a "
                  "recommendation below the background is one nobody read. "
                  "Leading with it is allowed for the same reason",
    }

    # Background is the section that swells. It is the easiest to write and the
    # least useful, and every word of it delays the choice.
    bg = len(bodies.get("background", "").split())
    rec = len(bodies.get("recommendation", "").split())
    total = max(1, len(text.split()))
    checks["background_does_not_swamp"] = {
        "verdict": "fail" if bg > total * 0.4 else "pass", "gating": True,
        "background_words": bg, "share": round(bg / total * 100, 1),
        "limit_percent": 40,
    }

    checks["recommendation_is_short"] = {
        "verdict": "fail" if rec > 60 else "pass", "gating": True,
        "words": rec, "limit": 60,
        "reason": "a recommendation that needs a page is two recommendations "
                  "or none",
    }

    scenery = scenery_options(bodies.get("options", ""))
    checks["no_scenery_options"] = {
        "verdict": "fail" if scenery else "pass", "gating": True,
        "count": scenery,
        "reason": "an option whose own cell says it buys nothing was rejected "
                  "before it was written, and it is there to make the count",
    }

    opts = option_count(bodies.get("options", ""))
    checks["offers_a_choice"] = {
        "verdict": "pass" if opts >= 2 else "fail", "gating": True,
        "count": opts,
        "reason": "one option is not a decision, it is a notification",
    }

    cona = bodies.get("cost_of_no_action", "")
    checks["cost_of_no_action_is_priced"] = {
        "verdict": "pass" if QUANTITY.search(cona) else "fail", "gating": True,
        "reason": "doing nothing wins by default because it needs no decision, "
                  "so a cost with no quantity in it does not price the option "
                  "most likely to be taken",
    }

    wide = wide_table_lines(text)
    checks["tables_fit_the_page"] = {
        "verdict": "fail" if wide else "pass", "gating": True,
        "lines": wide, "limit": TABLE_WIDTH,
        "reason": "past this width the cells interleave and the table arrives "
                  "unreadable, which happened to a real brief on 2026-08-15",
    }

    dashes = text.count("—")
    checks["em_dashes"] = {
        "verdict": "fail" if dashes % 2 else "pass", "gating": True,
        "count": dashes,
        "reason": ("odd count, so one is stray" if dashes % 2
                   else "even count, check they are paired"),
    }

    for key, pats in clarity.WORD_CLASSES:
        hits = [h for p in pats for h in clarity.scan(p, prose)]
        checks[key] = {"verdict": "fail" if hits else "pass", "gating": True,
                       "count": len(hits), "found": sorted(set(hits))}

    index = clarity.analyse(text, source)["index"]
    checks["clarity_index"] = {
        "verdict": "pass", "gating": False, "value": index["value"],
        "reason": "reported, never gated. The band is guidance for prose and a "
                  "brief carries tables and figures that distort it",
    }

    # The three that decide whether the brief is any good, and the three no
    # checker reaches. Named so their absence is visible rather than assumed.
    for key, reason in (
        ("recommendation_follows_from_the_situation",
         "a machine cannot tell a conclusion from a non sequitur"),
        ("options_are_the_real_ones",
         "a machine cannot see the option you did not write down"),
        ("the_cost_is_the_true_cost",
         "a machine can see a number and not whether it is the right one"),
    ):
        checks[key] = {"verdict": "unassessed", "gating": False,
                       "reason": reason}

    failed = [k for k, c in checks.items()
              if c["gating"] and c["verdict"] == "fail"]
    return {"source": source, "verdict": "fail" if failed else "pass",
            "exit": 1 if failed else 0, "gating_failures": failed,
            "sections_found": seen, "checks": checks}


def render(r: dict) -> str:
    c = r["checks"]
    out = ["decision brief: ok" if r["verdict"] == "pass"
           else f"decision brief: {len(r['gating_failures'])} defect(s)"]

    missing = [LABELS[k] for k, _ in SECTIONS if c[f"has_{k}"]["verdict"] == "fail"]
    if missing:
        out.append(f"  missing: {', '.join(missing)}")
    if c["sections_in_order"]["verdict"] == "fail":
        out.append(f"  out of order: {' then '.join(c['sections_in_order']['found'])}")
    if c["background_does_not_swamp"]["verdict"] == "fail":
        out.append(f"  background is {c['background_does_not_swamp']['share']}% "
                   f"of the brief, limit 40%")
    if c["recommendation_is_short"]["verdict"] == "fail":
        out.append(f"  recommendation runs {c['recommendation_is_short']['words']} "
                   f"words, limit 60")
    if c["no_scenery_options"]["verdict"] == "fail":
        out.append(f"  {c['no_scenery_options']['count']} option(s) say they buy "
                   f"nothing. Any universe where they pick that one? Really?")
    if c["offers_a_choice"]["verdict"] == "fail":
        out.append(f"  {c['offers_a_choice']['count']} option(s). One option is "
                   f"a notification, not a decision")
    if c["cost_of_no_action_is_priced"]["verdict"] == "fail":
        out.append("  cost of no action carries no quantity, so the option most "
                   "likely to be taken is unpriced")
    if c["tables_fit_the_page"]["verdict"] == "fail":
        lines = c["tables_fit_the_page"]["lines"]
        out.append(f"  {len(lines)} table row(s) over {TABLE_WIDTH} columns "
                   f"(lines {', '.join(str(n) for n in lines[:8])}). They will "
                   f"arrive shredded")
    if c["em_dashes"]["count"] and c["em_dashes"]["verdict"] == "fail":
        out.append(f"  {c['em_dashes']['count']} em dash(es), odd count so one is stray")
    for key, _ in clarity.WORD_CLASSES:
        if c[key]["verdict"] == "fail":
            out.append(f"  {clarity.LABELS[key].lower()}: "
                       f"{', '.join(c[key]['found'][:6])}")

    out.append(f"\n  clarity index {c['clarity_index']['value']}  (reported, not gated)")
    out.append("\n  NOT CHECKED, and these are the ones that matter:")
    out.append("    Does the recommendation follow from the situation?")
    out.append("    Are these the real options, or the ones easiest to write?")
    out.append("    Is that the true cost, or the one you can defend?")
    return "\n".join(out)


def main() -> int:
    argv = sys.argv
    as_json = "--json" in argv[1:]
    paths = clarity.paths_from(argv)
    if not paths:
        raw, source = sys.stdin.read(), "-"
    else:
        raw, error = clarity.read_one(paths[0])
        source = paths[0]
        if error:
            payload = {"source": source, "verdict": "unreadable", "exit": 2,
                       "error": error, "checks": {}}
            print(json.dumps(payload, indent=2) if as_json
                  else f"cannot read {source}: {error}")
            return 2
    result = analyse_brief(raw, source)
    print(json.dumps(result, indent=2) if as_json else render(result))
    return result["exit"]


# Exercised by tests/test_decision.py, which runs this as a hook would.
# In-process coverage cannot observe a child process, so the pragma records that
# the gap is in the instrument rather than in the tests.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
