# Installing slop-audit-l1

The write-time hook delegates L1.21 to `slop-audit-l1`. Without that binary it reports `NOT_RUN` and falls back to line count and trailing whitespace.

```sh
uv tool install --python 3.13 <path-to>/slop-audit/tools/l1_analyzer
```

The `--python` flag is required and the reason is not obvious. Without it, uv picks the newest interpreter it can find. Where that is a free-threaded CPython 3.14, every tree-sitter parser falls back to a source build and fails, because abi3 wheels do not exist for free-threaded builds. The compiler line about `-std=c11` in the output is the invocation rather than the cause. Any ordinary CPython 3.12 or later works, and `requires-python` cannot express this because the constraint is on the build rather than the version.

Do not symlink the project's own console script onto PATH. It works, and it ties the installed tool to whatever branch that source tree happens to be on.

## What this measures, and what it does not

It measures shape, not correctness. A session introduced a regression that moved zero rows in a database transfer and the hook said nothing about it, because nothing about the shape of that code was wrong. The test suite caught it. A clean L1.21 report is not evidence the code works.

It is advisory rather than blocking. The write has already happened when it speaks, so it tells you what you just did rather than stopping you doing it.

Measured across one package of 167 findings: 105 implicit defaults that were real and invisible to other checks, and 47 that the project had already decided against. 21 of those sat on functions carrying an explicit boundary decoration the analyzer does not read, and 26 were exception classes a project rule permits. Roughly a third of what it reports may be decisions someone already made.

## A fix in the analyzer needs a reinstall here

`uv tool install` takes a snapshot, so the binary on PATH is frozen at install time and does not follow the source tree. That is the trade: a binary that tracked the tree would change under you whenever someone switched branches in it.

The cost is that a fix to the analyzer does not reach this hook until you reinstall.

```sh
uv tool install --force --python 3.13 <path-to>/slop-audit/tools/l1_analyzer
```

This is not hypothetical. Two false positives were fixed in the analyzer and the hook kept reporting both, because the hook was running the snapshot. The author's own binary read the file clean while the hook did not, and only a reinstall reconciled them.

A finding you believe is wrong has a second answer that needs no reinstall: a comment at the site naming the clause and the reason, `honest-code-allow: L1.21.4 - <reason>`. The reason is required and a bare suppression is not honoured. It is per site rather than per directory on purpose, because a directory-wide exemption blinds the check to a real instance added there later.

## What the hook cannot tell you

A missing binary and a binary that rejects the flag both arrive as `NOT_RUN`, with nothing to separate them. That ambiguity hid a real defect for a week: L1.18 was being called with a file path it always refused, while the binary was also absent, and the two failures read identically. If the hook reports `NOT_RUN` and the binary is on your PATH, check what that binary actually supports.

`--honest-code` and `--facets` take one file. Every other command takes a directory, and passing a file to the panel is refused outright.

Nineteen clauses exist and fewer are decided on any file. A production Python file decided 14, a test file 15. There is no fixed number, which is why the hook reads `decided_clauses` from the response rather than printing what it expected.
