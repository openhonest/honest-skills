"""The swap that hands a running session new code without a restart.

Every test builds a real directory tree and checks the real filesystem. The
thing under test is what a path resolves to, and a mock of a filesystem would
answer from the same assumption that produced the bug.
"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "hotswap", Path(__file__).resolve().parent.parent / "tools/hotswap.py")
hotswap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hotswap)


def cache(tmp_path, *versions):
    """A plugin cache holding one real directory per version."""
    root = tmp_path / "cache"
    for v in versions:
        (root / v / "hooks").mkdir(parents=True)
        (root / v / "hooks/trace_hook.py").write_text(f"VERSION = {v!r}\n")
    return root


def test_versions_sort_as_numbers_not_as_text(tmp_path):
    """Sorted as text, 0.9.0 comes after 0.47.0 and the swap would point every
    running session at code from months ago."""
    root = cache(tmp_path, "0.9.0", "0.47.0", "0.10.0", "0.51.0")
    assert hotswap.installed(root) == ["0.9.0", "0.10.0", "0.47.0", "0.51.0"]


def test_an_old_version_resolves_to_the_new_code(tmp_path):
    """The whole mechanism in one assertion. A session holds the old path for
    as long as it lives and cannot be told to look elsewhere, so the old path
    has to lead to the new code."""
    root = cache(tmp_path, "0.47.0", "0.51.0")
    hotswap.swap(root, "0.51.0", hotswap.installed(root))
    old = root / "0.47.0/hooks/trace_hook.py"
    assert old.exists()
    assert old.read_text() == "VERSION = '0.51.0'\n"
    assert os.path.realpath(old).endswith("0.51.0/hooks/trace_hook.py")


def test_the_target_is_left_as_a_real_directory(tmp_path):
    root = cache(tmp_path, "0.47.0", "0.51.0")
    hotswap.swap(root, "0.51.0", hotswap.installed(root))
    assert not (root / "0.51.0").is_symlink()
    assert (root / "0.47.0").is_symlink()


def test_the_replaced_directory_is_kept_not_deleted(tmp_path):
    """Rollback has to have something to roll back to. A swap that deleted the
    old tree would be a one-way door on a live machine."""
    root = cache(tmp_path, "0.47.0", "0.51.0")
    hotswap.swap(root, "0.51.0", hotswap.installed(root))
    kept = root / "0.47.0.real/hooks/trace_hook.py"
    assert kept.read_text() == "VERSION = '0.47.0'\n"


def test_rolling_back_restores_the_real_directory(tmp_path):
    """Swapping to a version that is currently a link must put the real tree
    back. Left as a link it would chain, and a chain through a version that is
    itself rolled back sends every session to code nobody chose."""
    root = cache(tmp_path, "0.47.0", "0.51.0")
    versions = hotswap.installed(root)
    hotswap.swap(root, "0.51.0", versions)
    hotswap.swap(root, "0.47.0", versions)
    assert not (root / "0.47.0").is_symlink()
    assert (root / "0.47.0/hooks/trace_hook.py").read_text() == "VERSION = '0.47.0'\n"
    assert (root / "0.51.0").is_symlink()
    assert (root / "0.51.0/hooks/trace_hook.py").read_text() == "VERSION = '0.47.0'\n"


def test_rolling_back_to_a_link_with_nothing_kept_stops(tmp_path):
    """Rather than silently serving whatever the link happens to point at."""
    root = cache(tmp_path, "0.47.0", "0.51.0")
    hotswap.swap(root, "0.51.0", hotswap.installed(root))
    (root / "0.47.0.real").rename(root / "gone")
    with pytest.raises(SystemExit):
        hotswap.swap(root, "0.47.0", hotswap.installed(root))


def test_running_it_twice_changes_nothing_the_second_time(tmp_path):
    """A tool that reports work it did not do teaches the reader to ignore it."""
    root = cache(tmp_path, "0.42.0", "0.47.0", "0.51.0")
    versions = hotswap.installed(root)
    assert len(hotswap.swap(root, "0.51.0", versions)) == 2
    assert hotswap.swap(root, "0.51.0", versions) == []


def test_state_reads_the_filesystem_rather_than_a_manifest(tmp_path):
    """A manifest records what an installer believed. The directory is what a
    session will actually execute, and the two disagreed for four hours."""
    root = cache(tmp_path, "0.47.0", "0.51.0")
    hotswap.swap(root, "0.51.0", hotswap.installed(root))
    assert hotswap.state_of(root, "0.47.0") == "link to 0.51.0"
    assert hotswap.state_of(root, "0.51.0") == "real directory"


def test_a_missing_cache_is_reported_rather_than_passed_over(tmp_path, capsys,
                                                             monkeypatch):
    """A silent no-op would report success for a swap that never happened, and
    the caller would go on believing its sessions were updated."""
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(tmp_path / "nope")])
    assert hotswap.main() == 1
    assert "no plugin cache" in capsys.readouterr().err


def test_an_empty_cache_is_reported(tmp_path, capsys, monkeypatch):
    (tmp_path / "cache").mkdir()
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(tmp_path / "cache")])
    assert hotswap.main() == 1
    assert "no installed versions" in capsys.readouterr().err


def test_a_version_that_is_not_installed_is_refused(tmp_path, capsys, monkeypatch):
    root = cache(tmp_path, "0.47.0")
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(root), "--to", "9.9.9"])
    assert hotswap.main() == 1
    assert "not installed" in capsys.readouterr().err


def test_list_shows_every_version_and_where_it_points(tmp_path, capsys, monkeypatch):
    root = cache(tmp_path, "0.47.0", "0.51.0")
    hotswap.swap(root, "0.51.0", hotswap.installed(root))
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(root), "--list"])
    assert hotswap.main() == 0
    out = capsys.readouterr().out
    assert "0.47.0" in out and "link to 0.51.0" in out and "real directory" in out


def test_staging_names_the_directory_from_the_source_manifest(tmp_path, capsys,
                                                              monkeypatch):
    """Named by what the tree says it is. Named by hand, a staged tree would
    claim whatever the caller typed, and the trace would carry that number
    against code it never ran."""
    root = cache(tmp_path, "0.47.0")
    src = tmp_path / "src"
    (src / ".claude-plugin").mkdir(parents=True)
    (src / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"plugins": [{"version": "0.51.0"}]}))
    (src / "hooks").mkdir()
    (src / "hooks/trace_hook.py").write_text("VERSION = 'staged'\n")
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(root),
                                     "--stage", str(src)])
    assert hotswap.main() == 0
    assert (root / "0.51.0/hooks/trace_hook.py").read_text() == "VERSION = 'staged'\n"
    assert (root / "0.47.0/hooks/trace_hook.py").read_text() == "VERSION = 'staged'\n"


def test_staging_a_tree_with_no_manifest_is_refused(tmp_path, capsys, monkeypatch):
    root = cache(tmp_path, "0.47.0")
    (tmp_path / "src").mkdir()
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(root),
                                     "--stage", str(tmp_path / "src")])
    assert hotswap.main() == 1
    assert "no marketplace.json" in capsys.readouterr().err


def test_staging_over_an_existing_version_replaces_it(tmp_path, monkeypatch):
    """Re-staging during development is the normal case, and a stale file left
    behind from the previous stage would run without appearing in the source."""
    root = cache(tmp_path, "0.51.0")
    (root / "0.51.0/hooks/stale.py").write_text("x = 1\n")
    src = tmp_path / "src"
    (src / ".claude-plugin").mkdir(parents=True)
    (src / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"plugins": [{"version": "0.51.0"}]}))
    (src / "hooks").mkdir()
    (src / "hooks/trace_hook.py").write_text("VERSION = 'fresh'\n")
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(root),
                                     "--stage", str(src)])
    assert hotswap.main() == 0
    assert not (root / "0.51.0/hooks/stale.py").exists()


def test_staging_over_a_linked_version_replaces_the_link(tmp_path, monkeypatch):
    """The version being staged may itself have been linked away by an earlier
    swap. Written through the link, the new code would land in the target and
    the staged version would quietly be someone else's."""
    root = cache(tmp_path, "0.47.0", "0.51.0")
    hotswap.swap(root, "0.51.0", hotswap.installed(root))
    src = tmp_path / "src"
    (src / ".claude-plugin").mkdir(parents=True)
    (src / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"plugins": [{"version": "0.47.0"}]}))
    (src / "hooks").mkdir()
    (src / "hooks/trace_hook.py").write_text("VERSION = 'restaged'\n")
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(root),
                                     "--stage", str(src)])
    assert hotswap.main() == 0
    assert not (root / "0.47.0").is_symlink()
    assert (root / "0.51.0/hooks/trace_hook.py").read_text() == "VERSION = 'restaged'\n"


def test_the_git_directory_is_not_staged(tmp_path, monkeypatch):
    """A working tree carries its whole history. Copied in, every swap would
    move tens of megabytes and the plugin root would hold a second repository."""
    root = cache(tmp_path, "0.47.0")
    src = tmp_path / "src"
    (src / ".claude-plugin").mkdir(parents=True)
    (src / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"plugins": [{"version": "0.51.0"}]}))
    (src / ".git").mkdir()
    (src / ".git/HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(root),
                                     "--stage", str(src)])
    assert hotswap.main() == 0
    assert not (root / "0.51.0/.git").exists()


def test_a_swap_already_in_place_says_so_rather_than_nothing(tmp_path, capsys,
                                                             monkeypatch):
    root = cache(tmp_path, "0.47.0", "0.51.0")
    hotswap.swap(root, "0.51.0", hotswap.installed(root))
    monkeypatch.setattr("sys.argv", ["hotswap", "--root", str(root)])
    assert hotswap.main() == 0
    assert "nothing to do" in capsys.readouterr().out


def test_a_link_pointing_at_the_wrong_version_is_relinked(tmp_path):
    """Two swaps in a row, the second to a different target. Left pointing at
    the first target, a session on that path would go on running the version it
    was just moved off."""
    root = cache(tmp_path, "0.42.0", "0.47.0", "0.51.0")
    versions = hotswap.installed(root)
    hotswap.swap(root, "0.47.0", versions)
    assert os.readlink(root / "0.42.0") == "0.47.0"
    hotswap.swap(root, "0.51.0", versions)
    assert os.readlink(root / "0.42.0") == "0.51.0"
    assert (root / "0.42.0/hooks/trace_hook.py").read_text() == "VERSION = '0.51.0'\n"


def test_a_stale_kept_directory_is_replaced_not_left(tmp_path):
    """A second swap of the same version finds its own earlier copy waiting.
    Left in place, rollback would restore a tree from two swaps ago."""
    root = cache(tmp_path, "0.47.0", "0.51.0")
    versions = hotswap.installed(root)
    hotswap.swap(root, "0.51.0", versions)          # 0.47.0 real tree kept aside
    hotswap.swap(root, "0.47.0", versions)          # restored
    (root / "0.47.0/hooks/trace_hook.py").write_text("VERSION = 'newer'\n")
    hotswap.swap(root, "0.51.0", versions)          # kept aside again
    assert (root / "0.47.0.real/hooks/trace_hook.py").read_text() == "VERSION = 'newer'\n"


def test_a_kept_directory_left_by_a_crash_is_cleared(tmp_path):
    """A `.real` tree can survive a run that died between the rename and the
    link. Without clearing it the rename fails and the swap stops partway, with
    some sessions moved and some not."""
    root = cache(tmp_path, "0.47.0", "0.51.0")
    (root / "0.47.0.real").mkdir()
    (root / "0.47.0.real/leftover.py").write_text("x = 1\n")
    hotswap.swap(root, "0.51.0", hotswap.installed(root))
    assert not (root / "0.47.0.real/leftover.py").exists()
    assert (root / "0.47.0.real/hooks/trace_hook.py").read_text() == "VERSION = '0.47.0'\n"
