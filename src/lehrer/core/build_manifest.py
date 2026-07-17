"""Schema for the operator-supplied ``build_manifest.yaml``.

A build manifest is the declarative, single source of truth for an operator's
edx-platform build cells: one entry per ``(release, deployment)`` pair naming
the platform repo/branch, python/node versions, theme, translations, and the
verbatim pip requirement lines that make up that cell's Python dependency set.

These Pydantic models serve the same two purposes as :mod:`lehrer.core.mfe_config`:

* **Validation** — the dagger-coupled build functions parse a manifest through
  :class:`BuildManifest` so a malformed file fails fast with field-level
  errors.
* **Schema** — :func:`json_schema` emits a JSON Schema an operator can
  reference from their YAML (via a ``# yaml-language-server: $schema=``
  comment). Run ``python -m lehrer.core.build_manifest`` to print it.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ``node_version`` feeds ``install_deps``, which resolves it to a full release
# before ``nodeenv --node=<v> --prebuilt`` (nodeenv only fetches a prebuilt
# tarball for a full ``MAJOR.MINOR.PATCH``). A bare major (``"24"``) or
# ``MAJOR.MINOR`` prefix resolves to the latest matching release — mirroring the
# nodejs ``github_release`` resource the Concourse pipeline historically used;
# a full ``MAJOR.MINOR.PATCH`` is used verbatim (a reproducible pin). Each
# component is a SemVer numeric identifier — ASCII ``[0-9]`` (not ``\d``, which
# is Unicode-aware) and no leading zeros — so a value like ``"024.18.0"`` that
# would slip past to a nonexistent nodeenv download URL fails fast at
# manifest-load instead of deep in the Node build step.
NODE_VERSION_PATTERN = r"^(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*)){0,2}$"


class CellDefaults(BaseModel):
    """Group-wide values a cell may override."""

    model_config = ConfigDict(extra="forbid")

    settings_namespace: str | None = None
    platform_repo: str | None = None
    translations_repo: str | None = None
    translations_branch: str | None = None
    node_version: str | None = Field(default=None, pattern=NODE_VERSION_PATTERN)
    extra_ssh_hosts: list[str] = Field(default_factory=list)
    extra_npm_packages: list[str] = Field(default_factory=list)


class Cell(BaseModel):
    """One ``(release, deployment)`` edx-platform build cell."""

    model_config = ConfigDict(extra="forbid")

    release: str
    deployment: str
    packages: list[str] = Field(
        min_length=1,
        description=(
            "Verbatim active pip requirement lines (specifier + optional "
            "inline '# comment'), order-preserved."
        ),
    )
    overrides: list[str] = Field(default_factory=list)

    # Optional per-cell overrides of every CellDefaults field.
    settings_namespace: str | None = None
    platform_repo: str | None = None
    translations_repo: str | None = None
    translations_branch: str | None = None
    node_version: str | None = Field(default=None, pattern=NODE_VERSION_PATTERN)
    extra_ssh_hosts: list[str] | None = None
    extra_npm_packages: list[str] | None = None

    # Cell-only fields — no group-wide default.
    platform_branch: str | None = None
    python_version: str | None = None
    theme_repo: str | None = None
    theme_branch: str | None = None
    packages_to_remove: list[str] = Field(default_factory=list)

    def resolved(self, field: str, manifest: BuildManifest) -> object:
        """Resolve ``field`` via cell -> defaults -> release fallback.

        ``python_version`` falls back to ``manifest.release_python[release]``.
        Fields with no ``CellDefaults`` counterpart (``platform_branch``,
        ``theme_repo``, ``theme_branch``, ``packages_to_remove``) return the
        cell's own value unchanged.

        A field explicitly set on the cell wins even when its value is an
        empty list — ``model_fields_set`` (not just non-emptiness) is what
        distinguishes "explicitly overridden to []" from "not set here".
        """
        cell_value = getattr(self, field)
        if field in self.model_fields_set and cell_value is not None:
            return cell_value
        if field == "python_version":
            return manifest.release_python.get(self.release)
        if hasattr(manifest.defaults, field):
            return getattr(manifest.defaults, field)
        return cell_value

    def render_packages(self) -> str:
        """Render ``packages`` as pip-requirements-file text."""
        return "\n".join(self.packages) + "\n"

    def render_overrides(self) -> str:
        """Render ``overrides`` as pip-requirements-file text."""
        return "\n".join(self.overrides) + "\n"


class BuildManifest(BaseModel):
    """Top-level schema for an operator's ``build_manifest.yaml``."""

    model_config = ConfigDict(extra="forbid")

    version: int
    defaults: CellDefaults = Field(default_factory=CellDefaults)
    release_python: dict[str, str] = Field(default_factory=dict)
    cells: list[Cell] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_duplicate_cells(self) -> BuildManifest:
        seen: set[tuple[str, str]] = set()
        for cell in self.cells:
            key = (cell.release, cell.deployment)
            if key in seen:
                msg = f"duplicate cell for (release, deployment) = {key!r}"
                raise ValueError(msg)
            seen.add(key)
        return self

    def resolve_cell(self, release_name: str, deployment_name: str) -> Cell:
        """Return the cell matching ``(release_name, deployment_name)``.

        Raises a clear ``ValueError`` listing the available cells when no
        match exists — replaces the opaque "missing .txt" failure a bad
        ``--release-name``/``--deployment-name`` pair produces today.
        """
        for cell in self.cells:
            if cell.release == release_name and cell.deployment == deployment_name:
                return cell
        available = ", ".join(
            f"{cell.release}/{cell.deployment}" for cell in self.cells
        )
        msg = (
            f"no cell for release={release_name!r} deployment={deployment_name!r} "
            f"— available cells: {available}"
        )
        raise ValueError(msg)


def load_manifest(path: str | Path) -> BuildManifest:
    """Load and validate a ``build_manifest.yaml`` from ``path``.

    The typed consumption API external callers (e.g. ol-infrastructure's
    Concourse pipeline generator) should use to cross-check their topology
    coordinates against the manifest's cells.
    """
    with Path(path).open() as f:
        return BuildManifest.model_validate(yaml.safe_load(f))


def json_schema() -> dict:
    """Return the JSON Schema for ``build_manifest.yaml``."""
    return BuildManifest.model_json_schema()


if __name__ == "__main__":
    import json

    print(json.dumps(json_schema(), indent=2))  # noqa: T201
