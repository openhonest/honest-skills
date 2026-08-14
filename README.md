# Honest Skills

Most agent skills promise to make a model better at something. These make it
report what it cannot do.

- **`root-cause`** forbids a causal claim without evidence beside it, and keeps
  asking why until it reaches a design decision, a process gap, or something
  outside the system.
- **`sitrep`** puts the finding in the first sentence, bad news above good news,
  the confidence named per claim, and a gap named for anything unverified.
- **`tools/clarity.py`** scores a draft, so the rules are a check rather than
  advice.

Apache 2.0. No dependencies.

## The observation that produced this

Rules with an operation get followed. Rules stated as advice get lost.

An agent given "count the em dashes" obeyed for weeks. The same agent, given
"put the bottom line first", broke it repeatedly, because there was nothing to
run. It wrote a five-section report whose second sentence was its own debugging
noise and whose admission of error sat fourth.

That is why these ship as a script and a set of checks rather than as a style
guide. It rests on one operator watching one agent over several weeks. It is not
a study and is not offered as one.

## Install

Add the marketplace, then install the plugin:

```
/plugin marketplace add openhonest/honest-skills
/plugin install honest-skills
```

Or copy a skill directory into your own `skills/` folder. They are plain
Markdown with frontmatter and depend on nothing.

## The checker

```bash
uv run tools/clarity.py draft.md      # or pipe on stdin
```

```
clarity index   25.6   aim 30, band 20-40   in band
  sentences       30
  avg sentence  11.8 words     target 15
  long words    13.8%          target 15%

FIRST SENTENCE  Fixed and live.
    Does it carry the recommendation or the finding? If not, cut above it.
```

That output is real. It is the report described above, and the first-sentence
line is what identified the fault in seconds.

It also flags stray em dashes, hedging adverbs, intensifiers, stacked headings
and sentences over twenty words.

Any number of files can be given, which is what a pre-commit hook passes:

```bash
uv run tools/clarity.py --json draft.md notes.md README.md
```

```json
{
  "schema": 2,
  "verdict": "fail",
  "exit": 1,
  "counts": {"files": 3, "passed": 2, "failed": 1, "unreadable": 0},
  "files": [
    {
      "source": "draft.md",
      "verdict": "in_band",
      "exit": 0,
      "index": {"value": 23.1, "aim": 30, "band": [20, 40]},
      "checks": {
        "first_sentence": {"verdict": "unassessed",
                           "text": "BLUF: the homepage carried no links.",
                           "reason": "a machine cannot tell a buried lead from a deliberate one"},
        "headings": {"verdict": "fail", "count": 8, "limit": 2, "found": ["..."]},
        "em_dashes": {"verdict": "pass", "count": 0}
      }
    }
  ]
}
```

Four things about that format are deliberate.

The shape never changes with the number of files. One file still arrives as a
list of one, so a consumer never branches on how many arguments it happened to
pass.

Every check is present whether it passed or failed. Dropping a passing check
would save bytes and cost a consumer the ability to tell "passed" from "never
ran", which is the failure this project exists to name.

`first_sentence` returns `unassessed` with a reason. The checker prints your
opening line back because that is all it can honestly do; a machine cannot tell
a buried lead from a deliberate one. Most linters emit pass or fail only, so a
rule they cannot judge gets dropped or faked.

Exit codes separate the ways of failing. `0` every file in band, `1` one or more
out of band, `2` one or more could not be read. Worst wins, because a run that
could not read half its input has not passed, and a hook that collapsed those
would hide a broken setup behind a writing complaint.

## Running the tests, and why the venv matters

```bash
uv venv .venv
uv pip install --python .venv/bin/python pytest pytest-randomly coverage
.venv/bin/python -m pytest tests/ -q
```

The virtual environment is not committed, so a fresh clone has none. That is
worth knowing because of what depends on it.

This repository is audited with the [Slop Audit](https://slopaudit.org) L1
analyzer, which measures whether code can be exhaustively verified. Two of its
indicators need to execute the test suite rather than read it:

| indicator | what it measures | needs |
|---|---|---|
| L1.18 | state that can grow without limit | reading the code |
| L1.19 | decision branches the tests actually exercise | running the suite |
| L1.20 | whether the suite passes in a randomized order | `pytest-randomly` |

Without a venv holding pytest, L1.19 and L1.20 report `No data`. That is not the
same as reporting zero, and the analyzer says so: it distinguishes "we did not
run it" from "we could not run it here". Current results on a prepared clone:

```
L1.18   0 of 5 functions reference external mutable state
L1.18b  resolvable fraction 1.0
L1.19   26 of 26 decision branches exercised
L1.20   5 of 5 randomized-order runs passed
```

`tools/clarity.py` is at 100% branch coverage. The `__main__` guard carries a
no-cover pragma with the reason written beside it: the tests do exercise it, by
running the script the way a shell or a hook does, but in-process coverage
cannot observe a child process. The pragma records that the gap is in the
instrument rather than in the tests.

## These are readability rules, not AI-detection rules

The bans on hedges and deferring phrases resemble the tells people cite when
accusing a text of being machine-written. They are not that, and the difference
is checkable rather than a matter of opinion.

The clarity index comes from DA Pam 600-67, *Effective Writing for Army
Leaders*, 1986: average sentence length plus the percentage of words of three or
more syllables. Robert Gunning's Fog Index, 1952, is 0.4 times the same sum. The
Army index is Gunning's formula with the scaling dropped. An index of 30 is a Fog
of 12, the reading level of a high-school senior.

The test for including any rule here: would it still be worth following in a
world with no language models at all? Every rule passes. Any rule that fails
should be removed, and a pull request saying so is welcome.

Full argument in [docs/WHY-NOT-AN-AI-DETECTOR.md](docs/WHY-NOT-AN-AI-DETECTOR.md).

## What this does not claim

Nothing here has been tested against anyone other than its author. The rules are
old and well evidenced; the claim that packaging them as operations changes agent
behaviour is one person's observation. Treat the second as a hypothesis.

## From the Open Honest Foundation

<https://openhonest.org>. The Foundation also publishes the Honest Framework, an
architectural standard, and the Slop Audit, a measure of whether a codebase can
be exhaustively verified rather than merely tested.
