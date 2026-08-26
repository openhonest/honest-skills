"""The gate that lets the principles be vendored at all.

Vendoring is permitted on one condition: no push may carry a stale copy. These
tests are that condition holding, so they cover the refusals more heavily than
the happy path. A gate that passes when it should not is worse than no gate,
because the copy then carries a guarantee it has stopped earning.
"""
import importlib.util
import urllib.error
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "vendor_check", Path(__file__).resolve().parent.parent / "tools/vendor_check.py")
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)

BODY = "# Principles\n\nOne principle.\n"
SHA = "a449b58e1c2d3f4a5b6c7d8e9f0a1b2c3d4e5f60"


def vendored(root, body=BODY, sha=SHA, name="SKILL.md"):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"before\n\n{vc.BEGIN} @ {sha} -->\n{body}\n{vc.END}\n\nafter\n")
    return p


def source(monkeypatch, body=BODY, sha=SHA):
    monkeypatch.setattr(vc, "source_now", lambda: (body, sha))


def run(monkeypatch, root, *args):
    monkeypatch.setattr("sys.argv", ["vendor_check", "--root", str(root), *args])
    return vc.main()


def test_a_matching_copy_passes(tmp_path, monkeypatch, capsys):
    vendored(tmp_path)
    source(monkeypatch)
    assert run(monkeypatch, tmp_path) == 0
    assert "match the source" in capsys.readouterr().out


def test_a_changed_word_fails_the_push(tmp_path, monkeypatch, capsys):
    """One character. The drift that cost twelve copies was never a rewrite."""
    vendored(tmp_path, body=BODY.replace("One", "Two"))
    source(monkeypatch)
    assert run(monkeypatch, tmp_path) == 1
    assert "vendored at" in capsys.readouterr().err


def test_a_copy_matching_the_text_at_an_older_commit_fails(tmp_path, monkeypatch):
    """The text can be identical while the source has moved, if the change was
    to a part this file does not hold. Recording the commit is what makes the
    copy answerable for where it came from rather than only for what it says."""
    vendored(tmp_path, sha="0" * 40)
    source(monkeypatch)
    assert run(monkeypatch, tmp_path) == 1


def test_being_unable_to_check_fails_the_push(tmp_path, monkeypatch, capsys):
    """The test this file exists for. Not being able to check is not evidence
    of being current, and a gate that passes when it could not run has quietly
    stopped being a gate while still being cited as one."""
    vendored(tmp_path)
    def unreachable():
        raise urllib.error.URLError("no route to host")
    monkeypatch.setattr(vc, "source_now", unreachable)
    assert run(monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert "could not be checked" in err
    assert "not because it is known to be stale" in err


def test_a_malformed_answer_from_the_source_fails_the_push(tmp_path, monkeypatch):
    """A reply that is not the file is not the file. Read as an empty source it
    would report every copy as drifted, or worse, match an empty block."""
    vendored(tmp_path)
    def wrong():
        raise KeyError("sha")
    monkeypatch.setattr(vc, "source_now", wrong)
    assert run(monkeypatch, tmp_path) == 1


def test_an_unterminated_block_fails_rather_than_comparing_the_rest(
        tmp_path, monkeypatch, capsys):
    """A BEGIN with no END would otherwise read to the end of the file and
    report drift against everything after it, which nobody can act on."""
    p = tmp_path / "SKILL.md"
    p.write_text(f"{vc.BEGIN} @ {SHA} -->\n{BODY}\nno end marker here\n")
    source(monkeypatch)
    assert run(monkeypatch, tmp_path) == 1
    assert "no matching" in capsys.readouterr().err


def test_a_repository_with_nothing_vendored_passes(tmp_path, monkeypatch, capsys):
    """Nothing to keep fresh is not a failure, and treating it as one would
    make every contributor without the skill unable to push."""
    (tmp_path / "README.md").write_text("no vendored block here\n")
    assert run(monkeypatch, tmp_path) == 0
    assert "nothing to keep fresh" in capsys.readouterr().out


def test_files_are_found_by_reading_them_not_from_a_list(tmp_path, monkeypatch):
    """A hand-kept list of vendoring files is a third copy of the same fact and
    goes stale the first time someone vendors into a file nobody added."""
    vendored(tmp_path, name="skills/a/SKILL.md")
    vendored(tmp_path, name="docs/b.md")
    (tmp_path / "unrelated.md").write_text("nothing\n")
    assert len(vc.vendoring_files(tmp_path)) == 2


def test_every_vendoring_file_is_checked_not_only_the_first(tmp_path, monkeypatch):
    """Checking one and stopping would let a second copy drift under a gate
    reporting success."""
    vendored(tmp_path, name="skills/a/SKILL.md")
    vendored(tmp_path, name="docs/b.md", body=BODY.replace("One", "Three"))
    source(monkeypatch)
    assert run(monkeypatch, tmp_path) == 1


def test_sync_rewrites_the_body_and_the_commit(tmp_path, monkeypatch, capsys):
    p = vendored(tmp_path, body="stale text", sha="0" * 40)
    source(monkeypatch)
    assert run(monkeypatch, tmp_path, "--sync") == 0
    body, sha = vc.block_of(p.read_text())
    assert body == BODY and sha == SHA
    assert "refreshed" in capsys.readouterr().out


def test_sync_leaves_a_file_already_current_alone(tmp_path, monkeypatch, capsys):
    """A tool reporting work it did not do teaches the reader to skim it."""
    vendored(tmp_path)
    source(monkeypatch)
    assert run(monkeypatch, tmp_path, "--sync") == 0
    assert "already at" in capsys.readouterr().out


def test_sync_leaves_the_text_around_the_block_untouched(tmp_path, monkeypatch):
    """The block sits inside a skill that says things of its own."""
    p = vendored(tmp_path, body="stale", sha="0" * 40)
    source(monkeypatch)
    run(monkeypatch, tmp_path, "--sync")
    text = p.read_text()
    assert text.startswith("before\n") and text.rstrip().endswith("after")


def test_sync_skips_a_file_whose_markers_do_not_pair(tmp_path, monkeypatch):
    """Rewriting a half-marked block would swallow whatever followed it."""
    p = tmp_path / "SKILL.md"
    p.write_text(f"{vc.BEGIN} @ {SHA} -->\nbody\nkeep this line\n")
    source(monkeypatch)
    assert run(monkeypatch, tmp_path, "--sync") == 0
    assert "keep this line" in p.read_text()


def test_an_unreadable_file_does_not_stop_the_search(tmp_path):
    """One unreadable file in a tree is not a reason to check none of them."""
    vendored(tmp_path, name="skills/a/SKILL.md")
    bad = tmp_path / "locked.md"
    bad.write_text("x")
    bad.chmod(0o000)
    try:
        assert len(vc.vendoring_files(tmp_path)) == 1
    finally:
        bad.chmod(0o644)


def test_the_git_directory_is_not_searched(tmp_path):
    """A commit object holding an old copy of the block is not a copy anyone
    reads, and reporting it would make every push fail forever."""
    vendored(tmp_path, name=".git/objects/old.md")
    assert vc.vendoring_files(tmp_path) == []


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self.payload.encode()


def test_the_source_is_read_from_the_remote_with_its_commit(monkeypatch):
    """Read from the remote rather than a local clone. A clone is itself a copy
    and can be as stale as the one under test, so checking one against the other
    compares a copy with a copy and passes."""
    seen = []
    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        seen.append(url)
        if "api.github.com" in url:
            return FakeResponse('{"sha": "' + SHA + '", "commit": {}}')
        return FakeResponse(BODY + "\n\n")
    monkeypatch.setattr(vc.urllib.request, "urlopen", urlopen)
    body, sha = vc.source_now()
    assert sha == SHA
    assert body == BODY.rstrip("\n"), "trailing newlines must not read as drift"
    assert any("raw.githubusercontent.com" in u for u in seen)
    assert all(u.startswith("https://") for u in seen), "plain http is not a source"


def test_a_reply_that_is_not_json_is_an_error_not_an_empty_commit(monkeypatch):
    """Read as empty it would compare every copy against nothing and rewrite
    them all to blank on the next sync."""
    monkeypatch.setattr(vc.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse("<html>429</html>"))
    with pytest.raises(ValueError):
        vc.source_now()


def test_a_token_in_the_environment_is_used(monkeypatch):
    """Unauthenticated GitHub allows sixty requests an hour per address and
    this makes two per check. CI shares one address across jobs, so the checks
    there fail as could-not-verify: the right answer for the wrong reason.
    Actions always sets GITHUB_TOKEN."""
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    seen = {}
    def urlopen(req, timeout=None):
        seen.update(req.headers)
        return FakeResponse("body")
    monkeypatch.setattr(vc.urllib.request, "urlopen", urlopen)
    vc.fetch("https://example.invalid/x")
    assert seen.get("Authorization") == "Bearer t0ken"


def test_no_token_means_an_anonymous_request(monkeypatch):
    """A public file needs no credentials, and demanding one to check a public
    document would put a secret in the path of a rule anyone should be able to
    verify for themselves."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    seen = {}
    def urlopen(req, timeout=None):
        seen.update(req.headers)
        return FakeResponse("body")
    monkeypatch.setattr(vc.urllib.request, "urlopen", urlopen)
    vc.fetch("https://example.invalid/x")
    assert "Authorization" not in seen


# --- citations into the vendored text ----------------------------------------

CITING = ("cites [[One principle]] here\n\n"
          f"{vc.BEGIN} @ {SHA} -->\n## One principle\ntext\n{vc.END}\n")


def test_a_citation_that_resolves_is_not_reported():
    body, _ = vc.block_of(CITING)
    assert vc.citations(CITING, body) == []


def test_a_citation_the_vendored_text_does_not_define_is_reported():
    """A vendored copy carries the citations too, so a rename breaks them
    inside the copy exactly as silently as in the source."""
    text = CITING.replace("[[One principle]]", "[[A principle that went away]]")
    body, _ = vc.block_of(text)
    assert vc.citations(text, body) == ["A principle that went away"]


def test_a_rename_upstream_breaks_the_citation_and_is_caught():
    """The case this exists for. The skill did not change; the source did."""
    text = CITING.replace("## One principle", "## One Principle, Renamed")
    body, _ = vc.block_of(text)
    assert vc.citations(text, body) == ["One principle"]


def test_a_name_inside_the_vendored_block_is_not_read_as_a_citation():
    """The source may reference its own principles. Those are its author's to
    keep correct, and reporting them would fail every push over someone else's
    document."""
    text = CITING.replace("## One principle\ntext",
                          "## One principle\nsee [[Some other thing]]")
    body, _ = vc.block_of(text)
    assert vc.citations(text, body) == []


def test_citations_are_marked_rather_than_guessed_from_capitals():
    """The first attempt inferred them from capitalisation. Renaming a cited
    principle produced no finding: a check that goes quiet exactly when the
    thing it checks is broken. Ordinary prose naming a principle without the
    brackets is not a citation and is not checked, which is a real limit and
    the price of an exact answer."""
    text = CITING.replace("[[One principle]]", "One principle")
    body, _ = vc.block_of(text)
    assert vc.citations(text, body) == []


def test_a_dangling_citation_fails_the_push(tmp_path, monkeypatch, capsys):
    p = tmp_path / "SKILL.md"
    p.write_text(f"cites [[Gone]]\n\n{vc.BEGIN} @ {SHA} -->\n{BODY}\n{vc.END}\n")
    source(monkeypatch)
    assert run(monkeypatch, tmp_path) == 1
    assert "which the vendored text does not define" in capsys.readouterr().err


def test_a_second_file_with_no_dangling_citation_is_passed_over(
        tmp_path, monkeypatch, capsys):
    """Two vendoring files, one citing something real. The loop has to keep
    going past a clean one rather than stopping at the first."""
    vendored(tmp_path, name="a/SKILL.md")
    p = tmp_path / "b" / "SKILL.md"
    p.parent.mkdir()
    p.write_text(f"cites [[Gone]]\n\n{vc.BEGIN} @ {SHA} -->\n{BODY}\n{vc.END}\n")
    source(monkeypatch)
    assert run(monkeypatch, tmp_path) == 1
    assert "Gone" in capsys.readouterr().err
