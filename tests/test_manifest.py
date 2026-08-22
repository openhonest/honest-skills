"""The manifest holds the version twice, so the two must be checked to agree.

They drifted on 2026-08-21: a release bumped `metadata.version` alone, the
marketplace kept serving the old `plugins[0].version`, and `plugin update`
reported the plugin was already current. Nothing failed and nothing shipped.
"""
import json
from pathlib import Path

MANIFEST = json.loads(
    (Path(__file__).resolve().parent.parent
     / ".claude-plugin" / "marketplace.json").read_text())


def test_the_two_versions_in_the_manifest_agree():
    """Claude Code installs the one under `plugins`. A release that bumps only
    the other one is a release that silently does not happen."""
    assert MANIFEST["metadata"]["version"] == MANIFEST["plugins"][0]["version"]


def test_every_skill_the_manifest_lists_exists():
    root = Path(__file__).resolve().parent.parent
    missing = [s for s in MANIFEST["plugins"][0]["skills"]
               if not (root / s / "SKILL.md").exists()]
    assert missing == []
