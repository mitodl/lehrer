"""Schema for the operator-supplied legacy MFE ``build_config.yaml``.

These Pydantic models are the single source of truth for the structure of an
operator's legacy MFE build configuration.  They serve two purposes:

* **Validation** — :func:`OpenedxMfe.build_legacy_configured` parses the config
  through :class:`BuildConfig`, so a malformed file fails fast with field-level
  errors instead of a bare ``KeyError`` / ``AttributeError`` mid-build.
* **Schema** — :meth:`BuildConfig.model_json_schema` emits a JSON Schema an
  operator can reference from their YAML (via a
  ``# yaml-language-server: $schema=`` comment) for editor and agentic
  validation.  Run ``python -m lehrer.core.mfe_config`` to print it.
"""

from __future__ import annotations

import posixpath

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _relative_mfe_path(value: str) -> str:
    """Return ``value`` if it stays within the MFE build root, else raise.

    Destinations come from operator config, so reject absolute paths or ones
    that escape the build root via ``..``.
    """
    normalized = posixpath.normpath(value)
    if (
        posixpath.isabs(normalized)
        or normalized == ".."
        or normalized.startswith("../")
    ):
        msg = f"{value!r} must be a relative path within the MFE root"
        raise ValueError(msg)
    return value


class SlotFileByRelease(BaseModel):
    """A slot file whose source filename is selected by Open edX release name."""

    model_config = ConfigDict(extra="forbid")

    dest: str = Field(
        description="Destination filename, relative to the MFE build root.",
    )
    by_release: dict[str, str] = Field(
        min_length=1,
        description=(
            "Map of release name to source filename in the slot config. The "
            "'default' key is the fallback used when no release matches."
        ),
    )

    @field_validator("dest")
    @classmethod
    def _dest_within_root(cls, value: str) -> str:
        return _relative_mfe_path(value)

    def resolve(self, release_name: str) -> str:
        """Return the ``source:dest`` copy spec for ``release_name``."""
        source = self.by_release.get(release_name.lower()) or self.by_release.get(
            "default"
        )
        if source is None:
            msg = (
                f"No source for {self.dest!r} matching release {release_name!r} "
                "and no 'default' variant"
            )
            raise ValueError(msg)
        return f"{source}:{self.dest}"


class MfeBuildConfig(BaseModel):
    """Per-MFE build customizations, keyed by MFE application name."""

    model_config = ConfigDict(extra="forbid")

    extra_slot_files: list[str | SlotFileByRelease] = Field(
        default_factory=list,
        description=(
            "Files injected from the slot config into the MFE root before "
            "building. A plain string copies a file as-is, or use 'source:dest' "
            "to rename on copy; a mapping selects the source by release name."
        ),
    )
    extra_npm_bundles: list[str] = Field(
        default_factory=list,
        description=(
            "Pre-built npm bundles to pack and copy as static assets. Each "
            "entry has the form 'npm_package_spec|target_directory'."
        ),
    )

    def resolve_extra_slot_files(self, release_name: str) -> list[str]:
        """Resolve ``extra_slot_files`` into ``source:dest`` (or bare) specs."""
        return [
            item if isinstance(item, str) else item.resolve(release_name)
            for item in self.extra_slot_files
        ]


class BuildConfig(BaseModel):
    """Top-level schema for an operator's legacy MFE ``build_config.yaml``."""

    model_config = ConfigDict(extra="forbid")

    styles: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-deployment stylesheet override copied into the MFE root, keyed "
            "by deployment name; the value is a filename in the slot config."
        ),
    )
    mfes: dict[str, MfeBuildConfig] = Field(
        default_factory=dict,
        description="Per-MFE customizations keyed by MFE application name.",
    )

    def mfe(self, mfe_name: str) -> MfeBuildConfig:
        """Return the config for ``mfe_name``, or an empty default if unset."""
        return self.mfes.get(mfe_name.lower(), MfeBuildConfig())


def json_schema() -> dict:
    """Return the JSON Schema for ``build_config.yaml``."""
    return BuildConfig.model_json_schema()


if __name__ == "__main__":
    import json

    print(json.dumps(json_schema(), indent=2))  # noqa: T201
