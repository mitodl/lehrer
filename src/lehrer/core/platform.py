"""Generic edx-platform build pipeline for Open edX operators.

This module contains the ``OpenedxPlatform`` Dagger object type that builds,
configures, and publishes edx-platform container images.  All MIT OL–specific
values have been removed; callers supply their own settings namespace, SSH
hosts, package overrides, and translations repository.
"""

from typing import TypeVar, cast

import dagger
import yaml
from dagger import dag, function, object_type

from lehrer.core.build_manifest import BuildManifest, Cell
from lehrer.core.plugin_imports import plugin_distributions

_T = TypeVar("_T")


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
            node_version: Node.js version (default: 20.18.0)
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

        container = (
            container.with_workdir("/openedx/edx-platform")
            .with_env_variable("NPM_REGISTRY", "https://registry.npmjs.org/")
            .with_exec(
                [
                    "sh",
                    "-c",
                    f"nodeenv /openedx/nodeenv --node={node_version} --prebuilt",
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
            # models/aqueduct.py → generated AqueductSettings(ProductionSettingsMixin)
            # aqueduct.py       → DJANGO_SETTINGS_MODULE entry point
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

        Returns:
            Container with compiled translations
        """
        import shlex

        safe_repo = shlex.quote(translations_repository)
        safe_branch = shlex.quote(translations_branch)
        atlas_options = f"--repository {safe_repo} --revision {safe_branch}"

        # Check if pull_plugin_translations command exists
        container = container.with_env_variable(
            "DJANGO_SETTINGS_MODULE", f"lms.envs.{settings_namespace}.i18n"
        ).with_workdir("/openedx/edx-platform")

        # Pull and compile LMS translations
        container = (
            container.with_exec(
                [
                    "sh",
                    "-c",
                    f"python manage.py lms pull_plugin_translations {atlas_options} || true",
                ]
            )
            .with_exec(
                ["sh", "-c", "python manage.py lms compile_plugin_translations || true"]
            )
            .with_exec(
                [
                    "sh",
                    "-c",
                    f"python manage.py lms pull_xblock_translations {atlas_options} || true",
                ]
            )
            .with_exec(
                ["sh", "-c", "python manage.py lms compile_xblock_translations || true"]
            )
            .with_exec(
                [
                    "sh",
                    "-c",
                    f"atlas pull {atlas_options} translations/edx-platform/conf/locale:conf/locale || true",
                ]
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
                ["sh", "-c", "python manage.py cms compile_xblock_translations || true"]
            )
            .with_exec(
                [
                    "sh",
                    "-c",
                    f"atlas pull {atlas_options} translations/studio-frontend/src/i18n/messages:conf/plugins-locale/studio-frontend || true",
                ]
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
        translations_repo = _resolve_field(
            translations_repo,
            cell,
            manifest,
            "translations_repo",
            "openedx/openedx-translations",
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
                "check_deployment requires either --build-manifest, or both "
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
        node_version = _resolve_field(
            node_version, cell, manifest, "node_version", "20.18.0"
        )
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
        if python_version is None:
            resolved_python_version = None
            if cell is not None and manifest is not None:
                resolved_python_version = cell.resolved("python_version", manifest)
            python_version = cast("str | None", resolved_python_version) or (
                "3.12" if release_name == "master" else "3.11"
            )

        # Same install path a production build uses, so this gate verifies the
        # real resolution — not a shell reimplementation that can diverge.
        container: dagger.Container = self.apt_base(python_version=python_version)
        container = self.get_code(
            container,
            edx_platform_git_repo=platform_repo,
            edx_platform_git_branch=platform_branch,
        )
        container = self.install_deps(
            container,
            deployment_name=deployment_name,
            release_name=release_name,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            node_version=node_version,
            packages_to_remove=packages_to_remove,
            extra_npm_packages=extra_npm_packages,
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

        Installs the Python dependencies (no Node/webpack), injects minimal
        generation shims that do ``from <service>.envs.common import *;
        derive_settings()``, then calls ``ModuleInspector`` and
        ``SettingsModelGenerator`` from django-aqueduct directly — no
        management command needed, no INSTALLED_APPS dependency.

        Because the shims only import common.py and derive settings (exactly
        as the upstream ``generate_aqueduct_settings`` workflow works), all
        settings contributed by custom plugins via ``add_plugins()`` are
        captured automatically.

        Returns a directory containing:
          lms/models/aqueduct.py  — AqueductSettings(ProductionSettingsMixin)
          cms/models/aqueduct.py  — AqueductSettings(ProductionSettingsMixin)

        The generated class already inherits ``ProductionSettingsMixin`` so
        regeneration cannot accidentally lose the mixin.

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
                "regenerate_aqueduct_settings requires either --build-manifest, "
                "or both --pip-package-lists and --pip-package-overrides"
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

        if packages_to_remove is None:
            packages_to_remove = []
            if cell is not None and manifest is not None:
                resolved_removals = cell.resolved("packages_to_remove", manifest)
                if resolved_removals is not None:
                    packages_to_remove = cast("list[str]", resolved_removals)

        if python_version is None:
            resolved_python_version = None
            if cell is not None and manifest is not None:
                resolved_python_version = cell.resolved("python_version", manifest)
            python_version = cast("str | None", resolved_python_version) or (
                "3.12" if release_name == "master" else "3.11"
            )

        # ── Base system + code ────────────────────────────────────────────────
        container: dagger.Container = self.apt_base(python_version=python_version)
        container = self.get_code(
            container,
            edx_platform_git_repo=platform_repo,
            edx_platform_git_branch=platform_branch,
        )

        # ── Python-only dependency install (skip Node/webpack) ────────────────
        container = (
            container.with_mounted_directory(
                "/root/pip_package_lists", pip_package_lists
            )
            .with_mounted_directory(
                "/root/pip_package_overrides", pip_package_overrides
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

        # Install a local django-aqueduct checkout as an editable dev override.
        # Done before the deployment requirements so its version satisfies the
        # pinned ``django-aqueduct==`` constraint and uv skips the PyPI fetch —
        # letting regeneration pick up unreleased generator fixes.
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

        # Remove any deployment-specific packages that conflict with the build
        for pkg in packages_to_remove:
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

        # ── Install edx-platform in editable mode ─────────────────────────────
        container = container.with_workdir("/openedx/edx-platform").with_exec(
            ["uv", "pip", "install", "-e", "."]
        )

        # ── Inject minimal generation shims ───────────────────────────────────
        # These shims do exactly what the upstream generate_aqueduct_settings
        # workflow recommends: import common.py (which calls add_plugins so all
        # plugin settings are included) then resolve Derived values.  We write
        # them to throw-away module names so we never conflict with anything in
        # the platform source tree.
        lms_shim = (
            "# Temporary generation shim — not committed to the platform.\n"
            "from lms.envs.common import *  # noqa: F401,F403\n"
            "from openedx.core.lib.derived import derive_settings\n"
            "derive_settings(__name__)\n"
        )
        cms_shim = (
            "# Temporary generation shim — not committed to the platform.\n"
            "from cms.envs.common import *  # noqa: F401,F403\n"
            "# LMS_ROOT_URL may be a Derived sentinel; provide a concrete default\n"
            "# so derive_settings can resolve dependents.\n"
            "if not isinstance(LMS_ROOT_URL, str):  # noqa: F821\n"
            "    LMS_ROOT_URL = 'http://localhost:18000'  # noqa: F821\n"
            "from openedx.core.lib.derived import derive_settings\n"
            "derive_settings(__name__)\n"
        )
        container = (
            container.with_new_file("./lehrer_lms_shim.py", contents=lms_shim)
            .with_new_file("./lehrer_cms_shim.py", contents=cms_shim)
            .with_exec(["mkdir", "-p", "./lms/envs/models", "./cms/envs/models"])
            # Inject ProductionSettingsMixin so generated files can import it
            # and the self-test can instantiate AqueductSettings(ProductionSettingsMixin).
            .with_file(
                "./lms/envs/models/base.py",
                dag.current_module().source().file("src/lehrer/settings/base.py"),
            )
            .with_file(
                "./cms/envs/models/base.py",
                dag.current_module().source().file("src/lehrer/settings/base.py"),
            )
            .with_new_file("./lms/envs/models/__init__.py", contents="")
            .with_new_file("./cms/envs/models/__init__.py", contents="")
        )

        # ── Generate the models ───────────────────────────────────────────────
        # Call ModuleInspector + SettingsModelGenerator directly — no
        # management command required, no django_aqueduct in INSTALLED_APPS
        # required.  The shim modules import common.py into their own globals
        # so every UPPERCASE name (including plugin settings) is discovered.
        generate_script = "\n".join(
            [
                "import sys, os, re, importlib",
                "os.chdir('/openedx/edx-platform')",
                "sys.path.insert(0, '/openedx/edx-platform')",
                "from django_aqueduct.discovery.module import ModuleInspector",
                "from django_aqueduct.codegen.generator import SettingsModelGenerator",
                "def _add_imports(code):",
                "    # Add stdlib/third-party imports the generator references but omits.",
                "    # (Optional-widening of None-default fields is handled by the",
                "    # django-aqueduct generator itself as of 0.4.0.)",
                "    # Note: pathlib is now always emitted by django-aqueduct >= 0.5.0;",
                "    # 'from path import Path' is only needed for bare Path() calls that",
                "    # are NOT preceded by 'pathlib.' (i.e. legacy path.py usage).",
                "    extra = []",
                "    if re.search(r'(?<!pathlib\\.)(?<!\\.)Path\\(', code) and 'from path import' not in code:",
                "        extra.append('from path import Path')",
                "    if 'datetime.' in code and 'import datetime' not in code:",
                "        extra.append('import datetime')",
                "    if extra:",
                "        lines = code.splitlines()",
                '        last_import = max((i for i, l in enumerate(lines) if re.match(r"^(from|import)\\s", l)), default=0)',
                "        lines = lines[:last_import+1] + extra + lines[last_import+1:]",
                "        code = '\\n'.join(lines) + '\\n'",
                "    return code",
                "def _rewrite_base_class(code):",
                "    # Replace the generator's BaseSettings inheritance with ProductionSettingsMixin.",
                "    # ProductionSettingsMixin already inherits BaseSettings and owns model_config,",
                "    # so the generated class no longer needs to redeclare them.",
                "    #",
                "    # 1. Drop the BaseSettings / SettingsConfigDict pydantic-settings import.",
                "    code = re.sub(",
                "        r'from pydantic_settings import BaseSettings, SettingsConfigDict\\n',",
                "        '',",
                "        code,",
                "    )",
                "    # 2. Remove the generated model_config (inherited from the mixin).",
                "    code = re.sub(",
                r"        r'\\n    model_config = SettingsConfigDict\\([^)]+\\)\\n',",
                "        '\\n',",
                "        code,",
                "    )",
                "    # 3. Swap the base class.",
                "    code = code.replace(",
                "        'class AqueductSettings(BaseSettings):',",
                "        'class AqueductSettings(ProductionSettingsMixin):',",
                "    )",
                "    # 4. Add the mixin import after the last pydantic import line.",
                "    lines = code.splitlines()",
                "    last_pydantic = max(",
                "        (i for i, l in enumerate(lines) if re.match(r'^from pydantic', l)),",
                "        default=0,",
                "    )",
                "    lines.insert(last_pydantic + 1, 'from .base import ProductionSettingsMixin')",
                "    return '\\n'.join(lines) + '\\n'",
                "def _fix_str_path_annotations(code):",
                "    # Fix fields where the annotation is 'str' but the default is",
                "    # pathlib.Path(...).  This arises when edx-platform settings define",
                "    # a path as str(PROJECT_ROOT / ...) at generation time but supply a",
                "    # PosixPath at runtime via the aqueduct overlay source.  Pydantic",
                "    # does not coerce PosixPath → str, so the model would fail to",
                "    # instantiate.  django-aqueduct >= 0.5.0 detects PathLike defaults",
                "    # and emits pathlib.Path annotations correctly; this step is a",
                "    # belt-and-braces guard for any field the generator still misses.",
                "    return re.sub(",
                "        r'(\\b\\w+): str = (Field\\(\\s*\\n\\s*default=pathlib\\.Path\\b)',",
                "        r'\\1: pathlib.Path = \\2',",
                "        code,",
                "    )",
                "for shim, out in [",
                "    ('lehrer_lms_shim', 'lms/envs/models/aqueduct.py'),",
                "    ('lehrer_cms_shim', 'cms/envs/models/aqueduct.py'),",
                "]:",
                "    print(f'Generating {out} from {shim} ...')",
                "    fields = ModuleInspector(shim).discover()",
                "    code = _add_imports(SettingsModelGenerator(fields).render())",
                "    code = _rewrite_base_class(code)",
                "    code = _fix_str_path_annotations(code)",
                "    open(out, 'w').write(code)",
                "    print(f'  {len(fields)} fields written to {out}')",
                "# ── Boot self-test ──────────────────────────────────────────",
                "# Fail generation (not pod boot) if a model cannot instantiate or is",
                "# missing INSTALLED_APPS.  Load via proper package import so relative",
                "# imports (from .base import ProductionSettingsMixin) resolve correctly.",
                "for pkg in ['lms.envs.models.aqueduct', 'cms.envs.models.aqueduct']:",
                "    # Force fresh import — remove any stale cached module.",
                "    sys.modules.pop(pkg, None)",
                "    _saved = dict(os.environ); os.environ.clear()",
                "    try:",
                "        _m = importlib.import_module(pkg)",
                "        inst = _m.AqueductSettings()",
                "    finally:",
                "        os.environ.clear(); os.environ.update(_saved)",
                "    apps = getattr(inst, 'INSTALLED_APPS', None)",
                "    assert apps, f'{pkg}: INSTALLED_APPS empty/missing ({apps!r})'",
                "    print(f'  self-test OK: {pkg} instantiates, {len(apps)} INSTALLED_APPS')",
            ]
        )
        container = container.with_exec(["python", "-c", generate_script])

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
