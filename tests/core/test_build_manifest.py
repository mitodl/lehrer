from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from lehrer.core.build_manifest import (
    BuildManifest,
    Cell,
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

# (release, deployment) -> expected resolved matrix values, per plans/06-build-manifest.md
MIT_OL_MATRIX = {
    ("master", "mitxonline"): {
        "platform_repo": "https://github.com/openedx/edx-platform",
        "platform_branch": "master",
        "python_version": "3.12",
        "translations_repo": "https://github.com/mitodl/mitxonline-translations",
        "packages_to_remove": ["edx-name-affirmation"],
        "theme_repo": "https://github.com/mitodl/mitxonline-theme",
        "theme_branch": "main",
        "settings_namespace": "mitol",
    },
    ("master", "mitx"): {
        "platform_repo": "https://github.com/openedx/edx-platform",
        "platform_branch": "master",
        "python_version": "3.12",
        "translations_repo": "https://github.com/openedx/openedx-translations",
        "packages_to_remove": [],
        "theme_repo": "https://github.com/mitodl/mitx-theme",
        "theme_branch": "master",
        "settings_namespace": "mitol",
    },
    ("master", "mitx-staging"): {
        "platform_repo": "https://github.com/openedx/edx-platform",
        "platform_branch": "master",
        "python_version": "3.12",
        "translations_repo": "https://github.com/openedx/openedx-translations",
        "packages_to_remove": [],
        "theme_repo": "https://github.com/mitodl/mitx-theme",
        "theme_branch": "master",
        "settings_namespace": "mitol",
    },
    ("ulmo", "mitx"): {
        "platform_repo": "https://github.com/mitodl/edx-platform",
        "platform_branch": "mitx/ulmo",
        "python_version": "3.11",
        "translations_repo": "https://github.com/openedx/openedx-translations",
        "packages_to_remove": [],
        "theme_repo": "https://github.com/mitodl/mitx-theme",
        "theme_branch": "ulmo",
        "settings_namespace": "mitol",
    },
    ("ulmo", "mitx-staging"): {
        "platform_repo": "https://github.com/mitodl/edx-platform",
        "platform_branch": "mitx/ulmo",
        "python_version": "3.11",
        "translations_repo": "https://github.com/openedx/openedx-translations",
        "packages_to_remove": [],
        "theme_repo": "https://github.com/mitodl/mitx-theme",
        "theme_branch": "ulmo",
        "settings_namespace": "mitol",
    },
    ("ulmo", "xpro"): {
        "platform_repo": "https://github.com/openedx/edx-platform",
        "platform_branch": "release/ulmo",
        "python_version": "3.11",
        "translations_repo": "https://github.com/openedx/openedx-translations",
        "packages_to_remove": [],
        "theme_repo": "https://github.com/mitodl/mitxpro-theme",
        "theme_branch": "ulmo",
        "settings_namespace": "mitol",
    },
    ("verawood", "mitx"): {
        "platform_repo": "https://github.com/mitodl/edx-platform",
        "platform_branch": "mitx/verawood",
        "python_version": "3.12",
        "translations_repo": "https://github.com/openedx/openedx-translations",
        "packages_to_remove": [],
        "theme_repo": "https://github.com/mitodl/mitx-theme",
        "theme_branch": "verawood",
        "settings_namespace": "mitol",
    },
    ("verawood", "mitx-staging"): {
        "platform_repo": "https://github.com/mitodl/edx-platform",
        "platform_branch": "mitx/verawood",
        "python_version": "3.12",
        "translations_repo": "https://github.com/openedx/openedx-translations",
        "packages_to_remove": [],
        "theme_repo": "https://github.com/mitodl/mitx-theme",
        "theme_branch": "verawood",
        "settings_namespace": "mitol",
    },
    ("verawood", "xpro"): {
        "platform_repo": "https://github.com/openedx/edx-platform",
        "platform_branch": "release/verawood",
        "python_version": "3.12",
        "translations_repo": "https://github.com/openedx/openedx-translations",
        "packages_to_remove": [],
        "theme_repo": "https://github.com/mitodl/mitxpro-theme",
        "theme_branch": "verawood",
        "settings_namespace": "mitol",
    },
}


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


class TestMatrixValues:
    """Pin the values migrated from ol-infrastructure so drift is caught."""

    @pytest.mark.parametrize(("release", "deployment"), MIT_OL_CELLS)
    def test_resolved_matrix_matches_spec(
        self, mit_ol_manifest: BuildManifest, release: str, deployment: str
    ) -> None:
        cell = mit_ol_manifest.resolve_cell(release, deployment)
        expected = MIT_OL_MATRIX[(release, deployment)]
        for field, value in expected.items():
            assert cell.resolved(field, mit_ol_manifest) == value


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
