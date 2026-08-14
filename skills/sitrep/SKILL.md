---
name: sitrep
description: Report in military brief format, BLUF first. Use whenever the user says "investigate", "report", "resolve", "assess", "tell me", "what happened", "status", or sends a screenshot expecting you to read and act on it. Enforces bottom line in the first sentence, bad news above good news, evidence beside every claim, stated confidence, and a named gap for anything unverified. Run clarity.py before sending.
allowed-tools: Read Grep Glob Bash
---

# SITREP: brief the reader, do not narrate at them

Someone asked a question. They want the answer, then the evidence, then what
they have to do about it. They do not want to watch you think.

**Triggers: investigate, report, resolve, assess, tell me, what happened, status.**

Also every screenshot they send, because a screenshot is someone pointing at
something and asking what it means.

## Why this shape

A report is read by someone deciding what to do next, and they stop reading the
moment they have enough. Everything you place after that decision point is
invisible to them, so the order of a report is not presentation, it is what
survives. Putting the conclusion last hides it behind material the reader has
already stopped needing.

The military convention exists because the cost of a buried conclusion is
measured in something other than irritation. The same logic applies to an
incident report, a pull-request description or a status update: the reader wants
the answer, then the evidence for it, then the part that needs them.

## The format

Use this shape whatever the verb. It scales from three lines to a page.

```
BLUF: <one sentence. The answer, the finding, or the recommendation.>

<the worst news, immediately, before anything good>

FINDINGS
- <fact>  -  <the evidence, a number, a command output, a quoted line>

ASSESSMENT: <what it means. State confidence: confirmed / likely / unverified.>

ACTION
- Done: <what you already did>
- Needs you: <only what you genuinely cannot do yourself>

GAPS: <what you could not verify, and what it would take to close it>
```

Drop any section that is empty. Never drop BLUF and never drop GAPS when a gap
exists.

## The six rules that get broken

**1. BLUF is the first sentence, not the first paragraph.** Not "Fixed and live."
Not "Two things." Not a restatement of the question. The finding. If your opening
sentence could sit on any other report, it is not a BLUF.

**2. Bad news goes above good news.** Every time. A reader stops at the top once
they have what they need, so anything you bury you have hidden. If you were wrong
earlier, say so before you say what you fixed.

**3. Every claim carries its evidence on the same line.** A number, a command
output, a quoted line. "The homepage had no links" is an assertion. "anchors on
the homepage: 0" is a finding. Never write "probably," "likely the cause" or
"seems to be" in FINDINGS; those belong in ASSESSMENT with the confidence named.

**4. Name the confidence.** Confirmed means you ran it and saw it. Likely means
the evidence points one way and you did not close it. Unverified means you are
guessing, and guessing goes in GAPS, not in FINDINGS.

**5. Report the whole result, including the part that failed.** If a check did
not run, say which. If a number is contaminated, say by what. A clean report of
a messy result beats a tidy report that omits the mess.

**6. "Needs you" is only what you genuinely cannot do.** Before writing a line
under it, ask whether you could find the answer yourself in the next five
minutes. If you could, go and find it. The list is for things blocked on
something you do not have: a login, an account action, a message sent under
their name, or a preference only they hold. It is not a place to put research
you did not run, and a GAP is not a licence to leave the work undone. "I have
not checked X, that would take an hour" is an hour you should have spent.

## Screenshots

A screenshot means "look at this and tell me what to do," not "describe this
back to me."

- Read what is on it. Do not recite it back; they can see it.
- Lead with what it means or what is wrong.
- If it shows a failure, that failure is the BLUF.
- If you need something the image does not show, ask one question. Do not
  speculate around the gap.

## Length

The report is not the work, and length is not evidence of effort. A one-line fix
gets a three-line report. Padding one out with structure signals thoroughness
while costing the reader the time that thoroughness was supposed to save them.

- Two headings maximum. More means you are performing thoroughness.
- No table for fewer than three rows.
- Cut every sentence that only announces the next sentence.

## Before sending, run it

```bash
uv run tools/clarity.py draft.md    # or pipe on stdin
```

Fix what it flags, then send. It prints your first sentence back at you, which is
the check most often failed. The band is 20 to 40: under 20 you have cut meaning
out, over 40 it takes two passes.

Then four operations: first sentence carries the finding, bad news above good,
headings counted, em dashes counted.

## Worked example

Bad, and this is a real report, rewritten after review:

> Fixed and live. The earlier empty reads were cached copies.
> ## What was actually wrong
> ...five sections, the admission of error fourth...

Good:

> BLUF: honestframework.software had zero links on its homepage, so no crawler
> could get past it. Fixed and live.
>
> I got this wrong twice. I told you it was authority and that no technical fix
> would help. It was markup both times.
>
> FINDINGS
> - anchors on the homepage: 0, ten buttons driven by JavaScript
> - GPTBot, ClaudeBot, Google-Extended, PerplexityBot: each fetched "/" only, never deeper
> - the ten "deep fetches" I reported earlier were ChatGPT user-fetches, not crawls
>
> ACTION
> - Done: 20 canonical links on the homepage and in llms.txt, commit 520155c, deployed
> - Needs you: nothing
>
> GAPS: whether crawlers take the path is theirs to decide. Needs a re-crawl,
> so weeks. The monitor tracks it daily.
