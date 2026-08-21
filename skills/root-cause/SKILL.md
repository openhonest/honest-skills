---
name: root-cause
description: Run a true, recursive root-cause analysis. Use whenever the user asks for an RCA, a "root cause", why something happened, broke or regressed, or to diagnose the cause of a bug, incident, outage or wrong output. Enforces evidence-backed recursion from proximate cause to root cause. No "most likely", and no stopping at the first cause. Reports in SITREP shape.
allowed-tools: Read Grep Glob Bash
---

# Recursive Root-Cause Analysis

The user asked *why* something happened. They do not want a plausible story. They want the actual causal chain, with each link proven, followed down to the cause(s) of the cause(s) until you hit a root: a design decision, a process gap, or something outside the system boundary.

Follow this method. Do not shortcut it.

## The one rule that matters

**Every link in the chain is a verified fact, not a guess.** If you cannot show the evidence for a link, meaning a query result, a log line, a file you read, a value you reproduced, then you have not found that link yet. Keep digging or say you don't know. Never write "most likely," "probably," "it seems," or "this is likely because" as a substitute for looking.

If the user pushes back with "I don't want the most likely" or "verify it," that is a signal you skipped this rule. Go back and prove the link.

## The loop

Start at the symptom the user can see. Then repeat until you reach a root:

1. **State the current effect** in one concrete sentence (what is observed, with the specific case/value).
2. **Find its immediate cause.** The one thing directly upstream that produced this effect. Not the ultimate cause. The *next* one up.
3. **Prove it.** Run the query, read the file, pull the log, reproduce the value. Show the evidence inline.
4. **Ask "why is *that* true?"** and make that the new effect. Go to 1.

You are done with a branch when the cause is one of:
- a **design or process decision** (e.g. "serves from a cache with no invalidation on upstream correction"),
- a **defect in a specific component** you've located and proven,
- something **outside the system boundary** (a vendor, an upstream feed, a human action),

**and** you have verified nothing further upstream is also contributing.

## A cause is only a ROOT if it is NECESSARY, not merely PRESENT

The three "done" conditions share one property: each is something that could not simply be *different by choice*. a decision made for a reason, a located defect, an external constraint. That is the test. Before calling any cause a root, ask:

**Is this cause NECESSARY, or merely PRESENT?**

A root bottoms out in exactly one of: a physical/external constraint, a deliberate and defensible design decision, or a genuine requirement. If instead the "cause" is a piece of existing *implementation*, such as "the code loops and writes N times," "it re-reads every call" or "it opens a connection per request," that is **present, not necessary**. Existing code is not a law of physics; it is a candidate for change, and it owes one more "why": *why is it written this way, and does it need to be?* The answer is usually where the real fix lives, and usually a smaller, better fix than working around the symptom.

Two triggers that mean you have NOT reached the root, however well your explanation fits:

- **Your fix works AROUND the cause instead of removing it.** Relocating, caching, retrying, deferring, adding a queue: these accommodate a cause. A cope, not a cure, is proof the cause is still upstream. (This is the "don't layer a fix on a broken approach" rule wearing an RCA hat.)
- **A quantity is surprising.** If a number makes you blink, say a dozen writes to store one item, three seconds for a one-row update, the absurdity IS the signal. Do not record it as a finding and carry on. Ask why it is that large; the magnitude points at the root.

Having a viable fix in hand is not evidence you reached the root. The moment an explanation both fits the data and suggests an action is exactly when it is most tempting to stop, and most likely you are one level short.

## Trace the real path, do not theorize about it

The fast, correct way to find the next link is to follow the actual data/control flow, hop by hop, with tools:

- Resolve identifiers concretely (what UUID did the app map that slug to? what row?).
- Read the value at each hop and compare: is it correct *here* but wrong *there*? The break is between those two hops.
- When a hop is a service you can't read directly, find how it's wired (env vars, config, service list) and read the thing it points at.
- **Reproduce the failing path and the fixed path.** If you claim "the source is now correct," make the exact call the failing component makes and show it returns correct data. If you claim a component is stale, read its stored copy and show the stale value.

A theory you could have checked but didn't is not part of an RCA.

## Every instrument has a horizon: change instruments at each limit

An RCA rarely stalls from laziness. It stalls from trusting one instrument past the edge of what it can show. Every tool of observation is **constitutively blind** beyond some horizon, and the root frequently lives past that horizon. That is exactly why no amount of careful reading of a *single* instrument reaches it.

So at every stage, before accepting an instrument's output as the link, **name its blind spot, then pick up a different instrument whose light falls where the first's does not.** You learn the shape of the truth partly by cataloguing what each lens *cannot* show:

- A **latency number** shows *that* something is slow; it is blind to *composition and cause*: how many operations, which one, why. → time the parts separately; count the operations.
- A **single-operation probe** shows the warm, uncontended path; it is blind to *concurrency and contention*. → run N at once.
- An **aggregate** (a P95, a total, a mean) is blind to the *distribution* beneath it. → look at the individual values; the tail is often the whole story.
- **Reading the code** shows *structure*; it is blind to *necessity and runtime values*. → ask whether the structure must exist, and reproduce the values it actually produces.
- A **passing test** shows the path it covers; it is blind to *the paths it does not*. → ask what it cannot exercise.
- A **measurement on one build / box / session** is blind to *whether it is representative*. → vary the thing you held fixed and see if the result changes.

The discipline is active: after each link, ask "what is this instrument unable to show me *here*?" and treat that blind spot as the assignment for the next instrument. If you cannot name your current instrument's horizon, you do not yet understand what you are measuring, and you are about to mistake its edge for the bottom.

## Multiple causes are normal

Real incidents usually have **two roots**: the thing that *introduced* the bad state, and the thing that *let it persist / propagate / go unnoticed*. Look for both. "A wiped the data" and "B served the wiped data for a day because it has no freshness check" are both root causes and usually need separate fixes.

## Confirm scope before you finish

The reported case is a sample, not the boundary. Count the blast radius (was it one record or 19,000?). The number changes the severity and often the fix.

## Verify the fix closes the loop

If you propose or apply a fix, prove it addresses the proven root, ideally by re-checking the same evidence that showed the failure (the count drops, the value flips, the reproduced call now returns correct data). Don't declare "fixed" from the fact that you ran the fix; declare it from the evidence changing.

## How to present it: SITREP shape

The chain is the work. The report is not the chain. Lead with the root cause and what it costs, then show the chain underneath for anyone who wants to check it.

```
BLUF: <the root cause, in one sentence, and what it breaks>

<the worst news: blast radius, or what is still broken, before any fix>

CHAIN
- Symptom      <what is observed, the specific case>
- Cause 1      <the immediate cause>        evidence: <query, log line, value>
- Cause 2      <why cause 1 is true>        evidence: <...>
- Root         <design decision, process gap, or outside the boundary>

ASSESSMENT: <confirmed / likely / unverified, per link. Say which links you ran
and which you inferred.>

SCOPE: <how many records, requests, users, or files. One case is a sample.>

ACTION
- Done: <the fix, and the evidence it worked: the same check, now passing>
- Needs you: <what you cannot do, and why>

GAPS: <every link you could not prove, and what access would close it>
```

Rules that survive from the analysis into the report:

- **Every link carries its evidence on the same line.** A chain link without evidence is a story. Cut it or mark it unverified in GAPS.
- **Never write "most likely" in the CHAIN.** Confidence belongs in ASSESSMENT, named per link.
- **SCOPE is not optional.** The reported case is a sample, not the boundary. One record or nineteen thousand changes both the severity and the fix.
- **Two roots is normal.** One introduced the bad state; one let it persist or spread unnoticed. Report both, and say which fix closes which.
- **A fix is proven by the evidence changing**, not by having run the fix. Show the count dropping or the value flipping.

Keep prose over jargon. Never cite a number the evidence beside it does not show.

Run `tools/clarity.py` on the draft before sending. It prints your first sentence back at you, which is the check most often failed: a BLUF that restates the question instead of naming the cause.

## Anti-patterns (these fail the task)

- Stopping at the proximate cause and calling it the root.
- A chain with an unproven link ("the app is probably caching").
- "Most likely" / "typically this is caused by" without checking this instance.
- Blaming the component that *shows* the symptom without proving the data was already wrong upstream (or vice-versa).
- Declaring the fix works because you ran it, not because the evidence changed.
- Calling a merely-*present* implementation the root when it is a changeable candidate, signalled by a fix that copes rather than cures, or a surprising quantity left unexamined.
- Trusting one instrument past its horizon: accepting its output as the link without naming what it is blind to and reaching for a lens that sees there.
- Finding one root and stopping when a second (the persistence/propagation cause) is also present.
