from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from lehrer.core.build_manifest import (
    BuildManifest,
    Cell,
    CellDefaults,
    load_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

MIT_OL_CELLS = [
    ("master", "mitxonline"),
    ("master", "mitx"),
    ("master", "mitx-staging"),
    ("ulmo", "mitx"),
    ("ulmo", "mitx-staging"),
    ("ulmo", "xpro"),
    ("verawood", "mitx"),
    ("verawood", "mitx-staging"),
    ("verawood", "xpro"),
]

RESOLVED_STRING_FIELDS = [
    "platform_repo",
    "platform_branch",
    "translations_repo",
    "translations_branch",
    "node_version",
    "theme_repo",
    "theme_branch",
    "settings_namespace",
]

GITHUB_REPO_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+(?:\.git)?/?$")
SUPPORTED_PYTHON_VERSIONS = {"3.11", "3.12"}


def effective_lines(text: str) -> list[str]:
    """Strip pip inline comments (space-then-#) and comment-only lines."""
    out = []
    for raw in text.splitlines():
        line = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _committed_lines(kind: str, release: str, deployment: str) -> list[str]:
    path = (
        REPO_ROOT
        / "deployments"
        / "mit-ol"
        / f"pip_package_{kind}"
        / release
        / f"{deployment}.txt"
    )
    return effective_lines(path.read_text())


@pytest.fixture(scope="module")
def mit_ol_manifest() -> BuildManifest:
    return load_manifest(REPO_ROOT / "deployments" / "mit-ol" / "build_manifest.yaml")


@pytest.fixture(scope="module")
def generic_manifest() -> BuildManifest:
    return load_manifest(REPO_ROOT / "deployments" / "generic" / "build_manifest.yaml")


class TestFaithfulnessAgainstCommittedTxt:
    """Render↔.txt equality — the behavior-preservation proof for PR 1."""

    @pytest.mark.parametrize(("release", "deployment"), MIT_OL_CELLS)
    def test_packages_match_committed_txt(
        self, mit_ol_manifest: BuildManifest, release: str, deployment: str
    ) -> None:
        cell = mit_ol_manifest.resolve_cell(release, deployment)
        rendered = effective_lines(cell.render_packages())
        committed = _committed_lines("lists", release, deployment)
        assert rendered == committed

    @pytest.mark.parametrize(("release", "deployment"), MIT_OL_CELLS)
    def test_overrides_match_committed_txt(
        self, mit_ol_manifest: BuildManifest, release: str, deployment: str
    ) -> None:
        cell = mit_ol_manifest.resolve_cell(release, deployment)
        rendered = effective_lines(cell.render_overrides())
        committed = _committed_lines("overrides", release, deployment)
        assert rendered == committed

    def test_generic_packages_match_committed_txt(
        self, generic_manifest: BuildManifest
    ) -> None:
        cell = generic_manifest.resolve_cell("master", "generic")
        rendered = effective_lines(cell.render_packages())
        path = (
            REPO_ROOT
            / "deployments"
            / "generic"
            / "pip_package_lists"
            / "master"
            / "generic.txt"
        )
        assert rendered == effective_lines(path.read_text())


class TestResolvedFieldsWellFormed:
    """Structural invariants for resolved cell values.

    Exact repo/branch/version choices are a review-time concern (visible in
    the build_manifest.yaml diff), not something to pin in test source —
    otherwise every intentional config change requires an unrelated test edit.
    """

    @pytest.mark.parametrize(("release", "deployment"), MIT_OL_CELLS)
    @pytest.mark.parametrize("field", RESOLVED_STRING_FIELDS)
    def test_string_field_is_non_empty(
        self,
        mit_ol_manifest: BuildManifest,
        release: str,
        deployment: str,
        field: str,
    ) -> None:
        cell = mit_ol_manifest.resolve_cell(release, deployment)
        value = cell.resolved(field, mit_ol_manifest)
        assert isinstance(value, str)
        assert value != ""

    @pytest.mark.parametrize(("release", "deployment"), MIT_OL_CELLS)
    @pytest.mark.parametrize(
        "field", ["platform_repo", "translations_repo", "theme_repo"]
    )
    def test_repo_field_is_a_github_https_url(
        self,
        mit_ol_manifest: BuildManifest,
        release: str,
        deployment: str,
        field: str,
    ) -> None:
        cell = mit_ol_manifest.resolve_cell(release, deployment)
        value = cell.resolved(field, mit_ol_manifest)
        assert isinstance(value, str)
        assert GITHUB_REPO_RE.match(value), f"not a github https url: {value!r}"

    @pytest.mark.parametrize(("release", "deployment"), MIT_OL_CELLS)
    def test_python_version_is_supported(
        self, mit_ol_manifest: BuildManifest, release: str, deployment: str
    ) -> None:
        cell = mit_ol_manifest.resolve_cell(release, deployment)
        version = cell.resolved("python_version", mit_ol_manifest)
        assert version in SUPPORTED_PYTHON_VERSIONS

    @pytest.mark.parametrize(("release", "deployment"), MIT_OL_CELLS)
    def test_packages_to_remove_is_a_list_of_strings(
        self, mit_ol_manifest: BuildManifest, release: str, deployment: str
    ) -> None:
        cell = mit_ol_manifest.resolve_cell(release, deployment)
        packages_to_remove = cell.resolved("packages_to_remove", mit_ol_manifest)
        assert isinstance(packages_to_remove, list)
        assert all(isinstance(pkg, str) for pkg in packages_to_remove)


class TestResolvedRespectsExplicitEmptyOverride:
    """A cell explicitly overriding a list default to [] must win, not fall back."""

    def test_override_list_to_empty_respected(self) -> None:
        manifest = BuildManifest(
            version=1,
            defaults=CellDefaults(extra_ssh_hosts=["github.mit.edu"]),
            cells=[
                Cell(
                    release="master",
                    deployment="x",
                    packages=["a==1"],
                    extra_ssh_hosts=[],
                )
            ],
        )
        cell = manifest.resolve_cell("master", "x")
        assert cell.resolved("extra_ssh_hosts", manifest) == []

    def test_unset_list_still_falls_back_to_default(self) -> None:
        manifest = BuildManifest(
            version=1,
            defaults=CellDefaults(extra_ssh_hosts=["github.mit.edu"]),
            cells=[Cell(release="master", deployment="x", packages=["a==1"])],
        )
        cell = manifest.resolve_cell("master", "x")
        assert cell.resolved("extra_ssh_hosts", manifest) == ["github.mit.edu"]


class TestBuildManifestStructure:
    def test_all_expected_cells_present(self, mit_ol_manifest: BuildManifest) -> None:
        actual = {(c.release, c.deployment) for c in mit_ol_manifest.cells}
        assert actual == set(MIT_OL_CELLS)

    def test_no_duplicate_cells_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate cell"):
            BuildManifest(
                version=1,
                cells=[
                    Cell(release="master", deployment="x", packages=["a==1"]),
                    Cell(release="master", deployment="x", packages=["b==1"]),
                ],
            )

    def test_resolve_cell_raises_on_unknown_pair(
        self, mit_ol_manifest: BuildManifest
    ) -> None:
        with pytest.raises(ValueError, match="no cell for"):
            mit_ol_manifest.resolve_cell("nonexistent", "nowhere")

    def test_json_schema_round_trips(self) -> None:
        from lehrer.core.build_manifest import json_schema

        schema = json_schema()
        assert schema == BuildManifest.model_json_schema()
        assert schema["title"] == "BuildManifest"

    @pytest.mark.parametrize(
        "manifest_fixture", ["mit_ol_manifest", "generic_manifest"]
    )
    def test_every_rendered_line_is_a_pip_requirement(
        self, manifest_fixture: str, request: pytest.FixtureRequest
    ) -> None:
        manifest: BuildManifest = request.getfixturevalue(manifest_fixture)
        requirement_re = re.compile(
            r"^("
            r"git\+\S+#egg=\S+"  # git URL
            r"|[A-Za-z0-9][A-Za-z0-9._-]*(\[[^\]]+\])?"
            r"((==|>=|<=|>|<|~=)[^\s#]+)?"  # pinned, ranged, or bare
            r")$"
        )
        for cell in manifest.cells:
            for line in effective_lines(cell.render_packages()) + effective_lines(
                cell.render_overrides()
            ):
                assert requirement_re.match(line), f"not a valid requirement: {line!r}"
