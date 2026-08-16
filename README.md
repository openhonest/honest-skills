# Honest Skills

Most agent skills promise to make a model better at something. These make it
report what it cannot do.

- **`root-cause`** forbids a causal claim without evidence beside it, and keeps
  asking why until it reaches a design decision, a process gap, or something
  outside the system.
- **`sitrep`** puts the finding in the first sentence, bad news above good news,
  the confidence named per claim, and a gap named for anything unverified.
- **`decision-brief`** writes a request for a decision in five sections:
  background, current situation, options priced against what they buy, one
  recommendation, and the cost of doing nothing stated in figures.
- **`honest-code`** applies the same discipline to the code: no hidden state,
  no swallowed error, no implicit default. It delegates every mechanically
  decidable rule to a linter and names the three it cannot decide, rather than
  reporting a verdict it did not reach.
- **`tools/decision.py`** gates the form of a decision brief and refuses to
  judge its content, printing what it did not examine under every verdict.
- **`tools/clarity.py`** scores a draft, so the rules are a check rather than
  advice.
- **Three pre-commit hooks** run the same checks over your Markdown and your
  commit messages, and refuse to gate on anything a machine cannot judge.
- **A write-time hook** checks every file the moment an agent writes it, and
  says nothing at all when the file is fine.

Apache 2.0. No dependencies.

## The observation that produced this

Rules with an operation get followed. Rules stated as advice get lost.

An agent given "count the em dashes" obeyed for weeks. The same agent, given
"put the bottom line first," broke it repeatedly, because there was nothing to
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
and sentences over twenty words, plus the mechanical punctuation rules from the
AP Stylebook of 1960 that a regular expression can settle outright: a hyphen
after an -ly adverb, a comma or period left outside a closing quotation mark, a
comma before Jr. or an ampersand, and `week-end` for weekend.

Two AP rules are deliberately absent, and their absence is the same argument as
`first_sentence`. AP bans the comma before the final "and" in a series but keeps
it where both halves are full clauses, and telling those apart needs to parse
the sentence. AP also bans the comma before a roman-numeral suffix, and these
patterns ignore case, so `III` and `, I ran the query` are one string to the
check. Flagging the commonest pronoun in English to catch `John Jones, III` is a
trade no one would take. A check that flags correct prose gets turned off, and
it takes the checks that were worth having with it.

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
ran," which is the failure this project exists to name.

`first_sentence` returns `unassessed` with a reason. The checker prints your
opening line back because that is all it can honestly do; a machine cannot tell
a buried lead from a deliberate one. Most linters emit pass or fail only, so a
rule they cannot judge gets dropped or faked.

Exit codes separate the ways of failing. `0` every file clean, `1` one or more
failed a gate, `2` one or more could not be read. Worst wins, because a run that
could not read half its input has not passed, and a hook that collapsed those
would hide a broken setup behind a writing complaint.

## The unwritten-function hook

A function with an empty body is indistinguishable, from the caller's side,
from one that ran and had nothing to do. It returns `None`, the caller carries
on, and the first evidence that the work never happened arrives somewhere else
entirely. This finds those and asks for one line:

```python
def charge(card, amount):
    raise NotImplementedError("CODE NOT WRITTEN")
```

Each language gets its own idiom: `throw new Error`, `panic`, `todo!`,
`UnsupportedOperationException`, `NotImplementedException`.

**The wording is a suggestion, not a test.** What this requires is that the
function raise. A body containing any raise is not an empty body and is never
flagged, whatever the message says, so a project that standardises on its own
phrase is not fought. There was a file-level check for one exact marker, and it
was worse than useless: one correctly raising stub silenced every other stub in
the same file.

**A `Then` step that checks nothing is caught too, and it is the worse case.**
A stub returns `None` and something downstream eventually notices. A `Then`
step with no assertion publishes a pass, and the suite counts it. This finds a
`@then` whose body holds no `assert`, no `raise`, no `pytest.raises`, and no
call whose name says it checks. `Given` and `When` set things up and are left
alone; only `Then` is the assertion.

A step that calls a helper which asserts internally looks empty from here and
is not flagged as anything. That is a miss, and the errors fall that way on
purpose.

**Most of the work is not firing.** An empty body is correct more often than it
is a stub, and a hook that flags `@abstractmethod` is a hook nobody keeps.
Excluded by name: abstract methods, `Protocol` and `ABC` members, `@overload`
signatures, exception classes whose whole definition is `pass`, and anything
that already says `CODE NOT WRITTEN`. A `return 0` is a decision somebody made
and this cannot tell it from a placeholder, so it does not try.

**Python is parsed, the rest are matched, and the report says which.** `ast`
gives an exact answer and a syntax error becomes an honest silence rather than
a guess. Other languages get a narrow pattern over a header and an empty body,
which is approximate, and every such report says so. A reader who cannot tell a
parsed answer from a matched one cannot weigh it.

## The decision hook

A question that asks you to choose gets sent back to the model to be put as a
decision: background, current situation, options, recommendation, and the cost
of doing nothing. It fires on `Stop`, and only on `Stop`.

It used to block `AskUserQuestion` too, and that was a mistake worth recording.
A model writes the brief and calls the tool in one turn, so the brief is not a
completed message yet and is not in the transcript. The hook read the turn
before it, saw no brief, and rejected the call. Doing the right thing produced
the same rejection as doing the wrong thing, with no path through, and a live
session abandoned the widget and asked in plain text instead.

The rule it broke: judge only what you can see. It could not see the current
turn, so it could not know whether a brief had been written, and blocking on a
fact it had no access to is worse than not checking. Nothing is lost, because
when the turn ends the brief is in the transcript and `Stop` reads it there.

There is no hook that fires when a model asks a question in prose. `Stop` is the
only place to stand and it fires every turn, so nearly all of this hook is about
not firing.

**The costs are not symmetric.** Missing a decision question costs nothing: the
conversation carries on exactly as it would have. Blocking an ordinary question
costs a wasted turn and teaches you to switch the hook off, and a hook that is
switched off catches nothing. So it fires only when the words offer the reader
alternatives, and at most once for any one message.

Measured against a real 573-message session: it fired on 22, which is 3.8
percent, and all 22 were genuine requests to choose. "Which file did you mean?"
is not matched, because it asks you to identify something rather than to pick a
course of action.

Set `HONEST_HOOK_TRACE` to a file path and the hook records every turn it
runs, whether it fired or declined and why. Off by default, because a write on
every turn is churn nobody asked for. It exists because silence alone cannot
tell you the hook ran and correctly declined from the hook never running, which
is the same defect as a reported pass that was never performed.

The loop is the failure that would matter. Blocking on `Stop` produces a new
turn, which ends, which fires `Stop` again. The guard keys on the content of the
message rather than the turn, so reformatting gets you through and repeating
yourself does not. When the guard cannot be written to disk the hook stays
quiet, because a hook that cannot remember is a hook that repeats.

**What it refuses to decide** is whether a question deserves a brief. That is
intent, and intent is not readable from text. A genuine decision put in plain
words with no alternatives named passes straight through. That is a miss, and it
is the direction the errors are meant to fall in.

## Over MCP, for editors that are not Claude Code

`.mcp.json` declares a server exposing the same three checkers as MCP tools:
`check_decision_brief`, `check_prose` and `check_commit_message`. Installing
the plugin is the whole setup.

The hook and the server do different jobs. The hook fires whether or not the
agent cooperates, and it only reaches Claude Code. The server is deliberate,
answering "check this before I send it," and it reaches anything speaking MCP.

It is stdlib only, and that is a decision rather than an omission. It ships to
machines we do not control, every dependency is a thing that can be missing or
pinned wrong, and a checker that will not start is worse than no checker,
because the silence reads as a pass. JSON-RPC over stdio is a hundred lines.

It holds no analysis of its own. Every verdict comes from the three checkers,
called directly, and a test fails if a regular expression appears in the server
at all. Each reply leads with the verdict, then the report, then the JSON, so a
model acts on the first line and a client can still count the checks that were
never assessed.

## The write-time hook

Installing the plugin adds a `PostToolUse` hook. It runs after every Write and
Edit, and on a clean file it produces nothing: no tick, no summary, no line in
the transcript. When something is wrong it puts the finding in front of the
model that did the writing.

The silence is the design. A check that speaks on every write is noise, and
noise gets uninstalled inside a day, which is a worse outcome than never being
installed at all. The andon cord does not display a score to the worker; it is
silent, and then it is not.

### Why a hook rather than a tool the agent calls

An agent has no appetite for quality. It emits the most probable continuation.
An instruction to run a check is advice, and advice degrades over a long
session and gets skipped when inconvenient. Worse, an agent that stops calling
produces no output, so the silence reads as health.

A hook fires whether or not the agent cooperates. That is the whole point: it
turns the check from something the agent might remember into a step in the loop.

### What it checks, and what it refuses to

Two checks run with no dependency at all: whether the file has passed a thousand
lines, and trailing-whitespace density against the Slop Audit's published band.
Both are exact and neither has a rival implementation to disagree with.

For the mutable-state ratio it shells out to `slop-audit-l1` if that is
installed. **It does not implement the ratio itself.** The authoritative
definition lives in the Honest Framework with its bound-literal amendment, and a
second implementation under the same name is how two tools come to disagree
while both claim the standard. There is a test that fails if anyone adds
`import ast` to the hook.

### An absence is not a finding about your file

The first version announced the missing analyzer as a finding, so a clean file
produced `1 finding(s) in t.py` when there was nothing in t.py at all. The hook
was reporting on itself and labelling the report as an observation of your code.
Every new install met that on its first write, because nobody has the analyzer.

The rule that replaced it: an absence is worth saying only alongside a presence.
So a report leads with its coverage,

```
honest-code: 2 of 3 checks ran on big.py
  OUT_OF_SPEC  L1.17  1001 lines, over the 1000-line threshold
      split it, or accept it deliberately
  NOT_RUN      L1.18  slop-audit-l1 is not on PATH
      this file was not checked for mutable-state ratio
```

and when nothing surfaced there is no list to be incomplete about, so the hook
says nothing at all.

Silence is not a pass and never claims to be. Nothing here prints a tick, a
score, or the word clean, and a test scans the rendered output to keep it that
way. What keeps the silence honest is the coverage line: you cannot read a
finding from this tool without also reading what it did not examine.

This is not the Slop Audit. It is the part of it that means anything for one
file at one moment, which is four indicators out of twenty. Run the full audit
on a repository; run this while you write.

## As pre-commit hooks

```yaml
repos:
  - repo: https://github.com/openhonest/honest-skills
    rev: v0.2.0
    hooks:
      - id: honest-prose         # every staged Markdown file
      - id: honest-commit-msg    # the commit message itself
      - id: honest-skill-check   # SKILL.md files only
```

Pin a tag or a commit, not `main`. pre-commit caches a clone by its `rev`
string, so a branch name keeps serving whatever it fetched the first time and
never picks up a change. `pre-commit autoupdate` moves the pin for you.

`honest-commit-msg` needs the commit-msg stage installed, which pre-commit does
not do by default:

```bash
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

The hooks gate on what a machine can judge outright: stray em dashes, hedging
adverbs, intensifiers, deferring phrases, and an index outside the band. They
report heading count, long sentences and your opening line without failing on
them, because a machine cannot tell a deliberate long sentence from a careless
one. A hook that fails a judgement call gets disabled, and it takes the checks
that were worth having with it.

The commit-message hook does not apply the clarity index. A dozen-word subject
is too small a sample for it, so the number would look like a measurement and
be arithmetic on noise. It checks the subject length, the blank line after it,
and the same word classes, then prints the subject back and asks whether it says
what changed. Nothing can check that for you, and saying so is the point.

gitlint and commitizen already check commit syntax, prefix and imperative mood.
Run them alongside; they cover different ground.

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
run it" from "we could not run it here." Current results on a prepared clone:

```
L1.18   0 of 18 functions reference external mutable state
L1.18b  resolvable fraction 1.0
L1.19   72 of 72 decision branches exercised
L1.20   5 of 5 randomized-order runs passed
```

Both tools are at 100% branch coverage. The `__main__` guard carries a
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
