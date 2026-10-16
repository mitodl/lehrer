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


@pytest.fixture(scope="module")
def mit_ol_manifest() -> BuildManifest:
    return load_manifest(REPO_ROOT / "deployments" / "mit-ol" / "build_manifest.yaml")


@pytest.fixture(scope="module")
def generic_manifest() -> BuildManifest:
    return load_manifest(REPO_ROOT / "deployments" / "generic" / "build_manifest.yaml")


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


class TestNodeVersionValidation:
    """``node_version`` must reject anything that can't resolve to a real
    prebuilt tarball, on both ``CellDefaults`` and the per-cell ``Cell``
    override — the whole point of the pattern is to fail at manifest-load
    rather than deep in the Node build step."""

    VALID = ["24", "24.4", "24.18.0", "20"]
    # bare-major/minor prefixes resolve at build time; these are shapes that
    # would otherwise slip through to a nonexistent nodeenv download URL.
    INVALID = [
        "",  # empty
        "v24",  # leading v
        "24.x",  # non-numeric component
        "24.",  # trailing dot
        "24.18.0.1",  # too many components
        "024.18.0",  # leading zero — not a SemVer numeric identifier
        "24.4.0-rc.1",  # pre-release suffix (no prebuilt release)
        "٢٤",  # Unicode digits (\d would match; [0-9] must not)
    ]

    @pytest.mark.parametrize("value", VALID)
    def test_cell_defaults_accepts_valid(self, value: str) -> None:
        assert CellDefaults(node_version=value).node_version == value

    @pytest.mark.parametrize("value", VALID)
    def test_cell_accepts_valid(self, value: str) -> None:
        cell = Cell(
            release="master", deployment="x", packages=["a==1"], node_version=value
        )
        assert cell.node_version == value

    @pytest.mark.parametrize("value", INVALID)
    def test_cell_defaults_rejects_invalid(self, value: str) -> None:
        with pytest.raises(ValidationError, match="node_version"):
            CellDefaults(node_version=value)

    @pytest.mark.parametrize("value", INVALID)
    def test_cell_rejects_invalid(self, value: str) -> None:
        with pytest.raises(ValidationError, match="node_version"):
            Cell(
                release="master", deployment="x", packages=["a==1"], node_version=value
            )


# ── settings-model cell ───────────────────────────────────────────────────────
#
# The committed model is generated from exactly one cell -- codegen is passed
# ``--openedx-plugins``, so its field set depends on that cell's installed
# plugins, not just on the release. Every case below is a coordinate that parses
# but that the drift gate could never act on, which is the whole failure class
# the validator exists to close: silently marking every cell drift=False.


def _model_cell_manifest(
    release: str | None,
    deployment: str | None,
    cells: list[tuple[str, str]] | None = None,
    packages: list[str] | None = None,
) -> dict[str, object]:
    pkgs = ["django-aqueduct==0.15.0"] if packages is None else packages
    manifest: dict[str, object] = {
        "version": 1,
        "cells": [
            {"release": r, "deployment": d, "packages": pkgs}
            for r, d in cells or [("master", "mitx")]
        ],
    }
    if release is not None:
        manifest["settings_model_release"] = release
    if deployment is not None:
        manifest["settings_model_deployment"] = deployment
    return manifest


def test_settings_model_release_must_match_a_cell() -> None:
    with pytest.raises(ValidationError, match="settings_model_release"):
        BuildManifest.model_validate(_model_cell_manifest("mastr", "mitx"))


def test_settings_model_deployment_must_match_a_cell() -> None:
    # The regression that red-lit settings mit-ol/master/mitx: the deployment
    # half is what identifies the plugin set the model was rendered against.
    with pytest.raises(ValidationError, match="settings_model_deployment"):
        BuildManifest.model_validate(_model_cell_manifest("master", "mitxonlin"))


def test_settings_model_cell_rejects_a_non_cell_cross_product() -> None:
    # Both halves name something real; the pair names nothing. Two independent
    # membership tests would accept this, which is why the validator resolves
    # the pair.
    with pytest.raises(ValidationError, match="matches no cell"):
        BuildManifest.model_validate(
            _model_cell_manifest(
                "master",
                "mitx",
                cells=[("master", "mitxonline"), ("verawood", "mitx")],
            )
        )


def test_settings_model_release_without_a_deployment_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        BuildManifest.model_validate(_model_cell_manifest("master", None))


def test_settings_model_deployment_without_a_release_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        BuildManifest.model_validate(_model_cell_manifest(None, "mitx"))


def test_settings_model_cell_must_use_aqueduct() -> None:
    # The cell exists, so nothing above fires -- but a cell that does not
    # install the framework is filtered out of the settings matrix, so the gate
    # would be enabled on no cell at all.
    with pytest.raises(ValidationError, match="django-aqueduct"):
        BuildManifest.model_validate(
            _model_cell_manifest("master", "mitx", packages=["a==1"])
        )


def test_settings_model_cell_matching_a_cell_is_accepted() -> None:
    manifest = BuildManifest.model_validate(_model_cell_manifest("master", "mitx"))
    assert manifest.settings_model_release == "master"
    assert manifest.settings_model_deployment == "mitx"


def test_no_settings_model_cell_is_accepted() -> None:
    manifest = BuildManifest.model_validate(_model_cell_manifest(None, None))
    assert manifest.settings_model_release is None
    assert manifest.settings_model_deployment is None


@pytest.mark.parametrize("fixture", ["mit_ol_manifest", "generic_manifest"])
def test_repo_manifests_name_an_aqueduct_cell(
    fixture: str, request: pytest.FixtureRequest
) -> None:
    # Guards the real manifests, which is where the mistake would be made: the
    # committed model's source cell has to be one the settings matrix enumerates.
    manifest: BuildManifest = request.getfixturevalue(fixture)
    assert manifest.settings_model_release is not None
    assert manifest.settings_model_deployment is not None
    cell = manifest.resolve_cell(
        manifest.settings_model_release, manifest.settings_model_deployment
    )
    assert cell.uses_aqueduct()


@pytest.mark.parametrize(
    ("packages", "overrides", "expected"),
    [
        (["django-aqueduct==0.13.0"], [], True),
        (["a==1"], ["django-aqueduct==0.13.0"], True),
        (["a==1"], [], False),
        (["a==1  # replaces django-aqueduct"], [], False),
    ],
)
def test_cell_uses_aqueduct(
    packages: list[str], overrides: list[str], expected: bool
) -> None:
    cell = Cell(release="r", deployment="d", packages=packages, overrides=overrides)
    assert cell.uses_aqueduct() is expected


def test_mit_ol_ulmo_xpro_does_not_use_aqueduct() -> None:
    manifest = load_manifest(REPO_ROOT / "deployments/mit-ol/build_manifest.yaml")
    assert not manifest.resolve_cell("ulmo", "xpro").uses_aqueduct()


def test_cell_uses_aqueduct_ignores_removed_package() -> None:
    cell = Cell(
        release="r",
        deployment="d",
        packages=["django-aqueduct==0.13.0"],
        packages_to_remove=["django-aqueduct"],
    )
    assert not cell.uses_aqueduct()
