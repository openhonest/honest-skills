#!/usr/bin/env python3
"""Hand every running session the newest installed version, without a restart.

Why this is needed, and why it is not a hack.

A hook is a subprocess. Claude Code runs `python3 $CLAUDE_PLUGIN_ROOT/hooks/x.py`
on each event, so the file is read from disk every time it fires. New code in
that directory is therefore running code, immediately, in sessions that started
hours ago. That was verified rather than assumed: a marker written into the
plugin root appeared in the next hook row of an already-running session.

What a session cannot do is look somewhere else. CLAUDE_PLUGIN_ROOT is fixed
when the session launches and points at a directory named for the version that
was current then. A session started on 0.47.0 will read from the 0.47.0
directory for as long as it lives, whatever else gets installed beside it.

So the swap replaces the old version's directory with a link to the new one.
The session reads the same path, the filesystem sends it to the new code, and
`running_version()` resolves the link and reports what it actually ran. Without
that resolution the trace would carry the old number against the new behaviour,
which is the failure this plugin exists to catch.

Rollback is `--to <version>`, which relinks. Nothing is deleted: a real
directory that gets linked away is kept as `<version>.real` and restored if it
is ever needed again.

    uv run tools/hotswap.py --list
    uv run tools/hotswap.py                 # every older version to the newest
    uv run tools/hotswap.py --to 0.47.0     # roll back
"""
import argparse
import filecmp
import os
import shutil
import sys
from pathlib import Path

ROOT = Path.home() / ".claude/plugins/cache/honest-skills/honest-skills"


def as_number(name: str) -> tuple[int, ...]:
    """A version string ordered as numbers, so 0.9.0 sorts below 0.47.0.

    Sorted as text, 0.9.0 comes after 0.47.0 and the swap would point every
    session at a version from months ago.
    """
    return tuple(int(p) for p in name.split("."))


def is_version(name: str) -> bool:
    parts = name.split(".")
    return len(parts) == 3 and all(p.isdigit() for p in parts)


def installed(root: Path) -> list[str]:
    """Every installed version, oldest first.

    Reads the directory rather than any manifest. A manifest records what an
    installer believed; the directory is what a session will actually execute.
    """
    return sorted((d.name for d in root.iterdir() if is_version(d.name)),
                  key=as_number)


def state_of(root: Path, version: str) -> str:
    p = root / version
    return f"link to {os.readlink(p)}" if p.is_symlink() else "real directory"


def swap(root: Path, target: str, versions: list[str]) -> list[str]:
    """Point every version other than the target at the target.

    Returns what changed. A directory already linked where it should be is left
    alone and not reported, so running this twice says nothing the second time.
    """
    done = []
    for v in versions:
        p = root / v
        if v == target:
            if p.is_symlink():
                # The target must be the real thing. Left as a link it would
                # chain, and a chain through a version that gets rolled back
                # sends every session to code nobody chose.
                kept = root / f"{v}.real"
                if not kept.exists():
                    raise SystemExit(f"{v} is a link and no {v}.real is kept. "
                                     f"Reinstall it before swapping to it.")
                p.unlink()
                kept.rename(p)
                done.append(f"{v}: restored the real directory")
            continue
        if p.is_symlink() and os.readlink(p) == target:
            continue
        if p.is_symlink():
            p.unlink()
        else:
            kept = root / f"{v}.real"
            if kept.exists():
                shutil.rmtree(kept)
            p.rename(kept)
        p.symlink_to(target)
        done.append(f"{v} -> {target}")
    return done


def changed_skills(root: Path, moved: list[str], target: str) -> list[str]:
    """Skills whose text differs between what a session had and what it has now.

    A hook is a subprocess and updates the moment its file changes. A skill is
    not: its text enters a session's context when the skill is invoked and
    stays there for the rest of the conversation. Swapping the file changes
    what the next load reads and reaches nothing already loaded.

    So the swap can deliver new enforcement to a running session and cannot
    deliver new guidance. Naming the skills that changed is the difference
    between a caller who knows to go and tell those sessions and one who
    believes the update landed whole.
    """
    new = root / target / "skills"
    if not new.is_dir():
        return []
    names = set()
    for v in moved:
        # A version that shipped no skills at all is not skipped. A session on
        # it is running none of them, which is the largest gap there is, and
        # skipping it reported nothing to tell anybody about.
        old = root / f"{v}.real/skills"
        for skill in new.iterdir():
            before, after = old / skill.name / "SKILL.md", skill / "SKILL.md"
            if not after.is_file():
                continue
            if not before.is_file() or not filecmp.cmp(before, after, shallow=False):
                names.add(skill.name)
    return sorted(names)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--to", metavar="VERSION",
                    help="version to point every session at (default: newest)")
    ap.add_argument("--list", action="store_true",
                    help="show what is installed and where each one points")
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="plugin cache directory")
    ap.add_argument("--stage", type=Path, metavar="DIR",
                    help="copy a source tree in as a new version first, named "
                         "by the version in its own marketplace.json. The "
                         "normal install writes this directory; staging is for "
                         "code that is not released yet.")
    a = ap.parse_args()

    if not a.root.is_dir():
        # Said rather than swallowed. A silent no-op here would report success
        # for a swap that never happened, and the caller would go on believing
        # its sessions were updated.
        print(f"no plugin cache at {a.root}", file=sys.stderr)
        return 1

    if a.stage:
        import json
        manifest = a.stage / ".claude-plugin/marketplace.json"
        if not manifest.is_file():
            print(f"no marketplace.json under {a.stage}", file=sys.stderr)
            return 1
        version = json.loads(manifest.read_text())["plugins"][0]["version"]
        dest = a.root / version
        if dest.is_symlink():
            dest.unlink()
        elif dest.exists():
            shutil.rmtree(dest)
        # Copied rather than linked to the working tree. A link would make
        # every uncommitted keystroke live in every session at once, including
        # a file saved halfway through an edit.
        shutil.copytree(a.stage, dest,
                        ignore=shutil.ignore_patterns(".git", "__pycache__",
                                                      ".pytest_cache", ".venv"))
        print(f"  staged {a.stage} as {version}")
        a.to = a.to or version

    versions = installed(a.root)
    if not versions:
        print(f"no installed versions under {a.root}", file=sys.stderr)
        return 1

    if a.list:
        for v in versions:
            print(f"  {v:10} {state_of(a.root, v)}")
        return 0

    target = a.to or versions[-1]
    if target not in versions:
        print(f"{target} is not installed. Installed: {', '.join(versions)}",
              file=sys.stderr)
        return 1

    changed = swap(a.root, target, versions)
    if not changed:
        print(f"already pointing at {target}; nothing to do")
        return 0
    for line in changed:
        print(f"  {line}")
    print(f"\n{len(changed)} path(s) now serve {target}. Running sessions pick "
          f"this up on their next hook firing, with no restart. Confirm it in "
          f"the trace: the version field should read {target}.")

    moved = [line.split(" ->")[0] for line in changed if " -> " in line]
    stale = changed_skills(a.root, moved, target)
    if stale:
        print(f"\nHooks only. These skills also changed and a running session "
              f"will not see them:\n  {', '.join(stale)}\n"
              f"Skill text is held in a session's context from the moment it "
              f"was invoked. Tell those sessions to re-read the file, or "
              f"restart them.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
