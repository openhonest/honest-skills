# L1.18 in the hook: closed, it cannot read one file

**Closed 2026-08-21.** This planned an implementation of L1.18 inside the hook and was waiting on a classifier change. It is abandoned for a different reason: L1.18 refuses a file. Pointed at one it exits with "point me at a directory (a repo root), not a single file."

The hook had been passing it a single file since it shipped, so the call always failed and always reported `NOT_RUN`. Nobody caught it for a week, because `slop-audit-l1` was not installed and a missing binary produces the identical result. One failure was hiding the other, and installing the tool is what separated them.

L1.21 replaced it: one file by design, no git history, no CI, no repository, no network. See `installing-the-analyzer.md`.

## The measurement that misled me

I wrote earlier that L1.18 "works at file scope." It does not. What I measured was the panel against a directory containing one Python file, and I recorded that as file scope. Those are different claims, and the difference is the whole defect.

Pointed at the parent of a written file it returns 100.0 and band Slop, which describes the directory rather than the file. A check that answers a question nobody asked is worse than one that is absent, so it was removed rather than repointed.

Nothing here withdraws L1.18 itself. It remains the right measure for a repository and the panel still runs it there.
