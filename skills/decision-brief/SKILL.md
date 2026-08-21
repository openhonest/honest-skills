---
name: decision-brief
description: Write a request for a decision the way you would brief an executive. Five sections in a fixed order, options priced against what they buy, and the cost of doing nothing stated in numbers. Use when asking anyone to choose, approve, fund, or authorise something. Checked by tools/decision.py.
---

# Decision brief

You are asking someone to decide. They will read until they can decide and then stop.

## Do not write one when there is only one answer

**If the evidence points one way, say what you found, say what you are doing, and do it. Do not manufacture alternatives so a form can be filled in.**

This is the failure that matters most, and it happened on 2026-08-16. A session measured a defect, found one sound fix, and produced a brief with four options because the shape asked for options. Three of them were scenery. Adam's reply: *"Stop it with this empty ritual. There is only one answer and you know what it is."* He was right, and the session had known it before writing option B.

Presenting one option and calling it a decision is how consent gets manufactured. Presenting four when there is one is how a decision gets faked, and it is worse, because it spends the reader's attention on alternatives the writer had already rejected and asks them to re-derive a conclusion that was already reached.

The test is not "can I name three courses of action." Anyone can. The test is **whether you would genuinely proceed differently depending on the answer.** If you would not, you are not asking, you are performing. Report it and act.

A decision brief is for a real fork: two or more courses you would actually take, where the choice turns on something the reader knows and you do not, or on a cost only they can accept. Everything else is a finding, and a finding goes in a sitrep.

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

## No coinage, and half the words

Use only words that already exist, in the meaning they already have. Where a subject has its own vocabulary, use that and nothing else. If no existing word fits, describe the thing in a sentence rather than naming it.

This bites hardest in Options. A course of action given a label the reader has to learn is a course they cannot weigh, and a table of coined names is a table of unknowns priced against each other.

Then cut it in half. A brief is read by someone deciding, and every sentence they do not need is one they read before reaching the one they did. `clarity.py` gates announced coinage and measures nothing about length, so the deletion pass is yours.

## What the checker will not do for you

Three things decide whether the brief is any good, and the checker reports all three as unassessed every single time:

- Does the recommendation follow from the situation, or merely sit after it?
- Are these the real options, or the three easiest to write?
- Is that the true cost, or the one you can defend?

Nothing automates those. The checker names them so their absence stays visible rather than being assumed away by a green tick.

## The failure this form prevents

A brief that buries the ask, prices no alternative, and never states what happens if the reader ignores it is not a decision request. It is a status update wearing one, and the reader is being asked to reconstruct the decision themselves from material arranged for the writer's convenience.

Structural completeness is not agreement. A brief can pass every check here and still recommend the wrong thing, which is why the checker prints what it did not examine underneath every verdict it did reach.
