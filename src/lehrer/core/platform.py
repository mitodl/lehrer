"""Generic edx-platform build pipeline for Open edX operators.

This module contains the ``OpenedxPlatform`` Dagger object type that builds,
configures, and publishes edx-platform container images.  All MIT OL–specific
values have been removed; callers supply their own settings namespace, SSH
hosts, package overrides, and translations repository.
"""

import dagger
from dagger import dag, function, object_type


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

        # Fix lxml/xmlsec compatibility issues
        # Use plain pip (not uv) here because the override file uses inline --no-binary flags
        # that uv does not support in requirements files.
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
                "-r",
                f"/root/pip_package_overrides/{release_name}/{deployment_name}.txt",
            ]
        )

        # Install Node.js using nodeenv
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

        The ``custom_settings`` directory must follow this layout::

            custom_settings/
            ├── lms.env.yml
            ├── cms.env.yml
            ├── models/
            │   └── base.py          ← shared ProductionSettingsMixin
            ├── lms/
            │   ├── assets.py
            │   ├── i18n.py
            │   ├── aqueduct.py
            │   └── models/
            │       └── aqueduct.py
            ├── cms/
            │   ├── assets.py
            │   ├── i18n.py
            │   ├── aqueduct.py
            │   └── models/
            │       └── aqueduct.py
            ├── set_waffle_flags.py
            ├── process_scheduled_emails.py
            └── saml_pull.py

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

        # Copy custom settings
        container = (
            container.with_mounted_directory("/tmp/custom_settings", custom_settings)
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/lms.env.yml",
                    "/openedx/config/lms.env.yml",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/cms.env.yml",
                    "/openedx/config/cms.env.yml",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/lms/assets.py",
                    f"/openedx/edx-platform/lms/envs/{settings_namespace}/assets.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/lms/i18n.py",
                    f"/openedx/edx-platform/lms/envs/{settings_namespace}/i18n.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/cms/assets.py",
                    f"/openedx/edx-platform/cms/envs/{settings_namespace}/assets.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/cms/i18n.py",
                    f"/openedx/edx-platform/cms/envs/{settings_namespace}/i18n.py",
                ]
            )
            # django-aqueduct settings:
            # models/base.py    → ProductionSettingsMixin + SharedAqueductSettings, copied into both envs
            # models/aqueduct.py → generated AqueductSettings pydantic model per service
            # aqueduct.py       → settings module (DJANGO_SETTINGS_MODULE target)
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/models/base.py",
                    "/openedx/edx-platform/lms/envs/models/base.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/lms/models/aqueduct.py",
                    "/openedx/edx-platform/lms/envs/models/aqueduct.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/lms/aqueduct.py",
                    "/openedx/edx-platform/lms/envs/aqueduct.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/models/base.py",
                    "/openedx/edx-platform/cms/envs/models/base.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/cms/models/aqueduct.py",
                    "/openedx/edx-platform/cms/envs/models/aqueduct.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/cms/aqueduct.py",
                    "/openedx/edx-platform/cms/envs/aqueduct.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/set_waffle_flags.py",
                    "/openedx/edx-platform/set_waffle_flags.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/process_scheduled_emails.py",
                    "/openedx/edx-platform/process_scheduled_emails.py",
                ]
            )
            .with_exec(
                [
                    "cp",
                    "/tmp/custom_settings/saml_pull.py",
                    "/openedx/edx-platform/saml_pull.py",
                ]
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
        atlas_options = (
            f"--repository {translations_repository} --revision {translations_branch}"
        )

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

        all_hosts = ["github.com"] + extra_ssh_hosts
        hosts_str = " ".join(f"'{h}'" for h in all_hosts)

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

    @function
    async def build_platform(
        self,
        deployment_name: str,
        release_name: str,
        pip_package_lists: dagger.Directory,
        pip_package_overrides: dagger.Directory,
        custom_settings: dagger.Directory,
        translations_repo: str = "openedx/openedx-translations",
        source: dagger.Directory | None = None,
        platform_repo: str = "https://github.com/openedx/edx-platform",
        platform_branch: str = "master",
        theme_source: dagger.Directory | None = None,
        theme_repo: str | None = None,
        theme_branch: str | None = None,
        python_version: str | None = None,
        node_version: str = "20.18.0",
        locale_version: str = "master",
        translations_branch: str = "main",
        include_locales: bool = True,
        settings_namespace: str = "production",
        extra_ssh_hosts: list[str] | None = None,
        packages_to_remove: list[str] | None = None,
        extra_npm_packages: list[str] | None = None,
    ) -> dagger.Container:
        """Build a complete openedx-platform image

        This chains together all the build steps based on the Earthfile process.

        Args:
            deployment_name: Deployment name
            release_name: Release name (e.g., master, sumac, redwood)
            pip_package_lists: Directory with pip requirements files
            pip_package_overrides: Directory with pip override requirements
            custom_settings: Directory with custom settings files
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
        if extra_ssh_hosts is None:
            extra_ssh_hosts = []
        if packages_to_remove is None:
            packages_to_remove = []
        if extra_npm_packages is None:
            extra_npm_packages = []

        # Determine Python version based on release if not explicitly provided
        if python_version is None:
            python_version = "3.12" if release_name == "master" else "3.11"

        # ── Deps chain ────────────────────────────────────────────────────────
        # Run the heavy install steps on a throw-away chain.  All build caches
        # (npm ~/.npm, pip /tmp artefacts) accumulate here and are discarded
        # when we copy only the three needed directories to the clean base
        # below, mirroring the Earthfile's multi-stage `collected` approach.
        deps = self.apt_base(python_version=python_version)
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
        # Start fresh (equivalent to Earthfile `collected: FROM +apt-base`).
        # Copy only the built artefacts; npm/uv/pip caches are left behind.
        container = self.apt_base(python_version=python_version)
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
        container = self.docker_image(
            container,
            deployment_name=deployment_name,
            release_name=release_name,
            extra_ssh_hosts=extra_ssh_hosts,
        )

        return container

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
        pip_package_lists: dagger.Directory,
        pip_package_overrides: dagger.Directory,
        release_name: str = "master",
        platform_repo: str = "https://github.com/openedx/edx-platform",
        platform_branch: str = "master",
        python_version: str | None = None,
        packages_to_remove: list[str] | None = None,
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
          lms/models/aqueduct.py
          cms/models/aqueduct.py

        Usage::

            dagger call platform regenerate-aqueduct-settings \\
              --deployment-name my-deployment \\
              --pip-package-lists ./pip_package_lists \\
              --pip-package-overrides ./pip_package_overrides \\
              export --path ./generated

            # Then update the committed models:
            cp generated/lms/models/aqueduct.py settings/lms/models/aqueduct.py
            cp generated/cms/models/aqueduct.py settings/cms/models/aqueduct.py

        Args:
            deployment_name: Deployment name.
            pip_package_lists: Directory containing pip requirements files.
            pip_package_overrides: Directory containing pip override requirements.
            release_name: edx-platform release / branch name. Default: master.
            platform_repo: Git repository URL for edx-platform.
            platform_branch: Git branch to check out.
            python_version: Python version. Defaults to 3.12 for master.
            packages_to_remove: Python packages to uninstall after base install
                (default: empty list).
        """
        if packages_to_remove is None:
            packages_to_remove = []

        if python_version is None:
            python_version = "3.12" if release_name == "master" else "3.11"

        # ── Base system + code ────────────────────────────────────────────────
        container = self.apt_base(python_version=python_version)
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
        )

        # ── Generate the models ───────────────────────────────────────────────
        # Call ModuleInspector + SettingsModelGenerator directly — no
        # management command required, no django_aqueduct in INSTALLED_APPS
        # required.  The shim modules import common.py into their own globals
        # so every UPPERCASE name (including plugin settings) is discovered.
        generate_script = "\n".join(
            [
                "import sys, os, re",
                "os.chdir('/openedx/edx-platform')",
                "sys.path.insert(0, '/openedx/edx-platform')",
                "from django_aqueduct.discovery.module import ModuleInspector",
                "from django_aqueduct.codegen.generator import SettingsModelGenerator",
                "def _add_imports(code):",
                "    # 1. Add missing stdlib/third-party imports that the generator omits.",
                "    extra = []",
                "    if 'Path(' in code and 'from path import' not in code:",
                "        extra.append('from path import Path')",
                "    if 'datetime.' in code and 'import datetime' not in code:",
                "        extra.append('import datetime')",
                "    if extra:",
                "        lines = code.splitlines()",
                '        last_import = max((i for i, l in enumerate(lines) if re.match(r"^(from|import)\\s", l)), default=0)',
                "        lines = lines[:last_import+1] + extra + lines[last_import+1:]",
                "        code = '\\n'.join(lines) + '\\n'",
                "    # 2. Fix OPAQUE fields: `T = Field(default=None)` → `T | None = Field(default=None)`.",
                "    #    The generator marks certain values as OPAQUE (not serialisable) and emits",
                "    #    default=None, but keeps the non-nullable type annotation.  Widen it so",
                "    #    pydantic v2 doesn't raise a validation error when the field is absent.",
                "    code = re.sub(",
                "        r'^(    \\w+: (?:(?!None|Any)[^\\n=])+) = Field\\(default=None\\)',",
                "        r'\\1 | None = Field(default=None)',",
                "        code, flags=re.MULTILINE)",
                "    return code",
                "for shim, out in [",
                "    ('lehrer_lms_shim', 'lms/envs/models/aqueduct.py'),",
                "    ('lehrer_cms_shim', 'cms/envs/models/aqueduct.py'),",
                "]:",
                "    print(f'Generating {out} from {shim} ...')",
                "    fields = ModuleInspector(shim).discover()",
                "    code = _add_imports(SettingsModelGenerator(fields).render())",
                "    open(out, 'w').write(code)",
                "    print(f'  {len(fields)} fields written to {out}')",
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
