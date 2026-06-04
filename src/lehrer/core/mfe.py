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

    # ── OEP-65 frontend-base stubs ────────────────────────────────────────────

    @function
    async def build_site(
        self,
        site_project: dagger.Directory,
        node_version: str = "22",
    ) -> dagger.Directory:
        """Build an OEP-65 frontend-base Site Project.

        A Site Project is an operator-owned repository containing a site.config.tsx
        that declares which modules to load, along with any custom module source
        in src/. This function runs ``openedx build`` from @openedx/frontend-base,
        producing a deployable dist/ directory containing the Shell bundled with
        all imported modules.

        Args:
            site_project: Directory containing the Site Project. Must include:
                - package.json with @openedx/frontend-base as a dependency
                - site.config.build.tsx (or .jsx) declaring modules and config
                - (optional) src/ with custom module overrides
            node_version: Node.js version (default: 22, minimum required by frontend-base)

        Returns:
            dist/ directory suitable for static hosting (CDN, S3, nginx).

        See: plans/03-frontend-base-oep65.md for full implementation guide.
        See: https://github.com/openedx/frontend-base
        See: https://docs.openedx.org/projects/openedx-proposals/en/latest/architectural-decisions/oep-0065-arch-frontend-composability.html
        """
        raise NotImplementedError(
            "OEP-65 frontend-base Site Project builds are not yet implemented. "
            "See plans/03-frontend-base-oep65.md for the implementation guide."
        )

    @function
    async def build_federated_module(
        self,
        module_project: dagger.Directory,
        node_version: str = "22",
    ) -> dagger.Directory:
        """Build an OEP-65 frontend-base federated module for runtime loading.

        A Module Project exposes one or more application modules via webpack
        module federation. The resulting remoteEntry.js and chunk files are
        loaded at runtime by the Shell served from a Site Project build.

        Args:
            module_project: Directory containing the Module Project. Must include:
                - package.json with a "config" block declaring exposes entries
                - src/ with the module implementations
            node_version: Node.js version (default: 22)

        Returns:
            Directory of federated module assets (remoteEntry.js + chunks)
            to be deployed alongside or separately from the Site.

        See: plans/03-frontend-base-oep65.md for full implementation guide.
        """
        raise NotImplementedError(
            "OEP-65 federated module builds are not yet implemented. "
            "See plans/03-frontend-base-oep65.md for the implementation guide."
        )

    @function
    async def watch_site(
        self,
        site_project: dagger.Directory,
        node_version: str = "22",
        port: int = 8080,
    ) -> dagger.Service:
        """Run an OEP-65 Site Project dev server with hot reload.

        Equivalent to ``openedx dev`` from @openedx/frontend-base.

        Args:
            site_project: Directory containing the Site Project
            node_version: Node.js version (default: 22)
            port: Port to expose the dev server on (default: 8080)

        Returns:
            Service running the site dev server with hot reload.

        See: plans/03-frontend-base-oep65.md for full implementation guide.
        """
        raise NotImplementedError(
            "OEP-65 site dev server is not yet implemented. "
            "See plans/03-frontend-base-oep65.md for the implementation guide."
        )
