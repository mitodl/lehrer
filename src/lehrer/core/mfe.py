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
        extra_slot_files: list[str] | None = None,
        styles_file: str | None = None,
        extra_npm_bundles: list[str] | None = None,
        env_vars: list[str] | None = None,
        pre_build_commands: list[str] | None = None,
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
                **Required** — pass the directory from your operator slot config,
                e.g. ``--slot-config /path/to/mfe_slot_config/legacy``.
            extra_slot_files: Additional files to inject from ``slot_config`` into
                the MFE root before building.  Each entry is either
                ``"filename"`` (source and destination share the same name) or
                ``"source:dest"`` (rename on copy).  Example::

                    ["CustomBanner.jsx",
                     "MyComponent.v2.jsx:MyComponent.jsx"]

            styles_file: A file from ``slot_config`` to copy into the MFE root
                as a deployment-specific stylesheet override.
            extra_npm_bundles: Additional npm packages to pack and copy as
                static bundles.  Each entry has the format
                ``"npm_package_spec|target_directory"``, e.g.::

                    "@myorg/my-package@^1.0.0|public/static/my-package"

                The package is packed with ``npm pack``, extracted, and its
                ``package/dist/bundles/*`` contents are copied to
                ``target_directory``.  Default: empty list — no extra bundles.
            env_vars: Build-time environment variables in ``KEY=VALUE`` form.
                Applied before ``npm run build`` so webpack bakes them in via
                ``process.env.*``.
            pre_build_commands: Shell commands to run after ``npm install`` but
                before ``npm run build``.  Use for translation pulls, e.g.:
                ``["export ATLAS_OPTIONS='...'", "make pull_translations"]``.

        Returns:
            Directory containing built MFE dist files
        """
        if extra_npm_bundles is None:
            extra_npm_bundles = []

        if slot_config is None:
            raise ValueError(
                "slot_config is required — pass the MFE slot configuration directory "
                "for this build (e.g. --slot-config /path/to/mfe_slot_config)"
            )

        # Start with Node.js base image
        container = (
            dag.container()
            .from_(f"node:{node_version}-trixie-slim")
            .with_exec(
                [
                    "sh",
                    "-c",
                    "apt-get update -q && "
                    "apt-get install -y --no-install-recommends "
                    "git build-essential python3 python-is-python3 && "
                    "apt-get clean && "
                    "rm -rf /var/lib/apt/lists/*",
                ]
            )
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

        # Inject operator-specific slot files
        for spec in extra_slot_files or []:
            src, _, dest = spec.partition(":")
            if not dest:
                dest = src
            container = container.with_file(f"/app/mfe/{dest}", slot_config.file(src))

        # Copy styles file if specified
        if styles_file:
            styles = slot_config.file(styles_file)
            container = container.with_file(f"/app/mfe/{styles_file}", styles)

        # Apply build-time env vars (baked in by webpack via process.env.*)
        for kv in env_vars or []:
            key, _, val = kv.partition("=")
            container = container.with_env_variable(key, val)

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

        # Run pre-build commands (e.g. pull translations via openedx-atlas)
        if pre_build_commands:
            container = container.with_exec(["sh", "-c", "\n".join(pre_build_commands)])

        # Install webpack
        container = container.with_exec(["npm", "install", "webpack"])

        # Build the MFE
        container = container.with_env_variable("NODE_ENV", "production").with_exec(
            ["npm", "run", "build"]
        )

        # Return the dist directory
        return container.directory("/app/mfe/dist")

    @function
    async def build_legacy_configured(
        self,
        mfe_name: str,
        mfe_repo: str,
        slot_config: dagger.Directory,
        deployment_name: str = "default",
        release_name: str = "",
        config_file: str = "build_config.yaml",
        mfe_branch: str = "master",
        node_version: str = "20.18.0",
        env_vars: list[str] | None = None,
        pre_build_commands: list[str] | None = None,
    ) -> dagger.Directory:
        """Build a legacy MFE, resolving customizations from a YAML config file.

        This is the declarative counterpart to :func:`build_legacy`.  Instead of
        passing ``extra_slot_files`` / ``styles_file`` / ``extra_npm_bundles``
        explicitly, an operator describes them once in a ``build_config.yaml``
        living alongside their slot configuration.  The resolved values are
        forwarded to :func:`build_legacy`, so the build behaviour is identical.

        Config schema (all keys optional)::

            # Per-deployment stylesheet override copied into the MFE root.
            styles:
              <deployment_name>: <filename in slot_config>

            # Per-MFE customizations keyed by MFE application name.
            mfes:
              <mfe_name>:
                # Files copied from slot_config into the MFE root.  A plain
                # string copies as-is; a mapping picks the source by release
                # name and copies it to `dest`.
                extra_slot_files:
                  - SomeComponent.jsx
                  - dest: Coordinator.jsx
                    by_release:
                      <release_name>: Coordinator.special.jsx
                      default: Coordinator.jsx
                # Pre-built npm bundles (see build_legacy.extra_npm_bundles).
                extra_npm_bundles:
                  - "@org/pkg@^1.0.0|public/static/pkg"

        Args:
            mfe_name: MFE application name (e.g. ``learning``, ``discussions``).
            mfe_repo: Git repository URL for the MFE.
            slot_config: Directory containing slot configuration files and the
                ``build_config.yaml`` named by ``config_file``.
            deployment_name: Deployment name; selects the ``styles`` entry and
                ``{deployment_name}/common-mfe-config.env.jsx``.
            release_name: Open edX release name; selects ``by_release`` variants.
            config_file: Name of the YAML config inside ``slot_config``
                (default: ``build_config.yaml``).
            mfe_branch: Git branch (default: ``master``).
            node_version: Node.js version (default: ``20.18.0``).
            env_vars: Build-time environment variables in ``KEY=VALUE`` form.
            pre_build_commands: Shell commands run after ``npm install``.

        Returns:
            Directory containing built MFE dist files.
        """
        import yaml

        raw = await slot_config.file(config_file).contents()
        config = yaml.safe_load(raw)
        # A present-but-empty YAML key parses as None, so coalesce each level to
        # an empty container rather than assuming a default only fills absent keys.
        if not isinstance(config, dict):
            config = {}

        styles_file = (config.get("styles") or {}).get(deployment_name)
        mfe_cfg = (config.get("mfes") or {}).get(mfe_name.lower()) or {}

        extra_slot_files: list[str] = []
        for item in mfe_cfg.get("extra_slot_files") or []:
            if isinstance(item, str):
                extra_slot_files.append(item)
                continue
            dest = item["dest"]
            variants = item.get("by_release") or {}
            src = variants.get(release_name.lower()) or variants.get("default")
            if src is None:
                raise ValueError(
                    f"No source for {dest!r} matching release {release_name!r} "
                    f"and no 'default' variant in {config_file}"
                )
            extra_slot_files.append(f"{src}:{dest}")

        return await self.build_legacy(
            mfe_name=mfe_name,
            mfe_repo=mfe_repo,
            mfe_branch=mfe_branch,
            node_version=node_version,
            deployment_name=deployment_name,
            slot_config=slot_config,
            extra_slot_files=extra_slot_files,
            styles_file=styles_file,
            extra_npm_bundles=list(mfe_cfg.get("extra_npm_bundles") or []),
            env_vars=env_vars,
            pre_build_commands=pre_build_commands,
        )

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
        container = (
            dag.container()
            .from_(f"node:{node_version}-trixie-slim")
            .with_exec(
                [
                    "sh",
                    "-c",
                    "apt-get update -q && "
                    "apt-get install -y --no-install-recommends "
                    "git build-essential python3 python-is-python3 && "
                    "apt-get clean && "
                    "rm -rf /var/lib/apt/lists/*",
                ]
            )
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
            .with_exec(
                [
                    "sh",
                    "-c",
                    "apt-get update -q && "
                    "apt-get install -y --no-install-recommends "
                    "git build-essential python3 python-is-python3 && "
                    "apt-get clean && "
                    "rm -rf /var/lib/apt/lists/*",
                ]
            )
        )

    @function
    async def build_site(
        self,
        site_project: dagger.Directory,
        shared_src: dagger.Directory | None = None,
        node_version: str = "24",
        public_path: str | None = None,
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
                ``site_project`` must declare ``"@shared/*": ["./shared/src/*"]``
                under ``compilerOptions.paths``.
            node_version: Node.js version (default: 24, as required by frontend-base
                .nvmrc; minimum tested: 22).
            public_path: Optional public URL prefix for assets (webpack's publicPath).
                Used when static assets are hosted on a CDN (e.g., S3, Fastly).
                If provided, sets the ``PUBLIC_PATH`` environment variable before build.

        Returns:
            ``dist/`` directory suitable for static hosting (CDN, S3, nginx).

        See: mfe_slot_config/frontend/AUDIT.md for verified API details.
        See: https://github.com/openedx/frontend-base
        """
        container = (
            self._oep65_base(node_version)
            .with_mounted_cache("/root/.npm", dag.cache_volume("npm-cache"))
            .with_workdir("/app/site")
            .with_directory("/app/site", site_project)
        )
        if shared_src is not None:
            container = container.with_directory("/app/site/shared", shared_src)

        build_cmd = ["npx", "openedx", "build"]

        if public_path is not None:
            container = container.with_env_variable("PUBLIC_PATH", public_path)

        return (
            container.with_exec(["npm", "install"])
            .with_exec(build_cmd)
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
            .with_mounted_cache("/root/.npm", dag.cache_volume("npm-cache"))
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
