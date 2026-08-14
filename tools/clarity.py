#!/usr/bin/env python3
"""Score a draft for readability, so "measure it" stops depending on
anyone remembering to.

    uv run tools/clarity.py draft.md
    pbpaste | uv run tools/clarity.py

Reports the clarity index (DA Pam 600-67, para 4-3) and every mechanical defect
the standard names: stray em dashes, banned AI tells, hedging adverbs,
intensifiers, and sentences too long to read once. Exits 1 when the index falls
outside 20 to 40, so it can gate a hook.

Stdlib only, on purpose. This runs before sending a message, and a tool that
needs an install is a tool that gets skipped at the moment it is wanted.
"""
from __future__ import annotations

import re
import sys

VOWELS = "aeiouy"

# Adverbs that assert a confidence the evidence has not earned. Named separately
# from intensifiers because this group is a truthfulness problem, not a style
# one: an account that gives an award for not overclaiming cannot write
# "clearly" in its own posts.
HEDGES = ("clearly", "obviously", "certainly", "undoubtedly", "arguably",
          "essentially", "basically", "fundamentally", "notably", "importantly")
INTENSIFIERS = ("very", "really", "quite", "extremely", "incredibly",
                "significantly", "substantially", "highly", "vastly", "utterly")
# Filler that announces a point instead of making it.
TELLS = (r"the (honest|useful|interesting|real|hard|important|key) part\b",
         r"this is the part", r"here is the part", r"load-bearing",
         r"\bit'?s not (just )?about\b", r"\bnot only\b.{0,40}\bbut also\b")
BANNED_WORDS = (r"\bmove[sd]?\b", r"\bmoving\b", r"\bsharp(ly|er|en)?\b",
                r"\brare\b")


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

    Code blocks, tables and URLs are not prose. Counting them drags the average
    sentence length and the long-word share toward noise, and a report full of
    measurements would score as unreadable for containing its evidence.
    """
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"^\s*\|.*\|\s*$", " ", text, flags=re.M)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    return text


def sentences_of(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", text.strip())
    return [p.strip() for p in parts if len(re.findall(r"[A-Za-z]", p)) > 1]


def scan(pattern: str, text: str) -> list[str]:
    return [m.group(0) for m in re.finditer(pattern, text, re.I)]


def main() -> int:
    raw = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
    prose = strip_furniture(raw)
    sents = sentences_of(prose)
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", prose)
    if not sents or not words:
        print("nothing to measure")
        return 0

    long_words = [w for w in words if syllables(w) >= 3]
    asl = len(words) / len(sents)
    pct = len(long_words) / len(words) * 100
    index = asl + pct

    verdict = ("TOO ABRUPT, you have cut meaning out" if index < 20 else
               "TOO HARD to read in one pass" if index > 40 else "in band")
    print(f"clarity index  {index:5.1f}   aim 30, band 20-40   {verdict}")
    print(f"  sentences    {len(sents):5}")
    print(f"  avg sentence {asl:5.1f} words     target 15")
    print(f"  long words   {pct:5.1f}%          target 15%")

    # Structure is what gets broken, so it is checked first and loudest.
    heads = re.findall(r"^#{1,6} .+$", raw, flags=re.M)
    if len(heads) > 2:
        print(f"\nSTRUCTURE  {len(heads)} headings. More than two on one change "
              f"is performing thoroughness.")
        for h in heads:
            print(f"    {h.strip()[:70]}")

    first = sents[0]
    print(f"\nFIRST SENTENCE  {first[:88]}")
    print("    Does it carry the recommendation or the finding? If not, cut above it.")

    longs = [s for s in sents
             if len(re.findall(r"[A-Za-z][A-Za-z'\-]*", s)) > 20]
    if longs:
        print(f"\nOVER 20 WORDS  {len(longs)}")
        for s in longs[:5]:
            n = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", s))
            print(f"    {n:3}  {s[:80]}")

    # A pair of em dashes is sanctioned; an odd count means one is stray.
    dashes = raw.count("—")
    if dashes:
        state = "stray, fix it" if dashes % 2 else "check they are paired"
        print(f"\nEM DASHES  {dashes}   {state}")

    for label, pats in (("HEDGES", [rf"\b{h}\b" for h in HEDGES]),
                        ("INTENSIFIERS", [rf"\b{i}\b" for i in INTENSIFIERS]),
                        ("AI TELLS", list(TELLS)),
                        ("BANNED WORDS", list(BANNED_WORDS))):
        hits: list[str] = []
        for p in pats:
            hits += scan(p, prose)
        if hits:
            print(f"\n{label}  {len(hits)}   {', '.join(sorted(set(hits))[:8])}")

    return 0 if 20 <= index <= 40 else 1


if __name__ == "__main__":
    raise SystemExit(main())
