"""Fold the installed plugins' own test suites into the ``platform test`` run.

``platform test`` runs edx-platform's own suite under the deployment's derived
settings and installed plugin set. This module lets that same run *also* execute
whatever tests the installed plugins ship — one image build, one pytest
invocation, one JUnit report covering edx-platform **and** the plugins — so a
plugin bump, or a new edx-platform commit, that breaks a plugin's tests surfaces
in the same place as an upstream regression.

The strategy is pytest **discovery**, not source acquisition.  Published plugin
wheels/sdists do not ship their test suites, and the monorepo many ``ol-*``
plugins live in has no per-package tags — so fetching "the tests at the exact
installed version" is not something the ecosystem supports.  Instead we run
whatever tests are *installed in the image*: a plugin's tests become
discoverable once its distribution ships them, which a maintained plugin does
via a ``[tests]`` extra.  A plugin that ships no tests contributes nothing and
is reported, never failed — the same drift-proof philosophy as the import
check, which resolves ``dist -> module`` at runtime rather than from a
hand-maintained map.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Distributions in a namespace we maintain, and therefore can expect to expose
# a ``[tests]`` extra bundling their suite + test-only deps.  Requesting the
# extra for a distribution that does not define one is a safe no-op (uv/pip
# install the base version unchanged), so this can front-run the extras landing
# upstream without breaking the run.
_MAINTAINED_PREFIXES = ("ol-",)

# An exact ``name==version`` requirement (comment already stripped). Extras,
# ranges, markers and VCS/URL lines deliberately do not match: there is no
# single version to reproduce, and the point is to add the ``[tests]`` extra
# *without* moving the pin the cell already installed.
_PINNED = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)$")


def _normalize(name: str) -> str:
    """PEP 503 normalization: lower-case, runs of ``-_.`` collapsed to ``-``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def maintained_test_extra_specs(lines: Iterable[str]) -> list[str]:
    """Return ``<dist>[tests]==<version>`` specs for maintained, ``==``-pinned plugins.

    ``lines`` are verbatim pip-requirements lines (a cell's ``packages`` +
    ``overrides``).  For every exactly-pinned distribution in a namespace we
    maintain, emit a spec that re-requests the *same* version with the
    ``[tests]`` extra, so the plugin's shipped test suite and test-only
    dependencies are installed alongside the pinned build.  Order of first
    appearance is preserved and duplicates are dropped.

    Only ``==`` pins qualify: a range or a VCS/URL requirement has no single
    version to reproduce, and re-resolving it could move the pin the cell
    installed.  Requesting an undefined extra is harmless, so this is safe to
    run before the plugins publish their ``[tests]`` extras.
    """
    seen: dict[str, None] = {}
    specs: list[str] = []
    for raw in lines:
        line = raw.split("#", 1)[0].strip()  # drop trailing comments
        match = _PINNED.match(line)
        if match is None:
            continue
        dist = _normalize(match.group(1))
        if not dist.startswith(_MAINTAINED_PREFIXES) or dist in seen:
            continue
        seen[dist] = None
        specs.append(f"{dist}[tests]=={match.group(2)}")
    return specs


def combined_pytest_script(
    edx_paths: list[str],
    plugin_dists: list[str],
    settings_module: str,
    junit_path: str,
    markers: str | None = None,
) -> str:
    """Build the in-container driver that runs edx-platform *and* plugin tests.

    The returned program (written verbatim into the container and run with the
    image's Python from the edx-platform workdir) runs one ``pytest`` over the
    edx-platform ``edx_paths`` plus, appended via ``--pyargs``, the installed
    top-level packages of each plugin distribution — resolved at runtime from
    ``importlib.metadata.packages_distributions`` (the same drift-proof
    resolution the import check uses).  One invocation, one aggregated JUnit
    report at ``junit_path``.

    A plugin distribution that did not install, or installed without an
    importable module, is *reported and skipped* — never a hard failure, since
    the run's pass/fail is pytest's own exit code (edx-platform's suite is the
    load-bearing signal; the plugins are additive).  ``edx_paths`` are treated
    as filesystem paths and the plugin packages as import names in the same
    call: ``--pyargs`` only reinterprets args that are not existing paths.
    """
    return "\n".join(
        [
            "import sys",
            "import importlib.metadata as im",
            f"edx_paths = {edx_paths!r}",
            f"plugin_dists = {plugin_dists!r}",
            f"settings_module = {settings_module!r}",
            f"junit_path = {junit_path!r}",
            f"markers = {markers!r}",
            "import re",
            "def _norm(name):",
            "    return re.sub(r'[-_.]+', '-', name).lower()",
            # dist -> installed top-level import modules, read from metadata so
            # no hand-maintained mapping can drift and mis-skip a healthy plugin.
            "dist_to_modules = {}",
            "for mod, dists in im.packages_distributions().items():",
            "    for d in dists:",
            "        dist_to_modules.setdefault(_norm(d), []).append(mod)",
            "installed = {_norm(d.name) for d in im.distributions() if d.name}",
            "plugin_modules, missing, no_module = [], [], []",
            "for dist in plugin_dists:",
            "    if dist not in installed:",
            "        missing.append(dist)",
            "        continue",
            "    mods = sorted(set(dist_to_modules.get(dist, [])))",
            "    if not mods:",
            "        no_module.append(dist)",
            "        continue",
            "    plugin_modules.extend(mods)",
            "plugin_modules = sorted(set(plugin_modules))",
            "for dist in missing:",
            "    print(f'PLUGIN MISSING: {dist} did not install (skipped)')",
            "for dist in no_module:",
            "    print(f'PLUGIN SKIP:    {dist} has no importable top-level module')",
            "if plugin_modules:",
            "    print(f'PLUGIN TESTS:   discovering in {plugin_modules}')",
            "else:",
            "    print('PLUGIN TESTS:   no installed plugin packages to scan')",
            "import pytest",
            "args = list(edx_paths)",
            # --pyargs only reinterprets non-path args, so the edx filesystem
            # paths above and the plugin import names here coexist in one run.
            "if plugin_modules:",
            "    args += ['--pyargs', *plugin_modules]",
            "args += [",
            "    f'--ds={settings_module}',",
            "    '--no-migrations',",
            "    '-p', 'no:cacheprovider',",
            "    f'--junitxml={junit_path}',",
            "    '-ra',",
            "]",
            "if markers:",
            "    args += ['-m', markers]",
            "sys.exit(int(pytest.main(args)))",
        ]
    )
