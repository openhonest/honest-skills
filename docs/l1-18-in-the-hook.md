# Implementing L1.18 in the hook

**Status: waiting.** Approved by Adam on 2026-08-15, blocked on a change landing in the Slop Audit analyzer the same day. Build after it lands, not before.

## Why the hook delegates today

`hooks/edit_check.py` shells out to `slop-audit-l1` for the mutable-state ratio and reports `UNMEASURED` when that analyzer is absent. It does not implement the ratio itself, because a second implementation under one name is how two tools come to disagree while both claim the standard. `tests/test_edit_check.py` fails if anyone adds `import ast` to the hook.

The cost of that choice is real: on a bare plugin install nobody has the analyzer, so the most useful of the four indicators never runs. Closing that gap is what this note is about.

## Why a second implementation is legitimate here

The Slop Audit already has two implementations, the Python reference and the Rust port, and it keeps them honest with differential testing rather than trust. `tools/slop-audit-rs/validate.py` runs both on the same real repository, diffs every indicator, and exits 1 on any difference. Its standing rule: no indicator lands until it is validated equal to `l1_analyzer` on real repos.

A third implementation gated by the same validator is that discipline applied again. Equivalence is tested, not asserted.

The Gherkin suite in Paper A does not serve here. Its 188 scenarios test the internals of the tree-sitter implementation, calling functions that take tree-sitter nodes, so they are unit tests of that implementation rather than portable vectors.

## What the implementation has to do

Confirmed with the Slop Audit maintainer on 2026-08-15. Three things, not one:

1. **The ratio.**
2. **A census denominator produced independently of its own enumerator.** The independence required is between two *enumeration rules*, not two parsers. Sharing one `ast` tree between two independent walks satisfies it; sharing a walk does not. A shared enumerator is a shared blind spot, which is the defect the census exists to detect.
3. **The refusal rule.** Refuse to grade when nothing declared is of a kind the enumerator has a rule capable of matching, *and* nothing was admitted. Keeping the second clause is what makes it a one-way relaxation, so nothing can move from graded to refused.

**Capability must be measured, not declared.** A fixture per language and per declaration kind, run through the real enumerator, failing when the recorded answer and the measured answer disagree. An asserted table rots into the blind spot it exists to detect; five asserted enumerations produced confident wrong answers in that repository in one week.

## Two properties of `ast` that favour it

`ast.parse` raises on a syntax error where tree-sitter returns a partial tree. A `PostToolUse` hook sees broken files constantly, because an agent mid-edit leaves them that way, and raising makes the right answer trivial: `UNMEASURED`, loudly, with no partial reading to be tempted by. The tree-sitter implementation needed a new `unread` verdict precisely because an ERROR-bearing tree looked identical to clean code.

`ast` is Python only. The authoritative implementation covers nine languages. A stdlib single-file hook serves one honestly and reports `UNMEASURED` for the rest rather than guessing, which is the apophatic rule working in our favour rather than against us.

## Why it is blocked

A change landing 2026-08-15 teaches the classifier three declaration kinds it has no rule for, and it moves published numbers hard. Between the committed tree and the working tree minutes apart, one repository went from 466 declared with 216 unreadable to 512 declared with none unreadable. C and C# move much further: libuv had 1,133 of 1,345 declarations unreadable, Newtonsoft.Json 678 of 1,360.

Grades will fall. A repository whose struct fields were 84 percent invisible was not passing, it was unexamined.

Building before that lands means validating against numbers that will not exist afterwards.

## Known defect to avoid inheriting

`L1.18b`'s `basis` field reads `None` on a graded repository where it should read `measured` or `unread`. Reported by the maintainer on 2026-08-15 and unfixed at the time of writing. Do not read `basis` until it is confirmed working.

`L1.18` itself is unchanged: `value`, `band`, `details`. The hook's current read of `results["L1.18"]["band"]` is correct against the analyzer as it stands.

## Build order when unblocked

1. Confirm the analyzer change has landed and its numbers have stopped moving.
2. Write the two independent walks and the refusal rule.
3. Write the capability fixtures, one per declaration kind, measured rather than asserted.
4. Write the differential validator, modelled on `validate.py`, over a fixture corpus.
5. Make the validator a hard CI gate before the implementation is wired into the hook.
6. Delete the `import ast` guard test only when steps 3 and 4 are green, and replace it with a test asserting the validator runs.
