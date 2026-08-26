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
    now = time.time()
    cache(monkeypatch, tmp_path, checked_at=now, verified_at=now - 3600,
          source_sha=MINE, error="URLError: timed out")
    note = fresh.principles_note(skill(tmp_path), now)
    assert "could not be checked" in note and "Last verified on" in note


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


# --- unverified today, against unmonitored for good --------------------------

def test_a_failed_check_names_the_date_of_the_last_good_one(tmp_path, monkeypatch):
    """A date rather than a count, because a reader can act on "last verified
    on the 3rd" and cannot act on "stale"."""
    no_network(monkeypatch)
    now = time.time()
    cache(monkeypatch, tmp_path, checked_at=now, verified_at=now - 3600,
          source_sha=MINE, error="HTTPError: 403 rate limit exceeded")
    note = fresh.principles_note(skill(tmp_path), now)
    assert time.strftime("%Y-%m-%d", time.localtime(now - 3600)) in note
    assert "unmonitored" not in note, "an hour old is not a broken arrangement"


def test_a_copy_nothing_has_checked_for_a_week_reads_as_unmonitored(
        tmp_path, monkeypatch):
    """A rate limit clears within the hour. A renamed repository, a deleted
    one, one made private, a revoked token, a URL that 404s after a
    reorganisation: none of those clear, and each produces the same message as
    the rate limit, forever. Without a clock on it, a copy nothing can ever
    check again reports what a copy checked ninety seconds ago reports."""
    no_network(monkeypatch)
    now = time.time()
    cache(monkeypatch, tmp_path, checked_at=now,
          verified_at=now - fresh.UNMONITORED_AFTER - 1, source_sha=MINE,
          error="HTTPError: 404 Not Found")
    note = fresh.principles_note(skill(tmp_path), now)
    assert "unmonitored rather than current" in note
    assert "404" in note, "the reason it stopped is the actionable part"


def test_a_copy_that_has_never_verified_says_that_and_not_a_date(
        tmp_path, monkeypatch):
    """A first install that has never once reached the source. There is no date
    to give, and inventing one from the install time would claim a check that
    never happened."""
    no_network(monkeypatch)
    now = time.time()
    cache(monkeypatch, tmp_path, checked_at=now, error="URLError: no route")
    note = fresh.principles_note(skill(tmp_path), now)
    assert "never been checked" in note and "unknown" in note


def test_a_failure_does_not_erase_what_the_last_good_check_learned(
        tmp_path, monkeypatch):
    """Written fresh, one bad minute threw away the last known source commit
    and the date it was learned, so the evidence that anything had ever worked
    went with it."""
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    fresh.cache_file().write_text(json.dumps(
        {"checked_at": 500.0, "verified_at": 500.0, "source_sha": THEIRS}))
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    state = fresh.refresh(1000.0)
    assert state["source_sha"] == THEIRS
    assert state["verified_at"] == 500.0
    assert state["checked_at"] == 1000.0 and "error" in state


def test_a_good_check_clears_the_previous_error(tmp_path, monkeypatch):
    """Otherwise the copy reports a failure it has already recovered from, and
    a reader learns to skip the line."""
    monkeypatch.setenv("HONEST_PENDING_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    fresh.cache_file().write_text(json.dumps(
        {"checked_at": 500.0, "error": "OSError: down"}))
    import urllib.request
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"sha": THEIRS}).encode()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R())
    state = fresh.refresh(1000.0)
    assert "error" not in state and state["verified_at"] == 1000.0
