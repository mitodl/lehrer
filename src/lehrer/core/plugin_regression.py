"""Select and drive the installed-plugin test suites for a build cell.

The plugin-compat matrix's fast tier (:mod:`lehrer.core.plugin_imports` +
``OpenedxPlatform.check_deployment``) proves a cell's plugins *install and
import* against the matching edx-platform.  This module answers the next
question in the verification pyramid: do the plugins' *own* test suites still
pass against the deployment's platform build and settings?

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


def plugin_regression_script(
    plugin_dists: list[str], settings_module: str, junit_path: str
) -> str:
    """Build the in-container driver that runs pytest over installed plugin packages.

    The returned program (written verbatim into the container and run with the
    image's Python) resolves each target distribution's installed top-level
    import packages at runtime — via ``importlib.metadata.packages_distributions``,
    the same drift-proof resolution the import check uses — then runs pytest over
    them with ``--pyargs`` under the deployment's derived test settings, writing
    one aggregated JUnit report.

    Result semantics, so the run fails only on a *real* regression:

    * a target that did not install at all is a hard failure (install drift);
    * a target that installed but exposes no importable module is reported and
      skipped (namespace/data-only distribution);
    * pytest's "no tests collected" exit (5) is treated as success — the
      expected state until a plugin ships its suite via the ``[tests]`` extra;
    * any other non-zero pytest exit (test failures, collection/import errors)
      propagates and fails the calling ``dagger call``.
    """
    return "\n".join(
        [
            "import sys",
            "import importlib.metadata as im",
            f"targets = {plugin_dists!r}",
            f"settings_module = {settings_module!r}",
            f"junit_path = {junit_path!r}",
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
            "modules, missing, no_module = [], [], []",
            "for dist in targets:",
            "    if dist not in installed:",
            "        missing.append(dist)",
            "        continue",
            "    mods = sorted(set(dist_to_modules.get(dist, [])))",
            "    if not mods:",
            "        no_module.append(dist)",
            "        continue",
            "    modules.extend(mods)",
            "modules = sorted(set(modules))",
            "for dist in missing:",
            "    print(f'MISSING: {dist} did not install')",
            "for dist in no_module:",
            "    print(f'SKIP:    {dist} installed, no importable top-level module')",
            "if missing:",
            "    sys.exit(",
            "        f'plugin regression: {len(missing)} target(s) not installed: '",
            "        f'{missing}'",
            "    )",
            "if not modules:",
            "    print('plugin regression: no installed plugin packages to scan')",
            "    sys.exit(0)",
            "print(f'plugin regression: scanning {len(modules)} package(s): {modules}')",
            "import pytest",
            "args = [",
            "    '--pyargs', *modules,",
            "    f'--ds={settings_module}',",
            "    '--no-migrations',",
            "    '-p', 'no:cacheprovider',",
            "    f'--junitxml={junit_path}',",
            "    '-ra',",
            "]",
            "code = int(pytest.main(args))",
            # 5 == NO_TESTS_COLLECTED: expected until the plugins ship their
            # suites, so it must not fail the gate.
            "if code == 5:",
            "    print(",
            "        'plugin regression: no plugin tests discovered (exit 5) — '",
            "        'expected until plugins ship their [tests] extra'",
            "    )",
            "    sys.exit(0)",
            "sys.exit(code)",
        ]
    )
