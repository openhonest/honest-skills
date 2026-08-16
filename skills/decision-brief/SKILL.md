---
name: decision-brief
description: Write a request for a decision the way you would brief an executive. Five sections in a fixed order, options priced against what they buy, and the cost of doing nothing stated in numbers. Use when asking anyone to choose, approve, fund, or authorise something. Checked by tools/decision.py.
---

# Decision brief

You are asking someone to decide. They will read until they can decide and then stop.

## It goes in the reply

**Write the brief as your message. Do not write it to a file unless you were asked for a file.**

This is the failure this skill produced on its first real use. Asked to brief two open decisions, it wrote a 43-line document to `decisions/`, then spent four turns adjusting the column widths of a table nobody had seen, and the person waiting for an answer got a filename. The document was deleted and the question was asked again.

A brief is a message. The reader is in the conversation, the decision is blocking them now, and a file is one more thing to open. If you find yourself creating a directory for this, you have already lost the reader.

**One decision, one brief.** Two open questions means two briefs in the same reply, or one brief whose options are numbered across both. Never one brief that answers whichever question was easiest to write up.

**Never spend a turn on formatting.** If a table will not fit in 80 columns, write the options as a list instead. Rebuilding a table is work the reader never sees and never asked for.

Five sections, this order:

```
Background            what they need to know and do not
Current situation     what is true now, and why it forces a choice
Options               each with what it costs and what it buys
Recommendation        one course of action, named
Cost of no action     what happens if they do nothing
```

Check it before you send it. The checker reads stdin, so the brief never has to touch disk:

```sh
uv run tools/decision.py <<'BRIEF'
Recommendation: ...
BRIEF
```

It gates the form and refuses to judge the content, which is the division that matters: the checker cannot tell whether your recommendation follows, and it says so every time rather than letting you assume it approved.

## The two rules people break

**The recommendation goes above the reasoning, not below it.** A reader who has enough at paragraph two stops at paragraph two. Everything under the point where they stopped might as well be unwritten, so a recommendation at the bottom is a recommendation nobody read. Background earns exactly the space needed to make the situation legible and not one sentence more. The checker fails a brief whose background runs past 40 percent.

**Doing nothing is an option and it wins by default.** It needs no decision, no meeting, and no approval, so it happens whenever nobody acts. A brief that does not price it has quietly left out the outcome most likely to occur. Price it in figures: days, dollars, a percentage, a count. The checker fails a cost of no action with no quantity in it.

## Writing each section

**Background.** What they cannot decide without, and nothing else. If they already know it, cut it. If it does not change the choice, cut it. Two or three sentences is usually right; a page is a sign you are writing to prove you did the work.

**Current situation.** State what is true now and why that forces a choice today rather than next month. Carry the numbers here: what changed, how much, measured how. This is where evidence lives, so a claim without its evidence beside it belongs nowhere in the brief.

**Options.** At least two. One option is a notification, not a decision, and presenting one option while calling it a decision is how consent gets manufactured. Give each option what it costs and what it buys, side by side, and include the option you are not recommending in its strongest honest form. An option written weakly is not an option, it is scenery.

Keep the table under 80 columns. Past that it wraps in a terminal, a chat pane, and a quoted mail reply, and the cells interleave into nonsense. A real brief arrived shredded this way on 2026-08-15, with its cost column landing inside the wrong row.

**Recommendation.** One course of action, named, in under 60 words. Say what to do, then in one clause say what it costs you to be wrong. A recommendation that needs a page is two recommendations or none.

**Cost of no action.** What happens between now and whenever they get to it. In numbers.

## What the checker will not do for you

Three things decide whether the brief is any good, and the checker reports all three as unassessed every single time:

- Does the recommendation follow from the situation, or merely sit after it?
- Are these the real options, or the three easiest to write?
- Is that the true cost, or the one you can defend?

Nothing automates those. The checker names them so their absence stays visible rather than being assumed away by a green tick.

## The failure this form prevents

A brief that buries the ask, prices no alternative, and never states what happens if the reader ignores it is not a decision request. It is a status update wearing one, and the reader is being asked to reconstruct the decision themselves from material arranged for the writer's convenience.

Structural completeness is not agreement. A brief can pass every check here and still recommend the wrong thing, which is why the checker prints what it did not examine underneath every verdict it did reach.
