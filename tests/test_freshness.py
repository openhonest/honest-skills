"""The last link: telling an installed session its copy has been overtaken.

Automation covers the two links upstream. A push to the principles repository
notifies this one, and this one syncs and releases. Neither reaches a machine
where the plugin is already installed, because the text there sits in a
directory named for a version and follows nothing.

So the copy reports on itself, and these tests are mostly about the case where
it cannot. Not having looked must never read as up to date.
"""
import importlib.util
import json
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
spec = importlib.util.spec_from_file_location("freshness", HOOKS / "freshness.py")
fresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fresh)

MINE = "a449b58e1c2d3f4a5b6c7d8e9f0a1b2c3d4e5f60"
THEIRS = "b550c69f2d3e4a5b6c7d8e9f0a1b2c3d4e5f6071"


def skill(tmp_path, sha=MINE):
    p = tmp_path / "SKILL.md"
    p.write_text(f"words\n\n{fresh.BEGIN} @ {sha} -->\nbody\n"
                 f"<!-- END VENDORED -->\nmore\n")
    return p


def cache(monkeypatch, tmp_path, **state):
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir(exist_ok=True)
    fresh.cache_file().write_text(json.dumps(state))


def no_network(monkeypatch):
    """The refresh must never run from a test. It reaches the real GitHub."""
    monkeypatch.setattr(fresh, "start_refresh", lambda: None)


def test_a_copy_matching_the_source_says_nothing(tmp_path, monkeypatch):
    no_network(monkeypatch)
    cache(monkeypatch, tmp_path, checked_at=time.time(), source_sha=MINE)
    assert fresh.principles_note(skill(tmp_path)) == ""


def test_a_copy_behind_the_source_names_both_commits(tmp_path, monkeypatch):
    """Both, because one alone cannot be acted on. The held commit says what
    the reader is reading; the source commit says what they are missing."""
    no_network(monkeypatch)
    cache(monkeypatch, tmp_path, checked_at=time.time(), source_sha=THEIRS)
    note = fresh.principles_note(skill(tmp_path))
    assert MINE[:7] in note and THEIRS[:7] in note and "Update the plugin" in note


def test_a_check_that_failed_says_so_rather_than_nothing(tmp_path, monkeypatch):
    """The test this file exists for. A failed check and a passing one both
    produce no news, and no news reads as current. Every measurement defect in
    this project has been that shape: the unmeasured case landing in the
    numerator."""
    no_network(monkeypatch)
    cache(monkeypatch, tmp_path, checked_at=time.time(), error="URLError: timed out")
    note = fresh.principles_note(skill(tmp_path))
    assert "could not be checked" in note
    assert "may be current and that has not been established" in note


def test_a_first_run_says_nothing_and_starts_a_check(tmp_path, monkeypatch):
    """There is genuinely nothing to report yet, and inventing a warning on
    every fresh install would train people to ignore this line."""
    started = []
    monkeypatch.setattr(fresh, "start_refresh", lambda: started.append(1))
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))
    assert fresh.principles_note(skill(tmp_path)) == ""
    assert started == [1]


def test_a_stale_cache_starts_a_refresh_but_still_answers_now(
        tmp_path, monkeypatch):
    """The hook does not wait. It reports what it knows and the next firing has
    the newer answer. A check that costs a session two seconds gets removed."""
    started = []
    monkeypatch.setattr(fresh, "start_refresh", lambda: started.append(1))
    cache(monkeypatch, tmp_path,
          checked_at=time.time() - fresh.EVERY - 1, source_sha=THEIRS)
    note = fresh.principles_note(skill(tmp_path))
    assert started == [1]
    assert THEIRS[:7] in note


def test_a_fresh_cache_starts_nothing(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(fresh, "start_refresh", lambda: started.append(1))
    cache(monkeypatch, tmp_path, checked_at=time.time(), source_sha=MINE)
    fresh.principles_note(skill(tmp_path))
    assert started == []


def test_a_file_with_nothing_vendored_is_not_reported(tmp_path, monkeypatch):
    no_network(monkeypatch)
    p = tmp_path / "SKILL.md"
    p.write_text("a skill that holds no principles\n")
    assert fresh.principles_note(p) == ""


def test_a_missing_skill_file_is_not_reported(tmp_path, monkeypatch):
    """An install without that skill is not a stale install."""
    no_network(monkeypatch)
    assert fresh.principles_note(tmp_path / "gone.md") == ""


def test_an_unparseable_cache_reads_as_no_answer(tmp_path, monkeypatch):
    """Not as an answer of no. A truncated write during a refresh must not be
    read as "the source matches"."""
    started = []
    monkeypatch.setattr(fresh, "start_refresh", lambda: started.append(1))
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    fresh.cache_file().write_text("{ truncated")
    assert fresh.principles_note(skill(tmp_path)) == ""
    assert started == [1], "an unreadable cache must be treated as never checked"


def test_a_cache_holding_a_list_reads_as_no_answer(tmp_path, monkeypatch):
    no_network(monkeypatch)
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    fresh.cache_file().write_text("[]")
    assert fresh.read_cache() == {}


def test_the_refresh_records_a_failure_rather_than_dropping_it(tmp_path, monkeypatch):
    """Without the record, a run that could not reach the network looks exactly
    like one that never ran, and both read as no news."""
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))
    import urllib.request
    def boom(url, timeout=None):
        raise OSError("no route to host")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    state = fresh.refresh(1000.0)
    assert "error" in state and "source_sha" not in state
    assert json.loads(fresh.cache_file().read_text())["error"]


def test_the_refresh_records_the_commit_it_was_told(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))
    import urllib.request
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"sha": THEIRS}).encode()
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: R())
    assert fresh.refresh(1000.0)["source_sha"] == THEIRS


def test_a_cache_that_cannot_be_written_does_not_break_the_turn(
        tmp_path, monkeypatch):
    """The hook this runs under must never fail a turn over its own bookkeeping."""
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))
    import urllib.request
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"sha": THEIRS}).encode()
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: R())
    monkeypatch.setattr(Path, "write_text",
                        lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
    assert fresh.refresh(1000.0)["source_sha"] == THEIRS


def test_the_cache_lives_outside_the_versioned_plugin_directory(monkeypatch, tmp_path):
    """A plugin directory is named for a version and replaced on update. A
    cache written there is discarded exactly when it is most useful, and every
    update starts from no answer at all."""
    monkeypatch.delenv("HONEST_PENDING_DIR", raising=False)
    assert "plugins" not in str(fresh.cache_file())
    assert fresh.cache_file().parent.name == ".claude"


def test_start_refresh_survives_a_machine_that_cannot_spawn(monkeypatch):
    """A hook must not break a turn because a subprocess could not start."""
    import subprocess
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    fresh.start_refresh()


def test_start_refresh_detaches_and_swallows_its_output(monkeypatch):
    """Attached, its output would land in the middle of a session's turn."""
    import subprocess
    seen = {}
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: seen.update(k) or None)
    fresh.start_refresh()
    assert seen["start_new_session"] is True
    assert seen["stdout"] == subprocess.DEVNULL
    assert seen["stderr"] == subprocess.DEVNULL
