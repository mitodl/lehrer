import subprocess
from pathlib import Path

import pytest

from lehrer.core.notes import notes_clone_script, notes_ref_candidates


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def notes_remote(tmp_path: Path) -> Path:
    """A local repo with edx-notes-api's three branch-naming schemes."""
    remote = tmp_path / "edx-notes-api"
    remote.mkdir()
    _git("init", "--initial-branch=master", cwd=remote)
    _git("config", "user.email", "test@example.com", cwd=remote)
    _git("config", "user.name", "test", cwd=remote)
    for branch in ("master", "release/verawood", "open-release/sumac.master"):
        if branch != "master":
            _git("checkout", "-q", "-b", branch, "master", cwd=remote)
        (remote / "BRANCH").write_text(branch)
        _git("add", "BRANCH", cwd=remote)
        _git("commit", "-q", "-m", branch, cwd=remote)
        _git("checkout", "-q", "master", cwd=remote)
    _git("tag", "release/verawood.1", "release/verawood", cwd=remote)
    return remote


def _clone(remote: Path, release_name: str, dest: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", "-c", notes_clone_script(remote.as_uri(), release_name, str(dest))],
        capture_output=True,
        text=True,
        check=False,
    )


def test_candidates_put_the_exact_name_first() -> None:
    assert notes_ref_candidates("verawood") == [
        "verawood",
        "release/verawood",
        "open-release/verawood.master",
    ]


@pytest.mark.parametrize(
    ("release_name", "expected_branch"),
    [
        ("verawood", "release/verawood"),
        ("sumac", "open-release/sumac.master"),
        ("master", "master"),
        ("release/verawood", "release/verawood"),
        ("open-release/sumac.master", "open-release/sumac.master"),
        ("release/verawood.1", "release/verawood"),
    ],
)
def test_clone_resolves_release_name(
    notes_remote: Path, tmp_path: Path, release_name: str, expected_branch: str
) -> None:
    dest = tmp_path / "checkout"

    result = _clone(notes_remote, release_name, dest)

    assert result.returncode == 0, result.stderr
    assert (dest / "BRANCH").read_text() == expected_branch


def test_clone_fails_loudly_when_no_ref_matches(
    notes_remote: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "checkout"

    result = _clone(notes_remote, "zebrawood", dest)

    assert result.returncode == 1
    assert "Remote has none of the refs: zebrawood, release/zebrawood" in result.stderr
    assert notes_remote.as_uri() not in result.stderr
    assert not dest.exists()


def test_clone_stops_on_an_unreachable_repo(tmp_path: Path) -> None:
    dest = tmp_path / "checkout"

    result = _clone(tmp_path / "missing", "verawood", dest)

    # git's own failure, after one probe, not the "none of the refs" fallback.
    assert result.returncode == 128
    assert result.stderr.count("does not appear to be a git repository") == 1
    assert "has none of the refs" not in result.stderr
