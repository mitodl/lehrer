"""Generic MFE build pipeline for Open edX operators.

Contains the legacy per-MFE build functions and forward-looking OEP-65
frontend-base stubs.
"""

import dagger
from dagger import dag, function, object_type


@object_type
class OpenedxMfe:
    """Build Open edX Micro Frontends (MFEs).

    Two eras of MFE builds are supported:

    * **Legacy** — individual per-MFE webpack builds via ``build_legacy`` /
      ``watch_legacy``.  These correspond to the current
      ``@edx/frontend-build`` / ``@edx/frontend-platform`` era.

    * **OEP-65 (frontend-base)** — site-project and federated-module builds
      via ``build_site``, ``build_federated_module``, and ``watch_site``.
      These stubs will be implemented in Phase 2 (see
      ``plans/03-frontend-base-oep65.md``).
    """

    @function
    async def build_legacy(
        self,
        mfe_name: str,
        mfe_repo: str,
        mfe_branch: str = "master",
        node_version: str = "20.18.0",
        deployment_name: str = "default",
        slot_config: dagger.Directory | None = None,
        enable_ai_drawer: bool = False,
        styles_file: str | None = None,
        extra_npm_bundles: list[str] | None = None,
    ) -> dagger.Directory:
        """Build an Open edX Micro Frontend (MFE) — legacy webpack build

        Args:
            mfe_name: MFE application name (e.g., 'learning', 'discussions', 'account')
            mfe_repo: Git repository URL for the MFE
            mfe_branch: Git branch to build from (default: master)
            node_version: Node.js version to use (default: 20.18.0)
            deployment_name: Deployment name used to select config files from
                ``slot_config``.  Determines which
                ``{deployment_name}/common-mfe-config.env.jsx`` is loaded.
                Default: ``"default"``.
            slot_config: Directory containing slot configuration files.
                **Required** — pass the directory from your operator slot config
                pass the directory from your operator config, e.g. ``--slot-config /path/to/mfe_slot_config/legacy``.
            enable_ai_drawer: Enable AI drawer components (for learning MFE)
            styles_file: Deployment-specific styles file to include
            extra_npm_bundles: Additional npm packages to pack and copy as
                static bundles.  Each entry has the format
                ``"npm_package_spec|target_directory"``, e.g.::

                    "@myorg/my-package@^1.0.0|public/static/my-package"

                The package is packed with ``npm pack``, extracted, and its
                ``package/dist/bundles/*`` contents are copied to
                ``target_directory``.  Default: empty list — no extra bundles.

        Returns:
            Directory containing built MFE dist files

        Note:
            Set environment variables using with_env_variable() on the returned container.
            For example:
              dir = await build_legacy(...).with_env_variable("LMS_BASE_URL", "...").directory("/app/mfe/dist")
        """
        if extra_npm_bundles is None:
            extra_npm_bundles = []

        if slot_config is None:
            raise ValueError(
                "slot_config is required — pass the MFE slot configuration directory "
                "for this build (e.g. --slot-config /path/to/mfe_slot_config)"
            )

        # Start with Node.js base image
        container = dag.container().from_(f"node:{node_version}-trixie-slim")

        # Install system dependencies
        container = (
            container.with_exec(["apt-get", "update"])
            .with_exec(
                [
                    "apt",
                    "install",
                    "-y",
                    "python3",
                    "python-is-python3",
                    "build-essential",
                    "git",
                ]
            )
            .with_exec(["apt", "clean"])
        )

        # Clone MFE repository
        container = (
            container.with_workdir("/app")
            .with_exec(
                [
                    "git",
                    "clone",
                    "--branch",
                    mfe_branch,
                    "--depth",
                    "1",
                    mfe_repo,
                    "mfe",
                ]
            )
            .with_workdir("/app/mfe")
        )

        # Determine config file to use
        is_learning_mfe = mfe_name.lower() == "learning"
        config_file = (
            "learning-mfe-config"
            if is_learning_mfe
            else f"{deployment_name}/common-mfe-config"
        )

        # Copy Footer.jsx
        footer_file = slot_config.file("Footer.jsx")
        container = container.with_file("/app/mfe/Footer.jsx", footer_file)

        # Copy env.config.jsx
        env_config_file = slot_config.file(f"{config_file}.env.jsx")
        container = container.with_file("/app/mfe/env.config.jsx", env_config_file)

        # For learning MFE, copy common-mfe-config.env.jsx
        if is_learning_mfe:
            common_config_file = slot_config.file(
                f"{deployment_name}/common-mfe-config.env.jsx"
            )
            container = container.with_file(
                "/app/mfe/common-mfe-config.env.jsx", common_config_file
            )

        # Copy AI drawer components if enabled
        if enable_ai_drawer and is_learning_mfe:
            ai_drawer_sidebar = slot_config.file("AIDrawerManagerSidebar.jsx")
            container = container.with_file(
                "/app/mfe/AIDrawerManagerSidebar.jsx", ai_drawer_sidebar
            )

            sidebar_coordinator = slot_config.file("SidebarAIDrawerCoordinator.jsx")
            container = container.with_file(
                "/app/mfe/SidebarAIDrawerCoordinator.jsx", sidebar_coordinator
            )

        # Copy styles file if specified
        if styles_file:
            styles = slot_config.file(styles_file)
            container = container.with_file(f"/app/mfe/{styles_file}", styles)

        # Install npm dependencies
        container = container.with_exec(["npm", "install"])

        # Install openedx-atlas for translations
        container = container.with_exec(["npm", "install", "-g", "@edx/openedx-atlas"])

        # Pack and copy extra npm bundles (e.g. UI component libraries shipped
        # as pre-built bundles rather than as npm dependencies)
        import shlex

        for bundle_spec in extra_npm_bundles:
            pkg_spec, target_path = bundle_spec.split("|", 1)
            safe_target = shlex.quote(target_path)
            container = (
                container.with_exec(["npm", "pack", pkg_spec])
                .with_exec(["sh", "-c", "tar -xvzf *.tgz"])
                .with_exec(["mkdir", "-p", target_path])
                .with_exec(
                    [
                        "sh",
                        "-c",
                        f"cp package/dist/bundles/* {safe_target}/",
                    ]
                )
            )

        # Install webpack
        container = container.with_exec(["npm", "install", "webpack"])

        # Build the MFE
        container = container.with_env_variable("NODE_ENV", "production").with_exec(
            ["npm", "run", "build"]
        )

        # Return the dist directory
        return container.directory("/app/mfe/dist")

    @function
    async def watch_legacy(
        self,
        mfe_source: dagger.Directory,
        slot_config: dagger.Directory | None = None,
        node_version: str = "20.18.0",
        deployment_name: str = "default",
        mfe_name: str = "learning",
        port: int = 8080,
    ) -> dagger.Service:
        """Run MFE dev server with hot reload for local testing

        This creates a watch container for testing slot config changes locally.

        Args:
            mfe_source: Directory containing MFE source code
            slot_config: Directory containing slot configuration files.
                **Required** — pass the directory from your operator slot config
                pass the directory from your operator config, e.g. ``--slot-config /path/to/mfe_slot_config/legacy``.
            node_version: Node.js version to use (default: 20.18.0)
            deployment_name: Deployment name for config file selection
                (default: ``"default"``).
            mfe_name: MFE name (e.g., 'learning')
            port: Port to expose the dev server on (default: 8080)

        Returns:
            Service running the MFE dev server

        Note:
            Set environment variables using with_env_variable() before calling as_service().
            The service will automatically rebuild when slot config files change.
        """
        if slot_config is None:
            raise ValueError(
                "slot_config is required — pass the MFE slot configuration directory "
                "for this build (e.g. --slot-config /path/to/mfe_slot_config)"
            )

        # Start with Node.js base image
        container = dag.container().from_(f"node:{node_version}-trixie-slim")

        # Install system dependencies
        container = (
            container.with_exec(["apt-get", "update"])
            .with_exec(
                [
                    "apt",
                    "install",
                    "-y",
                    "python3",
                    "python-is-python3",
                    "build-essential",
                    "git",
                ]
            )
            .with_exec(["apt", "clean"])
        )

        # Set up work directory and mount source
        container = container.with_workdir("/app/mfe").with_directory(
            "/app/mfe", mfe_source
        )

        # Determine config files
        is_learning_mfe = mfe_name.lower() == "learning"
        config_file = (
            "learning-mfe-config"
            if is_learning_mfe
            else f"{deployment_name}/common-mfe-config"
        )

        # Mount slot config files
        footer_file = slot_config.file("Footer.jsx")
        container = container.with_file("/app/mfe/Footer.jsx", footer_file)

        env_config_file = slot_config.file(f"{config_file}.env.jsx")
        container = container.with_file("/app/mfe/env.config.jsx", env_config_file)

        if is_learning_mfe:
            common_config_file = slot_config.file(
                f"{deployment_name}/common-mfe-config.env.jsx"
            )
            container = container.with_file(
                "/app/mfe/common-mfe-config.env.jsx", common_config_file
            )

        # Ensure PORT is set for the dev server
        container = container.with_env_variable("PORT", str(port))

        # Install dependencies if package-lock.json exists
        container = container.with_exec(["npm", "install"]).with_exec(
            ["npm", "install", "-g", "@edx/openedx-atlas"]
        )

        # Expose port and start dev server
        container = container.with_exposed_port(port).with_exec(["npm", "start"])

        return container.as_service()

    # ── OEP-65 frontend-base ─────────────────────────────────────────────────

    def _oep65_base(
        self,
        node_version: str,
    ) -> dagger.Container:
        """Shared Node base container for all OEP-65 builds."""
        return (
            dag.container()
            .from_(f"node:{node_version}-trixie-slim")
            .with_exec(["apt-get", "update", "-q"])
            .with_exec(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "--no-install-recommends",
                    "git",
                    "build-essential",
                    "python3",
                    "python-is-python3",
                ]
            )
            .with_exec(["apt-get", "clean"])
            .with_exec(["rm", "-rf", "/var/lib/apt/lists/*"])
        )

    @function
    async def build_site(
        self,
        site_project: dagger.Directory,
        shared_src: dagger.Directory | None = None,
        node_version: str = "24",
    ) -> dagger.Directory:
        """Build an OEP-65 frontend-base Site Project.

        Runs ``openedx build`` (webpack production build) against a Site Project
        directory.  The Site Project must contain:

        - ``package.json`` with ``@openedx/frontend-base`` listed as a dependency
        - ``site.config.build.tsx`` declaring the Shell, header, footer, and any
          imported module library app configs
        - ``site.config.dev.tsx`` (not used during build, but expected by the
          webpack config resolver)
        - ``tsconfig.json`` (required by TsconfigPathsPlugin)
        - (optional) ``src/`` with operator module overrides

        Args:
            site_project: Directory containing the complete Site Project.
            shared_src: Optional directory of shared TypeScript source mounted at
                ``/app/site/shared``.  Use when multiple Site Projects share components
                via a ``@shared/*`` tsconfig path alias.  The tsconfig in
                ``site_project`` must declare ``"@shared/*": ["../shared/src/*"]``
                (or the equivalent absolute path) under ``compilerOptions.paths``.
            node_version: Node.js version (default: 24, as required by frontend-base
                .nvmrc; minimum tested: 22).

        Returns:
            ``dist/`` directory suitable for static hosting (CDN, S3, nginx).

        See: mfe_slot_config/frontend/AUDIT.md for verified API details.
        See: https://github.com/openedx/frontend-base
        """
        container = (
            self._oep65_base(node_version)
            .with_workdir("/app/site")
            .with_directory("/app/site", site_project)
        )
        if shared_src is not None:
            container = container.with_directory("/app/site/shared", shared_src)
        return (
            container.with_exec(["npm", "install"])
            .with_exec(["npx", "openedx", "build"])
            .directory("/app/site/dist")
        )

    @function
    async def build_federated_module(
        self,
        module_project: dagger.Directory,
        node_version: str = "24",
    ) -> dagger.Directory:
        """Build an OEP-65 frontend-base federated module for runtime loading.

        **Not yet implemented.** The ``openedx build:module`` CLI command does not
        exist in ``@openedx/frontend-base`` as of ``v1.0.0-alpha.41`` (2026-04-27).
        Module libraries are currently imported directly by Site Projects as npm
        package dependencies and bundled at build time — they are not deployed as
        independently loadable federated remotes at this stage.

        Args:
            module_project: Directory containing the Module Project. Must include:
                - package.json with a module library configuration
                - src/ with the module implementations
            node_version: Node.js version (default: 24)

        Returns:
            Directory of federated module assets (remoteEntry.js + chunks)
            to be deployed alongside or separately from the Site.

        See: mfe_slot_config/frontend/AUDIT.md for the blocking finding.
        See: plans/03-frontend-base-oep65.md for the implementation guide.
        """
        raise NotImplementedError(
            "openedx build:module does not exist in @openedx/frontend-base "
            "v1.0.0-alpha.41. Module libraries are bundled into the Site Project "
            "at build time. See mfe_slot_config/frontend/AUDIT.md."
        )

    @function
    async def watch_site(
        self,
        site_project: dagger.Directory,
        shared_src: dagger.Directory | None = None,
        node_version: str = "24",
        port: int = 8080,
    ) -> dagger.Service:
        """Run an OEP-65 Site Project dev server with hot reload.

        Runs ``openedx dev`` (webpack-dev-server) against a Site Project directory.
        The Site Project must include ``site.config.dev.tsx`` — see
        ``mfe_slot_config/frontend/AUDIT.md`` for the required structure.

        Args:
            site_project: Directory containing the Site Project.
            shared_src: Optional directory of shared TypeScript source; mounted at
                ``/app/site/shared`` (same contract as ``build_site``).
            node_version: Node.js version (default: 24).
            port: Port to expose the dev server on (default: 8080).

        Returns:
            Service running the webpack-dev-server at the given port.

        See: mfe_slot_config/frontend/AUDIT.md for verified API details.
        """
        container = (
            self._oep65_base(node_version)
            .with_workdir("/app/site")
            .with_directory("/app/site", site_project)
        )
        if shared_src is not None:
            container = container.with_directory("/app/site/shared", shared_src)
        return (
            container.with_env_variable("PORT", str(port))
            .with_exec(["npm", "install"])
            .with_exposed_port(port)
            .with_exec(["npx", "openedx", "dev"])
            .as_service()
        )
