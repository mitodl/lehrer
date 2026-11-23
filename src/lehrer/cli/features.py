"""``lehrer features`` — validate and compile feature manifests.

A group's feature manifests live in ``deployments/<group>/features/``
(plans/08-feature-manifest.md §4.1)::

    definitions/<feature>.yaml   operator and not-yet-shipped plugin features
    vendored/<dist>/<version>/   reserved for definitions copied from plugins
    scopes.yaml                  scope labels -> build cells, sets, frontends
    adoption.yaml                which features each scope takes

Path reasoning lives here rather than in :mod:`lehrer.core.feature_manifest`,
because the core boundary hook forbids a ``deployments/`` path under core.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import cyclopts
import yaml

import lehrer
from lehrer.bootstrap.spec import load as load_bootstrap
from lehrer.bootstrap.spec import merge
from lehrer.cli import _paths
from lehrer.core.build_manifest import load_manifest
from lehrer.core.feature_manifest import (
    FeatureManifestError,
    Group,
    ResolvedFeature,
    load_adoption,
    load_definitions,
    load_scopes,
)
from lehrer.core.mfe_config import BuildConfig
from lehrer.core.settings_inventory import (
    SettingField,
    configured_class,
    inventory,
)

app = cyclopts.App(
    name="features",
    help="Validate, inspect and compile feature manifests.",
)

GroupArg = Annotated[
    str,
    cyclopts.Parameter(
        name="--group", help="Deployment group under deployments/, e.g. mit-ol."
    ),
]
ScopeArg = Annotated[
    str, cyclopts.Parameter(name="--scope", help="A scope declared in scopes.yaml.")
]

_PACKAGE = Path(lehrer.__file__).parent
CATALOG = _PACKAGE / "features"
"""lehrer's shipped upstream-native definitions. May be absent while empty."""
SETTINGS_BASE = _PACKAGE / "settings" / "base.py"
"""Injected into the image as ``settings/<svc>/models/base.py``."""


def group_dir(group: str) -> Path:
    path = _paths.repo_root() / "deployments" / group
    if not path.is_dir():
        msg = f"no deployment group {group!r} at {path}"
        raise FeatureManifestError(msg)
    return path


def settings_inventories(root: Path) -> dict[str, dict[str, SettingField]]:
    """Each service's settings inventory, for services with an aqueduct entry."""
    found = {}
    for svc in ("lms", "cms"):
        entry = root / "settings" / svc / "aqueduct.py"
        if entry.is_file():
            found[svc] = inventory(
                entry, configured_class(entry), {".models.base": SETTINGS_BASE}
            )
    return found


def load_group(group: str) -> Group:
    """Load everything a group's features compile against."""
    root = group_dir(group)
    features = root / "features"
    slot_dir = root / "mfe_slot_config" / "legacy"
    baseline_path = slot_dir / "build_config.yaml"
    baseline = (
        BuildConfig.model_validate(yaml.safe_load(baseline_path.read_text()) or {})
        if baseline_path.is_file()
        else None
    )
    return Group(
        definitions=load_definitions(
            CATALOG, features / "definitions", features / "vendored"
        ),
        scopes=load_scopes(features / "scopes.yaml"),
        adoption=load_adoption(features / "adoption.yaml"),
        manifest=load_manifest(root / "build_manifest.yaml"),
        inventories=settings_inventories(root),
        # Passed even when absent, so a slot file referenced by a feature fails
        # rather than going unchecked.
        slot_dir=slot_dir,
        baseline=baseline,
    )


def _dump(data: Any) -> None:
    sys.stdout.write(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def _fail(error: Exception) -> None:
    sys.stderr.write(f"lehrer features: {error}\n")
    raise SystemExit(1)


@app.command
def check(group: GroupArg, *, base_spec: Path | None = None) -> None:
    """Resolve every scope in a group and report every failure. Emits nothing.

    Parameters
    ----------
    base_spec
        An operator bootstrap spec to merge each scope's bootstrap fragment
        with, reporting conflicts between them.
    """
    try:
        loaded = load_group(group)
    except (FeatureManifestError, ValueError) as error:
        _fail(error)
        return
    errors = loaded.check()
    if base_spec is not None:
        base = load_bootstrap(base_spec)
        for scope in loaded.scopes.scopes:
            try:
                merge(base, loaded.resolve(scope).bootstrap())
            except FeatureManifestError:
                continue  # already reported by check()
            except ValueError as error:
                errors.append(f"{scope}: bootstrap with {base_spec}: {error}")
    for message in errors:
        sys.stderr.write(f"{message}\n")
    if errors:
        raise SystemExit(1)
    sys.stdout.write(
        f"{group}: {len(loaded.scopes.scopes)} scopes, "
        f"{len(loaded.definitions)} definitions OK\n"
    )


@app.command
def catalog(group: str | None = None) -> None:
    """List every definition and its parameters.

    Parameters
    ----------
    group
        Include this group's definitions. Omitted, lehrer's shipped catalog alone.
    """
    try:
        if group is None:
            definitions = load_definitions(CATALOG, None, None)
        else:
            features = group_dir(group) / "features"
            definitions = load_definitions(
                CATALOG, features / "definitions", features / "vendored"
            )
    except (FeatureManifestError, ValueError) as error:
        _fail(error)
        return
    _dump(
        [
            {
                "feature": d.model.feature,
                "origin": d.model.origin,
                **({"provided_by": d.model.provided_by} if d.model.provided_by else {}),
                "summary": d.model.summary,
                "source": str(d.source),
                "parameters": {
                    name: p.model_dump(exclude_none=True, exclude_unset=True)
                    for name, p in d.model.parameters.items()
                },
            }
            for d in sorted(definitions.values(), key=lambda d: d.model.feature)
        ]
    )


@app.command
def adopted(group: GroupArg, scope: ScopeArg) -> None:
    """What a scope takes, with parameter values resolved."""
    try:
        taken = load_group(group).adopted(scope)
    except (FeatureManifestError, ValueError) as error:
        _fail(error)
        return
    _dump(
        {
            name: {"params": adoption.params, "via": adoption.via}
            for name, adoption in taken.items()
        }
    )


@app.command
def explain(
    feature: str, *, group: str | None = None, scope: str | None = None
) -> None:
    """Print one feature's fan-out.

    Without --scope, the contract with parameter placeholders intact. With
    --scope (which needs --group), the values resolved for that scope, the
    targets it shares with other features, and every account, staff flag and
    token its bootstrap data creates.
    """
    try:
        if scope is not None:
            if group is None:
                msg = "--scope needs --group"
                raise FeatureManifestError(msg)
            resolved = load_group(group).resolve(scope)
            match = [f for f in resolved.features if f.feature == feature]
            if not match:
                msg = f"{scope} does not adopt {feature!r}"
                raise FeatureManifestError(msg)
            shared = {
                " ".join(target): owners
                for target, owners in resolved.owners.items()
                if feature in owners and len(owners) > 1
            }
            _dump({**_resolved_view(match[0]), "shared_targets": shared})
            return
        features = group_dir(group) / "features" if group else None
        definitions = load_definitions(
            CATALOG,
            features / "definitions" if features else None,
            features / "vendored" if features else None,
        )
    except (FeatureManifestError, ValueError) as error:
        _fail(error)
        return
    if feature not in definitions:
        _fail(FeatureManifestError(f"no definition for {feature!r}"))
    definition = definitions[feature]
    _dump(
        {
            "source": str(definition.source),
            **definition.model.model_dump(exclude_defaults=True),
        }
    )


def _resolved_view(feature: ResolvedFeature) -> dict[str, Any]:
    view: dict[str, Any] = {
        "source": str(feature.source),
        "params": feature.params,
        "requires": feature.requires.model_dump(exclude_defaults=True),
    }
    for name in ("settings", "features", "site_config", "mfe_build_env", "mfe_assets"):
        value = getattr(feature, name)
        if value:
            view[name] = value
    if feature.bootstrap is not None:
        view["bootstrap"] = feature.bootstrap.model_dump(exclude_defaults=True)
        view["privilege"] = _privilege(feature)
    if feature.commands:
        view["commands"] = [c.model_dump() for c in feature.commands]
    return view


def _privilege(feature: ResolvedFeature) -> list[str]:
    """Accounts and tokens the fragment creates, so a staff grant is visible."""
    assert feature.bootstrap is not None  # noqa: S101
    lines = [
        f"user {u.username}{' (staff)' if u.staff else ''}"
        for u in feature.bootstrap.users
    ]
    lines += [
        f"service account {t.username}{' (staff)' if t.staff else ''} with a "
        f"{t.expires_in_days}-day token from {t.token_env}"
        for t in feature.bootstrap.service_access_tokens
    ]
    return lines


@app.command(name="compile")
def compile_(group: GroupArg, scope: ScopeArg, *, out: Path) -> None:
    """Resolve and validate one scope and write its artifacts to --out.

    The artifact emitters (settings fragments, bootstrap.yaml, legacy MFE
    build inputs, checklist.yaml, manifest.json) are not implemented yet, so
    this validates the scope and then fails rather than report a success
    that wrote nothing.
    """
    try:
        load_group(group).resolve(scope)
    except (FeatureManifestError, ValueError) as error:
        _fail(error)
        return
    _fail(
        NotImplementedError(
            f"{scope} validates, but artifact emitters are not implemented yet; "
            f"nothing was written to {out}"
        )
    )
