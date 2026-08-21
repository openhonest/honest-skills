# Installing slop-audit-l1

The write-time hook delegates L1.21 to `slop-audit-l1`. Without that binary it reports `NOT_RUN` and falls back to line count and trailing whitespace.

```sh
uv tool install --python 3.13 <path-to>/slop-audit/tools/l1_analyzer
```

The `--python` flag is required and the reason is not obvious. Without it, uv picks the newest interpreter it can find. Where that is a free-threaded CPython 3.14, every tree-sitter parser falls back to a source build and fails, because abi3 wheels do not exist for free-threaded builds. The compiler line about `-std=c11` in the output is the invocation rather than the cause. Any ordinary CPython 3.12 or later works, and `requires-python` cannot express this because the constraint is on the build rather than the version.

Do not symlink the project's own console script onto PATH. It works, and it ties the installed tool to whatever branch that source tree happens to be on.

## What the hook cannot tell you

A missing binary and a binary that rejects the flag both arrive as `NOT_RUN`, with nothing to separate them. That ambiguity hid a real defect for a week: L1.18 was being called with a file path it always refused, while the binary was also absent, and the two failures read identically. If the hook reports `NOT_RUN` and the binary is on your PATH, check what that binary actually supports.

`--honest-code` and `--facets` take one file. Every other command takes a directory, and passing a file to the panel is refused outright.

Nineteen clauses exist and fewer are decided on any file. A production Python file decided 14, a test file 15. There is no fixed number, which is why the hook reads `decided_clauses` from the response rather than printing what it expected.
