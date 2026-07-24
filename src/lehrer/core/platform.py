"""Generic edx-platform build pipeline for Open edX operators.

This module contains the ``OpenedxPlatform`` Dagger object type that builds,
configures, and publishes edx-platform container images.  All MIT OL–specific
values have been removed; callers supply their own settings namespace, SSH
hosts, package overrides, and translations repository.
"""

import json
import re
import shlex
import urllib.request
from dataclasses import dataclass, field
from typing import TypeVar, cast

import dagger
import yaml
from dagger import dag, function, object_type

from lehrer.core.build_manifest import BuildManifest, Cell
from lehrer.core.plugin_imports import plugin_distributions
from lehrer.core.plugin_tests import (
    REPORT_TOOL_DIR,
    REPORTS_DIR,
    combined_pytest_script,
    maintained_test_extra_specs,
    normalize_dist,
)

_T = TypeVar("_T")

# ruff version used to format generated aqueduct models inside the regeneration
# container. Keep in sync with the ``ruff==`` pin in pyproject.toml so the
# committed model matches what CI's ``ruff format --check`` expects.
_RUFF_VERSION = "0.15.20"

# Where the full list of released Node versions lives. Each entry is
# ``{"version": "v24.18.0", ...}``; the file is authoritative for which
# prebuilt tarballs ``nodeenv --prebuilt`` can actually fetch.
NODE_RELEASE_INDEX_URL = "https://nodejs.org/download/release/index.json"
_FULL_NODE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _node_version_key(version: str) -> tuple[int, ...]:
    """Numeric sort key for a ``vMAJOR.MINOR.PATCH`` (or bare) version string."""
    return tuple(int(part) for part in version.lstrip("v").split("."))


def _pick_latest_node_version(spec: str, available: list[str]) -> str:
    """Return the highest ``available`` release whose version starts with ``spec``.

    ``spec`` is a ``MAJOR`` or ``MAJOR.MINOR`` prefix; ``available`` holds full
    ``vMAJOR.MINOR.PATCH`` strings (the nodejs release index). Mirrors the
    Concourse ``github_release`` resource (``tag_filter=^v(<spec>\\.\\d+\\.\\d+)``,
    ``order_by=version``) that historically resolved this.
    """
    prefix = tuple(int(part) for part in spec.split("."))
    matching = [
        v
        for v in available
        if _FULL_NODE_VERSION_RE.match(v.lstrip("v"))
        and _node_version_key(v)[: len(prefix)] == prefix
    ]
    if not matching:
        msg = f"no released Node version matches {spec!r}"
        raise ValueError(msg)
    return max(matching, key=_node_version_key).lstrip("v")


def _fetch_node_versions() -> list[str]:
    """Fetch the list of released Node version strings from nodejs.org."""
    with urllib.request.urlopen(NODE_RELEASE_INDEX_URL) as resp:  # noqa: S310
        return [entry["version"] for entry in json.load(resp)]


def resolve_node_version(spec: str, available: list[str] | None = None) -> str:
    """Resolve a manifest ``node_version`` to a full ``MAJOR.MINOR.PATCH``.

    A full version is returned unchanged (a reproducible pin, and — since it
    needs no lookup — the Concourse path that passes an already-resolved
    ``--node-version`` never hits the network). A ``MAJOR`` or ``MAJOR.MINOR``
    prefix resolves to the latest matching release. ``available`` is injectable
    for testing; it is fetched from :data:`NODE_RELEASE_INDEX_URL` when omitted.
    """
    if _FULL_NODE_VERSION_RE.match(spec):
        return spec
    if available is None:
        available = _fetch_node_versions()
    return _pick_latest_node_version(spec, available)


def _plugin_import_script(plugin_dists: list[str]) -> str:
    """Build the in-container script that smoke-imports each plugin distribution.

    The distribution → import-module mapping is resolved at runtime from the
    installed metadata (``importlib.metadata.packages_distributions``) so a
    healthy plugin is never failed by a stale hand-maintained mapping.  A
    distribution that did not install at all is a hard failure; one that
    installed but exposes no importable top-level module is reported and
    skipped (namespace-only or data-only distributions).
    """
    return "\n".join(
        [
            "import importlib, os, sys",
            "import importlib.metadata as im",
            # Initialize Django before importing plugins.  Many Open edX plugins
            # and XBlocks touch settings or declare models at import time, so a
            # bare import without an app registry raises AppRegistryNotReady /
            # ImproperlyConfigured — a false positive unrelated to compatibility.
            # Guarded: if setup can't run here, fall back to bare imports.
            "try:",
            "    import django",
            "    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms.envs.test')",
            "    django.setup()",
            "except Exception as exc:",  # noqa: E501
            "    sys.stderr.write(f'django.setup() skipped: {exc!r}\\n')",
            f"targets = {plugin_dists!r}",
            "def _norm(name):",
            "    import re",
            "    return re.sub(r'[-_.]+', '-', name).lower()",
            "dist_to_modules = {}",
            "for mod, dists in im.packages_distributions().items():",
            "    for d in dists:",
            "        dist_to_modules.setdefault(_norm(d), []).append(mod)",
            "installed = set()",
            "for dist in im.distributions():",
            # Distribution.name is the standard accessor (Python >= 3.10); it
            # avoids re-parsing the metadata file that dist.metadata['Name'] does.
            "    name = dist.name",
            "    if name:",
            "        installed.add(_norm(name))",
            "failures = []",
            "for dist in targets:",
            "    if dist not in installed:",
            "        print(f'MISSING: {dist} did not install'); failures.append(dist)",
            "        continue",
            "    modules = sorted(set(dist_to_modules.get(dist, [])))",
            "    if not modules:",
            "        print(f'SKIP:    {dist} installed, no importable top-level module')",
            "        continue",
            "    for module in modules:",
            "        try:",
            "            importlib.import_module(module)",
            "            print(f'OK:      {dist} -> import {module}')",
            "        except Exception as exc:",  # noqa: E501
            "            print(f'FAIL:    {dist} -> import {module}: {exc!r}')",
            "            failures.append(f'{dist}:{module}')",
            "if failures:",
            "    sys.exit(f'plugin import check failed for {len(failures)}: {failures}')",
            "print(f'plugin import check passed for {len(targets)} distributions')",
        ]
    )


@dataclass
class _ResolvedCell:
    """Every build parameter for one ``(release, deployment)`` cell, resolved.

    Precedence per field is explicit argument > manifest cell/defaults >
    hardcoded default.  Extracted so the verification entry points
    (``check_deployment``, ``verify_settings``, ``regenerate_aqueduct_settings``)
    all resolve a cell the *same* way — a divergence here would mean CI verifies
    a different dependency set than the build produces.
    """

    pip_package_lists: dagger.Directory
    pip_package_overrides: dagger.Directory
    platform_repo: str
    platform_branch: str
    python_version: str
    node_version: str
    packages_to_remove: list[str] = field(default_factory=list)
    extra_npm_packages: list[str] = field(default_factory=list)


@dataclass
class _PreparedTestRun:
    """A test run built but not executed: the container and its pytest command.

    ``test`` and ``test_report`` execute the *same* run and differ only in what
    they keep — stdout with the exit code as the gate, or the report directory
    regardless of the exit code.  Handing both the identical prepared run is
    what guarantees the artifact describes what the gate ran.
    """

    container: dagger.Container
    args: list[str]


def _resolve_field(
    explicit: _T | None,
    cell: Cell | None,
    manifest: BuildManifest | None,
    field: str,
    default: _T,
) -> _T:
    """Resolve a build param: explicit CLI arg > manifest cell > hardcoded default."""
    if explicit is not None:
        return explicit
    if cell is not None and manifest is not None:
        value = cell.resolved(field, manifest)
        if value is not None:
            return cast("_T", value)
    return default


# Throwaway Django settings module used by the aqueduct management commands and
# the boot self-test.  It does NOT drive generation (codegen v2 discovers
# settings by static AST analysis of lms/cms.envs.common's *source*); it exists
# only so `python -m django` can load a command at all.
_GEN_SETTINGS_MODULE = "lehrer_gen_settings"
_GEN_SETTINGS_SOURCE = (
    "# Throwaway settings — lets `python -m django` load the\n"
    "# generate_aqueduct_settings command.  It does NOT drive generation:\n"
    "# static AST discovery reads lms/cms.envs.common source directly.\n"
    'SECRET_KEY = "lehrer-aqueduct-generation"  # noqa: S105\n'  # pragma: allowlist secret
    'INSTALLED_APPS = ["django_aqueduct"]\n'
    "DATABASES: dict = {}\n"
    "USE_TZ = True\n"
)

# [tool.aqueduct] policy block (deliberate, documented choices):
#   extra="allow"       — edx-platform + openedx plugins inject many settings the
#                         static common.py snapshot does not model;
#                         "forbid"/"ignore" would reject/drop them.
#   enrich_url_types=false — 0.9.0 made str→AnyUrl promotion opt-in after it
#                         broke on Django's many relative-URL settings.
# (--modules/--output vary per service and stay on the CLI.)
_AQUEDUCT_TOML = (
    "\n[tool.aqueduct]\n"
    'class_name = "AqueductSettings"\n'
    'extra = "allow"\n'
    "enrich_url_types = false\n"
)


def _boot_self_test_script() -> str:
    """Python source asserting ``<svc>.envs.aqueduct`` boots without dropping apps.

    Imports each service's aqueduct entry module — which runs
    ``configure_django_settings(..., base="<svc>.envs.common")`` — then compares
    the resulting ``INSTALLED_APPS`` against the *live* ``common.py`` value.
    ``common.py`` runs openedx's ``add_plugins()`` on import, so its list is
    plugin-complete while the statically generated model's is not; the overlay
    (django-aqueduct >= 0.10.0) must defer to the live base rather than
    overwrite it.  A dropped app means a plugin silently vanished from the
    running platform — exactly the class of breakage this gate exists to catch.
    """
    return "\n".join(
        [
            "import importlib",
            "failures = []",
            "for svc in ('lms', 'cms'):",
            "    entry = importlib.import_module(f'{svc}.envs.aqueduct')",
            "    common = importlib.import_module(f'{svc}.envs.common')",
            "    base_apps = set(getattr(common, 'INSTALLED_APPS', []) or [])",
            "    final_apps = getattr(entry, 'INSTALLED_APPS', None)",
            "    if not final_apps:",
            "        failures.append(f'{svc}: INSTALLED_APPS empty/missing ({final_apps!r})')",  # noqa: E501
            "        continue",
            "    dropped = base_apps - set(final_apps)",
            "    if dropped:",
            "        failures.append(",
            "            f'{svc}: overlay dropped {len(dropped)} base/plugin apps '",
            "            f'e.g. {sorted(dropped)[:5]}'",
            "        )",
            "        continue",
            "    print(",
            "        f'  self-test OK: {svc}.envs.aqueduct boots, {len(final_apps)} '",
            "        f'INSTALLED_APPS (live base {len(base_apps)}, none dropped)'",
            "    )",
            "if failures:",
            "    raise SystemExit('SELF-TEST FAILED:\\n' + '\\n'.join(failures))",
        ]
    )


def _aqueduct_gen_setup(container: dagger.Container) -> dagger.Container:
    """Install the throwaway settings module and ``[tool.aqueduct]`` policy block.

    Both the generation path and the verification path need edx-platform's
    checkout prepared this way: a loadable ``DJANGO_SETTINGS_MODULE`` so the
    aqueduct management commands can run at all, the shared policy block so
    generation is reproducible from config rather than CLI flags, and the
    ``envs/models`` package directories the models live in.
    """
    return (
        container.with_new_file(
            f"/openedx/edx-platform/{_GEN_SETTINGS_MODULE}.py",
            contents=_GEN_SETTINGS_SOURCE,
        )
        .with_exec(
            [
                "sh",
                "-c",
                "printf '%s' "
                + shlex.quote(_AQUEDUCT_TOML)
                + " >> /openedx/edx-platform/pyproject.toml",
            ]
        )
        .with_exec(["mkdir", "-p", "./lms/envs/models", "./cms/envs/models"])
    )


def _tolerant(command: str, label: str, *, strict: bool) -> str:
    """Wrap a translations step so a failure is loud rather than invisible.

    Several ``fetch_translations`` steps are legitimately allowed to fail — not
    every plugin or release has translations published in the target atlas
    repository, and a missing one must not fail the build.  The original
    ``|| true`` achieved that but discarded the distinction entirely: a genuine
    regression (a renamed command, a bad revision, an unreachable repo) looked
    exactly like the expected miss, so builds silently shipped with no
    translations at all.

    Non-strict mode keeps the build going but prints a labelled warning to
    stderr, so the miss is visible in the build log.  Strict mode lets the
    failure through, for a caller that treats any miss as a regression; it is
    off everywhere by default until the current per-step baseline is known —
    turning it on blind would make an already-failing step a hard build break.
    """
    if strict:
        return command
    return (
        f"{command} || echo "
        + shlex.quote(f"WARNING: translations step failed (non-fatal): {label}")
        + " >&2"
    )


_LEHRER_RUFF_CONFIG = "/root/lehrer-ruff/pyproject.toml"


def _ruff_format(container: dagger.Container, paths: list[str]) -> dagger.Container:
    """Format generated model files with *lehrer's* ruff config.

    The committed models have to satisfy this repo's own ``ruff format --check
    .``, so the in-container formatting must use this repo's settings.  Ruff
    resolves configuration by walking up from the file *and* falling back to the
    working directory — which here is ``/openedx/edx-platform``, whose
    ``pyproject.toml`` sets a different line length.  Formatting under that
    config produces a file this repo's CI would immediately reformat, which made
    regeneration non-idempotent and made the drift gate report pure line-wrap
    noise as staleness.  Pinning ``--config`` to lehrer's own ``pyproject.toml``
    is what makes both sides of the comparison mean the same thing.

    ``uv tool run``, not ``uvx``: ``apt_base`` copies only the ``uv`` binary out
    of the astral image, so ``uvx`` does not exist in this container at all.
    """
    return container.with_file(
        _LEHRER_RUFF_CONFIG,
        dag.current_module().source().file("pyproject.toml"),
    ).with_exec(
        [
            "sh",
            "-c",
            f"uv tool run ruff@{_RUFF_VERSION} format "
            f"--config {_LEHRER_RUFF_CONFIG} {' '.join(paths)}",
        ]
    )


def _repo_shorthand(value: str) -> str:
    """Normalize a GitHub repo reference to ``org/repo`` shorthand.

    Manifest fields like ``platform_repo``/``theme_repo``/``translations_repo``
    are all stored as full GitHub URLs — the form ``git clone`` needs. Some
    consumers instead want bare ``org/repo`` (``translations_repo`` feeds
    ``atlas``/``pull_*_translations``, which take that form, not a URL); this
    is the shared normalizer for any such site. Already-shorthand values pass
    through unchanged.
    """
    return value.removeprefix("https://github.com/").rstrip("/").removesuffix(".git")


# Curated smoke subset for `test` — the edx-platform suites most likely to
# regress on a plugin/settings change, cheap enough to gate a PR. `student` and
# `third_party_auth` live under common/djangoapps; `courseware` under
# lms/djangoapps. The full suite (behind `--full`) walks the whole service tree
# and takes hours, so it belongs in the scheduled canary, not a PR gate.
_SMOKE_PATHS: dict[str, list[str]] = {
    "lms": [
        "lms/djangoapps/courseware",
        "common/djangoapps/student",
        "common/djangoapps/third_party_auth",
    ],
    "cms": [
        "cms/djangoapps/contentstore/tests",
    ],
}
# Mirror the roots upstream edx-platform's own full runs collect. `common`
# covers common/djangoapps + common/lib; `xmodule` is a sibling top-level tree
# (core modulestore/XBlock tests) that neither `common` nor the service root
# picks up, so name it explicitly or the canary silently skips it.
_FULL_PATHS: dict[str, list[str]] = {
    "lms": ["lms", "openedx", "common", "xmodule"],
    "cms": ["cms", "openedx", "common", "xmodule"],
}


def _test_paths(service: str, full: bool) -> list[str]:  # noqa: FBT001
    """Default pytest target paths for a service's smoke or full run."""
    if service not in _SMOKE_PATHS:
        msg = f"service must be one of {sorted(_SMOKE_PATHS)}, got {service!r}"
        raise ValueError(msg)
    return _FULL_PATHS[service] if full else _SMOKE_PATHS[service]


def _derive_test_settings(service: str) -> str:
    """Source of the derived deployment test settings module for ``service``.

    Starts from edx-platform's own test settings and layers the deployment's
    configuration on top.  ``{service}.envs.test`` stays authoritative for the
    test harness (sqlite DBs, dummy cache, mock search engine, in-memory email)
    — the pieces that make the suite runnable without a production backing
    stack.

    The **primary** compatibility signal is that the deployment's plugins are
    installed and register automatically through the Open edX plugin framework
    the moment their distributions are pip-installed, so ``INSTALLED_APPS``
    already reflects the deployment's plugin set here.

    The **FEATURES overlay is conditional**: the deployment's real flag values
    live in ``OL_SETTINGS_DIR`` YAML config-sources (K8s ConfigMaps at runtime),
    not in the generated model — whose ``FEATURES`` field default is ``None``.
    So the overlay contributes flags only when the caller supplies the cell's
    config-sources directory (``platform test --config-sources ...``), which
    mounts it at ``/openedx/config-sources`` before this module imports
    ``AqueductSettings``.  Without it the run uses the upstream test FEATURES,
    still against the deployment's plugin set.  The merge is done in place
    (item assignment) rather than by rebinding ``FEATURES``, so a modern
    edx-platform ``FeaturesProxy`` — through which ``@override_settings`` and
    top-level flag reads flow — is preserved, not replaced by a plain dict.
    """
    if service not in _SMOKE_PATHS:
        msg = f"service must be one of {sorted(_SMOKE_PATHS)}, got {service!r}"
        raise ValueError(msg)
    return "\n".join(
        [
            '"""Derived deployment test settings — generated by lehrer '
            '`platform test`."""',
            f"from {service}.envs.test import *  # noqa: F401,F403",
            "",
            "import sys",
            "",
            "# Overlay the deployment's feature flags on top of the upstream test",
            "# harness.  Guarded: a deployment without generated models (or one",
            "# whose model cannot instantiate standalone) still runs the suite",
            "# against the plugin set, just without the FEATURES overlay.  The",
            "# flag values are only non-empty when the cell's config-sources were",
            "# mounted at /openedx/config-sources (see `platform test",
            "# --config-sources`); the generated FEATURES default is None.",
            "try:",
            f"    from {service}.envs.models.aqueduct import AqueductSettings",
            "    _deployment = AqueductSettings()",
            "except Exception as exc:  # pragma: no cover - models are optional",
            "    sys.stderr.write(",
            "        f'lehrer_test: deployment AqueductSettings unavailable: "
            "{exc!r}\\n'",
            "    )",
            "    _deployment = None",
            "",
            "if _deployment is not None:",
            "    _features = getattr(_deployment, 'FEATURES', None)",
            "    if _features:",
            "        # Merge in place so a FeaturesProxy is preserved, not",
            "        # replaced by a plain dict (which would drop @override_settings",
            "        # and top-level flag reflection).",
            "        for _flag, _value in dict(_features).items():",
            "            FEATURES[_flag] = _value  # noqa: F405",
            "",
        ]
    )


@object_type
class OpenedxPlatform:
    """Generic edx-platform build pipeline.

    Usage::

        dagger call platform build-platform \\
          --deployment-name my-deployment \\
          --release-name sumac \\
          --settings-namespace production \\
          --pip-package-lists ./pip_package_lists \\
          --pip-package-overrides ./pip_package_overrides \\
          --custom-settings ./settings \\
          --translations-repo openedx/openedx-translations
    """

    @function
    def apt_base(
        self,
        python_version: str = "3.11",
    ) -> dagger.Container:
        """Create base Python container with system dependencies

        Args:
            python_version: Python version (default: 3.11)

        Returns:
            Container with Python and apt packages installed
        """
        apt_packages = [
            "curl",
            "default-libmysqlclient-dev",
            "gettext",
            "gfortran",
            "git",
            "graphviz",
            "libffi-dev",
            "libfreetype-dev",
            "libgeos-dev",
            "libgraphviz-dev",
            "libjpeg-dev",
            "liblapack-dev",
            "libpng-dev",
            "libsqlite3-dev",
            "libxml2-dev",
            "libxmlsec1-dev",
            "libxmlsec1-openssl",
            "lynx",
            "pkg-config",
            "rdfind",
        ]

        # Get uv binary from official image
        uv_binary = dag.container().from_("ghcr.io/astral-sh/uv:latest").file("/uv")

        return (
            dag.container()
            .from_(f"python:{python_version}-bookworm")
            .with_env_variable("DEBIAN_FRONTEND", "noninteractive")
            .with_file("/usr/local/bin/uv", uv_binary)
            # Set uv environment variables for virtual environment
            # uv will automatically create the venv when first needed
            .with_env_variable("UV_NO_MANAGED_PYTHON", "1")
            .with_env_variable("UV_PYTHON_DOWNLOADS", "never")
            .with_env_variable("UV_NO_CACHE", "1")
            .with_env_variable("UV_LINK_MODE", "copy")
            .with_env_variable("UV_PROJECT_ENVIRONMENT", "/openedx/venv")
            .with_env_variable("VIRTUAL_ENV", "/openedx/venv")
            .with_env_variable("PATH", "/openedx/venv/bin:/usr/local/bin:/usr/bin:/bin")
            # Cap setuptools < 82 for EVERY uv install in the pipeline (base
            # requirements, lxml/xmlsec rebuild, and the editable edx-platform
            # install in `collected`, which otherwise re-resolves to the latest).
            # pkg_resources — imported by edx-platform — was removed in
            # setuptools 82, so an unconstrained resolve breaks the build. The
            # bound is < 82 (not < 81) so a consumer that pins setuptools==81.x
            # for PyFilesystem2 compatibility still resolves.
            .with_new_file("/openedx/uv-constraints.txt", "setuptools<82\n")
            .with_env_variable("UV_CONSTRAINT", "/openedx/uv-constraints.txt")
            .with_exec(["apt", "update"])
            .with_exec(
                ["apt", "install", "-y", "--no-install-recommends"] + apt_packages
            )
            .with_exec(["apt", "autoremove", "-y"])
            .with_exec(["apt", "clean"])
            .with_exec(["rm", "-rf", "/var/lib/apt/lists/*"])
        )

    @function
    def locales(
        self,
        container: dagger.Container,
        locale_version: str = "master",
    ) -> dagger.Container:
        """Download and extract openedx-i18n locale files

        Note: The openedx-i18n repository is archived and only has a master branch.
        For recent Open edX releases, locale files are typically included in the platform.

        Args:
            container: Base container
            locale_version: Git ref for openedx-i18n (default: master)

        Returns:
            Container with locale files at /openedx/locale
        """
        return (
            container.with_exec(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    locale_version,
                    "https://github.com/openedx-unsupported/openedx-i18n.git",
                    "/tmp/openedx-i18n",
                ]
            )
            .with_exec(["mkdir", "-p", "/openedx/locale/contrib"])
            .with_exec(
                [
                    "sh",
                    "-c",
                    "mv /tmp/openedx-i18n/edx-platform/locale /openedx/locale/contrib || true",
                ]
            )
            .with_exec(["rm", "-rf", "/tmp/openedx-i18n"])
        )

    @function
    def get_code(
        self,
        container: dagger.Container,
        source: dagger.Directory | None = None,
        edx_platform_git_repo: str | None = None,
        edx_platform_git_branch: str | None = None,
    ) -> dagger.Container:
        """Get edx-platform source code from local directory or Git

        Args:
            container: Base container
            source: Local directory with edx-platform source (optional)
            edx_platform_git_repo: Git repository URL (required if source not provided)
            edx_platform_git_branch: Git branch/tag (required if source not provided)

        Returns:
            Container with edx-platform at /openedx/edx-platform and venv created
        """
        if source is not None:
            container = container.with_directory("/openedx/edx-platform", source)
        elif edx_platform_git_repo and edx_platform_git_branch:
            container = container.with_exec(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    edx_platform_git_branch,
                    edx_platform_git_repo,
                    "/openedx/edx-platform",
                ]
            )
        else:
            raise ValueError(
                "Must provide either source or both edx_platform_git_repo and edx_platform_git_branch"
            )

        # Create the virtual environment now that /openedx exists
        return container.with_exec(["uv", "venv", "/openedx/venv"])

    @function
    def themes(
        self,
        container: dagger.Container,
        deployment_name: str,
        theme_source: dagger.Directory | None = None,
        theme_git_repo: str | None = None,
        theme_git_branch: str | None = None,
    ) -> dagger.Container:
        """Get theme files from local directory or Git

        Args:
            container: Base container
            deployment_name: Name of the deployment (used for theme path ``/openedx/themes/{deployment_name}``)
            theme_source: Local directory with theme source (optional)
            theme_git_repo: Git repository URL (required if theme_source not provided)
            theme_git_branch: Git branch/tag (required if theme_source not provided)

        Returns:
            Container with theme at /openedx/themes/{deployment_name}
        """
        theme_path = f"/openedx/themes/{deployment_name}"

        if theme_source is not None:
            return container.with_directory(theme_path, theme_source)

        if not theme_git_repo or not theme_git_branch:
            raise ValueError(
                "Must provide either theme_source or both theme_git_repo and theme_git_branch"
            )

        return container.with_exec(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                theme_git_branch,
                theme_git_repo,
                theme_path,
            ]
        )

    @function
    def install_deps(
        self,
        container: dagger.Container,
        deployment_name: str,
        release_name: str,
        pip_package_lists: dagger.Directory,
        pip_package_overrides: dagger.Directory,
        node_version: str = "20.18.0",
        packages_to_remove: list[str] | None = None,
        extra_npm_packages: list[str] | None = None,
        install_node: bool = True,
    ) -> dagger.Container:
        """Install Python and Node.js dependencies using uv

        Args:
            container: Container with edx-platform source at /openedx/edx-platform
            deployment_name: Deployment name
            release_name: Release name (e.g., sumac, redwood)
            pip_package_lists: Directory containing pip requirements files
            pip_package_overrides: Directory containing pip override requirements
            node_version: Node.js version (default: 20.18.0). A ``MAJOR`` or
                ``MAJOR.MINOR`` prefix resolves to the latest matching release;
                a full ``MAJOR.MINOR.PATCH`` is used verbatim.
            packages_to_remove: Python packages to uninstall after base install
                (e.g., packages that conflict with deployment-specific builds).
                Default: empty list — no packages removed.
            extra_npm_packages: Additional npm packages to install after
                ``npm clean-install`` (e.g., private packages from git).
                Default: empty list — no extra packages.
            install_node: Install Node.js (nodeenv) and run ``npm clean-install``
                for edx-platform's frontend assets. Default ``True``. Set
                ``False`` for Python-only consumers (e.g. plugin import checks,
                settings regeneration) that never build webpack assets — the
                Python environment above is complete without it.

        Returns:
            Container with all dependencies installed
        """
        if packages_to_remove is None:
            packages_to_remove = []
        if extra_npm_packages is None:
            extra_npm_packages = []

        container = (
            container.with_mounted_directory(
                "/root/pip_package_lists", pip_package_lists
            )
            .with_mounted_directory(
                "/root/pip_package_overrides", pip_package_overrides
            )
            # Copy base requirements from edx-platform
            .with_exec(
                [
                    "sh",
                    "-c",
                    "cp /openedx/edx-platform/requirements/edx/base.txt /root/pip_package_lists/edx_base.txt",
                ]
            )
            .with_exec(
                [
                    "sh",
                    "-c",
                    "cp /openedx/edx-platform/requirements/edx/assets.txt /root/pip_package_lists/edx_assets.txt",
                ]
            )
            # Install base Python dependencies using uv (much faster than pip)
            # uv automatically uses the VIRTUAL_ENV set in apt_base
            .with_exec(
                [
                    "uv",
                    "pip",
                    "install",
                    "-r",
                    "/root/pip_package_lists/edx_base.txt",
                    "-r",
                    "/root/pip_package_lists/edx_assets.txt",
                    "-r",
                    f"/root/pip_package_lists/{release_name}/{deployment_name}.txt",
                ]
            )
        )

        # Remove any deployment-specific packages that conflict with the build
        for pkg in packages_to_remove:
            container = container.with_exec(["uv", "pip", "uninstall", pkg])

        # Fix lxml/xmlsec compatibility issues by building from source.
        # --no-binary is a CLI flag that uv pip install supports; it is NOT
        # an in-requirements-file option, so uv handles it correctly here.
        #
        # lxml and xmlsec are passed as explicit install targets (not only as
        # --no-binary arguments) so the from-source rebuild always reinstalls
        # them after the uninstall above — regardless of whether the deployment
        # overrides file happens to list them. A deployment that *does* pin them
        # (e.g. lxml==5.3.0) still wins, because the -r requirement constrains
        # the version of the unversioned positional package.
        container = container.with_exec(
            ["uv", "pip", "uninstall", "lxml", "xmlsec"]
        ).with_exec(
            [
                "uv",
                "pip",
                "install",
                "--no-cache-dir",
                "--no-binary",
                "lxml",
                "--no-binary",
                "xmlsec",
                "lxml",
                "xmlsec",
                "-r",
                f"/root/pip_package_overrides/{release_name}/{deployment_name}.txt",
            ]
        )

        # Pin setuptools < 82 as the final pip step. uv-created venvs do not seed
        # setuptools, and edx-platform imports ``pkg_resources`` (pyfilesystem's
        # ``fs`` and legacy ``pkg_resources.declare_namespace`` packages).
        # pkg_resources was removed in setuptools 82, and the base-requirements
        # resolution above pulls in the latest (>= 82) — so this must run last,
        # after that resolution, to guarantee a pkg_resources-bearing setuptools.
        container = container.with_exec(
            ["uv", "pip", "install", "setuptools<82", "wheel", "pip"]
        )

        # Install Node.js using nodeenv (skipped for Python-only consumers).
        if not install_node:
            return container

        # nodeenv --prebuilt only resolves a tarball for a full MAJOR.MINOR.PATCH,
        # so expand a manifest prefix (e.g. "24") to the latest matching release
        # here — the resolution the Concourse pipeline used to do out-of-band.
        resolved_node_version = resolve_node_version(node_version)

        container = (
            container.with_workdir("/openedx/edx-platform")
            .with_env_variable("NPM_REGISTRY", "https://registry.npmjs.org/")
            .with_exec(
                [
                    "sh",
                    "-c",
                    f"nodeenv /openedx/nodeenv --node={resolved_node_version} --prebuilt",
                ]
            )
            .with_env_variable(
                "PATH",
                "/openedx/venv/bin:/openedx/nodeenv/bin:/usr/local/bin:/usr/bin:/bin",
            )
            .with_exec(
                [
                    "sh",
                    "-c",
                    "npm clean-install -s --registry=https://registry.npmjs.org/",
                ]
            )
        )

        # Install any extra npm packages (e.g. private packages from git)
        for pkg in extra_npm_packages:
            container = container.with_exec(["npm", "install", pkg])

        return container

    @function
    def dockerize(self) -> dagger.File:
        """Get dockerize binary for templating and waiting

        Returns:
            Dockerize binary file
        """
        return (
            dag.container()
            .from_(
                "docker.io/powerman/dockerize@sha256:f3ecfd5ac0f74eed3990782309ac6bf8b700f4eca0ea9e9ef507b11742c19cc6"
            )
            .file("/usr/local/bin/dockerize")
        )

    @function
    def tutor_utils(
        self,
        tutor_version: str = "v19.0.0",
    ) -> dagger.Directory:
        """Get utility scripts from Tutor

        Args:
            tutor_version: Tutor version tag (default: v19.0.0)

        Returns:
            Directory with tutor bin scripts
        """
        return (
            dag.container()
            .from_("debian:bookworm-slim")
            .with_exec(["apt-get", "update"])
            .with_exec(["apt-get", "install", "-y", "git"])
            .with_exec(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    tutor_version,
                    "https://github.com/overhangio/tutor.git",
                    "/openedx/tutor",
                ]
            )
            .directory("/openedx/tutor/tutor/templates/build/openedx/bin")
        )

    @function
    def collected(
        self,
        container: dagger.Container,
        deployment_name: str,
        dockerize_bin: dagger.File,
        tutor_bin: dagger.Directory,
        custom_settings: dagger.Directory,
        settings_namespace: str = "production",
        app_user_id: int = 1000,
        include_locales: bool = True,
    ) -> dagger.Container:
        """Assemble all artifacts and configure the container

        Injects only the files required for static asset compilation
        (``assets.py``, ``i18n.py``, ``lms.env.yml``, ``cms.env.yml``).
        The aqueduct runtime settings are injected separately by
        :meth:`inject_aqueduct_settings`, which is called *after*
        ``build_static_assets`` so that aqueduct edits do not invalidate
        the npm/collectstatic cache layer.

        The ``custom_settings`` directory must follow this layout::

            custom_settings/
            ├── lms.env.yml
            ├── cms.env.yml
            ├── lms/
            │   ├── assets.py        ← used here (needed by collectstatic)
            │   ├── i18n.py          ← used here (needed by compilemessages)
            │   ├── aqueduct.py      ← used by inject_aqueduct_settings()
            │   └── models/
            │       └── aqueduct.py  ← used by inject_aqueduct_settings()
            ├── cms/
            │   ├── assets.py
            │   ├── i18n.py
            │   ├── aqueduct.py
            │   └── models/
            │       └── aqueduct.py
            ├── set_waffle_flags.py
            ├── process_scheduled_emails.py
            └── saml_pull.py

        ``ProductionSettingsMixin`` (``models/base.py``) is supplied by lehrer
        core via :meth:`inject_aqueduct_settings` — operators do not provide it.

        Args:
            container: Container with installed dependencies
            deployment_name: Deployment name
            dockerize_bin: Dockerize binary file
            tutor_bin: Tutor bin directory with utility scripts
            custom_settings: Directory with custom settings and config files
                (must follow the layout described above)
            settings_namespace: Django settings sub-package name.  All settings
                files are copied into ``lms/envs/{settings_namespace}/`` and
                ``cms/envs/{settings_namespace}/`` inside edx-platform.
                Default: ``"production"``.  See docs/creating-a-deployment.md for guidance.
            app_user_id: User ID for app user (default: 1000)
            include_locales: Include locale files (default: True)

        Returns:
            Container with all artifacts collected and configured
        """
        if app_user_id == 0:
            raise ValueError("app user may not be root")

        # Create app user (needs /usr/sbin in PATH for useradd)
        # Copy tutor bin and set permissions before switching to app user
        # Then chown entire /openedx directory (includes venv, edx-platform, themes, etc.)
        container = (
            container.with_env_variable(
                "PATH",
                "/usr/sbin:/openedx/venv/bin:/openedx/nodeenv/bin:/usr/local/bin:/usr/bin:/bin",
            )
            .with_directory("/openedx/bin", tutor_bin)
            .with_exec(["chmod", "-R", "a+x", "/openedx/bin"])
            .with_exec(
                [
                    "useradd",
                    "--home-dir",
                    "/openedx",
                    "--create-home",
                    "--shell",
                    "/bin/bash",
                    "--uid",
                    str(app_user_id),
                    "app",
                ]
            )
            .with_exec(["chown", "-R", f"{app_user_id}:{app_user_id}", "/openedx"])
            .with_user(str(app_user_id))
            .with_file("/usr/local/bin/dockerize", dockerize_bin)
        )

        # Set up PATH for app user
        container = container.with_env_variable(
            "PATH",
            "/openedx/venv/bin:/openedx/bin:/openedx/edx-platform/node_modules/.bin:/openedx/nodeenv/bin:/usr/local/bin:/usr/bin:/bin",
        )

        # Install edx-platform in editable mode using uv
        container = (
            container.with_workdir("/openedx/edx-platform")
            .with_exec(["uv", "pip", "install", "-e", "."])
            .with_exec(
                [
                    "mkdir",
                    "-p",
                    "/openedx/config",
                    f"./lms/envs/{settings_namespace}",
                    "./lms/envs/models",
                    f"./cms/envs/{settings_namespace}",
                    "./cms/envs/models",
                ]
            )
        )

        # Inject per-file using with_file rather than a bulk directory mount.
        # A mounted-directory cache key covers the ENTIRE custom_settings tree,
        # so any edit (even to aqueduct.py) would bust the cache for assets.py
        # and every downstream step, including the heavy npm/collectstatic build.
        # Per-file injection gives each file an independent cache key.
        #
        # Only the files needed for `collectstatic` / `compilemessages` are
        # injected here.  The aqueduct runtime settings are injected later (after
        # build_static_assets) via inject_aqueduct_settings() so that iterating
        # on aqueduct.py never invalidates the static-asset cache.
        container = (
            container.with_file(
                "/openedx/config/lms.env.yml",
                custom_settings.file("lms.env.yml"),
            )
            .with_file(
                "/openedx/config/cms.env.yml",
                custom_settings.file("cms.env.yml"),
            )
            .with_file(
                f"/openedx/edx-platform/lms/envs/{settings_namespace}/assets.py",
                custom_settings.file("lms/assets.py"),
            )
            .with_file(
                f"/openedx/edx-platform/lms/envs/{settings_namespace}/i18n.py",
                custom_settings.file("lms/i18n.py"),
            )
            .with_file(
                f"/openedx/edx-platform/cms/envs/{settings_namespace}/assets.py",
                custom_settings.file("cms/assets.py"),
            )
            .with_file(
                f"/openedx/edx-platform/cms/envs/{settings_namespace}/i18n.py",
                custom_settings.file("cms/i18n.py"),
            )
        )

        # Set environment variables
        container = (
            container.with_env_variable("REVISION_CFG", "/openedx/config/revisions.yml")
            .with_env_variable("LMS_CFG", "/openedx/config/lms.env.yml")
            .with_env_variable("CMS_CFG", "/openedx/config/cms.env.yml")
            .with_env_variable("NO_PYTHON_UNINSTALL", "1")
            .with_env_variable("NO_PREREQ_INSTALL", "0")
        )

        return container

    @function
    def inject_aqueduct_settings(
        self,
        container: dagger.Container,
        custom_settings: dagger.Directory,
        settings_namespace: str = "production",
    ) -> dagger.Container:
        """Inject django-aqueduct runtime settings into the container.

        This is deliberately separate from ``collected()`` so that iterating on
        ``aqueduct.py`` or ``models/aqueduct.py`` during local development does
        NOT invalidate the ``build_static_assets`` cache layer.  The static-asset
        build only needs ``assets.py`` and ``i18n.py``; those are injected by
        ``collected()``.  Everything aqueduct-specific goes here.

        Call order in ``build_platform``::

            collected()              ← assets.py + i18n.py
            fetch_translations()
            build_static_assets()   ← cached; unaffected by aqueduct changes
            inject_aqueduct_settings()   ← this function
            docker_image()

        Args:
            container: Container produced by ``build_static_assets()``.
            custom_settings: Operator settings directory (same one passed to
                ``collected()``).
            settings_namespace: Django settings sub-package name — must match
                the value passed to ``collected()``.  Default: ``"production"``.

        Returns:
            Container with aqueduct runtime settings and helper scripts wired in.
        """
        # models/base.py comes from lehrer core, not from the operator's
        # custom_settings, so it is injected via dag.current_module().source().
        # Using .file() gives a cache key based on that single file's content,
        # not the entire lehrer source tree.
        lehrer_base = dag.current_module().source().file("src/lehrer/settings/base.py")
        return (
            container
            # django-aqueduct settings:
            # models/base.py    → ProductionSettingsMixin from lehrer core
            # models/__init__.py → makes models/ a package for relative imports
            # models/aqueduct.py → pure generated AqueductSettings(BaseSettings)
            # aqueduct.py       → entry point; composes
            #                     <Svc>ProductionSettings(ProductionSettingsMixin,
            #                     AqueductSettings) then configure_django_settings
            #                     (DJANGO_SETTINGS_MODULE=<svc>.envs.aqueduct)
            .with_file(
                "/openedx/edx-platform/lms/envs/models/base.py",
                lehrer_base,
            )
            .with_new_file(
                "/openedx/edx-platform/lms/envs/models/__init__.py", contents=""
            )
            .with_file(
                "/openedx/edx-platform/lms/envs/models/aqueduct.py",
                custom_settings.file("lms/models/aqueduct.py"),
            )
            .with_file(
                "/openedx/edx-platform/lms/envs/aqueduct.py",
                custom_settings.file("lms/aqueduct.py"),
            )
            .with_file(
                "/openedx/edx-platform/cms/envs/models/base.py",
                lehrer_base,
            )
            .with_new_file(
                "/openedx/edx-platform/cms/envs/models/__init__.py", contents=""
            )
            .with_file(
                "/openedx/edx-platform/cms/envs/models/aqueduct.py",
                custom_settings.file("cms/models/aqueduct.py"),
            )
            .with_file(
                "/openedx/edx-platform/cms/envs/aqueduct.py",
                custom_settings.file("cms/aqueduct.py"),
            )
            # Runtime helper scripts (not needed for asset compilation)
            .with_file(
                "/openedx/edx-platform/set_waffle_flags.py",
                custom_settings.file("set_waffle_flags.py"),
            )
            .with_file(
                "/openedx/edx-platform/process_scheduled_emails.py",
                custom_settings.file("process_scheduled_emails.py"),
            )
            .with_file(
                "/openedx/edx-platform/saml_pull.py",
                custom_settings.file("saml_pull.py"),
            )
        )

    @function
    def fetch_translations(
        self,
        container: dagger.Container,
        translations_repository: str,
        settings_namespace: str = "production",
        translations_branch: str = "main",
        strict: bool = False,  # noqa: FBT001, FBT002
    ) -> dagger.Container:
        """Fetch and compile translations using atlas

        Args:
            container: Container with collected artifacts
            translations_repository: Repository for translations (required —
                e.g. ``"openedx/openedx-translations"`` for the upstream
                community repo, or your deployment's own translations repo).
            settings_namespace: Django settings sub-package name used to
                determine the ``DJANGO_SETTINGS_MODULE`` for management
                commands (``lms.envs.{settings_namespace}.i18n`` and
                ``cms.envs.{settings_namespace}.i18n``).  Must match the
                value passed to ``collected()``.  Default: ``"production"``.
            translations_branch: Branch for translations (default: main)
            strict: Fail the build when an optional pull/compile step fails
                instead of warning and continuing (default: False).  See
                :func:`_tolerant` for why these steps are tolerant by default.

        Returns:
            Container with compiled translations
        """
        safe_repo = shlex.quote(translations_repository)
        safe_branch = shlex.quote(translations_branch)
        atlas_options = f"--repository {safe_repo} --revision {safe_branch}"

        # Check if pull_plugin_translations command exists
        container = container.with_env_variable(
            "DJANGO_SETTINGS_MODULE", f"lms.envs.{settings_namespace}.i18n"
        ).with_workdir("/openedx/edx-platform")

        def _step(command: str, label: str) -> list[str]:
            return ["sh", "-c", _tolerant(command, label, strict=strict)]

        # Pull and compile LMS translations
        container = (
            container.with_exec(
                _step(
                    f"python manage.py lms pull_plugin_translations {atlas_options}",
                    "lms pull_plugin_translations",
                )
            )
            .with_exec(
                _step(
                    "python manage.py lms compile_plugin_translations",
                    "lms compile_plugin_translations",
                )
            )
            .with_exec(
                _step(
                    f"python manage.py lms pull_xblock_translations {atlas_options}",
                    "lms pull_xblock_translations",
                )
            )
            .with_exec(
                _step(
                    "python manage.py lms compile_xblock_translations",
                    "lms compile_xblock_translations",
                )
            )
            .with_exec(
                _step(
                    f"atlas pull {atlas_options} "
                    "translations/edx-platform/conf/locale:conf/locale",
                    "atlas pull edx-platform locale",
                )
            )
            .with_exec(["python", "manage.py", "lms", "compilemessages"])
            .with_exec(["python", "manage.py", "lms", "compilejsi18n"])
        )

        # Compile CMS translations
        container = (
            container.with_env_variable(
                "DJANGO_SETTINGS_MODULE", f"cms.envs.{settings_namespace}.i18n"
            )
            .with_exec(
                _step(
                    "python manage.py cms compile_xblock_translations",
                    "cms compile_xblock_translations",
                )
            )
            .with_exec(
                _step(
                    f"atlas pull {atlas_options} translations/studio-frontend/src/"
                    "i18n/messages:conf/plugins-locale/studio-frontend",
                    "atlas pull studio-frontend messages",
                )
            )
            .with_exec(["python", "manage.py", "cms", "compilejsi18n"])
        )

        return container

    @function
    def build_static_assets(
        self,
        container: dagger.Container,
        deployment_name: str,
        settings_namespace: str = "production",
    ) -> dagger.Container:
        """Build and collect static assets

        Args:
            container: Container with translations
            deployment_name: Deployment name for theme
            settings_namespace: Django settings sub-package name used for
                ``--settings={settings_namespace}.assets`` in collectstatic
                calls.  Must match the value passed to ``collected()``.
                Default: ``"production"``.

        Returns:
            Container with static assets built
        """
        # Set environment for asset building
        container = (
            container.with_env_variable("STATIC_ROOT_LMS", "/openedx/staticfiles/")
            .with_env_variable("NODE_ENV", "prod")
            .with_env_variable(
                "JS_ENV_EXTRA_CONFIG",
                '{"PROCTORTRACK_CDN_URL":"\\"\\"","PROCTORTRACK_CONFIG_KEY":"\\"\\""}',
            )
        )

        # Build static assets
        container = (
            container.with_exec(["mkdir", "-p", "/openedx/staticfiles/"])
            .with_exec(["npm", "run", "postinstall"])
            .with_exec(
                [
                    "npm",
                    "run",
                    "compile-sass",
                    "--",
                    "--theme-dir",
                    "/openedx/themes/",
                    "--theme",
                    deployment_name,
                ]
            )
            .with_exec(
                [
                    "python",
                    "manage.py",
                    "lms",
                    "collectstatic",
                    "--noinput",
                    f"--settings={settings_namespace}.assets",
                ]
            )
            .with_exec(
                [
                    "python",
                    "manage.py",
                    "cms",
                    "collectstatic",
                    "--noinput",
                    f"--settings={settings_namespace}.assets",
                ]
            )
            .with_exec(["npm", "run", "webpack"])
            .with_exec(
                [
                    "python",
                    "manage.py",
                    "lms",
                    "collectstatic",
                    "--noinput",
                    f"--settings={settings_namespace}.assets",
                ]
            )
            .with_exec(
                [
                    "python",
                    "manage.py",
                    "cms",
                    "collectstatic",
                    "--noinput",
                    f"--settings={settings_namespace}.assets",
                ]
            )
            .with_exec(
                [
                    "rdfind",
                    "-makesymlinks",
                    "true",
                    "-followsymlinks",
                    "true",
                    "/openedx/staticfiles/",
                ]
            )
            .with_exec(["mkdir", "-p", "/openedx/data/export_course_repos"])
            .with_exec(["mkdir", "-p", "/openedx/data/var/log/edx"])
        )

        return container

    @function
    def docker_image(
        self,
        container: dagger.Container,
        deployment_name: str,
        release_name: str,
        extra_ssh_hosts: list[str] | None = None,
    ) -> dagger.Container:
        """Finalize the Docker image for deployment

        Args:
            container: Container with static assets built
            deployment_name: Deployment name
            release_name: Release name
            extra_ssh_hosts: Additional SSH hosts to add to known_hosts beyond
                ``github.com``.  Pass e.g. ``["git.example.com"]`` for internal
                Git servers that host private packages.
                Default: empty list — only ``github.com`` is scanned.

        Returns:
            Container ready for deployment
        """
        if extra_ssh_hosts is None:
            extra_ssh_hosts = []

        import shlex

        all_hosts = ["github.com"] + extra_ssh_hosts
        hosts_str = " ".join(shlex.quote(h) for h in all_hosts)

        container = (
            container.with_env_variable("DJANGO_SETTINGS_MODULE", "invalid")
            # Byte-compile Python files for faster startup
            .with_exec(
                [
                    "python",
                    "-m",
                    "compileall",
                    "-q",
                    "/openedx/edx-platform",
                    "/openedx/venv",
                ]
            )
            # Set up SSH config for GitHub
            .with_exec(["mkdir", "/openedx/.ssh"])
            .with_exec(["chown", "app:app", "/openedx/.ssh"])
            .with_exec(["chmod", "0700", "/openedx/.ssh"])
            .with_exec(
                [
                    "sh",
                    "-c",
                    f"ssh-keyscan {hosts_str} >> /openedx/.ssh/known_hosts",
                ]
            )
            .with_exec(["chmod", "0600", "/openedx/.ssh/known_hosts"])
            # Create export directory
            .with_exec(["mkdir", "-p", "/openedx/data/export_course_repos"])
            # Configure git
            .with_exec(["git", "config", "--global", "--add", "safe.directory", "*"])
        )

        return container

    async def _resolve_manifest_cell(
        self,
        build_manifest: dagger.File,
        release_name: str,
        deployment_name: str,
    ) -> tuple[BuildManifest, Cell]:
        """Parse ``build_manifest`` and resolve the requested cell.

        Dagger-coupled (reads file contents); all parsing/rendering/resolution
        beyond that is delegated to the pure ``build_manifest`` module.
        """
        manifest = BuildManifest.model_validate(
            yaml.safe_load(await build_manifest.contents())
        )
        cell = manifest.resolve_cell(release_name, deployment_name)
        return manifest, cell

    def _materialize_cell_requirements(
        self, release_name: str, deployment_name: str, cell: Cell
    ) -> tuple[dagger.Directory, dagger.Directory]:
        """Materialize a cell's packages/overrides into the ``install_deps`` layout."""
        lists = dag.directory().with_new_file(
            f"{release_name}/{deployment_name}.txt", cell.render_packages()
        )
        overrides = dag.directory().with_new_file(
            f"{release_name}/{deployment_name}.txt", cell.render_overrides()
        )
        return lists, overrides

    async def _resolve_cell(  # noqa: PLR0913
        self,
        *,
        caller: str,
        deployment_name: str,
        release_name: str,
        build_manifest: dagger.File | None,
        pip_package_lists: dagger.Directory | None,
        pip_package_overrides: dagger.Directory | None,
        platform_repo: str | None = None,
        platform_branch: str | None = None,
        python_version: str | None = None,
        node_version: str | None = None,
        packages_to_remove: list[str] | None = None,
        extra_npm_packages: list[str] | None = None,
    ) -> _ResolvedCell:
        """Resolve every build parameter for one cell (see :class:`_ResolvedCell`).

        Args:
            caller: Dagger function name, used only in the error message when
                neither a manifest nor both requirement directories are given.
            deployment_name: Deployment name.
            release_name: edx-platform release / branch name.
            build_manifest: Optional ``build_manifest.yaml``; when given, its
                matching cell supplies requirements and any parameter the caller
                left unset.
            pip_package_lists: Requirements directory. Required without a manifest.
            pip_package_overrides: Overrides directory. Required without a manifest.
            platform_repo: Git repository URL for edx-platform.
            platform_branch: Git branch to check out.
            python_version: Python version. Defaults to 3.12 for master, else 3.11.
            node_version: Node.js version.
            packages_to_remove: Packages to uninstall after the base install.
            extra_npm_packages: Additional npm packages to install.

        Returns:
            The fully resolved cell parameters.

        Raises:
            ValueError: Neither ``build_manifest`` nor both requirement
                directories were supplied.
        """
        manifest: BuildManifest | None = None
        cell: Cell | None = None
        if build_manifest is not None:
            manifest, cell = await self._resolve_manifest_cell(
                build_manifest, release_name, deployment_name
            )
            manifest_lists, manifest_overrides = self._materialize_cell_requirements(
                release_name, deployment_name, cell
            )
            if pip_package_lists is None:
                pip_package_lists = manifest_lists
            if pip_package_overrides is None:
                pip_package_overrides = manifest_overrides

        if pip_package_lists is None or pip_package_overrides is None:
            msg = (
                f"{caller} requires either --build-manifest, or both "
                "--pip-package-lists and --pip-package-overrides"
            )
            raise ValueError(msg)

        def _list_field(explicit: list[str] | None, name: str) -> list[str]:
            if explicit is not None:
                return explicit
            if cell is not None and manifest is not None:
                resolved = cell.resolved(name, manifest)
                if resolved is not None:
                    return cast("list[str]", resolved)
            return []

        if python_version is None:
            resolved_python = None
            if cell is not None and manifest is not None:
                resolved_python = cell.resolved("python_version", manifest)
            # master tracks edx-platform's own 3.12 floor; named releases are
            # still on 3.11 until they cut over.
            python_version = cast("str | None", resolved_python) or (
                "3.12" if release_name == "master" else "3.11"
            )

        return _ResolvedCell(
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            platform_repo=_resolve_field(
                platform_repo,
                cell,
                manifest,
                "platform_repo",
                "https://github.com/openedx/edx-platform",
            ),
            platform_branch=_resolve_field(
                platform_branch, cell, manifest, "platform_branch", "master"
            ),
            python_version=python_version,
            node_version=_resolve_field(
                node_version, cell, manifest, "node_version", "20.18.0"
            ),
            packages_to_remove=_list_field(packages_to_remove, "packages_to_remove"),
            extra_npm_packages=_list_field(extra_npm_packages, "extra_npm_packages"),
        )

    def _python_only_env(
        self,
        cell: _ResolvedCell,
        deployment_name: str,
        release_name: str,
        aqueduct_source: dagger.Directory | None = None,
    ) -> dagger.Container:
        """edx-platform checkout with the cell's Python deps installed, no Node.

        Shared by the settings-verification entry points (``verify_settings``,
        ``regenerate_aqueduct_settings``).  Both need a working ``lms.envs.*``
        import — which needs the plugins installed — but neither compiles
        frontend assets, and installing Node (a nodeenv tarball download) would
        add a pure failure surface to a check that never uses it.

        Args:
            cell: Resolved build parameters for the target cell.
            deployment_name: Deployment name (names the requirements file).
            release_name: Release name (names the requirements sub-directory).
            aqueduct_source: Optional local django-aqueduct checkout, installed
                editable *before* the deployment requirements so its version
                satisfies the pinned ``django-aqueduct==`` constraint and uv
                skips the PyPI fetch.  Lets a verification run pick up
                unreleased framework fixes.

        Returns:
            A container with the workdir set to ``/openedx/edx-platform``.
        """
        container: dagger.Container = self.apt_base(python_version=cell.python_version)
        container = self.get_code(
            container,
            edx_platform_git_repo=cell.platform_repo,
            edx_platform_git_branch=cell.platform_branch,
        )
        container = (
            container.with_mounted_directory(
                "/root/pip_package_lists", cell.pip_package_lists
            )
            .with_mounted_directory(
                "/root/pip_package_overrides", cell.pip_package_overrides
            )
            .with_exec(
                [
                    "sh",
                    "-c",
                    "cp /openedx/edx-platform/requirements/edx/base.txt"
                    " /root/pip_package_lists/edx_base.txt"
                    " && cp /openedx/edx-platform/requirements/edx/assets.txt"
                    " /root/pip_package_lists/edx_assets.txt",
                ]
            )
        )

        if aqueduct_source is not None:
            container = container.with_mounted_directory(
                "/root/django-aqueduct", aqueduct_source
            ).with_exec(["uv", "pip", "install", "-e", "/root/django-aqueduct"])

        container = container.with_exec(
            [
                "uv",
                "pip",
                "install",
                "-r",
                "/root/pip_package_lists/edx_base.txt",
                "-r",
                "/root/pip_package_lists/edx_assets.txt",
                "-r",
                f"/root/pip_package_lists/{release_name}/{deployment_name}.txt",
            ]
        )

        for pkg in cell.packages_to_remove:
            container = container.with_exec(["uv", "pip", "uninstall", pkg])

        # Reinstall lxml/xmlsec from source. They are passed as explicit install
        # targets (not only --no-binary args) so they always come back after the
        # uninstall, even when the deployment overrides file does not list them.
        container = container.with_exec(
            ["uv", "pip", "uninstall", "lxml", "xmlsec"]
        ).with_exec(
            [
                "uv",
                "pip",
                "install",
                "--no-cache-dir",
                "--no-binary",
                "lxml",
                "--no-binary",
                "xmlsec",
                "lxml",
                "xmlsec",
                "-r",
                f"/root/pip_package_overrides/{release_name}/{deployment_name}.txt",
            ]
        )

        return container.with_workdir("/openedx/edx-platform").with_exec(
            ["uv", "pip", "install", "-e", "."]
        )

    @function
    async def build_platform(
        self,
        deployment_name: str,
        release_name: str,
        custom_settings: dagger.Directory,
        build_manifest: dagger.File | None = None,
        pip_package_lists: dagger.Directory | None = None,
        pip_package_overrides: dagger.Directory | None = None,
        translations_repo: str | None = None,
        source: dagger.Directory | None = None,
        platform_repo: str | None = None,
        platform_branch: str | None = None,
        theme_source: dagger.Directory | None = None,
        theme_repo: str | None = None,
        theme_branch: str | None = None,
        python_version: str | None = None,
        node_version: str | None = None,
        locale_version: str = "master",
        translations_branch: str | None = None,
        include_locales: bool = True,
        settings_namespace: str | None = None,
        extra_ssh_hosts: list[str] | None = None,
        packages_to_remove: list[str] | None = None,
        extra_npm_packages: list[str] | None = None,
        verify_boot: bool = True,  # noqa: FBT001, FBT002
        strict_translations: bool = False,  # noqa: FBT001, FBT002
    ) -> dagger.Container:
        """Build a complete openedx-platform image

        This chains together all the build steps into a multi-stage pipeline.

        Args:
            deployment_name: Deployment name
            release_name: Release name (e.g., master, sumac, redwood)
            custom_settings: Directory with custom settings files
            build_manifest: Optional ``build_manifest.yaml`` (see
                ``lehrer.core.build_manifest``). When given, the cell matching
                ``(release_name, deployment_name)`` supplies
                ``pip_package_lists``/``pip_package_overrides`` (materialized
                on the fly) and every other parameter below that the caller
                did not pass explicitly — an explicit CLI arg always wins.
            pip_package_lists: Directory with pip requirements files. Required
                unless ``build_manifest`` is given.
            pip_package_overrides: Directory with pip override requirements.
                Required unless ``build_manifest`` is given.
            translations_repo: Translations repository (default:
                ``"openedx/openedx-translations"`` — the upstream community
                repo).  Pass your deployment's own translations repo if you
                maintain separate translations.
            source: Local edx-platform source (optional)
            platform_repo: Git repo URL (used if source not provided)
            platform_branch: Git branch (used if source not provided)
            theme_source: Local theme source (optional)
            theme_repo: Theme git repo URL (optional)
            theme_branch: Theme git branch (optional)
            python_version: Python version (default: 3.12 for master, 3.11 for others)
            node_version: Node.js version (default: 20.18.0)
            locale_version: openedx-i18n version (default: master, repo is archived)
            translations_branch: Translations branch (default: main)
            include_locales: Include locale files (default: True)
            settings_namespace: Django settings sub-package name (default:
                ``"production"``).  See docs/creating-a-deployment.md for guidance.
            extra_ssh_hosts: Additional SSH hosts beyond ``github.com``
                (default: empty list — only ``github.com`` is scanned).
            packages_to_remove: Python packages to uninstall after base install
                (default: empty list).
            extra_npm_packages: Additional npm packages to install after
                ``npm clean-install`` (default: empty list).
            verify_boot: Run Django's system checks against the finished image
                for both services, failing the build if it cannot start
                (default: True).
            strict_translations: Fail the build when an optional translation
                pull/compile step fails, instead of warning (default: False —
                a missing plugin translation is normal, so this is opt-in until
                the per-step baseline is known).

        Returns:
            Container ready to be deployed
        """
        manifest: BuildManifest | None = None
        cell: Cell | None = None
        if build_manifest is not None:
            manifest, cell = await self._resolve_manifest_cell(
                build_manifest, release_name, deployment_name
            )
            manifest_lists, manifest_overrides = self._materialize_cell_requirements(
                release_name, deployment_name, cell
            )
            if pip_package_lists is None:
                pip_package_lists = manifest_lists
            if pip_package_overrides is None:
                pip_package_overrides = manifest_overrides

        if pip_package_lists is None or pip_package_overrides is None:
            msg = (
                "build_platform requires either --build-manifest, or both "
                "--pip-package-lists and --pip-package-overrides"
            )
            raise ValueError(msg)

        platform_repo = _resolve_field(
            platform_repo,
            cell,
            manifest,
            "platform_repo",
            "https://github.com/openedx/edx-platform",
        )
        platform_branch = _resolve_field(
            platform_branch, cell, manifest, "platform_branch", "master"
        )
        translations_repo = _repo_shorthand(
            _resolve_field(
                translations_repo,
                cell,
                manifest,
                "translations_repo",
                "openedx/openedx-translations",
            )
        )
        translations_branch = _resolve_field(
            translations_branch, cell, manifest, "translations_branch", "main"
        )
        settings_namespace = _resolve_field(
            settings_namespace, cell, manifest, "settings_namespace", "production"
        )
        node_version = _resolve_field(
            node_version, cell, manifest, "node_version", "20.18.0"
        )
        if theme_repo is None and cell is not None and manifest is not None:
            resolved_theme_repo = cell.resolved("theme_repo", manifest)
            if resolved_theme_repo:
                theme_repo = cast("str", resolved_theme_repo)
        if theme_branch is None and cell is not None and manifest is not None:
            resolved_theme_branch = cell.resolved("theme_branch", manifest)
            if resolved_theme_branch:
                theme_branch = cast("str", resolved_theme_branch)
        if extra_ssh_hosts is None:
            extra_ssh_hosts = []
            if cell is not None and manifest is not None:
                resolved_hosts = cell.resolved("extra_ssh_hosts", manifest)
                if resolved_hosts is not None:
                    extra_ssh_hosts = cast("list[str]", resolved_hosts)
        if packages_to_remove is None:
            packages_to_remove = []
            if cell is not None and manifest is not None:
                resolved_removals = cell.resolved("packages_to_remove", manifest)
                if resolved_removals is not None:
                    packages_to_remove = cast("list[str]", resolved_removals)
        if extra_npm_packages is None:
            extra_npm_packages = []
            if cell is not None and manifest is not None:
                resolved_npm = cell.resolved("extra_npm_packages", manifest)
                if resolved_npm is not None:
                    extra_npm_packages = cast("list[str]", resolved_npm)

        # Determine Python version: explicit arg > manifest cell/release_python
        # > 3.12-for-master/3.11-otherwise fallback.
        if python_version is None:
            resolved_python_version = None
            if cell is not None and manifest is not None:
                resolved_python_version = cell.resolved("python_version", manifest)
            python_version = cast("str | None", resolved_python_version) or (
                "3.12" if release_name == "master" else "3.11"
            )

        # ── Deps chain ────────────────────────────────────────────────────────
        # Run the heavy install steps on a throw-away chain.  All build caches
        # (npm ~/.npm, pip /tmp artefacts) accumulate here and are discarded
        # when we copy only the three needed directories to the clean base
        # below, following the same multi-stage pattern.
        deps: dagger.Container = self.apt_base(python_version=python_version)
        deps = self.get_code(
            deps,
            source=source,
            edx_platform_git_repo=platform_repo,
            edx_platform_git_branch=platform_branch,
        )
        deps = self.install_deps(
            deps,
            deployment_name=deployment_name,
            release_name=release_name,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            node_version=node_version,
            packages_to_remove=packages_to_remove,
            extra_npm_packages=extra_npm_packages,
        )

        # ── Clean base ────────────────────────────────────────────────────────
        # Start fresh (equivalent to a multi-stage build's clean base layer).
        # Copy only the built artefacts; npm/uv/pip caches are left behind.
        container: dagger.Container = self.apt_base(python_version=python_version)
        container = (
            container.with_directory("/openedx/venv", deps.directory("/openedx/venv"))
            .with_directory(
                "/openedx/edx-platform", deps.directory("/openedx/edx-platform")
            )
            .with_directory("/openedx/nodeenv", deps.directory("/openedx/nodeenv"))
            # Carry the PATH that install_deps set so nodeenv is on PATH
            .with_env_variable(
                "PATH",
                "/openedx/venv/bin:/openedx/nodeenv/bin:/usr/local/bin:/usr/bin:/bin",
            )
        )

        # Locales run on the clean base (not the deps chain)
        if include_locales:
            container = self.locales(container, locale_version=locale_version)

        # Themes are a plain directory copy; apply directly to the clean base
        if theme_source or theme_repo:
            container = self.themes(
                container,
                deployment_name=deployment_name,
                theme_source=theme_source,
                theme_git_repo=theme_repo,
                theme_git_branch=theme_branch,
            )

        # ── Remaining pipeline ────────────────────────────────────────────────
        tutor_bin = self.tutor_utils()
        dockerize_bin = self.dockerize()

        # Phase 1: inject only the files needed for asset compilation
        # (assets.py, i18n.py, env.yml).  Aqueduct settings are injected
        # AFTER build_static_assets so that editing aqueduct.py during
        # local development does not invalidate the npm/collectstatic cache.
        container = self.collected(
            container,
            deployment_name=deployment_name,
            dockerize_bin=dockerize_bin,
            tutor_bin=tutor_bin,
            custom_settings=custom_settings,
            settings_namespace=settings_namespace,
            include_locales=include_locales,
        )
        container = self.fetch_translations(
            container,
            translations_repository=translations_repo,
            settings_namespace=settings_namespace,
            translations_branch=translations_branch,
            strict=strict_translations,
        )
        container = self.build_static_assets(
            container,
            deployment_name=deployment_name,
            settings_namespace=settings_namespace,
        )
        # Phase 2: inject aqueduct runtime settings (changes frequently during
        # dev; isolated here so the heavy build_static_assets layer stays cached)
        container = self.inject_aqueduct_settings(
            container,
            custom_settings=custom_settings,
            settings_namespace=settings_namespace,
        )
        container = self.docker_image(
            container,
            deployment_name=deployment_name,
            release_name=release_name,
            extra_ssh_hosts=extra_ssh_hosts,
        )

        # Phase 3: prove the image we just built can actually start. Everything
        # up to here can succeed while producing an image whose LMS refuses to
        # boot — a plugin whose app module raises on import, or a settings
        # regression, surfaces only at `django.setup()`. Running the system
        # checks here makes that a build failure instead of a deploy failure.
        # Opt-out (`--verify-boot=false`) exists for iterating on the earlier
        # stages, not for shipping.
        if verify_boot:
            container = self._verify_boot(container)

        return container

    def _verify_boot(self, container: dagger.Container) -> dagger.Container:
        """Run Django's system checks for both services against a built image.

        ``manage.py <svc> check --settings=aqueduct`` performs a full
        ``django.setup()``: it resolves the settings module and then imports
        every app in ``INSTALLED_APPS``.  That import is what the earlier build
        stages never exercise — asset compilation runs under ``assets.py``, not
        the production settings — so this is the first point where a plugin that
        installs cleanly but raises on import, or a settings regression that
        only bites at app-registry load, becomes visible.

        Runs against the finished image so it verifies what ships, and stays
        inside the Dagger chain so a failure fails the build.  Note this needs
        no database: system checks are static, which is what makes them usable
        as an unconditional build gate.

        ``--settings=aqueduct`` names the entry module ``inject_aqueduct_settings``
        writes (``<svc>/envs/aqueduct.py``), which is fixed regardless of the
        deployment's ``settings_namespace``.

        Args:
            container: The finished image from :meth:`docker_image`.

        Returns:
            The same container with the check executions appended.  The image's
            own workdir/entrypoint are left untouched — the ``cd`` happens
            inside the check shell, not as container metadata.
        """
        for svc in ("lms", "cms"):
            container = container.with_exec(
                [
                    "sh",
                    "-c",
                    f"echo 'boot check: {svc}' && cd /openedx/edx-platform && "
                    f"SERVICE_VARIANT={svc} python manage.py {svc} check "
                    "--settings=aqueduct",
                ]
            )
        return container

    @function
    async def check_deployment(
        self,
        deployment_name: str,
        release_name: str,
        build_manifest: dagger.File | None = None,
        pip_package_lists: dagger.Directory | None = None,
        pip_package_overrides: dagger.Directory | None = None,
        platform_repo: str | None = None,
        platform_branch: str | None = None,
        python_version: str | None = None,
        node_version: str | None = None,
        packages_to_remove: list[str] | None = None,
        extra_npm_packages: list[str] | None = None,
    ) -> str:
        """Verify a build cell's pinned requirements against edx-platform.

        This is the execution engine for the plugin-compat matrix.  For the
        given ``(release_name, deployment_name)`` cell it installs the exact
        same dependency set a production build would (via :meth:`install_deps`,
        not a parallel resolver that could drift), then runs three checks that
        catch a plugin bump which resolves but is nonetheless broken against
        this edx-platform branch:

        1. ``uv pip check`` — the resolved environment has no conflicting or
           missing transitive dependencies.
        2. Import every plugin distribution in the cell (``ol-*``, ``openedx-*``,
           ``edx-*``, ``*-xblock``).  The distribution → import-module mapping is
           read at runtime from each installed distribution's metadata, so no
           hand-maintained mapping can drift; a distribution that failed to
           install is a hard failure, one that installed but exposes no
           importable top-level module is reported and skipped.

        Any failing check exits non-zero and fails the calling ``dagger call``.

        Scope (by design): this is the fast, Python-only tier of the
        verification pyramid — it installs Python deps only
        (``install_node=False``) and does not compile frontend assets. Plugin
        JS/CSS build breakage is a webpack/sass concern that only surfaces in a
        full platform asset build, which is exercised by the scheduled canary
        running :meth:`build_platform` (whose ``build_static_assets`` step
        compiles plugin-contributed webpack config). Keeping this tier
        Python-only is what lets it gate every PR cheaply.

        Args:
            deployment_name: Deployment name.
            release_name: edx-platform release / branch name (e.g. master).
            build_manifest: Optional ``build_manifest.yaml``.  When given, the
                cell matching ``(release_name, deployment_name)`` supplies the
                requirements and every build parameter the caller did not pass.
            pip_package_lists: Requirements directory.  Required unless
                ``build_manifest`` is given.
            pip_package_overrides: Overrides directory.  Required unless
                ``build_manifest`` is given.
            platform_repo: Git repository URL for edx-platform.
            platform_branch: Git branch to check out.
            python_version: Python version. Defaults to 3.12 for master, else 3.11.
            node_version: Node.js version (default: 20.18.0).
            packages_to_remove: Python packages to uninstall after base install.
            extra_npm_packages: Additional npm packages to install.

        Returns:
            The combined stdout of the checks (only reached when all pass).
        """
        resolved = await self._resolve_cell(
            caller="check_deployment",
            deployment_name=deployment_name,
            release_name=release_name,
            build_manifest=build_manifest,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            platform_repo=platform_repo,
            platform_branch=platform_branch,
            python_version=python_version,
            node_version=node_version,
            packages_to_remove=packages_to_remove,
            extra_npm_packages=extra_npm_packages,
        )
        pip_package_lists = resolved.pip_package_lists
        pip_package_overrides = resolved.pip_package_overrides

        # Same install path a production build uses, so this gate verifies the
        # real resolution — not a shell reimplementation that can diverge.
        container: dagger.Container = self.apt_base(
            python_version=resolved.python_version
        )
        container = self.get_code(
            container,
            edx_platform_git_repo=resolved.platform_repo,
            edx_platform_git_branch=resolved.platform_branch,
        )
        container = self.install_deps(
            container,
            deployment_name=deployment_name,
            release_name=release_name,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            node_version=resolved.node_version,
            packages_to_remove=resolved.packages_to_remove,
            extra_npm_packages=resolved.extra_npm_packages,
            # Plugin import compat needs only the Python env; Node/webpack are
            # irrelevant here and installing them (nodeenv download) is a
            # needless failure surface for a check that never builds assets.
            install_node=False,
        )

        # Derive the plugin distributions to smoke-import from the SAME
        # requirement files install_deps installs from — the effective
        # directories resolved above (materialized from the manifest cell, or
        # the caller's explicit --pip-package-lists when those were passed and
        # win over the manifest).  Reading the cell directly would diverge from
        # what was installed whenever both a manifest and explicit dirs are
        # supplied, reporting manifest-only plugins as missing and skipping
        # newly installed ones.
        list_txt = await pip_package_lists.file(
            f"{release_name}/{deployment_name}.txt"
        ).contents()
        override_txt = await pip_package_overrides.file(
            f"{release_name}/{deployment_name}.txt"
        ).contents()
        plugin_dists = plugin_distributions(
            [*list_txt.splitlines(), *override_txt.splitlines()]
        )

        import_script = _plugin_import_script(plugin_dists)
        return await (
            container.with_exec(["uv", "pip", "check"])
            .with_exec(["python", "-c", import_script])
            .stdout()
        )

    @function
    async def test(  # noqa: PLR0913
        self,
        deployment_name: str,
        release_name: str,
        custom_settings: dagger.Directory,
        build_manifest: dagger.File | None = None,
        pip_package_lists: dagger.Directory | None = None,
        pip_package_overrides: dagger.Directory | None = None,
        platform_repo: str | None = None,
        platform_branch: str | None = None,
        python_version: str | None = None,
        node_version: str | None = None,
        packages_to_remove: list[str] | None = None,
        extra_npm_packages: list[str] | None = None,
        service: str = "lms",
        test_paths: list[str] | None = None,
        markers: str | None = None,
        full: bool = False,  # noqa: FBT001, FBT002
        include_plugins: bool = True,  # noqa: FBT001, FBT002
        install_test_extras: bool = True,  # noqa: FBT001, FBT002
        settings_module: str | None = None,
        install_node: bool = False,  # noqa: FBT001, FBT002
        mongo_image: str = "mongo:7",
        config_sources: dagger.Directory | None = None,
    ) -> str:
        """Run the edx-platform test suite for a build cell inside its image.

        This is the execution engine for the verification pyramid's deep tier:
        it installs the *same* dependency set a production build would (via
        :meth:`install_deps`, not a parallel resolver), installs edx-platform's
        own test requirements, and runs pytest against the deployment's
        installed plugin set — so a regression particular to a
        ``(deployment × release × plugin set)`` surfaces here rather than in
        production.

        Settings: the run uses ``{service}.envs.lehrer_test``, generated by
        :func:`_derive_test_settings`.  It starts from ``{service}.envs.test``
        (authoritative for the test harness — sqlite DBs, dummy cache, mock
        search engine).  The deployment's plugins register automatically via the
        Open edX plugin framework once installed, so ``INSTALLED_APPS`` already
        reflects the deployment's plugin set — that is the primary compatibility
        signal.  The deployment's ``FEATURES`` are overlaid *only* when
        ``--config-sources`` is supplied (see below); otherwise the generated
        model's ``FEATURES`` default is ``None`` and the run keeps the upstream
        test flags.  Pass ``--settings-module`` to override the module entirely.

        Backing services: edx-platform's stock test settings need only MongoDB
        (the modulestore) — databases are sqlite, the cache is a dummy backend,
        and search is the in-process mock engine — so only a Mongo service is
        provisioned and wired via ``EDXAPP_TEST_MONGO_HOST``.

        Test selection: the full suite takes hours, so this defaults to a
        curated smoke subset (:data:`_SMOKE_PATHS`).  Pass ``--test-paths`` to
        target specific apps/paths/node-ids (e.g. a plugin's integration tests),
        ``--markers`` for a ``-m`` expression, or ``--full`` for the whole
        service tree (canary tier).

        Plugins: with ``--include-plugins`` (default) the *same* pytest run also
        executes whatever tests the installed plugins ship — appended to the
        edx-platform targets via ``--pyargs`` (see
        :func:`lehrer.core.plugin_tests.combined_pytest_script`), so one run
        covers edx-platform **and** the plugins.  With ``--install-test-extras``
        (default) each maintained ``ol-*`` plugin is re-requested at its pinned
        version with a ``[tests]`` extra so its suite and test-only deps are
        present (a safe no-op until the plugin defines the extra); any package
        the cell removed via ``packages_to_remove`` is excluded so the run
        matches the production resolution.  A plugin that ships no tests simply
        collects nothing (never a failure), so this stays green today and starts
        exercising real plugin suites the moment one is published; pass
        ``--no-include-plugins`` for the edx-platform suite alone.

        Args:
            deployment_name: Deployment name.
            release_name: edx-platform release / branch name (e.g. master).
            custom_settings: Operator settings directory — the same one passed
                to ``build-platform``.  Its ``{service}/models/aqueduct.py`` is
                injected so the derived test settings can import it.
            build_manifest: Optional ``build_manifest.yaml``.  When given, the
                cell matching ``(release_name, deployment_name)`` supplies the
                requirements and every build parameter the caller did not pass.
            pip_package_lists: Requirements directory.  Required unless
                ``build_manifest`` is given.
            pip_package_overrides: Overrides directory.  Required unless
                ``build_manifest`` is given.
            platform_repo: Git repository URL for edx-platform.
            platform_branch: Git branch to check out.
            python_version: Python version. Defaults to 3.12 for master, else 3.11.
            node_version: Node.js version (default: 20.18.0).
            packages_to_remove: Python packages to uninstall after base install.
            extra_npm_packages: Additional npm packages to install.
            service: ``"lms"`` or ``"cms"`` — which service's suite to run.
            test_paths: pytest target paths/node-ids.  Defaults to the curated
                smoke subset for ``service`` (or the full tree with ``--full``).
            markers: Optional pytest ``-m`` marker expression.
            full: Run the whole service test tree instead of the smoke subset.
            include_plugins: Also run the installed plugins' own test suites in
                the same pytest run (default True). ``--no-include-plugins``
                runs only the edx-platform targets.
            install_test_extras: When including plugins, re-request each
                maintained ``ol-*`` plugin at its pinned version with a
                ``[tests]`` extra so its suite + test deps install (default
                True; a no-op for plugins without the extra).
            settings_module: Override the Django settings module pytest loads
                (default: the derived ``{service}.envs.lehrer_test``).
            install_node: Install Node/webpack too (default False — the default
                smoke suites are Python-only; enable for tests that need built
                frontend assets).
            mongo_image: MongoDB image for the modulestore service container.
            config_sources: Optional directory of the cell's rendered
                ``OL_SETTINGS_DIR`` YAML config-sources (the same complex-type
                values K8s ConfigMaps supply at runtime — ``FEATURES``, etc.).
                When given, it is mounted at ``/openedx/config-sources`` before
                the derived settings import ``AqueductSettings``, so the run
                exercises the deployment's *actual* feature flags rather than
                the upstream test defaults.  Omitted in a bare lehrer-repo CI
                run (those values live in ol-infrastructure, not here), where
                the plugin set alone is the compatibility signal.

        Returns:
            The pytest stdout, ending with the per-target summary table (only
            reached when the suite passes; a failing suite exits non-zero and
            fails the calling ``dagger call``).  Use ``test-report`` when you
            need the report as a retrievable artifact, pass or fail.
        """
        prepared = await self._prepare_test_run(
            caller="test",
            deployment_name=deployment_name,
            release_name=release_name,
            custom_settings=custom_settings,
            build_manifest=build_manifest,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            platform_repo=platform_repo,
            platform_branch=platform_branch,
            python_version=python_version,
            node_version=node_version,
            packages_to_remove=packages_to_remove,
            extra_npm_packages=extra_npm_packages,
            service=service,
            test_paths=test_paths,
            markers=markers,
            full=full,
            include_plugins=include_plugins,
            install_test_extras=install_test_extras,
            settings_module=settings_module,
            install_node=install_node,
            mongo_image=mongo_image,
            config_sources=config_sources,
        )
        # No `expect=` override: a non-zero pytest run must fail the call. That
        # exit-code-as-gate ergonomic is the whole difference between this and
        # `test_report`, which swallows the code to keep the artifact reachable.
        return await prepared.container.with_exec(prepared.args).stdout()

    @function
    async def test_report(  # noqa: PLR0913
        self,
        deployment_name: str,
        release_name: str,
        custom_settings: dagger.Directory,
        build_manifest: dagger.File | None = None,
        pip_package_lists: dagger.Directory | None = None,
        pip_package_overrides: dagger.Directory | None = None,
        platform_repo: str | None = None,
        platform_branch: str | None = None,
        python_version: str | None = None,
        node_version: str | None = None,
        packages_to_remove: list[str] | None = None,
        extra_npm_packages: list[str] | None = None,
        service: str = "lms",
        test_paths: list[str] | None = None,
        markers: str | None = None,
        full: bool = False,  # noqa: FBT001, FBT002
        include_plugins: bool = True,  # noqa: FBT001, FBT002
        install_test_extras: bool = True,  # noqa: FBT001, FBT002
        settings_module: str | None = None,
        install_node: bool = False,  # noqa: FBT001, FBT002
        mongo_image: str = "mongo:7",
        config_sources: dagger.Directory | None = None,
    ) -> dagger.Directory:
        """Run :meth:`test` and return its report directory instead of stdout.

        Identical run, different contract.  :meth:`test` is the *gate*: it
        returns stdout and a failing suite fails the ``dagger call``, which is
        what a CI step wants.  This returns the run's report **directory**, so
        the artifact is retrievable — and it is retrievable precisely in the
        case that matters, a failing suite, which is why the pytest exec here
        runs with ``expect=ANY``.  A caller that wants both should run the gate
        and export the report as separate steps.

        The directory contains:

        * ``report.xml`` — pytest's JUnit XML for the whole run.
        * ``summary.json`` — per-target counts (edx-platform and each plugin
          package), plus ``contributing_plugins``/``silent_plugins``.  This is
          how you tell "the plugin's suite passed" from "the plugin shipped no
          suite", which the exit code alone cannot express.
        * ``summary.md`` — the same, rendered for a CI step summary.

        Export it with ``dagger call platform test-report ... export --path
        ./reports``.

        Args:
            deployment_name: See :meth:`test`.
            release_name: See :meth:`test`.
            custom_settings: See :meth:`test`.
            build_manifest: See :meth:`test`.
            pip_package_lists: See :meth:`test`.
            pip_package_overrides: See :meth:`test`.
            platform_repo: See :meth:`test`.
            platform_branch: See :meth:`test`.
            python_version: See :meth:`test`.
            node_version: See :meth:`test`.
            packages_to_remove: See :meth:`test`.
            extra_npm_packages: See :meth:`test`.
            service: See :meth:`test`.
            test_paths: See :meth:`test`.
            markers: See :meth:`test`.
            full: See :meth:`test`.
            include_plugins: See :meth:`test`.
            install_test_extras: See :meth:`test`.
            settings_module: See :meth:`test`.
            install_node: See :meth:`test`.
            mongo_image: See :meth:`test`.
            config_sources: See :meth:`test`.

        Returns:
            The run's report directory, whether or not the suite passed.
        """
        prepared = await self._prepare_test_run(
            caller="test-report",
            deployment_name=deployment_name,
            release_name=release_name,
            custom_settings=custom_settings,
            build_manifest=build_manifest,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            platform_repo=platform_repo,
            platform_branch=platform_branch,
            python_version=python_version,
            node_version=node_version,
            packages_to_remove=packages_to_remove,
            extra_npm_packages=extra_npm_packages,
            service=service,
            test_paths=test_paths,
            markers=markers,
            full=full,
            include_plugins=include_plugins,
            install_test_extras=install_test_extras,
            settings_module=settings_module,
            install_node=install_node,
            mongo_image=mongo_image,
            config_sources=config_sources,
        )
        # ReturnType.ANY: a failing suite must still yield the directory — a
        # report you can only retrieve when everything passed is useless.
        return prepared.container.with_exec(
            prepared.args, expect=dagger.ReturnType.ANY
        ).directory(REPORTS_DIR)

    async def _prepare_test_run(  # noqa: PLR0913
        self,
        *,
        caller: str,
        deployment_name: str,
        release_name: str,
        custom_settings: dagger.Directory,
        build_manifest: dagger.File | None,
        pip_package_lists: dagger.Directory | None,
        pip_package_overrides: dagger.Directory | None,
        platform_repo: str | None,
        platform_branch: str | None,
        python_version: str | None,
        node_version: str | None,
        packages_to_remove: list[str] | None,
        extra_npm_packages: list[str] | None,
        service: str,
        test_paths: list[str] | None,
        markers: str | None,
        full: bool,
        include_plugins: bool,
        install_test_extras: bool,
        settings_module: str | None,
        install_node: bool,
        mongo_image: str,
        config_sources: dagger.Directory | None,
    ) -> _PreparedTestRun:
        """Build the container and pytest command for a test run.

        Shared by :meth:`test` and :meth:`test_report` so the two differ only in
        what they do with the result — a divergence here would mean the report
        describes a different run than the gate executed.  See :meth:`test` for
        what every argument means; ``caller`` names the Dagger function in the
        "requires a manifest or both requirement directories" error.

        Returns:
            The prepared container plus the exec args, unexecuted.

        Raises:
            ValueError: ``service`` is not a service with a known test suite.
        """
        if service not in _SMOKE_PATHS:
            msg = f"service must be one of {sorted(_SMOKE_PATHS)}, got {service!r}"
            raise ValueError(msg)

        # The same resolution the build and the other verification entry points
        # use, so the suite runs against the cell a build would produce.
        resolved = await self._resolve_cell(
            caller=caller,
            deployment_name=deployment_name,
            release_name=release_name,
            build_manifest=build_manifest,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            platform_repo=platform_repo,
            platform_branch=platform_branch,
            python_version=python_version,
            node_version=node_version,
            packages_to_remove=packages_to_remove,
            extra_npm_packages=extra_npm_packages,
        )
        pip_package_lists = resolved.pip_package_lists
        pip_package_overrides = resolved.pip_package_overrides
        packages_to_remove = resolved.packages_to_remove

        # Same install path a production build uses, so the suite runs against
        # the real resolution — not a shell reimplementation that can diverge.
        container: dagger.Container = self.apt_base(
            python_version=resolved.python_version
        )
        container = self.get_code(
            container,
            edx_platform_git_repo=resolved.platform_repo,
            edx_platform_git_branch=resolved.platform_branch,
        )
        container = self.install_deps(
            container,
            deployment_name=deployment_name,
            release_name=release_name,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            node_version=resolved.node_version,
            packages_to_remove=packages_to_remove,
            extra_npm_packages=resolved.extra_npm_packages,
            install_node=install_node,
        )

        # Editable install (so lms/cms and their console entry points resolve)
        # plus edx-platform's own test requirements (pytest, pytest-django,
        # factory_boy, ...).
        container = (
            container.with_workdir("/openedx/edx-platform")
            .with_exec(["uv", "pip", "install", "-e", "."])
            .with_exec(["uv", "pip", "install", "-r", "requirements/edx/testing.txt"])
        )

        # When folding the plugins' own suites into this run, derive the plugin
        # distributions from the SAME requirement files install_deps installed
        # from, and add each maintained plugin's `[tests]` extra at its pinned
        # version (a safe no-op until the plugin defines it) so its shipped
        # tests + test deps are present.
        plugin_dists: list[str] = []
        if include_plugins:
            list_txt = await pip_package_lists.file(
                f"{release_name}/{deployment_name}.txt"
            ).contents()
            override_txt = await pip_package_overrides.file(
                f"{release_name}/{deployment_name}.txt"
            ).contents()
            requirement_lines = [*list_txt.splitlines(), *override_txt.splitlines()]
            plugin_dists = plugin_distributions(requirement_lines)
            extra_specs = (
                maintained_test_extra_specs(requirement_lines)
                if install_test_extras
                else []
            )
            # install_deps uninstalls packages_to_remove, so a removed ol-*
            # plugin must not be reinstalled by its [tests] extra nor handed to
            # pytest as a target — that would make the test env diverge from the
            # production cell. Exclude the (normalized) removals from both.
            removals = {normalize_dist(pkg) for pkg in packages_to_remove}
            if removals:
                plugin_dists = [d for d in plugin_dists if d not in removals]
                extra_specs = [
                    spec
                    for spec in extra_specs
                    if spec.split("[", 1)[0] not in removals
                ]
            if extra_specs:
                container = container.with_exec(["uv", "pip", "install", *extra_specs])

        # Inject the deployment's aqueduct model layer + the derived test
        # settings module.  Only the model layer is needed here (not the full
        # runtime aqueduct.py entry point) — the derived settings import
        # AqueductSettings directly to lift its FEATURES.  base.py comes from
        # lehrer core, exactly as inject_aqueduct_settings wires it for a build.
        module_source = dag.current_module().source()
        lehrer_base = module_source.file("src/lehrer/settings/base.py")
        container = (
            container.with_exec(["mkdir", "-p", f"./{service}/envs/models"])
            .with_file(f"./{service}/envs/models/base.py", lehrer_base)
            .with_new_file(f"./{service}/envs/models/__init__.py", contents="")
            .with_file(
                f"./{service}/envs/models/aqueduct.py",
                custom_settings.file(f"{service}/models/aqueduct.py"),
            )
            .with_new_file(
                f"./{service}/envs/lehrer_test.py",
                contents=_derive_test_settings(service),
            )
        )

        # Mount the cell's rendered config-sources at the path base.py reads
        # (OL_SETTINGS_DIR, default /openedx/config-sources) so the FEATURES
        # overlay lifts the deployment's real flag values, not the generated
        # None default.  Without it the run keeps the upstream test flags.
        if config_sources is not None:
            container = container.with_directory(
                "/openedx/config-sources", config_sources
            )

        # The report summarizer runs next to pytest, so ship the very module the
        # host-side unit tests cover rather than a second copy embedded in the
        # driver string — one implementation, tested once.
        container = container.with_file(
            f"{REPORT_TOOL_DIR}/lehrer_test_report.py",
            module_source.file("src/lehrer/core/test_report.py"),
        )

        # MongoDB is the one backing service the stock test settings require.
        mongo = (
            dag.container()
            .from_(mongo_image)
            .with_exposed_port(27017)
            .as_service(use_entrypoint=True)
        )

        ds = settings_module or f"{service}.envs.lehrer_test"
        # `is not None`, not truthiness: an explicitly-passed empty list is an
        # intentional override (discover from the repo root), distinct from the
        # unset default that falls back to the curated smoke/full paths.
        paths = test_paths if test_paths is not None else _test_paths(service, full)

        base = (
            container.with_service_binding("mongo", mongo)
            .with_env_variable("EDXAPP_TEST_MONGO_HOST", "mongo")
            .with_env_variable("EDXAPP_TEST_MONGO_PORT", "27017")
            .with_env_variable("NO_PREREQ_INSTALL", "1")
        )

        # One driver for both modes — with `--no-include-plugins`, plugin_dists
        # is empty and the script degrades to a plain edx-platform run. Sharing
        # it is what makes the JUnit report and its summary unconditional
        # instead of a privilege of the plugin-inclusive path.
        #
        # `python -c` (not a script file) so sys.path[0] stays the empty string:
        # pytest and edx-platform's conftests resolve imports relative to the
        # /openedx/edx-platform workdir, and running a file would put the
        # driver's own directory there instead.
        #
        # The script passes --no-migrations (pytest-django): create the schema
        # straight from the models instead of running every historical
        # migration — the default for edx-platform's own runs and the
        # difference between minutes and tens of minutes for a smoke subset.
        script = combined_pytest_script(paths, plugin_dists, ds, markers)
        return _PreparedTestRun(container=base, args=["python", "-c", script])

    @function
    async def publish_platform(
        self,
        container: dagger.Container,
        registry: str,
        repository: str,
        tag: str = "latest",
        username: str | None = None,
        password: dagger.Secret | None = None,
    ) -> str:
        """Publish the platform image to a container registry

        Args:
            container: Built container to publish
            registry: Container registry (e.g., ghcr.io, docker.io)
            repository: Repository name (e.g., myorg/openedx-platform)
            tag: Image tag
            username: Registry username (optional)
            password: Registry password/token (optional)

        Returns:
            Published image reference
        """
        image_ref = f"{registry}/{repository}:{tag}"

        if username and password:
            container = container.with_registry_auth(registry, username, password)

        return await container.publish(image_ref)

    @function
    async def regenerate_aqueduct_settings(
        self,
        deployment_name: str,
        release_name: str = "master",
        build_manifest: dagger.File | None = None,
        pip_package_lists: dagger.Directory | None = None,
        pip_package_overrides: dagger.Directory | None = None,
        platform_repo: str | None = None,
        platform_branch: str | None = None,
        python_version: str | None = None,
        packages_to_remove: list[str] | None = None,
        aqueduct_source: dagger.Directory | None = None,
    ) -> dagger.Directory:
        """Regenerate the AqueductSettings pydantic models for LMS and CMS.

        Installs the Python dependencies (no Node/webpack), then runs
        django-aqueduct's ``generate_aqueduct_settings`` management command
        (codegen v2), which discovers settings by *static AST analysis* of
        ``<service>.envs.common`` — the module is never imported, so there are
        no shims, no ``derive_settings``, no plugin booting, and no regex
        post-processing of the rendered model.  Policy (``extra="allow"``,
        ``class_name``, ``enrich_url_types=false``) comes from an injected
        ``[tool.aqueduct]`` block; ``--modules``/``--output`` are per service.

        Because static discovery reads only common.py's *source*, the generated
        ``INSTALLED_APPS`` (and the other settings openedx's ``add_plugins()``
        augments at runtime) is a *plugin-incomplete* snapshot.  That is by
        design: at runtime ``configure_django_settings(base="…envs.common")``
        defers those un-overridden settings to the live, plugin-complete base
        (django-aqueduct >= 0.10.0 overlay semantics).  The boot self-test below
        exercises that overlay path and asserts no base/plugin app is dropped.

        Returns a directory containing:
          lms/models/aqueduct.py  — AqueductSettings(BaseSettings)
          cms/models/aqueduct.py  — AqueductSettings(BaseSettings)

        The generated model is pure codegen output (subclasses ``BaseSettings``);
        ``ProductionSettingsMixin`` is composed by each service's entry module
        (``class <Svc>ProductionSettings(ProductionSettingsMixin, AqueductSettings)``),
        never by the generated file.

        Usage::

            dagger call platform regenerate-aqueduct-settings \\
              --deployment-name my-deployment \\
              --pip-package-lists ./pip_package_lists \\
              --pip-package-overrides ./pip_package_overrides \\
              export --path ./generated

            # Then update the committed models:
            cp generated/lms/models/aqueduct.py <deploy>/settings/lms/models/aqueduct.py
            cp generated/cms/models/aqueduct.py <deploy>/settings/cms/models/aqueduct.py

        Args:
            deployment_name: Deployment name.
            release_name: edx-platform release / branch name. Default: master.
            build_manifest: Optional ``build_manifest.yaml`` (see
                ``lehrer.core.build_manifest``). When given, the cell matching
                ``(release_name, deployment_name)`` supplies
                ``pip_package_lists``/``pip_package_overrides`` (materialized
                on the fly) and ``platform_repo``/``platform_branch``/
                ``python_version``/``packages_to_remove`` for any of those the
                caller did not pass explicitly.
            pip_package_lists: Directory containing pip requirements files.
                Required unless ``build_manifest`` is given.
            pip_package_overrides: Directory containing pip override
                requirements. Required unless ``build_manifest`` is given.
            platform_repo: Git repository URL for edx-platform.
            platform_branch: Git branch to check out.
            python_version: Python version. Defaults to 3.12 for master.
            packages_to_remove: Python packages to uninstall after base install
                (default: empty list).
            aqueduct_source: Optional local django-aqueduct checkout to install
                editable instead of the PyPI-pinned version from the deployment
                requirements.  Use this to regenerate with unreleased generator
                fixes.  Installed before the deployment requirements so its
                version satisfies the pinned ``django-aqueduct==`` constraint.
        """
        resolved = await self._resolve_cell(
            caller="regenerate_aqueduct_settings",
            deployment_name=deployment_name,
            release_name=release_name,
            build_manifest=build_manifest,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            platform_repo=platform_repo,
            platform_branch=platform_branch,
            python_version=python_version,
            packages_to_remove=packages_to_remove,
        )
        container = self._python_only_env(
            resolved, deployment_name, release_name, aqueduct_source
        )

        # ── codegen v2 generation setup ───────────────────────────────────────
        # django-aqueduct >= 0.7.0 discovers settings by *static AST analysis* of
        # the source module — it never imports common.py, so no shims, no
        # derive_settings, no plugin booting, and no regex post-processing of the
        # rendered model are needed.  The management command needs Django set up
        # only enough to be discovered, so we hand it a throwaway settings module
        # whose sole INSTALLED_APPS entry is django_aqueduct itself.
        container = _aqueduct_gen_setup(container)

        # ── Generate the models (static AST, one management command per service) ─
        for svc in ("lms", "cms"):
            container = container.with_exec(
                [
                    "sh",
                    "-c",
                    "DJANGO_SETTINGS_MODULE=lehrer_gen_settings "
                    "python -m django generate_aqueduct_settings "
                    f"--modules {svc}.envs.common "
                    f"--output {svc}/envs/models/aqueduct.py --reset",
                ]
            )

        # ── ruff-format the generated models ──────────────────────────────────
        # django-aqueduct's renderer emits verbatim EXPR-default source segments
        # (e.g. multi-line dicts/tuple concatenations copied straight from
        # common.py), which keep the platform's own single-quote/indentation
        # style — so the raw output is not `ruff format`-stable for a settings
        # module as complex as edx-platform's.  Format here (pinned to lehrer's
        # ruff version) so the committed model passes CI's `ruff format --check`
        # and regeneration is idempotent.  Managed-region markers are comments
        # and survive formatting.  (Renderer-side wrapping is tracked upstream in
        # tk-codegen-v2-renderer-residual-line-wrap-gaps.)
        container = _ruff_format(
            container, ["lms/envs/models/aqueduct.py", "cms/envs/models/aqueduct.py"]
        )

        # ── Boot self-test (the real runtime overlay path) ────────────────────
        # Inject ProductionSettingsMixin (models/base.py) and a *synthetic*
        # minimal entry per service, then import the entry — which runs
        # configure_django_settings(base="<svc>.envs.common").  We compose the
        # same class hierarchy the real deployment entries use
        # (<Svc>ProductionSettings(ProductionSettingsMixin, AqueductSettings)) but
        # skip operator-specific validators/post_configure: this test targets the
        # framework overlay, which is operator-independent, so it stays valid for
        # any deployment cell (deployment_name here names a requirements cell, not
        # an operator; the operator's real entry modules live under its own
        # settings tree and are exercised end-to-end by the plugin-compat build).
        #
        # The generated AqueductSettings carries only the plugin-INCOMPLETE static
        # snapshot of INSTALLED_APPS; the overlay must defer it to the live,
        # plugin-complete common.py value (common.py runs add_plugins on import).
        # The self-test asserts exactly that: the final INSTALLED_APPS is a
        # superset of the live base, i.e. no plugin/base app was dropped.
        lehrer_base = dag.current_module().source().file("src/lehrer/settings/base.py")
        container = container.with_file(
            "./lms/envs/models/base.py", lehrer_base
        ).with_file("./cms/envs/models/base.py", lehrer_base)
        for svc in ("lms", "cms"):
            entry = (
                "from django_aqueduct import configure_django_settings\n"
                "from .models.aqueduct import AqueductSettings\n"
                "from .models.base import ProductionSettingsMixin\n\n\n"
                "class _SelfTestSettings(ProductionSettingsMixin, AqueductSettings):\n"
                "    pass\n\n\n"
                f'configure_django_settings(_SelfTestSettings, base="{svc}.envs.common")\n'
            )
            container = container.with_new_file(
                f"./{svc}/envs/models/__init__.py", contents=""
            ).with_new_file(f"./{svc}/envs/aqueduct.py", contents=entry)
        self_test = _boot_self_test_script()
        container = container.with_exec(
            [
                "sh",
                "-c",
                f"DJANGO_SETTINGS_MODULE=lehrer_gen_settings python -c {shlex.quote(self_test)}",
            ]
        )

        # ── Return the two generated model files ──────────────────────────────
        return (
            dag.directory()
            .with_file(
                "lms/models/aqueduct.py",
                container.file("lms/envs/models/aqueduct.py"),
            )
            .with_file(
                "cms/models/aqueduct.py",
                container.file("cms/envs/models/aqueduct.py"),
            )
        )

    @function
    async def verify_settings(  # noqa: PLR0913
        self,
        deployment_name: str,
        release_name: str,
        custom_settings: dagger.Directory,
        build_manifest: dagger.File | None = None,
        pip_package_lists: dagger.Directory | None = None,
        pip_package_overrides: dagger.Directory | None = None,
        platform_repo: str | None = None,
        platform_branch: str | None = None,
        python_version: str | None = None,
        packages_to_remove: list[str] | None = None,
        django_check: bool = True,  # noqa: FBT001, FBT002
        drift: bool = False,  # noqa: FBT001, FBT002
        aqueduct_source: dagger.Directory | None = None,
    ) -> str:
        """Verify an operator's *committed* aqueduct settings against a build cell.

        This is the settings tier of the verification pyramid, and the only gate
        that exercises the settings a deployment actually ships.  Where
        :meth:`check_deployment` proves the cell's plugins *install and import*,
        this proves the operator's committed settings tree still
        *resolves into a working Django configuration* on top of them.  It runs
        the same Python-only environment (:meth:`_python_only_env`) and the same
        injection used by a production build (:meth:`inject_aqueduct_settings`),
        so what it verifies is what gets shipped — not a parallel approximation.

        Checks, cheapest first:

        1. **Boot self-test** — import ``lms.envs.aqueduct`` and
           ``cms.envs.aqueduct`` (the operator's real entry modules, composing
           its real validators and ``post_configure`` hooks) with no
           ``OL_SETTINGS_DIR`` present, then assert the resulting
           ``INSTALLED_APPS`` is a superset of the live, plugin-complete
           ``<svc>.envs.common`` value.  Catches both a settings module that
           cannot be imported at all and the subtler overlay regression where a
           model default silently overwrites a plugin-injected list.
        2. **Django system checks** (``django_check``, default on) — run
           ``manage.py <svc> check`` under the entry module, which performs a
           full ``django.setup()``: every app in ``INSTALLED_APPS`` is imported
           and every registered system check runs.  This is what turns "the
           settings parse" into "the platform would actually start".
        3. **Model drift** (``drift``, opt-in) — regenerate the model from this
           cell's edx-platform source through the identical pipeline
           :meth:`regenerate_aqueduct_settings` uses (static AST generation then
           ``ruff format``) and diff it against the committed
           ``models/aqueduct.py``.  A non-empty diff means the committed model
           is stale relative to the pinned edx-platform, and the fix is to
           re-run regeneration and commit the result.

           Why not django-aqueduct's own ``generate_aqueduct_settings
           --check``: that compares the on-disk file's managed regions against a
           *raw* render, but lehrer's committed models are ``ruff format``-ed
           after generation (the renderer emits verbatim source segments from
           edx-platform's own style, so its output is not format-stable).  The
           raw comparison would therefore report formatting as drift on a model
           that is perfectly in sync.  Diffing after the same formatting step
           the generator applies compares like with like.

           Drift is opt-in because one committed model serves every release in a
           group, while the generated model is edx-platform-version-specific —
           so it can only be in sync with the release regeneration was run
           against — the manifest's ``settings_model_release``.  Enable it
           for that release's cells only.

        Args:
            deployment_name: Deployment name.
            release_name: edx-platform release / branch name (e.g. master).
            custom_settings: The operator's settings directory, containing
                ``lms/aqueduct.py``,
                ``lms/models/aqueduct.py`` (and the cms equivalents) plus the
                runtime helper scripts.
            build_manifest: Optional ``build_manifest.yaml``.  When given, the
                cell matching ``(release_name, deployment_name)`` supplies the
                requirements and every build parameter the caller did not pass.
            pip_package_lists: Requirements directory.  Required unless
                ``build_manifest`` is given.
            pip_package_overrides: Overrides directory.  Required unless
                ``build_manifest`` is given.
            platform_repo: Git repository URL for edx-platform.
            platform_branch: Git branch to check out.
            python_version: Python version. Defaults to 3.12 for master, else 3.11.
            packages_to_remove: Python packages to uninstall after base install.
            django_check: Run ``manage.py check`` per service (default: true).
            drift: Also regenerate the model and fail on a diff against the
                committed one (default: false — see above).
            aqueduct_source: Optional local django-aqueduct checkout to install
                editable instead of the PyPI-pinned version, for verifying
                against an unreleased framework fix.

        Returns:
            The combined stdout of the checks (only reached when all pass).
        """
        resolved = await self._resolve_cell(
            caller="verify_settings",
            deployment_name=deployment_name,
            release_name=release_name,
            build_manifest=build_manifest,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            platform_repo=platform_repo,
            platform_branch=platform_branch,
            python_version=python_version,
            packages_to_remove=packages_to_remove,
        )
        container = self._python_only_env(
            resolved, deployment_name, release_name, aqueduct_source
        )
        container = _aqueduct_gen_setup(container)

        # The operator's committed settings, placed exactly where a production
        # build places them — so a path or import assumption that only holds in
        # the build is caught here rather than at deploy time.
        container = self.inject_aqueduct_settings(container, custom_settings)

        # ── 1. Boot self-test ─────────────────────────────────────────────────
        # No OL_SETTINGS_DIR: the entry modules must resolve from field defaults
        # alone, which is what makes this runnable in CI with no secrets. A
        # setting that is genuinely required at runtime should carry a default
        # here and be supplied by the cluster's YAML/env, not make the module
        # unimportable.
        container = container.with_env_variable(
            "DJANGO_SETTINGS_MODULE", _GEN_SETTINGS_MODULE
        ).with_exec(
            [
                "sh",
                "-c",
                f"python -c {shlex.quote(_boot_self_test_script())}",
            ]
        )

        # ── 2. Django system checks ───────────────────────────────────────────
        # `manage.py <svc> check` maps --settings=aqueduct to <svc>.envs.aqueduct
        # and runs django.setup(), importing every app in INSTALLED_APPS. That
        # import is the real gate: a plugin bump whose app module raises on
        # import passes both `uv pip check` and a bare settings import, and only
        # fails here.
        if django_check:
            for svc in ("lms", "cms"):
                container = container.with_exec(
                    [
                        "sh",
                        "-c",
                        f"SERVICE_VARIANT={svc} python manage.py {svc} check "
                        "--settings=aqueduct",
                    ]
                )

        # ── 3. Model drift ────────────────────────────────────────────────────
        if drift:
            for svc in ("lms", "cms"):
                container = container.with_exec(
                    [
                        "sh",
                        "-c",
                        f"DJANGO_SETTINGS_MODULE={_GEN_SETTINGS_MODULE} "
                        "python -m django generate_aqueduct_settings "
                        f"--modules {svc}.envs.common "
                        f"--output /tmp/{svc}_aqueduct.py --reset",  # noqa: S108
                    ]
                )
            # Same formatting step regeneration applies, so the diff below
            # compares content rather than line wrapping.
            container = _ruff_format(
                container,
                ["/tmp/lms_aqueduct.py", "/tmp/cms_aqueduct.py"],  # noqa: S108
            )
            # The remediation has to be copy-pasteable from a CI log by someone
            # who did not write this function: the full command with this cell's
            # coordinates, the export step (regeneration returns a Directory —
            # without `export` nothing lands on disk), and the copy. The
            # manifest path is the one value that genuinely varies by operator,
            # so it stays a named placeholder rather than a wrong guess.
            for svc in ("lms", "cms"):
                remediation = (
                    f"DRIFT: the committed {svc}/models/aqueduct.py is stale "
                    f"against {resolved.platform_branch}. Regenerate and commit "
                    "it:\\n"
                    "  dagger call platform regenerate-aqueduct-settings \\\\\\n"
                    f"    --deployment-name {deployment_name} "
                    f"--release-name {release_name} \\\\\\n"
                    "    --build-manifest <your group's build_manifest.yaml> "
                    "\\\\\\n"
                    "    export --path ./generated\\n"
                    f"  cp generated/{svc}/models/aqueduct.py "
                    f"<your settings dir>/{svc}/models/aqueduct.py"
                )
                container = container.with_exec(
                    [
                        "sh",
                        "-c",
                        f"diff -u {svc}/envs/models/aqueduct.py "  # noqa: S108
                        f"/tmp/{svc}_aqueduct.py || {{ "
                        f"printf '%s\\n' {shlex.quote(remediation)}; exit 1; }}",
                    ]
                )

        return await container.stdout()
