#!/usr/bin/env python3
"""Refuse a push whose vendored copy differs from the source it came from.

Vendoring is allowed here on one condition: no push may carry a stale copy.
This is what makes that true rather than intended.

The alternative was for the skill to cite the principles and read them at
invocation. That costs a tool call every time the skill loads, and a step that
costs something is the step that gets skipped under pressure. Holding the text
is faster to read and free to drift. The drift is the measured problem: the
principles lived in twelve places holding twenty-two versions between them, and
no copy held them all. Four were missing from the folder the framework itself
called canonical, and one numbering scheme resolved a citation of P14 to
different principles depending on which file the reader had open.

So the copy stays and the drift is made impossible to push. A copy that cannot
survive a push while stale is a cache, and a cache with a hard invalidation is
not the thing that went wrong twelve times.

Verified against the remote, not against a local clone. A local clone is itself
a copy and can be as stale as the one under test, which would check a copy
against a copy and pass. A push is already a network operation: anything able to
push is able to fetch.

Failure to verify fails the push. Not being able to check is not evidence of
being current, and a check that passes when it could not run is the silent
failure this project exists to name.

What this covers, and what it does not.

It gates pushes of this repository, so no release can be cut carrying a stale
copy. It does not follow the source after a release. Someone who installs the
plugin holds a snapshot, and the source can move the next day.

That boundary is why each block records the commit it was taken from, in the
file, where a reader sees it. Anyone can run this against their own install and
be told the answer:

    uv run tools/vendor_check.py --root ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>

    uv run tools/vendor_check.py            # verify, exit 1 on drift
    uv run tools/vendor_check.py --sync     # pull the source in and record it
"""
import argparse
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

SOURCE_URL = ("https://raw.githubusercontent.com/openhonest/"
              "honest-code-principles/main/honest-code-principles.md")
# The last commit that touched the principles FILE, not the head of the
# repository. Pinned to the head, a commit that edits only the README reports
# the vendored copy as drifted and refuses the push, while the text it holds is
# byte-identical. That happened on 2026-08-30 with commit 4670cf6. The same
# defect sat in hooks/freshness.py, which is why both were fixed together: a
# check that fires when nothing it checks has changed teaches people to bypass
# it, and a bypassed check is worse than no check.
API_URL = ("https://api.github.com/repos/openhonest/honest-code-principles"
           "/commits?path=honest-code-principles.md&per_page=1")
BEGIN = "<!-- BEGIN VENDORED honest-code-principles.md"
END = "<!-- END VENDORED -->"
TIMEOUT = 20


def vendoring_files(root: Path) -> list[Path]:
    """Every file holding a vendored block, found by reading them.

    Listed by search rather than by a hand-kept list. A list is a third copy of
    the same fact, and it goes stale the first time someone vendors into a file
    nobody remembered to add.
    """
    found = []
    for p in sorted(root.rglob("*.md")):
        if ".git/" in str(p):
            continue
        try:
            if BEGIN in p.read_text(errors="replace"):
                found.append(p)
        except OSError:
            continue
    return found


def block_of(text: str) -> tuple[str, str] | None:
    """The vendored body and the commit it was taken from, or None.

    Returns None when the markers are absent or unpaired. A half-marked block
    is not read as an empty one: an unterminated BEGIN would otherwise compare
    the rest of the file and report drift nobody can act on.
    """
    m = re.search(re.escape(BEGIN) + r"\s+@\s+([0-9a-f]{7,40})\s*-->\n"
                  + r"(.*?)\n" + re.escape(END), text, re.S)
    return (m.group(2), m.group(1)) if m else None


def fetch(url: str) -> str:
    """Read a URL, authenticated when a token is in the environment.

    Unauthenticated GitHub allows sixty requests an hour per address, and this
    makes two per check. That is ample for a person and thin for CI, where
    several jobs share one runner address: the checks then fail as
    could-not-verify, which is the right answer and the wrong reason. Actions
    always sets GITHUB_TOKEN, which lifts the limit to a thousand, so the place
    that needs the headroom already has it and nothing has to be configured.

    Anonymous when no token is set. A public file needs no credentials, and
    demanding one to check a public document would put a secret in the path of
    a rule anyone should be able to verify.
    """
    req = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode()


def source_now() -> tuple[str, str]:
    """The canonical text and the commit it is at, from the remote."""
    import json
    commits = json.loads(fetch(API_URL))
    if not commits:
        raise LookupError("no commits found for honest-code-principles.md; "
                          "the file was renamed or removed upstream")
    head = commits[0]["sha"]
    return fetch(SOURCE_URL).rstrip("\n"), head


def sync(files: list[Path], body: str, sha: str) -> list[Path]:
    changed = []
    for p in files:
        text = p.read_text()
        found = block_of(text)
        if found is None:
            continue
        old_body, old_sha = found
        if old_body == body and old_sha == sha:
            continue
        new = re.sub(re.escape(BEGIN) + r"\s+@\s+[0-9a-f]{7,40}\s*-->\n"
                     + r".*?\n" + re.escape(END),
                     f"{BEGIN} @ {sha} -->\n{body}\n{END}", text, count=1,
                     flags=re.S)
        p.write_text(new)
        changed.append(p)
    return changed


def citations(text: str, body: str) -> list[str]:
    """Names cited as [[Principle Name]] that the vendored block does not define.

    A vendored copy carries the citations too, so a rename breaks them inside
    the copy exactly as silently as in the source, and in a place nobody is
    watching. This is that place watching.

    It exists because of a break nothing reported. Replacing a skill's restated
    rules with the vendored text deleted the numbering the rest of the file
    cited, and "rule 16 always, rules 6 and 7 partly" went on pointing at
    numbers that no longer existed anywhere. Four hours, every gate in this
    repository green, and it surfaced only because somebody asked what the
    citations resolved to.

    A citation has to be marked to be checked. The first attempt at this
    guessed at them from capitalisation, and when a cited principle was renamed
    it reported nothing wrong: a check that goes quiet exactly when the thing
    it checks is broken. So the marker is explicit. [[Name]] costs the writer
    two brackets and buys an exact answer instead of a plausible one.
    """
    defined = {m.group(1).strip() for m in re.finditer(r"^## (.+)$", body, re.M)}
    at, end = text.find(BEGIN), text.find(END)
    outside = text[:at] + text[end + len(END):] if at >= 0 else text
    cited = {m.strip() for m in re.findall(r"\[\[([^\]]+)\]\]", outside)}
    return sorted(cited - defined)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sync", action="store_true",
                    help="rewrite each vendored block from the source")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    a = ap.parse_args()

    files = vendoring_files(a.root)
    if not files:
        print("no vendored blocks found; nothing to keep fresh")
        return 0

    try:
        body, sha = source_now()
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        # Not being able to check is not evidence of being current.
        print(f"cannot reach the principles source to verify it: {e}\n"
              f"  {SOURCE_URL}\n"
              f"  The push is refused because the copy could not be checked, "
              f"not because it is known to be stale.", file=sys.stderr)
        return 1

    if a.sync:
        changed = sync(files, body, sha)
        for p in changed:
            print(f"  refreshed {p.relative_to(a.root)} to {sha[:7]}")
        print(f"{len(changed)} file(s) refreshed" if changed
              else f"already at {sha[:7]}")
        return 0

    stale, blocks = [], []
    for p in files:
        text = p.read_text()
        found = block_of(text)
        if found is None:
            print(f"{p.relative_to(a.root)}: a BEGIN marker with no matching "
                  f"END. The block cannot be compared.", file=sys.stderr)
            return 1
        old_body, old_sha = found
        blocks.append((p, text, old_body))
        if old_body != body or old_sha != sha:
            stale.append((p, old_sha))
    # Reuses what the loop above already parsed. Re-reading and re-parsing here
    # meant handling a missing block a second time, and that branch could never
    # run: the loop above returns before reaching it. Unreachable handling for a
    # case that cannot occur reads as care and is one more thing to keep true.
    dangling = [(p, name) for p, text, old_body in blocks
                for name in citations(text, old_body)]
    if dangling:
        for p, name in dangling:
            print(f"{p.relative_to(a.root)}: cites \"{name}\", which the "
                  f"vendored text does not define", file=sys.stderr)
        print("\nA rename upstream breaks a citation in the copy as silently "
              "as in the source. Fix the citation or take the newer text.",
              file=sys.stderr)
        return 1
    if not stale:
        print(f"vendored copies match the source at {sha[:7]}")
        return 0

    for p, old_sha in stale:
        print(f"{p.relative_to(a.root)}: vendored at {old_sha[:7]}, "
              f"source is at {sha[:7]}", file=sys.stderr)
    print(f"\nRun `uv run tools/vendor_check.py --sync` and commit the result.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
