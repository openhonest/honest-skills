---
name: verify
description: Check what you claim before you claim it. Use before reporting that work is done, that tests pass, that something does not exist, or that a change is safe. Turns "be rigorous" into operations - confirm the commit in the same shell, run the whole suite, quote the path beside every negative, read the thing before characterising it, and check what the tool actually returned. Checked by tools/claims.py.
allowed-tools: Read Grep Glob Bash
---

# Verify: earn the claim before you make it

**Triggers:** `done`, `fixed`, `passing`, `working`, `not found`, `no callers`, `nothing uses it`, `safe to change`.

Those are the four claim types that go wrong: completion, correctness, absence, and safety. Everything else you say is either a question or an opinion, and neither can be false in the way these can.

## Why this is separate from sitrep

`sitrep` governs the report. Evidence beside every claim, confidence named, a gap for anything unverified. It assumes the verification happened and was sound.

This skill is about the hour before that. A report can satisfy every rule in `sitrep` and still be wrong, because a scoped test run reported as a pass carries its evidence faithfully and says something false. Reporting discipline cannot catch a check that was never the right check.

## The rules

**1. Attribute a result to the state that produced it.** Before writing that a test run, a grep or a build holds at commit X, run `git rev-parse HEAD` in the same shell the check ran in and confirm it is X. Working trees move under you: a rebase, a colleague's push, an agent in another window. The claim is about a state, so name the state you were in.

**2. Run the whole suite for what you touched.** Never a scoped module run. A scoped pass hides breakage outside its scope, and the breakage outside its scope is the reason to run tests at all. If the full suite is too slow to run, that is a finding about the suite, and it goes in the report.

**3. A negative claim carries the place you looked.** "Not found under `crates/`" is a claim. "Not found" is a guess wearing a claim's clothes. An unqualified negative is the easiest thing in engineering to be wrong about, because it asserts something about everywhere you did not look.

Write the command or the path beside it. If the search covered one directory, say the directory. If it covered one branch, say the branch.

**4. Read the thing before you characterise it.** Not the filename, not the directory it sits in, not what a similar file contained last time. Open it.

On 2026-08-17 an agent told its operator that a document was licensed the same way in two repositories, having read neither licensing section. Four files in one of them said otherwise, including both entry points. The claim was one `grep` away from correct and the agent had already run greps that afternoon.

**5. Reproduce both paths before saying fixed.** The failing path, so you know you had the right defect, and the fixed path, so you know you closed it. A change that stops a symptom appearing is not the same as a change that removes its cause, and only running both tells you which you have.

**6. Check what the tool returned, not what you asked it for.** A tool call can succeed and answer a different question. A fetch that hits a login page returns a clean, confident, well-structured description of the login page. Nothing in the output says "this is not the thing you wanted."

On 2026-08-17 an agent fetched a colleague's technical specification and received an analysis reporting "a minimal wireframe" with "notable absences: no error handling, no access control, no device responsiveness." It was about to relay that to the colleague's manager. The page was a passphrase prompt. The tell was in the output the whole time: *"Enter your passphrase to continue."*

Before using a tool result, find the sentence in it that could only be true of the thing you asked for. If there is no such sentence, you have not got the thing.

**7. Get a second opinion on risk, without priming it.** Do not tell the reviewer what you expect them to find. A reviewer told what to look for reports on what they were told and calls the rest reviewed.

**8. Scale effort to risk.** A config tweak just gets done. Anything touching persistence, authentication, money, or a user-visible surface earns all of the above. The rules are cheap; deciding they were unnecessary is where the cost lands.

## The check

```bash
uv run tools/claims.py draft.md      # or pipe on stdin
```

It flags unqualified negatives, completion claims with no evidence beside them, and absolutes about a system. Fix what it flags, then send.

## What it refuses to judge

Whether the evidence supports the claim. Whether the command you ran was the right command. Whether the scope you named was the scope that mattered. Whether the second opinion was independent.

Those are the whole of the work and no checker reaches them, which is why they are printed under every verdict and never gated.
