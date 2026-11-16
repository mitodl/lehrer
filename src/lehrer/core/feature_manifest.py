"""Schema and resolution for feature manifests (plans/08-feature-manifest.md).

A feature's *definition* names every operation it needs across layers
(settings, ``FEATURES``, bootstrap data, MFE build input, runtime frontend
config, commands) and the typed parameters it accepts. A group's
``scopes.yaml`` declares opaque scope labels joined to build cells, and its
``adoption.yaml`` says which scopes take which features with which values.

These models serve the same two purposes as :mod:`lehrer.core.build_manifest`:
validation, and a JSON Schema per file (:func:`json_schemas`) for a
``# yaml-language-server: $schema=`` modeline.

Nothing here knows an operator's directory layout. :class:`Group` is handed
the files and the settings inventory by the CLI, which is where paths are
allowed to be reasoned about.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lehrer.bootstrap.spec import (
    IDENTITIES as BOOTSTRAP_IDENTITIES,
)
from lehrer.bootstrap.spec import (
    BootstrapSpec,
    check_fragment,
    merge,
)
from lehrer.core.build_manifest import BuildManifest, Cell
from lehrer.core.mfe_config import BuildConfig, MfeBuildConfig
from lehrer.core.plugin_imports import declares_distribution, normalize_distribution
from lehrer.core.settings_inventory import SettingField

ENTRY_POINT_GROUP = "lehrer.features"
"""Reserved: the entry-point group a plugin will advertise definitions in."""

Service = Literal["lms", "cms"]
Origin = Literal["upstream", "plugin", "operator"]
FrontendPath = Literal["legacy", "site"]

FEATURE_NAME = r"^[a-z0-9][a-z0-9-]*$"
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_WAFFLE_NAME = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+$")

SITE_CONFIG_SETTINGS: dict[str, str] = {
    "frontend_site_config": "FRONTEND_SITE_CONFIG",
    "mfe_config": "MFE_CONFIG",
    "mfe_config_overrides": "MFE_CONFIG_OVERRIDES",
}
RESERVED_SETTINGS = frozenset({*SITE_CONFIG_SETTINGS.values(), "ENABLE_MFE_CONFIG_API"})
"""Settings only ``site_config`` may write, so a feature cannot replace an
operator's whole runtime config through ``operations.settings``."""

_TRANSLATED_SITE_KEYS = {
    "SITE_NAME": "siteName",
    "BASE_URL": "baseUrl",
    "LMS_BASE_URL": "lmsBaseUrl",
    "LOGIN_URL": "loginUrl",
    "LOGOUT_URL": "logoutUrl",
    "STUDIO_BASE_URL": "cmsBaseUrl",
    "LOGO_URL": "headerLogoImageUrl",
    "ACCESS_TOKEN_COOKIE_NAME": "accessTokenCookieName",
    "LANGUAGE_PREFERENCE_COOKIE_NAME": "languagePreferenceCookieName",
    "USER_INFO_COOKIE_NAME": "userInfoCookieName",
    "CSRF_TOKEN_API_PATH": "csrfTokenApiPath",
    "REFRESH_ACCESS_TOKEN_API_PATH": "refreshAccessTokenApiPath",
    "SEGMENT_KEY": "segmentKey",
}
PROMOTED_SITE_KEYS = frozenset(
    {
        *_TRANSLATED_SITE_KEYS,
        *_TRANSLATED_SITE_KEYS.values(),
        "PARAGON_THEME_URLS",
        "theme",
    }
)
"""Keys the runtime config API lifts to site level, in both spellings.

Mirrors ``SITE_CONFIG_TRANSLATION_MAP`` and ``LEGACY_SITE_LEVEL_KEYS`` in
edx-platform's ``lms/djangoapps/mfe_config_api/views.py`` (master 449f6c42278).
These are operator topology (URLs, cookie names, logo), never a feature's.
"""


class FeatureManifestError(ValueError):
    """A definition, scope or adoption that does not compile."""


# --- Definitions -----------------------------------------------------------


class Parameter(BaseModel):
    """A typed value a definition accepts from adoption."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["integer", "string", "boolean", "enum"]
    choices: list[str] | None = Field(
        default=None, description="Allowed values; required for, and only for, enum."
    )
    default: Any = Field(
        default=None,
        description=(
            "Value when adoption supplies none. Null omits every key that "
            "uses it. Leave unset to make the parameter required."
        ),
    )
    description: str | None = None

    @property
    def required(self) -> bool:
        return "default" not in self.model_fields_set

    @model_validator(mode="after")
    def _choices_match_type(self) -> Parameter:
        if (self.type == "enum") != (self.choices is not None):
            msg = "choices is required for an enum parameter and only for one"
            raise ValueError(msg)
        if self.choices is not None and not self.choices:
            msg = "an enum parameter needs at least one choice"
            raise ValueError(msg)
        if not self.required:
            self.check(self.default)
        return self

    def check(self, value: Any) -> Any:
        """Return ``value`` if it fits this parameter, else raise."""
        if value is None:
            return value
        ok = {
            # bool is an int subclass; an integer parameter must not take one.
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "enum": value in (self.choices or []),
        }[self.type]
        if not ok:
            expected = f"one of {self.choices}" if self.type == "enum" else self.type
            msg = f"{value!r} is not {expected}"
            raise ValueError(msg)
        return value


class Requires(BaseModel):
    """What must hold wherever the feature is adopted. Not overridable."""

    model_config = ConfigDict(extra="forbid")

    plugins: list[str] = Field(
        default_factory=list,
        description="Distributions the scope's build cell must install.",
    )
    services: list[str] = Field(
        default_factory=list,
        description="Services the deployment must run, e.g. notes.",
    )
    frontends: list[str] = Field(
        default_factory=list,
        description="MFEs the feature touches; each must be in the scope's frontends.",
    )
    features: list[str] = Field(
        default_factory=list,
        description="Features that must also be adopted in the same scope.",
    )
    secret_settings: list[str] = Field(
        default_factory=list,
        description="Secret-valued settings the operator supplies out of band.",
    )


class Command(BaseModel):
    """Work that cannot converge on declared state. Listed, never run."""

    model_config = ConfigDict(extra="forbid")

    id: str
    service: str
    argv: list[str] = Field(min_length=1)
    recurring: bool = False


class Operations(BaseModel):
    """A feature's complete fan-out.

    Values may use ``${parameter}`` or a ``{by_parameter, cases}`` lookup on
    an enum parameter (except inside ``mfe_assets``, which takes
    ``${parameter}`` in strings only).
    """

    model_config = ConfigDict(extra="forbid")

    settings: dict[Service, dict[str, Any]] = Field(default_factory=dict)
    features: dict[Service, dict[str, Any]] = Field(
        default_factory=dict, description="FEATURES dict entries."
    )
    bootstrap: dict[str, Any] = Field(
        default_factory=dict,
        description="A lehrer.bootstrap BootstrapSpec fragment.",
    )
    mfe_build_env: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Build-time env vars per legacy MFE."
    )
    mfe_assets: dict[str, MfeBuildConfig] = Field(
        default_factory=dict,
        description="Slot files and npm bundles per legacy MFE.",
    )
    site_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Runtime config API keys: frontend_site_config, mfe_config, "
            "mfe_config_overrides, or by_release over blocks of those."
        ),
    )
    commands: list[Command] = Field(default_factory=list)


class FeatureDefinition(BaseModel):
    """The contract for one feature, independent of where it is on."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    feature: str = Field(pattern=FEATURE_NAME)
    summary: str
    origin: Origin
    provided_by: str | None = Field(
        default=None, description="The distribution; required when origin is plugin."
    )
    frontend_paths: list[FrontendPath] = Field(default_factory=list)
    parameters: dict[str, Parameter] = Field(default_factory=dict)
    requires: Requires = Field(default_factory=Requires)
    operations: Operations = Field(default_factory=Operations)

    @model_validator(mode="after")
    def _consistent(self) -> FeatureDefinition:
        if (self.origin == "plugin") != (self.provided_by is not None):
            msg = "provided_by is required for origin: plugin and only for it"
            raise ValueError(msg)
        if "enabled" in self.parameters:
            msg = "'enabled' is reserved in adoption and cannot be a parameter"
            raise ValueError(msg)
        ops = self.operations
        built = set(ops.mfe_build_env) | set(ops.mfe_assets)
        if built - set(self.requires.frontends):
            msg = (
                f"mfe_build_env/mfe_assets name {sorted(built - set(self.requires.frontends))} "
                "which requires.frontends does not list"
            )
            raise ValueError(msg)
        if built and "legacy" not in self.frontend_paths:
            msg = "mfe_build_env/mfe_assets apply to legacy builds; add legacy to frontend_paths"
            raise ValueError(msg)
        if self.requires.frontends and not self.frontend_paths:
            msg = "requires.frontends needs frontend_paths to say which builds are supported"
            raise ValueError(msg)
        _check_operation_shapes(ops, "definition")
        _check_parameter_references(
            ops.model_dump(exclude_defaults=True), self.parameters
        )
        return self


def _check_operation_shapes(ops: Operations, where: str) -> None:
    for svc, group in (*ops.settings.items(), *ops.features.items()):
        reserved = RESERVED_SETTINGS & set(group)
        if reserved:
            msg = f"{where}: {svc} {sorted(reserved)} may only be written through site_config"
            raise ValueError(msg)
    ids = [c.id for c in ops.commands]
    if len(ids) != len(set(ids)):
        msg = f"{where}: commands ids repeat: {ids}"
        raise ValueError(msg)
    for mfe, assets in ops.mfe_assets.items():
        for bundle in assets.extra_npm_bundles:
            spec, sep, target = bundle.partition("|")
            if not (sep and spec and target):
                msg = f"{where}: mfe_assets.{mfe} npm bundle {bundle!r} is not 'spec|target'"
                raise ValueError(msg)
    _check_site_config(ops.site_config, where)


def _check_site_config(site_config: Mapping[str, Any], where: str) -> None:
    blocks: Iterable[tuple[str, Mapping[str, Any]]]
    if "by_release" in site_config:
        if set(site_config) != {"by_release"}:
            msg = f"{where}: site_config.by_release cannot sit beside other keys"
            raise ValueError(msg)
        blocks = [
            (f"by_release.{r}", b or {}) for r, b in site_config["by_release"].items()
        ]
    else:
        blocks = [("", site_config)]
    for prefix, block in blocks:
        unknown = set(block) - set(SITE_CONFIG_SETTINGS)
        if unknown:
            msg = (
                f"{where}: site_config{'.' + prefix if prefix else ''} keys "
                f"{sorted(unknown)} are not one of {sorted(SITE_CONFIG_SETTINGS)}"
            )
            raise ValueError(msg)
        fsc = block.get("frontend_site_config") or {}
        if set(fsc) - {"commonAppConfig"}:
            msg = f"{where}: site_config.frontend_site_config may only write commonAppConfig.*"
            raise ValueError(msg)
        leaves = [*(fsc.get("commonAppConfig") or {}), *(block.get("mfe_config") or {})]
        for overrides in (block.get("mfe_config_overrides") or {}).values():
            leaves += list(overrides or {})
        promoted = PROMOTED_SITE_KEYS & set(leaves)
        if promoted:
            msg = (
                f"{where}: site_config may not write site-level keys {sorted(promoted)}"
            )
            raise ValueError(msg)


def _is_lookup(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"by_parameter", "cases"}


def _written_keys(group: Any) -> set[str]:
    """Every key a settings group can write, including each lookup case's."""
    if _is_lookup(group):
        keys: set[str] = set()
        for case in group["cases"].values():
            keys |= _written_keys(case or {})
        return keys
    return set(group) if isinstance(group, dict) else set()


def _check_parameter_references(tree: Any, parameters: Mapping[str, Parameter]) -> None:
    if _is_lookup(tree):
        name = tree["by_parameter"]
        param = parameters.get(name)
        if param is None or param.type != "enum":
            msg = f"by_parameter {name!r} is not an enum parameter"
            raise ValueError(msg)
        missing = set(param.choices or []) - set(tree["cases"])
        if missing and "default" not in tree["cases"]:
            msg = f"by_parameter {name!r} cases miss {sorted(missing)} and have no default"
            raise ValueError(msg)
        extra = set(tree["cases"]) - set(param.choices or []) - {"default"}
        if extra:
            msg = f"by_parameter {name!r} cases {sorted(extra)} are not choices"
            raise ValueError(msg)
        for case in tree["cases"].values():
            _check_parameter_references(case, parameters)
    elif isinstance(tree, dict):
        for value in tree.values():
            _check_parameter_references(value, parameters)
    elif isinstance(tree, list):
        for value in tree:
            _check_parameter_references(value, parameters)
    elif isinstance(tree, str):
        for name in _PLACEHOLDER.findall(tree):
            if name not in parameters:
                msg = f"${{{name}}} names no declared parameter"
                raise ValueError(msg)


# --- Scopes and adoption ---------------------------------------------------


class CellRef(BaseModel):
    """A ``build_manifest.yaml`` cell coordinate."""

    model_config = ConfigDict(extra="forbid")

    release: str
    deployment: str


class SharedLegacy(BaseModel):
    """A legacy MFE built once under ``legacy`` and served by several scopes."""

    model_config = ConfigDict(extra="forbid")

    legacy: str


class SiteProject(BaseModel):
    """An MFE served from the frontend-base Site Project artifact ``site``."""

    model_config = ConfigDict(extra="forbid")

    site: str


FrontendBinding = Literal["legacy"] | SharedLegacy | SiteProject


def binding_path(binding: FrontendBinding) -> FrontendPath:
    return "site" if isinstance(binding, SiteProject) else "legacy"


class Scope(BaseModel):
    """An operator-chosen label lehrer stores and matches but never parses."""

    model_config = ConfigDict(extra="forbid")

    cell: CellRef
    frontends: dict[str, FrontendBinding] = Field(
        default_factory=dict,
        description=(
            "How each MFE features may touch is built: legacy (for this scope "
            "alone), {legacy: label} (one build shared under label) or "
            "{site: label} (a Site Project artifact)."
        ),
    )


class ScopesFile(BaseModel):
    """A group's ``features/scopes.yaml``."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    scopes: dict[str, Scope] = Field(min_length=1)
    sets: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Named, unordered lists of scopes. Sets cannot contain sets.",
    )

    @model_validator(mode="after")
    def _sets_name_scopes(self) -> ScopesFile:
        shared = set(self.sets) & set(self.scopes)
        if shared:
            msg = f"{sorted(shared)} name both a scope and a set"
            raise ValueError(msg)
        for name, members in self.sets.items():
            unknown = set(members) - set(self.scopes)
            if unknown:
                msg = f"set {name!r} lists {sorted(unknown)}, which are not scopes"
                raise ValueError(msg)
            if not members:
                msg = f"set {name!r} is empty"
                raise ValueError(msg)
        return self


class AdoptionFile(BaseModel):
    """A group's ``features/adoption.yaml``: scope or set -> feature -> values.

    A feature block holds parameter values, plus the reserved keys
    ``enabled`` (false records a deliberate non-adoption) and ``operations``
    (an override merged over the definition).
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    adoption: dict[str, dict[str, dict[str, Any] | None]] = Field(default_factory=dict)


# --- Merge and substitution ------------------------------------------------


def _slot_dest(entry: Any) -> str:
    if isinstance(entry, dict):
        return entry["dest"]
    source, _, dest = str(entry).partition(":")
    return dest or source


def _list_identity(path: tuple[str, ...]) -> Callable[[Any], object] | None:
    match path:
        case ("commands",):
            return lambda e: e["id"]
        case ("mfe_assets", _, "extra_slot_files"):
            return _slot_dest
        case ("mfe_assets", _, "extra_npm_bundles"):
            return lambda e: str(e).partition("|")[2]
        case ("bootstrap", list_name) if list_name in BOOTSTRAP_IDENTITIES:
            key = {
                "users": "username",
                "oauth_applications": "name",
                "third_party_auth_providers": "backend_name",
                "service_access_tokens": "username",
                "waffle_flags": "name",
            }[list_name]
            return lambda e: e[key]
    return None


def merge_operations(
    base: Mapping[str, Any], override: Mapping[str, Any], path: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Merge ``override`` over ``base`` by the rules in plans/08 §4.3.2.

    Mappings merge recursively and the override wins at each leaf. A list
    with an identity merges by it: a matching entry is replaced whole and an
    unmatched one appended, defaults first. Any other list is a leaf.
    """
    merged = dict(base)
    for key, value in override.items():
        here = (*path, key)
        current = merged.get(key)
        if here == ("site_config",) and isinstance(current, dict):
            current, value = _same_site_config_form(current, value)
        if (
            isinstance(current, dict)
            and isinstance(value, dict)
            and not _is_lookup(value)
        ):
            merged[key] = merge_operations(current, value, here)
        elif isinstance(current, list) and isinstance(value, list):
            identity = _list_identity(here)
            if identity is None:
                merged[key] = value
            else:
                keyed = _keyed(identity, here)
                replacements = {keyed(e): e for e in value}
                kept = [replacements.pop(keyed(e), e) for e in current]
                merged[key] = kept + [e for e in value if keyed(e) in replacements]
        else:
            merged[key] = value
    return merged


def _keyed(
    identity: Callable[[Any], object], path: tuple[str, ...]
) -> Callable[[Any], object]:
    def key(entry: Any) -> object:
        try:
            return identity(entry)
        except (KeyError, TypeError):
            msg = f"{'.'.join(path)}: entry {entry!r} has no identity to merge on"
            raise FeatureManifestError(msg) from None

    return key


def _same_site_config_form(
    base: dict[str, Any], override: Any
) -> tuple[dict[str, Any], Any]:
    """Put both sides of a site_config merge in ``by_release`` form if either is.

    A flat block applies to every release, so it becomes that block under each
    release the other side names plus ``default``. Without this, a flat
    override of a ``by_release`` definition merges in beside ``by_release``,
    where resolution never reads it.
    """
    if not isinstance(override, dict) or (
        "by_release" not in base and "by_release" not in override
    ):
        return base, override
    releases = {"default"}
    for side in (base, override):
        releases |= set(side.get("by_release") or {})

    def spread(block: dict[str, Any]) -> dict[str, Any]:
        if "by_release" in block:
            return block
        return {"by_release": {release: block for release in sorted(releases)}}

    return spread(base), spread(override)


class _Omit:
    """A value that resolved to null: the key holding it is dropped."""


OMIT = _Omit()


def substitute(
    value: Any, params: Mapping[str, Any], path: tuple[str, ...] = ()
) -> Any:
    """Replace ``${name}`` and ``by_parameter`` lookups with parameter values.

    A string that is exactly ``${name}`` takes the parameter's typed value;
    one embedding it takes its string form. Either form with a null value,
    and a lookup case of null, return :data:`OMIT`, which drops the key or
    list entry holding it.
    """
    if _is_lookup(value):
        cases = value["cases"]
        chosen = params[value["by_parameter"]]
        if chosen is None:
            return OMIT
        case = cases[chosen] if chosen in cases else cases["default"]
        return OMIT if case is None else substitute(case, params, path)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            resolved = substitute(item, params, (*path, key))
            if resolved is not OMIT:
                out[key] = resolved
        return out
    if isinstance(value, list):
        items = [substitute(item, params, path) for item in value]
        return [item for item in items if item is not OMIT]
    if not isinstance(value, str):
        return value
    whole = _PLACEHOLDER.fullmatch(value)
    if whole:
        result = params[whole.group(1)]
        if result is None:
            return OMIT
        _check_bootstrap_value(result, path)
        return result
    names = _PLACEHOLDER.findall(value)
    if any(params[name] is None for name in names):
        return OMIT
    for name in names:
        _check_bootstrap_value(params[name], path)
    return _PLACEHOLDER.sub(lambda m: str(params[m.group(1)]), value)


def _check_bootstrap_value(value: Any, path: tuple[str, ...]) -> None:
    """Keep parameters from smuggling secrets or settings lookups into bootstrap.

    The runner reads a ``*_env`` field as a variable name and resolves
    ``{SETTING}`` in other strings with ``str.format_map``, so a brace in a
    parameter would become a Django settings lookup.
    """
    if not path or path[0] != "bootstrap" or not isinstance(value, str):
        return
    if path[-1].endswith("_env"):
        if not _ENV_NAME.fullmatch(value):
            msg = f"{'.'.join(path)}: {value!r} is not an environment variable name"
            raise FeatureManifestError(msg)
    elif "{" in value or "}" in value:
        msg = f"{'.'.join(path)}: a parameter value may not contain braces ({value!r})"
        raise FeatureManifestError(msg)


# --- Resolution ------------------------------------------------------------


@dataclass(frozen=True)
class Definition:
    """A loaded definition and the file it came from."""

    model: FeatureDefinition
    source: Path


@dataclass
class Adoption:
    """One feature as a scope takes it."""

    feature: str
    params: dict[str, Any]
    operations: dict[str, Any]
    via: list[str]
    """The scope and/or set blocks it came from, for explain."""


@dataclass
class ResolvedFeature:
    """A feature's operations with parameters and releases resolved for a scope."""

    feature: str
    source: Path
    params: dict[str, Any]
    requires: Requires
    settings: dict[str, dict[str, Any]]
    features: dict[str, dict[str, Any]]
    site_config: dict[str, dict[str, Any]]
    """LMS setting name (e.g. FRONTEND_SITE_CONFIG) -> value."""
    bootstrap: BootstrapSpec | None
    mfe_build_env: dict[str, dict[str, str]]
    mfe_assets: dict[str, dict[str, list[dict[str, str]]]]
    commands: list[Command]


@dataclass
class ResolvedScope:
    scope: str
    cell: Cell
    frontends: dict[str, FrontendBinding]
    features: list[ResolvedFeature]
    owners: dict[tuple[str, ...], list[str]] = field(default_factory=dict)
    """Every target written, with the features writing it (equal values)."""

    def bootstrap(self) -> BootstrapSpec:
        """The merged fragment of every adopted feature, by feature name."""
        return merge(*(f.bootstrap for f in self.features if f.bootstrap))


_Owner = tuple[str, Path]
_BASELINE: _Owner = ("build_config.yaml", Path("build_config.yaml"))


class _Claims:
    """Targets written in one scope, refusing two owners with unequal values."""

    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.held: dict[tuple[str, ...], tuple[_Owner, Any]] = {}
        self.below: dict[tuple[str, ...], list[tuple[_Owner, Any]]] = {}
        """Per proper prefix, every write beneath it."""
        self.owners: dict[tuple[str, ...], list[str]] = {}

    def add(self, target: tuple[str, ...], owner: _Owner, value: Any) -> None:
        first, held = self.held.setdefault(target, (owner, value))
        if first[0] != owner[0] and held != value:
            self._refuse(" ".join(target), (first, held), (owner, value))
        # A scalar at K and a mapping leaf at K.x are different targets, but
        # one replaces the other, so they compete as much as equal targets.
        for i in range(1, len(target)):
            above = self.held.get(target[:i])
            if above and above[0][0] != owner[0]:
                self._refuse(" ".join(target[:i]), above, (owner, value))
        for below in self.below.get(target, []):
            if below[0][0] != owner[0]:
                self._refuse(" ".join(target), below, (owner, value))
        for i in range(1, len(target)):
            self.below.setdefault(target[:i], []).append((owner, value))
        if owner[0] not in self.owners.setdefault(target, []):
            self.owners[target].append(owner[0])

    def check_legacy_overrides(self) -> None:
        """``MFE_CONFIG.K`` reaches every legacy MFE, so it competes with
        another feature's ``MFE_CONFIG_OVERRIDES.<mfe>.K`` there."""
        shared = {
            t[2:]: v for t, v in self.held.items() if t[:2] == ("legacy-config", "*")
        }
        for target, (owner, value) in self.held.items():
            if target[0] != "legacy-config" or target[1] == "*":
                continue
            everywhere = shared.get(target[2:])
            if everywhere and everywhere[0][0] != owner[0] and everywhere[1] != value:
                self._refuse(
                    f"legacy MFE config {'.'.join(target[2:])} for {target[1]}",
                    everywhere,
                    (owner, value),
                )

    def _refuse(
        self, what: str, first: tuple[_Owner, Any], second: tuple[_Owner, Any]
    ) -> None:
        (name_a, path_a), value_a = first
        (name_b, path_b), value_b = second
        msg = (
            f"{self.scope}: conflict on {what}: {name_a} ({path_a}) sets "
            f"{value_a!r}, {name_b} ({path_b}) sets {value_b!r}"
        )
        raise FeatureManifestError(msg)


@dataclass
class Group:
    """Everything one group's features compile against.

    :param inventories: Per service, the settings inventory of the group's
        aqueduct entry classes (see :mod:`lehrer.core.settings_inventory`).
    :param slot_dir: The legacy slot config directory slot files resolve in.
    :param baseline: The group's ``build_config.yaml``, for dest/target
        conflicts with the unconditional customisation.
    """

    definitions: dict[str, Definition]
    scopes: ScopesFile
    adoption: AdoptionFile
    manifest: BuildManifest
    inventories: Mapping[str, Mapping[str, SettingField]]
    slot_dir: Path | None = None
    baseline: BuildConfig | None = None

    # -- adoption ----------------------------------------------------------

    def adopted(self, scope: str) -> dict[str, Adoption]:
        """The features ``scope`` takes, with parameters and overrides merged."""
        if scope not in self.scopes.scopes:
            msg = f"unknown scope {scope!r}; scopes.yaml declares {sorted(self.scopes.scopes)}"
            raise FeatureManifestError(msg)
        unknown = (
            set(self.adoption.adoption)
            - set(self.scopes.scopes)
            - set(self.scopes.sets)
        )
        if unknown:
            msg = f"adoption.yaml names {sorted(unknown)}, which are neither scopes nor sets"
            raise FeatureManifestError(msg)
        sets = [s for s, members in self.scopes.sets.items() if scope in members]
        names = set(self.adoption.adoption.get(scope, {}))
        for set_name in sets:
            names |= set(self.adoption.adoption.get(set_name, {}))
        result = {}
        for name in sorted(names):
            adoption = self._adopt(scope, sets, name)
            if adoption is not None:
                result[name] = adoption
        return result

    def _adopt(self, scope: str, sets: list[str], name: str) -> Adoption | None:
        definition = self.definitions.get(name)
        if definition is None:
            msg = f"{scope}: adoption names {name!r}, which no definition declares"
            raise FeatureManifestError(msg)
        from_sets = [
            (s, self.adoption.adoption[s][name] or {})
            for s in sets
            if name in self.adoption.adoption.get(s, {})
        ]
        if len(from_sets) > 1:
            msg = (
                f"{scope}: {name!r} is adopted by more than one set containing it "
                f"({', '.join(s for s, _ in from_sets)})"
            )
            raise FeatureManifestError(msg)
        blocks = list(from_sets)
        if name in self.adoption.adoption.get(scope, {}):
            blocks.append((scope, self.adoption.adoption[scope][name] or {}))
        if blocks[-1][1].get("enabled", True) is False:
            return None
        params: dict[str, Any] = {}
        operations = definition.model.operations.model_dump(exclude_defaults=True)
        for where, block in blocks:
            for key, value in block.items():
                if key == "enabled":
                    if not isinstance(value, bool):
                        msg = f"{where}: {name}.enabled must be true or false"
                        raise FeatureManifestError(msg)
                    continue
                if key == "operations":
                    try:
                        override = Operations.model_validate(value)
                        _check_operation_shapes(override, f"{where}: {name}")
                    except (ValidationError, ValueError) as error:
                        raise FeatureManifestError(str(error)) from None
                    try:
                        operations = merge_operations(operations, value)
                    except FeatureManifestError as error:
                        msg = f"{where}: {name}: {error}"
                        raise FeatureManifestError(msg) from None
                    continue
                param = definition.model.parameters.get(key)
                if param is None:
                    msg = (
                        f"{where}: {name} has no parameter {key!r}; it declares "
                        f"{sorted(definition.model.parameters) or 'none'}"
                    )
                    raise FeatureManifestError(msg)
                try:
                    params[key] = param.check(value)
                except ValueError as error:
                    msg = f"{where}: {name}.{key}: {error}"
                    raise FeatureManifestError(msg) from None
        for key, param in definition.model.parameters.items():
            if key not in params:
                if param.required:
                    msg = f"{scope}: {name} needs a value for parameter {key!r}"
                    raise FeatureManifestError(msg)
                params[key] = param.default
        try:
            _check_parameter_references(operations, definition.model.parameters)
        except ValueError as error:
            raise FeatureManifestError(f"{scope}: {name}: {error}") from None
        return Adoption(name, params, operations, [w for w, _ in blocks])

    # -- resolution --------------------------------------------------------

    def cell(self, scope: str) -> Cell:
        ref = self.scopes.scopes[scope].cell
        try:
            return self.manifest.resolve_cell(ref.release, ref.deployment)
        except ValueError as error:
            raise FeatureManifestError(f"{scope}: {error}") from None

    def resolve(self, scope: str) -> ResolvedScope:
        """Resolve and validate every feature ``scope`` adopts.

        :raises FeatureManifestError: On the first check that fails.
        """
        adopted = self.adopted(scope)
        cell = self.cell(scope)
        frontends = self.scopes.scopes[scope].frontends
        features = [
            self._resolve_feature(scope, cell, frontends, adoption)
            for adoption in adopted.values()
        ]
        for feature in features:
            missing = set(feature.requires.features) - set(adopted)
            if missing:
                msg = (
                    f"{scope}: {feature.feature} requires features "
                    f"{sorted(missing)}, which this scope does not adopt"
                )
                raise FeatureManifestError(msg)
        resolved = ResolvedScope(scope, cell, frontends, features)
        resolved.owners = self._conflicts(resolved)
        return resolved

    def _resolve_feature(
        self,
        scope: str,
        cell: Cell,
        frontends: Mapping[str, FrontendBinding],
        adoption: Adoption,
    ) -> ResolvedFeature:
        definition = self.definitions[adoption.feature]
        model = definition.model
        where = f"{scope}: {adoption.feature}"
        try:
            ops = substitute(adoption.operations, adoption.params)
        except FeatureManifestError as error:
            raise FeatureManifestError(f"{where}: {error}") from None
        self._check_plugins(where, cell, model)
        self._check_frontends(where, frontends, model)
        # Keys whose value resolves to null are omitted by substitution, so
        # check every key as written as well: a typo must fail in every
        # scope, not only the ones that happen to supply a value.
        for group_name in ("settings", "features"):
            for svc, group in adoption.operations.get(group_name, {}).items():
                for key in _written_keys(group):
                    self._check_not_reserved(where, svc, key)
                    if group_name == "settings" and self._field(svc, key) is None:
                        msg = (
                            f"{where}: {svc} setting {key!r} is not declared by "
                            "the settings model"
                        )
                        raise FeatureManifestError(msg)

        settings_ops = {svc: dict(v) for svc, v in ops.get("settings", {}).items()}
        features_ops = {svc: dict(v) for svc, v in ops.get("features", {}).items()}
        site_config = _resolve_site_config(ops.get("site_config", {}), cell.release)
        try:
            # Again after substitution: a by_parameter lookup can produce
            # keys the definition-time check never saw.
            _check_site_config(
                {
                    key: site_config[setting]
                    for key, setting in SITE_CONFIG_SETTINGS.items()
                    if setting in site_config
                },
                where,
            )
        except ValueError as error:
            raise FeatureManifestError(str(error)) from None
        if (settings_ops or features_ops or site_config) and not cell.uses_aqueduct():
            msg = (
                f"{where}: cell {cell.release}/{cell.deployment} does not use "
                "django-aqueduct, so nothing reads settings, features or site_config"
            )
            raise FeatureManifestError(msg)
        for svc, group in settings_ops.items():
            settings_ops[svc] = self._canonical_settings(where, svc, group)
        for svc, group in features_ops.items():
            for key in group:
                self._check_not_reserved(where, svc, key)

        bootstrap = None
        if ops.get("bootstrap"):
            fragment = ops["bootstrap"]
            for list_name in ("third_party_auth_providers", "service_access_tokens"):
                for entry in fragment.get(list_name, []):
                    entry["optional"] = False
            try:
                bootstrap = BootstrapSpec.model_validate(fragment)
                check_fragment(bootstrap)
            except (ValidationError, ValueError) as error:
                raise FeatureManifestError(f"{where}: bootstrap: {error}") from None
            for flag in bootstrap.waffle_flags:
                if not _WAFFLE_NAME.fullmatch(flag.name):
                    msg = f"{where}: waffle flag {flag.name!r} is not namespace.name"
                    raise FeatureManifestError(msg)

        build_env: dict[str, dict[str, str]] = {}
        for mfe, env in ops.get("mfe_build_env", {}).items():
            build_env[mfe] = {key: _env_value(where, key, v) for key, v in env.items()}
        assets = {
            mfe: self._resolve_assets(
                where, mfe, MfeBuildConfig.model_validate(raw), cell
            )
            for mfe, raw in ops.get("mfe_assets", {}).items()
        }
        return ResolvedFeature(
            feature=adoption.feature,
            source=definition.source,
            params=adoption.params,
            requires=model.requires,
            settings=settings_ops,
            features=features_ops,
            site_config=site_config,
            bootstrap=bootstrap,
            mfe_build_env=build_env,
            mfe_assets=assets,
            commands=[Command.model_validate(c) for c in ops.get("commands", [])],
        )

    def _check_plugins(self, where: str, cell: Cell, model: FeatureDefinition) -> None:
        lines = [*cell.packages, *cell.overrides]
        wanted = [*model.requires.plugins]
        if model.provided_by and model.provided_by not in wanted:
            wanted.append(model.provided_by)
        for dist in wanted:
            if declares_distribution(lines, dist, cell.packages_to_remove):
                continue
            target = normalize_distribution(dist)
            unverifiable = any(
                "://" in line and target in normalize_distribution(line)
                for line in lines
            )
            reason = (
                "is installed only from a VCS/URL line, which cannot be verified"
                if unverifiable
                else "is not installed"
            )
            msg = f"{where}: plugin {dist!r} {reason} in cell {cell.release}/{cell.deployment}"
            raise FeatureManifestError(msg)

    def _check_frontends(
        self,
        where: str,
        frontends: Mapping[str, FrontendBinding],
        model: FeatureDefinition,
    ) -> None:
        for mfe in model.requires.frontends:
            if mfe not in frontends:
                msg = f"{where}: needs MFE {mfe!r}, which the scope's frontends do not list"
                raise FeatureManifestError(msg)
            path = binding_path(frontends[mfe])
            if path not in model.frontend_paths:
                msg = (
                    f"{where}: the scope builds {mfe!r} as {path}, which the "
                    f"definition does not support (frontend_paths: {model.frontend_paths})"
                )
                raise FeatureManifestError(msg)

    def _field(self, svc: str, key: str) -> SettingField | None:
        inventory = self.inventories.get(svc, {})
        found = inventory.get(key)
        if found is not None:
            return found
        return next((f for f in inventory.values() if f.alias == key), None)

    def _check_not_reserved(self, where: str, svc: str, key: str) -> None:
        found = self._field(svc, key)
        names = {key} | ({found.name, found.key} if found else set())
        if names & RESERVED_SETTINGS:
            msg = f"{where}: {svc} {key} may only be written through site_config"
            raise FeatureManifestError(msg)

    def _canonical_settings(
        self, where: str, svc: str, group: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Key each setting by the name pydantic-settings reads (its alias)."""
        out: dict[str, Any] = {}
        for key, value in group.items():
            found = self._field(svc, key)
            if found is None:
                msg = f"{where}: {svc} setting {key!r} is not declared by the settings model"
                raise FeatureManifestError(msg)
            self._check_not_reserved(where, svc, key)
            out[found.key] = value
        return out

    def _resolve_assets(
        self, where: str, mfe: str, assets: MfeBuildConfig, cell: Cell
    ) -> dict[str, list[dict[str, str]]]:
        slot_files = []
        for item in assets.extra_slot_files:
            spec = item if isinstance(item, str) else item.resolve(cell.release)
            source, _, dest = spec.partition(":")
            dest = dest or source
            if self.slot_dir is not None and not (self.slot_dir / source).is_file():
                msg = (
                    f"{where}: slot file {source!r} for {mfe} is not in {self.slot_dir}"
                )
                raise FeatureManifestError(msg)
            slot_files.append({"source": source, "dest": dest})
        bundles = []
        for bundle in assets.extra_npm_bundles:
            spec, _, target = bundle.partition("|")
            bundles.append({"spec": spec, "target": target})
        return {"extra_slot_files": slot_files, "extra_npm_bundles": bundles}

    # -- conflicts ---------------------------------------------------------

    def _conflicts(self, resolved: ResolvedScope) -> dict[tuple[str, ...], list[str]]:
        """Every target each feature writes; two unequal values is an error.

        Equal values from several features are not a conflict; the returned
        map lists every owner of each target for ``explain``.
        """
        claims = _Claims(resolved.scope)
        baseline = self.baseline or BuildConfig()
        for mfe in sorted({m for f in resolved.features for m in f.mfe_assets}):
            config = baseline.mfe(mfe)
            for copy in config.resolve_extra_slot_files(resolved.cell.release):
                origin, _, dest = copy.partition(":")
                claims.add(("slot-file", mfe, dest or origin), _BASELINE, origin)
            for line in config.extra_npm_bundles:
                package, _, directory = line.partition("|")
                claims.add(("npm-bundle", mfe, directory), _BASELINE, package)
        for feature in resolved.features:
            owner = (feature.feature, feature.source)
            for target, value in self._targets(feature):
                claims.add(target, owner, value)
        claims.check_legacy_overrides()
        try:
            resolved.bootstrap()
        except ValueError as error:
            msg = f"{resolved.scope}: bootstrap: {error}"
            raise FeatureManifestError(msg) from None
        return claims.owners

    def _targets(
        self, feature: ResolvedFeature
    ) -> Iterable[tuple[tuple[str, ...], Any]]:
        for svc in ("lms", "cms"):
            for key, value in feature.settings.get(svc, {}).items():
                for path, leaf in _leaves(value):
                    yield ("setting", svc, key, *path), leaf
            for key, value in feature.features.get(svc, {}).items():
                found = self._field(svc, key)
                canonical = found.key if found else key
                for path, leaf in _leaves(value):
                    yield ("setting", svc, canonical, *path), leaf
        for setting, value in feature.site_config.items():
            for path, leaf in _leaves(value):
                yield ("setting", "lms", setting, *path), leaf
                for destination in _runtime_destinations(setting, path):
                    yield destination, leaf
        for mfe, env in feature.mfe_build_env.items():
            for key, text in env.items():
                yield ("mfe-build-env", mfe, key), text
        for mfe, assets in feature.mfe_assets.items():
            for slot in assets["extra_slot_files"]:
                yield ("slot-file", mfe, slot["dest"]), slot["source"]
            for bundle in assets["extra_npm_bundles"]:
                yield ("npm-bundle", mfe, bundle["target"]), bundle["spec"]
        for command in feature.commands:
            yield ("command", command.id), command.model_dump()
        if feature.bootstrap:
            for list_name, identity in BOOTSTRAP_IDENTITIES.items():
                for entry in getattr(feature.bootstrap, list_name):
                    yield (
                        ("bootstrap", list_name, str(identity(entry))),
                        entry.model_dump(),
                    )

    # -- whole group -------------------------------------------------------

    def check(self) -> list[str]:
        """Resolve every scope; return one message per scope that fails."""
        errors = []
        resolved: dict[str, ResolvedScope] = {}
        for scope in self.scopes.scopes:
            try:
                resolved[scope] = self.resolve(scope)
            except FeatureManifestError as error:
                errors.append(str(error))
        errors += self._shared_legacy_builds(resolved)
        return errors

    def _shared_legacy_builds(self, resolved: Mapping[str, ResolvedScope]) -> list[str]:
        """Scopes sharing a ``{legacy: label}`` build must agree on its input."""
        builds: dict[tuple[str, str], tuple[str, str]] = {}
        errors = []
        for scope, result in resolved.items():
            for mfe, binding in result.frontends.items():
                if not isinstance(binding, SharedLegacy):
                    continue
                digest = build_digest(result, mfe)
                held = builds.setdefault((mfe, binding.legacy), (scope, digest))
                if held[1] != digest:
                    errors.append(
                        f"{held[0]} and {scope} share the {mfe} build "
                        f"{binding.legacy!r} but resolve different build input for it"
                    )
        return errors


def _env_value(where: str, key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int)):
        return str(value)
    msg = f"{where}: mfe_build_env {key} must resolve to a scalar, not {value!r}"
    raise FeatureManifestError(msg)


def _resolve_site_config(
    site_config: Mapping[str, Any], release: str
) -> dict[str, dict[str, Any]]:
    block = site_config
    if "by_release" in site_config:
        by_release = site_config["by_release"]
        block = by_release.get(release.lower(), by_release.get("default")) or {}
    return {SITE_CONFIG_SETTINGS[key]: value for key, value in block.items() if value}


def _leaves(
    value: Any, path: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], Any]]:
    """Mapping leaves individually; lists and scalars whole."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from _leaves(item, (*path, str(key)))
    else:
        yield path, value


def _runtime_destinations(setting: str, path: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Where a site_config leaf lands in the runtime config API responses.

    On the Site Project endpoint a non-promoted ``MFE_CONFIG.K`` becomes
    ``commonAppConfig.K``, which ``FRONTEND_SITE_CONFIG.commonAppConfig.K``
    then overwrites, and ``MFE_CONFIG_OVERRIDES.<mfe>.K`` becomes that app's
    ``config.K``. On the legacy endpoint the override replaces ``MFE_CONFIG.K``
    for that MFE.
    """
    match setting, path:
        case "MFE_CONFIG", (key, *rest):
            return [
                ("site-config", "commonAppConfig", key, *rest),
                ("legacy-config", "*", key, *rest),
            ]
        case "FRONTEND_SITE_CONFIG", ("commonAppConfig", key, *rest):
            return [("site-config", "commonAppConfig", key, *rest)]
        case "MFE_CONFIG_OVERRIDES", (mfe, key, *rest):
            return [
                ("site-config", "app", mfe, key, *rest),
                ("legacy-config", mfe, key, *rest),
            ]
    return []


def build_digest(resolved: ResolvedScope, mfe: str) -> str:
    """A stable hash of the build-time operations every feature sends ``mfe``."""
    import hashlib  # noqa: PLC0415
    import json  # noqa: PLC0415

    payload = [
        {
            "feature": f.feature,
            "env": f.mfe_build_env.get(mfe, {}),
            "assets": f.mfe_assets.get(mfe, {}),
        }
        for f in resolved.features
        if mfe in f.mfe_build_env or mfe in f.mfe_assets
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# --- Loading ---------------------------------------------------------------


def _read(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _validate[M: BaseModel](model: type[M], path: Path) -> M:
    try:
        return model.model_validate(_read(path))
    except ValidationError as error:
        raise FeatureManifestError(f"{path}: {error}") from None


def load_definitions(
    catalog: Path | None, definitions: Path | None, vendored: Path | None
) -> dict[str, Definition]:
    """Load every definition, failing on a name declared twice.

    :param catalog: lehrer's shipped upstream-native definitions.
    :param definitions: A group's ``features/definitions/``.
    :param vendored: A group's ``features/vendored/`` (``<dist>/<version>/``).
    """
    found: dict[str, Definition] = {}
    sources: list[tuple[str, Path]] = []
    for kind, root in (
        ("catalog", catalog),
        ("definitions", definitions),
        ("vendored", vendored),
    ):
        if root is not None and root.is_dir():
            sources += [(kind, p) for p in sorted(root.rglob("*.yaml"))]
    for kind, path in sources:
        model = _validate(FeatureDefinition, path)
        if kind != "vendored" and path.stem != model.feature:
            msg = f"{path}: declares feature {model.feature!r}; name the file {model.feature}.yaml"
            raise FeatureManifestError(msg)
        if kind == "vendored":
            dist = path.parent.parent.name
            if model.origin != "plugin" or model.provided_by != dist:
                msg = f"{path}: a vendored definition must be origin: plugin, provided_by: {dist}"
                raise FeatureManifestError(msg)
        if model.feature in found:
            msg = (
                f"feature {model.feature!r} is declared by both "
                f"{found[model.feature].source} and {path}"
            )
            raise FeatureManifestError(msg)
        found[model.feature] = Definition(model, path)
    return found


def load_scopes(path: Path) -> ScopesFile:
    return _validate(ScopesFile, path)


def load_adoption(path: Path) -> AdoptionFile:
    if not path.is_file():
        return AdoptionFile(version=1)
    return _validate(AdoptionFile, path)


def json_schemas() -> dict[str, dict]:
    """The JSON Schema for each feature manifest file, by file kind."""
    return {
        "definition": FeatureDefinition.model_json_schema(),
        "scopes": ScopesFile.model_json_schema(),
        "adoption": AdoptionFile.model_json_schema(),
    }


def write_json_schemas(directory: Path) -> None:
    """Write ``feature_<kind>.schema.json`` for each file kind into ``directory``."""
    import json  # noqa: PLC0415

    for kind, schema in json_schemas().items():
        path = directory / f"feature_{kind}.schema.json"
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_json_schemas(Path.cwd())
