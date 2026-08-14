#!/usr/bin/env python3
"""Score a draft for readability, so "measure it" stops depending on
anyone remembering to.

    uv run tools/clarity.py draft.md
    uv run tools/clarity.py --json draft.md doc.md   # any number of files
    pbpaste | uv run tools/clarity.py

Reports the clarity index (DA Pam 600-67, para 4-3) and every mechanical defect
the standard names: stray em dashes, deferring phrases, hedging adverbs,
intensifiers, and sentences too long to read once. Every rule here would be
worth following in a world with no language models; anything that fails that
test does not belong in this tool. Exits 1 when the index falls
outside 20 to 40, so it can gate a hook.

Exit codes: 0 every file in band, 1 one or more out of band, 2 one or more
could not be read. Worst wins, because a run that could not read half its input
has not passed.

Stdlib only, on purpose. This runs before sending a message, and a tool that
needs an install is a tool that gets skipped at the moment it is wanted.

analyse() is a pure function returning a result dict; the renderers read that
dict and print. Nothing computes while it prints, which is what makes the two
output formats one measurement rather than two implementations of it.
"""
from __future__ import annotations

import json
import re
import sys

VOWELS = "aeiouy"
BAND = (20, 40)
AIM = 30
SENTENCE_LIMIT = 20
HEADING_LIMIT = 2

# Which checks decide the exit code. A gate may only rest on what a machine can
# judge outright. Heading count and sentence length are judgement calls: a long
# sentence can be right and a fourth heading can be earned, so they are reported
# and do not fail the run. first_sentence is unassessable by construction.
GATING = ("em_dashes", "hedges", "intensifiers", "tells", "ap_mechanics")

# Adverbs that assert a confidence the evidence has not earned. Named separately
# from intensifiers because this group is a truthfulness problem, not a style
# one: a project that judges others for overclaiming cannot write "clearly".
HEDGES = ("clearly", "obviously", "certainly", "undoubtedly", "arguably",
          "essentially", "basically", "fundamentally", "notably", "importantly")
INTENSIFIERS = ("very", "really", "quite", "extremely", "incredibly",
                "significantly", "substantially", "highly", "vastly", "utterly")
# Filler that announces a point instead of making it.
TELLS = (r"the (honest|useful|interesting|real|hard|important|key) part\b",
         r"this is the part", r"here is the part", r"load-bearing",
         r"\bit'?s not (just )?about\b", r"\bnot only\b.{0,40}\bbut also\b")

# Mechanical punctuation from the AP Stylebook, 1960, the first joint AP/UPI
# edition. Only the rules a regular expression can settle outright are here.
#
# AP's serial-comma rule is deliberately absent. It bans the comma before the
# final "and" in a list, but keeps it where both halves are full clauses, and
# telling those apart needs to parse the sentence. A check that guesses would
# flag correct prose, and a check that flags correct prose gets turned off.
AP_MECHANICS = (
    # 3.31: never hyphenate an adverb ending in -ly. "badly damaged", not
    # "badly-damaged". The one hyphen rule with no exceptions.
    r"\b\w+ly-\w+",
    # 3.24: the comma and the period always go inside the quotation marks.
    r"[\"”][,.]",
    # 3.21: no comma before Jr., Sr., or an ampersand. AP bans it before a
    # roman numeral too, and that half is left out: these patterns are matched
    # without regard to case, so "III" and ", I ran the query" are the same
    # string to the check. Flagging the commonest pronoun in English to catch
    # "John Jones, III" is a trade no one would take.
    r",\s+(Jr\.|Sr\.|&\s)",
    # AP sets these solid.
    r"\b(week-end|world-wide|nation-wide)\b",
)

WORD_CLASSES = (
    ("hedges", [rf"\b{h}\b" for h in HEDGES]),
    ("intensifiers", [rf"\b{i}\b" for i in INTENSIFIERS]),
    ("tells", list(TELLS)),
    ("ap_mechanics", list(AP_MECHANICS)),
)
LABELS = {"hedges": "HEDGES", "intensifiers": "INTENSIFIERS",
          "tells": "AI TELLS", "ap_mechanics": "AP PUNCTUATION"}


def syllables(word: str) -> int:
    w = word.lower()
    count, prev_vowel = 0, False
    for ch in w:
        is_vowel = ch in VOWELS
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if w.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)


def strip_furniture(text: str) -> str:
    """Drop what the index should not judge.

    Code blocks, tables, headings and URLs are not prose. Counting them drags
    the average sentence length and the long-word share toward noise, and a
    report full of measurements would score as unreadable for carrying its own
    evidence.
    """
    # YAML frontmatter, at the top only. A skill file opens with its metadata,
    # so without this the tool reports "name: sitrep" back as your first
    # sentence, which is the check it exists to make.
    text = re.sub(r"\A---\n[\s\S]*?\n---\n", " ", text)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # Headings are furniture too. Left in, "## Length" counts as a one-word
    # sentence and drags the average down, so a document with many headings
    # scores falsely low and reads as too abrupt when its prose is fine. Found
    # by running this tool on the skill file that ships beside it. Heading COUNT
    # is still checked, separately, in analyse().
    text = re.sub(r"^\s*#{1,6} .*$", " ", text, flags=re.M)
    text = re.sub(r"^\s*\|.*\|\s*$", " ", text, flags=re.M)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    return text


def sentences_of(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", text.strip())
    return [p.strip() for p in parts if len(re.findall(r"[A-Za-z]", p)) > 1]


def scan(pattern: str, text: str) -> list[str]:
    return [m.group(0) for m in re.finditer(pattern, text, re.I)]


def words_in(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'\-]*", text)


def analyse(raw: str, source: str = "-") -> dict:
    """Measure a draft. Pure: no printing, no exit, no file access.

    Every check appears in the result whether it passed or failed. Omitting a
    passing check saves bytes and costs a consumer the ability to tell "passed"
    from "never ran", which is the failure this project exists to name.
    """
    prose = strip_furniture(raw)
    sents = sentences_of(prose)
    words = words_in(prose)
    if not sents or not words:
        return {"source": source, "verdict": "nothing_to_measure",
                "exit": 0, "index": None,
                "counts": {"sentences": 0, "words": 0, "long_words": 0},
                "measures": {}, "checks": {}}

    long_words = [w for w in words if syllables(w) >= 3]
    asl = len(words) / len(sents)
    pct = len(long_words) / len(words) * 100
    index = asl + pct
    verdict = ("too_abrupt" if index < BAND[0] else
               "too_hard" if index > BAND[1] else "in_band")

    heads = [h.strip() for h in re.findall(r"^#{1,6} .+$", raw, flags=re.M)]
    longs = [{"words": len(words_in(s)), "text": s}
             for s in sents if len(words_in(s)) > SENTENCE_LIMIT]
    dashes = raw.count("—")

    checks = {
        # The one check this tool cannot make. It prints the sentence back and
        # says so, rather than dropping the rule or inventing a verdict for it.
        "first_sentence": {
            "verdict": "unassessed",
            "text": sents[0],
            "reason": "a machine cannot tell a buried lead from a deliberate one",
        },
        "headings": {
            "verdict": "fail" if len(heads) > HEADING_LIMIT else "pass",
            "count": len(heads), "limit": HEADING_LIMIT, "found": heads,
        },
        "long_sentences": {
            "verdict": "fail" if longs else "pass",
            "count": len(longs), "limit": SENTENCE_LIMIT, "found": longs,
        },
        # A pair of em dashes is sanctioned; an odd count means one is stray.
        "em_dashes": {
            "verdict": "fail" if dashes % 2 else "pass",
            "count": dashes,
            "reason": ("odd count, so one is stray" if dashes % 2
                       else "even count, check they are paired"),
        },
    }
    for key, pats in WORD_CLASSES:
        hits = [h for p in pats for h in scan(p, prose)]
        checks[key] = {"verdict": "fail" if hits else "pass",
                       "count": len(hits), "found": sorted(set(hits))}
    for key, check in checks.items():
        check["gating"] = key in GATING

    # A document can sit in the band and still be full of hedges. Reading the
    # index alone let that pass, which made the gate report a pass it had not
    # established.
    failed = [k for k in GATING if checks[k]["verdict"] == "fail"]
    return {
        "source": source,
        "verdict": verdict,
        "exit": 0 if verdict == "in_band" and not failed else 1,
        "gating_failures": failed,
        "index": {"value": round(index, 1), "aim": AIM, "band": list(BAND)},
        "counts": {"sentences": len(sents), "words": len(words),
                   "long_words": len(long_words)},
        "measures": {"avg_sentence_words": round(asl, 1),
                     "long_word_pct": round(pct, 1)},
        "checks": checks,
    }


def render_text(r: dict) -> str:
    if r["verdict"] == "nothing_to_measure":
        return "nothing to measure"
    said = {"too_abrupt": "TOO ABRUPT, you have cut meaning out",
            "too_hard": "TOO HARD to read in one pass",
            "in_band": "in band"}[r["verdict"]]
    out = [f"clarity index  {r['index']['value']:5.1f}   "
           f"aim {AIM}, band {BAND[0]}-{BAND[1]}   {said}",
           f"  sentences    {r['counts']['sentences']:5}",
           f"  avg sentence {r['measures']['avg_sentence_words']:5.1f} words     target 15",
           f"  long words   {r['measures']['long_word_pct']:5.1f}%          target 15%"]

    c = r["checks"]
    # Structure is what gets broken, so it is reported first and loudest.
    if c["headings"]["verdict"] == "fail":
        out.append(f"\nSTRUCTURE  {c['headings']['count']} headings. More than "
                   f"{HEADING_LIMIT} on one change is performing thoroughness.")
        out += [f"    {h[:70]}" for h in c["headings"]["found"]]

    out.append(f"\nFIRST SENTENCE  {c['first_sentence']['text'][:88]}")
    out.append("    Does it carry the recommendation or the finding? If not, cut above it.")

    if c["long_sentences"]["verdict"] == "fail":
        out.append(f"\nOVER {SENTENCE_LIMIT} WORDS  {c['long_sentences']['count']}")
        out += [f"    {s['words']:3}  {s['text'][:80]}"
                for s in c["long_sentences"]["found"][:5]]

    if c["em_dashes"]["count"]:
        state = ("stray, fix it" if c["em_dashes"]["verdict"] == "fail"
                 else "check they are paired")
        out.append(f"\nEM DASHES  {c['em_dashes']['count']}   {state}")

    for key, _ in WORD_CLASSES:
        if c[key]["verdict"] == "fail":
            out.append(f"\n{LABELS[key]}  {c[key]['count']}   "
                       f"{', '.join(c[key]['found'][:8])}")
    return "\n".join(out)


def paths_from(argv: list[str]) -> list[str]:
    """Every non-flag argument. A pre-commit hook passes all staged files at
    once, so taking only the first would pass a commit on the strength of its
    tidiest file."""
    return [a for a in argv[1:] if not a.startswith("-")]


def read_one(path: str) -> tuple[str | None, str | None]:
    """Return (text, error). Never raises on a bad path.

    A traceback is a fine way to fail at a prompt and a poor way to fail inside
    a hook, where the calling tool sees a crash instead of a verdict.
    """
    try:
        with open(path) as fh:
            return fh.read(), None
    except OSError as e:
        return None, f"{type(e).__name__}: {e}"


def unreadable(source: str, error: str) -> dict:
    # Exit 2, not 1. A caller must be able to tell "this draft is bad" from "I
    # could not read the draft"; collapsing them hides a broken setup behind a
    # writing complaint.
    return {"source": source, "verdict": "unreadable", "exit": 2,
            "error": error, "index": None,
            "counts": {}, "measures": {}, "checks": {}}


def analyse_paths(paths: list[str], stdin_text: str | None = None) -> dict:
    """Measure every path given, or stdin when none is.

    The shape does not change with the number of files. A consumer should never
    have to branch on how many arguments it happened to pass, so one file still
    arrives as a list of one.
    """
    if not paths:
        files = [analyse(stdin_text or "", "-")]
    else:
        files = []
        for path in paths:
            text, error = read_one(path)
            files.append(unreadable(path, error) if error else analyse(text, path))
    # Worst result wins: unreadable beats out-of-band beats clean. A run that
    # could not read half its input has not passed.
    worst = max(f["exit"] for f in files)
    return {
        "schema": 2,
        "verdict": {0: "pass", 1: "fail", 2: "unreadable"}[worst],
        "exit": worst,
        "counts": {"files": len(files),
                   "passed": sum(1 for f in files if f["exit"] == 0),
                   "failed": sum(1 for f in files if f["exit"] == 1),
                   "unreadable": sum(1 for f in files if f["exit"] == 2)},
        "files": files,
    }


def render_run(run: dict) -> str:
    out = []
    many = run["counts"]["files"] > 1
    for f in run["files"]:
        if f["verdict"] == "unreadable":
            out.append(f"cannot read {f['source']}: {f['error']}")
            continue
        if many:
            out.append(f"\n=== {f['source']}")
        out.append(render_text(f))
    if many:
        # "out of band" named only one of the two ways to fail, so a file that
        # scored 26 and failed four word checks was reported as unreadable
        # prose. The summary now says which gate refused, not which one it
        # happened to check first.
        c = run["counts"]
        out.append(f"\n{c['files']} files: {c['passed']} clean, "
                   f"{c['failed']} failed a gate, {c['unreadable']} unreadable")
    return "\n".join(out)


def main() -> int:
    argv = sys.argv
    as_json = "--json" in argv[1:]
    paths = paths_from(argv)
    run = analyse_paths(paths, None if paths else sys.stdin.read())
    print(json.dumps(run, indent=2) if as_json else render_run(run))
    return run["exit"]


# The tests in tests/test_clarity.py DO exercise this, by running the script
# as a shell or a pre-commit hook would. In-process coverage cannot see a
# child process, so it reports the branch as missed. The pragma records that
# the gap is in the instrument, not in the tests.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
