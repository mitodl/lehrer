"""``lehrer build`` — drive the Dagger build pipelines.

These commands are thin, well-labelled wrappers around ``dagger call`` against
the lehrer Dagger module (``src/lehrer/main.py``).  They run from the repo root
so relative ``--source`` / config paths resolve the same way they would for a
bare ``dagger call``.

Every wrapper forwards its trailing arguments straight through to Dagger, so
the full ``dagger call`` flag surface (``--help``, ``export``, ``publish``,
``--source``, ...) is available.  Use ``lehrer build call ...`` as a raw
escape hatch for any function not given a dedicated wrapper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import cyclopts

from lehrer.cli import _paths
from lehrer.cli._proc import run
from lehrer.core.build_manifest import load_manifest

app = cyclopts.App(
    name="build",
    help="Run the Dagger build pipelines (edx-platform, MFEs, codejail, notes).",
)

# Trailing tokens are passed verbatim to `dagger`, including ones that begin
# with a hyphen (e.g. `--deployment-name`, `export`, `--path`).
DaggerArgs = Annotated[str, cyclopts.Parameter(allow_leading_hyphen=True)]


def _dagger(*argv: str) -> None:
    run("dagger", *argv, cwd=str(_paths.repo_root()))


def _manifest_path(group: str) -> Path:
    return _paths.repo_root() / "deployments" / group / "build_manifest.yaml"


def _default_manifest_path() -> Path:
    """Return a manifest path when the caller didn't pass ``--manifest``.

    Prefers ``deployments/mit-ol`` (this repo's reference deployment) but
    falls back to auto-discovering any ``build_manifest.yaml`` under
    ``deployments/`` so generic/external operators without a ``mit-ol``
    directory still get a usable default.
    """
    mit_ol = _manifest_path("mit-ol")
    if mit_ol.exists():
        return mit_ol
    manifests = sorted(_paths.repo_root().glob("deployments/*/build_manifest.yaml"))
    if not manifests:
        msg = (
            "no build_manifest.yaml found under deployments/ and no --manifest "
            "path was given"
        )
        raise FileNotFoundError(msg)
    return manifests[0]


def _parse_cell(cell: str) -> tuple[str, str, str]:
    parts = cell.split("/")
    if len(parts) != 3:  # noqa: PLR2004
        msg = f"--cell must be <group>/<release>/<deployment>, got {cell!r}"
        raise ValueError(msg)
    group, release, deployment = parts
    return group, release, deployment


@app.command
def functions() -> None:
    """List all available Dagger functions (``dagger functions``)."""
    _dagger("functions")


@app.command
def platform(
    cell: Annotated[
        str | None,
        cyclopts.Parameter(
            help=(
                "<group>/<release>/<deployment> (e.g. mit-ol/master/mitxonline). "
                "Resolves deployments/<group>/build_manifest.yaml and forwards "
                "--build-manifest/--release-name/--deployment-name."
            )
        ),
    ] = None,
    *dagger_args: DaggerArgs,
) -> None:
    """Build the edx-platform LMS/CMS image (``platform build-platform``)."""
    if cell is None:
        _dagger("call", "platform", "build-platform", *dagger_args)
        return
    group, release, deployment = _parse_cell(cell)
    _dagger(
        "call",
        "platform",
        "build-platform",
        "--build-manifest",
        str(_manifest_path(group)),
        "--release-name",
        release,
        "--deployment-name",
        deployment,
        *dagger_args,
    )


@app.command
def check(
    cell: Annotated[
        str | None,
        cyclopts.Parameter(
            help=(
                "<group>/<release>/<deployment> (e.g. mit-ol/master/mitxonline). "
                "Resolves deployments/<group>/build_manifest.yaml and forwards "
                "--build-manifest/--release-name/--deployment-name."
            )
        ),
    ] = None,
    *dagger_args: DaggerArgs,
) -> None:
    """Verify a cell's requirements install + import (``platform check-deployment``)."""
    if cell is None:
        _dagger("call", "platform", "check-deployment", *dagger_args)
        return
    group, release, deployment = _parse_cell(cell)
    _dagger(
        "call",
        "platform",
        "check-deployment",
        "--build-manifest",
        str(_manifest_path(group)),
        "--release-name",
        release,
        "--deployment-name",
        deployment,
        *dagger_args,
    )


@app.command
def test(
    cell: Annotated[
        str | None,
        cyclopts.Parameter(
            help=(
                "<group>/<release>/<deployment> (e.g. mit-ol/master/mitxonline). "
                "Resolves deployments/<group>/build_manifest.yaml and forwards "
                "--build-manifest/--release-name/--deployment-name."
            )
        ),
    ] = None,
    *dagger_args: DaggerArgs,
) -> None:
    """Run the edx-platform test suite inside a built image (``platform test``).

    Defaults to a curated smoke subset; pass ``--full`` for the whole suite,
    ``--test-paths`` for specific apps/paths, or ``--service cms`` for Studio.
    Remember ``--custom-settings ./deployments/<group>/settings``.
    """
    if cell is None:
        _dagger("call", "platform", "test", *dagger_args)
        return
    group, release, deployment = _parse_cell(cell)
    _dagger(
        "call",
        "platform",
        "test",
        "--build-manifest",
        str(_manifest_path(group)),
        "--release-name",
        release,
        "--deployment-name",
        deployment,
        *dagger_args,
    )


@app.command(name="codejail-test")
def codejail_test(*dagger_args: DaggerArgs) -> None:
    """Run the codejailservice test suite in its image (``codejail test``)."""
    _dagger("call", "codejail", "test", *dagger_args)


@app.command(name="notes-test")
def notes_test(*dagger_args: DaggerArgs) -> None:
    """Run the edx-notes-api test suite in its image (``notes test``)."""
    _dagger("call", "notes", "test", *dagger_args)


@app.command
def cells(
    manifest: Annotated[
        str | None, cyclopts.Parameter(help="Path to a build_manifest.yaml.")
    ] = None,
) -> None:
    """Print the (release, deployment) cells in a build_manifest.yaml.

    The consumption API external consumers (e.g. ol-infrastructure's Concourse
    pipeline generator) cross-check their topology coordinates against — call
    ``lehrer.core.build_manifest.load_manifest`` directly instead of shelling
    out to this command when consuming from Python.
    """
    path = Path(manifest) if manifest else _default_manifest_path()
    build_manifest = load_manifest(path)
    for build_cell in build_manifest.cells:
        print(f"{build_cell.release}/{build_cell.deployment}")  # noqa: T201


@app.command(name="mfe-legacy")
def mfe_legacy(*dagger_args: DaggerArgs) -> None:
    """Build a legacy MFE ``dist/`` (``mfe build-legacy``)."""
    _dagger("call", "mfe", "build-legacy", *dagger_args)


@app.command(name="mfe-site")
def mfe_site(*dagger_args: DaggerArgs) -> None:
    """Build an OEP-65 Site Project (``mfe build-site``)."""
    _dagger("call", "mfe", "build-site", *dagger_args)


@app.command
def codejail(*dagger_args: DaggerArgs) -> None:
    """Build the codejail service image (``codejail build``)."""
    _dagger("call", "codejail", "build", *dagger_args)


@app.command
def notes(*dagger_args: DaggerArgs) -> None:
    """Build the edx-notes-api image (``notes build``)."""
    _dagger("call", "notes", "build", *dagger_args)


@app.command
def call(*dagger_args: DaggerArgs) -> None:
    """Raw ``dagger call`` passthrough for any function or chain."""
    _dagger("call", *dagger_args)
