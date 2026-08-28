"""Telling a session its skills moved, because the swap cannot move them for it.

A hook picks up new code the moment it lands, because a hook is a subprocess.
A skill does not. Its description is handed to the session at start and decides
when the skill fires, and its text goes into context on first use. Neither one
follows the file afterwards.

Verified on 2026-08-28: sitrep's trigger was narrowed from seven phrases to one,
and the session that made the change was still holding the seven-phrase
description an hour later.
"""
import importlib.util
import json
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
spec = importlib.util.spec_from_file_location("skill_drift", HOOKS / "skill_drift.py")
drift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drift)


def skills(tmp_path, **files):
    root = tmp_path / "skills"
    for name, text in files.items():
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "SKILL.md").write_text(text)
    return root


def here(monkeypatch, tmp_path):
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))


def test_a_session_that_has_read_nothing_is_told_nothing(tmp_path, monkeypatch):
    """A session that just started holds no skill text, so nothing it holds can
    be stale. Firing here would put a warning in front of every fresh session
    and teach everyone to skip the line."""
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a", verify="b")
    assert drift.note("s1", root=root) == ""


def test_a_changed_skill_is_named(tmp_path, monkeypatch):
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a", verify="b")
    drift.note("s1", root=root)
    (root / "sitrep" / "SKILL.md").write_text("changed")
    note = drift.note("s1", root=root)
    assert "sitrep" in note and "verify" not in note
    assert "Re-read the file, or restart" in note


def test_the_same_change_is_said_once(tmp_path, monkeypatch):
    """A line repeated on every write is a line people learn to skip, and the
    next real change goes with it."""
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a")
    drift.note("s1", root=root)
    (root / "sitrep" / "SKILL.md").write_text("changed")
    assert drift.note("s1", root=root) != ""
    assert drift.note("s1", root=root) == ""


def test_a_second_change_after_the_first_is_said_again(tmp_path, monkeypatch):
    """Said once per set of changes, not once per session. A skill that moves
    again is news again."""
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a", verify="b")
    drift.note("s1", root=root)
    (root / "sitrep" / "SKILL.md").write_text("changed")
    assert "sitrep" in drift.note("s1", root=root)
    (root / "verify" / "SKILL.md").write_text("also changed")
    second = drift.note("s1", root=root)
    assert "verify" in second and "sitrep" in second


def test_each_session_is_tracked_apart(tmp_path, monkeypatch):
    """One session's baseline is not another's. A session that started after
    the change never held the old text and has nothing to be told."""
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a")
    drift.note("s1", root=root)
    (root / "sitrep" / "SKILL.md").write_text("changed")
    assert drift.note("s2", root=root) == ""
    assert "sitrep" in drift.note("s1", root=root)


def test_a_new_skill_appearing_counts_as_a_change(tmp_path, monkeypatch):
    """A session cannot invoke a skill its listing does not name, so a skill
    added after the session started is invisible to it. That is worth saying."""
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a")
    drift.note("s1", root=root)
    skills(tmp_path, writing="brand new")
    assert "writing" in drift.note("s1", root=root)


def test_content_decides_rather_than_timestamps(tmp_path, monkeypatch):
    """A hot swap copies files in, so every mtime moves whether or not the text
    did. Keyed on mtime this would report every skill as changed on every
    release, which is a warning that means nothing."""
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a")
    drift.note("s1", root=root)
    p = root / "sitrep" / "SKILL.md"
    p.write_text(p.read_text())          # rewritten, identical text
    assert drift.note("s1", root=root) == ""


def test_no_skills_directory_reports_nothing(tmp_path, monkeypatch):
    here(monkeypatch, tmp_path)
    assert drift.note("s1", root=tmp_path / "absent") == ""


def test_an_unreadable_state_file_starts_over_rather_than_failing(
        tmp_path, monkeypatch):
    """A truncated write must not break the hook that reports on it."""
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a")
    (tmp_path / "state").mkdir(exist_ok=True)
    drift.state_file().write_text("{ truncated")
    assert drift.note("s1", root=root) == ""
    assert isinstance(json.loads(drift.state_file().read_text()), dict)


def test_a_state_file_that_cannot_be_written_does_not_break_the_hook(
        tmp_path, monkeypatch):
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a")
    monkeypatch.setattr(Path, "write_text",
                        lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
    assert drift.note("s1", root=root) == ""


def test_an_unreadable_skill_file_is_skipped_not_fatal(tmp_path, monkeypatch):
    """One locked file is not a reason to report on none of them."""
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a", verify="b")
    bad = root / "verify" / "SKILL.md"
    bad.chmod(0o000)
    try:
        assert set(drift.fingerprints(root)) == {"sitrep"}
    finally:
        bad.chmod(0o644)


def test_forgetting_a_session_makes_it_new_again(tmp_path, monkeypatch):
    """For when a session has re-read its skills. Nothing calls this on its own,
    because the hook cannot watch a session read a file."""
    here(monkeypatch, tmp_path)
    root = skills(tmp_path, sitrep="a")
    drift.note("s1", root=root)
    (root / "sitrep" / "SKILL.md").write_text("changed")
    drift.forget("s1")
    assert drift.note("s1", root=root) == ""


def test_forgetting_a_session_that_was_never_seen_is_harmless(tmp_path, monkeypatch):
    here(monkeypatch, tmp_path)
    drift.forget("never-seen")
