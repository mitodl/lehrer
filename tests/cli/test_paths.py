from __future__ import annotations

from pathlib import Path

import pytest

from lehrer.cli import _paths


@pytest.fixture(autouse=True)
def _clear_repo_root_cache():
    _paths.repo_root.cache_clear()
    yield
    _paths.repo_root.cache_clear()


def _make_fake_repo(tmp_path: Path) -> Path:
    marker = tmp_path / "local-dev"
    marker.mkdir()
    (marker / "k3d-config.yaml").write_text("metadata:\n  name: lehrer-dev\n")
    return tmp_path


class TestSearchFrom:
    def test_finds_marker_in_ancestor_directory(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        nested = repo / "a" / "b"
        nested.mkdir(parents=True)
        assert _paths._search_from(nested) == repo

    def test_returns_none_when_no_marker_in_any_ancestor(self, tmp_path: Path) -> None:
        # tmp_path itself has no local-dev/k3d-config.yaml, nor do any of its
        # real filesystem ancestors (outside the repo checkout under test).
        assert _paths._search_from(tmp_path) is None


class TestRepoRoot:
    def test_env_override_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo = _make_fake_repo(tmp_path)
        monkeypatch.setenv("LEHRER_REPO_ROOT", str(repo))
        assert _paths.repo_root() == repo

    def test_env_override_without_marker_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("LEHRER_REPO_ROOT", str(tmp_path))
        with pytest.raises(_paths.RepoNotFoundError):
            _paths.repo_root()

    def test_falls_back_to_cwd_search(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("LEHRER_REPO_ROOT", raising=False)
        repo = _make_fake_repo(tmp_path)
        monkeypatch.chdir(repo)
        assert _paths.repo_root() == repo
