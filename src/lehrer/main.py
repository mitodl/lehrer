import dagger
from dagger import dag, function, object_type


@object_type
class Lehrer:
    """Dagger module for building and deploying Open edX platform images
    
    Based on the Earthly build process from ol-infrastructure
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
        uv_binary = (
            dag.container()
            .from_("ghcr.io/astral-sh/uv:latest")
            .file("/uv")
        )
        
        return (
            dag.container()
            .from_(f"python:{python_version}-bookworm")
            .with_env_variable("DEBIAN_FRONTEND", "noninteractive")
            .with_file("/usr/local/bin/uv", uv_binary)
            # Set uv environment variables for virtual environment
            # uv will automatically create the venv when first needed
            .with_env_variable("UV_NO_MANAGED_PYTHON", "1")
            .with_env_variable("UV_PYTHON_DOWNLOADS", "never")
            .with_env_variable("UV_COMPILE_BYTECODE", "1")
            .with_env_variable("UV_LINK_MODE", "copy")
            .with_env_variable("UV_PROJECT_ENVIRONMENT", "/openedx/venv")
            .with_env_variable("VIRTUAL_ENV", "/openedx/venv")
            .with_env_variable("PATH", "/openedx/venv/bin:/usr/local/bin:/usr/bin:/bin")
            .with_exec(["apt", "update"])
            .with_exec(["apt", "install", "-y", "--no-install-recommends"] + apt_packages)
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
            container
            .with_exec([
                "git", "clone", "--depth", "1", "--branch", locale_version,
                "https://github.com/openedx-unsupported/openedx-i18n.git", "/tmp/openedx-i18n"
            ])
            .with_exec(["mkdir", "-p", "/openedx/locale/contrib"])
            .with_exec(["sh", "-c", "mv /tmp/openedx-i18n/edx-platform/locale /openedx/locale/contrib || true"])
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
            container = container.with_mounted_directory("/openedx/edx-platform", source)
        elif edx_platform_git_repo and edx_platform_git_branch:
            container = container.with_exec([
                "git", "clone", "--depth", "1", "--branch", edx_platform_git_branch,
                edx_platform_git_repo, "/openedx/edx-platform"
            ])
        else:
            raise ValueError("Must provide either source or both edx_platform_git_repo and edx_platform_git_branch")
        
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
            deployment_name: Name of the deployment (e.g., mitx, mitxonline)
            theme_source: Local directory with theme source (optional)
            theme_git_repo: Git repository URL (required if theme_source not provided)
            theme_git_branch: Git branch/tag (required if theme_source not provided)
        
        Returns:
            Container with theme at /openedx/themes/{deployment_name}
        """
        theme_path = f"/openedx/themes/{deployment_name}"
        
        if theme_source is not None:
            return container.with_mounted_directory(theme_path, theme_source)
        
        if not theme_git_repo or not theme_git_branch:
            raise ValueError("Must provide either theme_source or both theme_git_repo and theme_git_branch")
        
        return (
            container
            .with_exec([
                "git", "clone", "--depth", "1", "--branch", theme_git_branch,
                theme_git_repo, theme_path
            ])
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
    ) -> dagger.Container:
        """Install Python and Node.js dependencies using uv
        
        Args:
            container: Container with edx-platform source at /openedx/edx-platform
            deployment_name: Deployment name (e.g., mitx, mitxonline)
            release_name: Release name (e.g., sumac, redwood)
            pip_package_lists: Directory containing pip requirements files
            pip_package_overrides: Directory containing pip override requirements
            node_version: Node.js version (default: 20.18.0)
        
        Returns:
            Container with all dependencies installed
        """
        container = (
            container
            .with_mounted_directory("/root/pip_package_lists", pip_package_lists)
            .with_mounted_directory("/root/pip_package_overrides", pip_package_overrides)
            # Copy base requirements from edx-platform
            .with_exec([
                "sh", "-c",
                "cp /openedx/edx-platform/requirements/edx/base.txt /root/pip_package_lists/edx_base.txt"
            ])
            .with_exec([
                "sh", "-c",
                "cp /openedx/edx-platform/requirements/edx/assets.txt /root/pip_package_lists/edx_assets.txt"
            ])
            # Install base Python dependencies using uv (much faster than pip)
            # uv automatically uses the VIRTUAL_ENV set in apt_base
            .with_exec([
                "uv", "pip", "install",
                "-r", "/root/pip_package_lists/edx_base.txt",
                "-r", "/root/pip_package_lists/edx_assets.txt",
                "-r", f"/root/pip_package_lists/{release_name}/{deployment_name}.txt"
            ])
        )
        
        # Special handling for mitxonline
        if deployment_name == "mitxonline":
            container = container.with_exec(["uv", "pip", "uninstall", "edx-name-affirmation"])
        
        # Fix lxml/xmlsec compatibility issues
        # Note: Use pip instead of uv here because the override file uses --no-binary flags
        # that need special handling
        container = (
            container
            .with_exec(["pip", "uninstall", "--yes", "lxml", "xmlsec"])
            .with_exec([
                "pip", "install", "--no-cache-dir",
                "-r", f"/root/pip_package_overrides/{release_name}/{deployment_name}.txt"
            ])
        )
        
        # Install Node.js using nodeenv
        container = (
            container
            .with_workdir("/openedx/edx-platform")
            .with_env_variable("NPM_REGISTRY", "https://registry.npmjs.org/")
            .with_exec([
                "sh", "-c",
                f"nodeenv /openedx/nodeenv --node={node_version} --prebuilt"
            ])
            .with_env_variable("PATH", "/openedx/venv/bin:/openedx/nodeenv/bin:/usr/local/bin:/usr/bin:/bin")
            .with_exec([
                "sh", "-c",
                "npm clean-install -s --registry=https://registry.npmjs.org/"
            ])
            .with_exec([
                "sh", "-c",
                "npm install 'git+https://git@github.com/verificient/edx-proctoring-proctortrack.git#f0fa9edbd16aa5af5a41ac309d2609e529ea8732'"
            ])
        )
        
        return container

    @function
    def dockerize(self) -> dagger.File:
        """Get dockerize binary for templating and waiting
        
        Returns:
            Dockerize binary file
        """
        return (
            dag.container()
            .from_("docker.io/powerman/dockerize@sha256:f3ecfd5ac0f74eed3990782309ac6bf8b700f4eca0ea9e9ef507b11742c19cc6")
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
            .with_exec([
                "git", "clone", "--depth", "1", "--branch", tutor_version,
                "https://github.com/overhangio/tutor.git", "/openedx/tutor"
            ])
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
        app_user_id: int = 1000,
        include_locales: bool = True,
    ) -> dagger.Container:
        """Assemble all artifacts and configure the container
        
        Args:
            container: Container with installed dependencies
            deployment_name: Deployment name
            dockerize_bin: Dockerize binary file
            tutor_bin: Tutor bin directory with utility scripts
            custom_settings: Directory with custom settings and config files
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
            container
            .with_env_variable("PATH", "/usr/sbin:/openedx/venv/bin:/openedx/nodeenv/bin:/usr/local/bin:/usr/bin:/bin")
            .with_directory("/openedx/bin", tutor_bin)
            .with_exec(["chmod", "-R", "a+x", "/openedx/bin"])
            .with_exec([
                "useradd", "--home-dir", "/openedx", "--create-home",
                "--shell", "/bin/bash", "--uid", str(app_user_id), "app"
            ])
            .with_exec(["chown", "-R", f"{app_user_id}:{app_user_id}", "/openedx"])
            .with_user(str(app_user_id))
            .with_mounted_file("/usr/local/bin/dockerize", dockerize_bin)
        )
        
        # Set up PATH for app user
        container = container.with_env_variable(
            "PATH",
            "/openedx/venv/bin:/openedx/bin:/openedx/edx-platform/node_modules/.bin:/openedx/nodeenv/bin:/usr/local/bin:/usr/bin:/bin"
        )
        
        # Install edx-platform in editable mode using uv
        container = (
            container
            .with_workdir("/openedx/edx-platform")
            .with_exec(["uv", "pip", "install", "-e", "."])
            .with_exec(["mkdir", "-p", "/openedx/config", "./lms/envs/mitol", "./cms/envs/mitol"])
        )
        
        # Copy custom settings
        container = (
            container
            .with_mounted_directory("/tmp/custom_settings", custom_settings)
            .with_exec(["cp", "/tmp/custom_settings/lms.env.yml", "/openedx/config/lms.env.yml"])
            .with_exec(["cp", "/tmp/custom_settings/cms.env.yml", "/openedx/config/cms.env.yml"])
            .with_exec(["cp", "/tmp/custom_settings/lms/assets.py", "/openedx/edx-platform/lms/envs/mitol/assets.py"])
            .with_exec(["cp", "/tmp/custom_settings/lms/i18n.py", "/openedx/edx-platform/lms/envs/mitol/i18n.py"])
            .with_exec(["cp", "/tmp/custom_settings/cms/assets.py", "/openedx/edx-platform/cms/envs/mitol/assets.py"])
            .with_exec(["cp", "/tmp/custom_settings/cms/i18n.py", "/openedx/edx-platform/cms/envs/mitol/i18n.py"])
            # Note: custom_settings_module files (lms_settings.py, cms_settings.py, models.py, utils.py)
            # are not currently provided. These would come from a separate directory in a full setup.
            .with_exec(["cp", "/tmp/custom_settings/set_waffle_flags.py", "/openedx/edx-platform/set_waffle_flags.py"])
            .with_exec(["cp", "/tmp/custom_settings/process_scheduled_emails.py", "/openedx/edx-platform/process_scheduled_emails.py"])
            .with_exec(["cp", "/tmp/custom_settings/saml_pull.py", "/openedx/edx-platform/saml_pull.py"])
        )
        
        # Set environment variables
        container = (
            container
            .with_env_variable("REVISION_CFG", "/openedx/config/revisions.yml")
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
        translations_repository: str = "mitodl/mitxonline-translations",
        translations_branch: str = "main",
    ) -> dagger.Container:
        """Fetch and compile translations using atlas
        
        Args:
            container: Container with collected artifacts
            translations_repository: Repository for translations
            translations_branch: Branch for translations
        
        Returns:
            Container with compiled translations
        """
        atlas_options = f"--repository {translations_repository} --revision {translations_branch}"
        
        # Check if pull_plugin_translations command exists
        container = (
            container
            .with_env_variable("DJANGO_SETTINGS_MODULE", "lms.envs.mitol.i18n")
            .with_workdir("/openedx/edx-platform")
        )
        
        # Pull and compile LMS translations
        container = (
            container
            .with_exec(["sh", "-c", f"python manage.py lms pull_plugin_translations {atlas_options} || true"])
            .with_exec(["sh", "-c", "python manage.py lms compile_plugin_translations || true"])
            .with_exec(["sh", "-c", f"python manage.py lms pull_xblock_translations {atlas_options} || true"])
            .with_exec(["sh", "-c", "python manage.py lms compile_xblock_translations || true"])
            .with_exec([
                "sh", "-c",
                f"atlas pull {atlas_options} translations/edx-platform/conf/locale:conf/locale || true"
            ])
            .with_exec(["python", "manage.py", "lms", "compilemessages"])
            .with_exec(["python", "manage.py", "lms", "compilejsi18n"])
        )
        
        # Compile CMS translations
        container = (
            container
            .with_env_variable("DJANGO_SETTINGS_MODULE", "cms.envs.mitol.i18n")
            .with_exec(["sh", "-c", "python manage.py cms compile_xblock_translations || true"])
            .with_exec([
                "sh", "-c",
                f"atlas pull {atlas_options} translations/studio-frontend/src/i18n/messages:conf/plugins-locale/studio-frontend || true"
            ])
            .with_exec(["python", "manage.py", "cms", "compilejsi18n"])
        )
        
        return container

    @function
    def build_static_assets(
        self,
        container: dagger.Container,
        deployment_name: str,
    ) -> dagger.Container:
        """Build and collect static assets
        
        Args:
            container: Container with translations
            deployment_name: Deployment name for theme
        
        Returns:
            Container with static assets built
        """
        # Set environment for asset building
        container = (
            container
            .with_env_variable("STATIC_ROOT_LMS", "/openedx/staticfiles/")
            .with_env_variable("NODE_ENV", "prod")
            .with_env_variable("JS_ENV_EXTRA_CONFIG", '{"PROCTORTRACK_CDN_URL":"\\"\\"","PROCTORTRACK_CONFIG_KEY":"\\"\\""}')
        )
        
        # Build static assets
        container = (
            container
            .with_exec(["mkdir", "-p", "/openedx/staticfiles/"])
            .with_exec(["npm", "run", "postinstall"])
            .with_exec([
                "npm", "run", "compile-sass", "--",
                "--theme-dir", "/openedx/themes/",
                "--theme", deployment_name
            ])
            .with_exec(["python", "manage.py", "lms", "collectstatic", "--noinput", "--settings=mitol.assets"])
            .with_exec(["python", "manage.py", "cms", "collectstatic", "--noinput", "--settings=mitol.assets"])
            .with_exec(["npm", "run", "webpack"])
            .with_exec(["python", "manage.py", "lms", "collectstatic", "--noinput", "--settings=mitol.assets"])
            .with_exec(["python", "manage.py", "cms", "collectstatic", "--noinput", "--settings=mitol.assets"])
            .with_exec(["rdfind", "-makesymlinks", "true", "-followsymlinks", "true", "/openedx/staticfiles/"])
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
    ) -> dagger.Container:
        """Finalize the Docker image for deployment
        
        Args:
            container: Container with static assets built
            deployment_name: Deployment name
            release_name: Release name
        
        Returns:
            Container ready for deployment
        """
        container = (
            container
            .with_env_variable("DJANGO_SETTINGS_MODULE", "invalid")
            # Byte-compile Python files for faster startup
            .with_exec(["python", "-m", "compileall", "-q", "/openedx/edx-platform", "/openedx/venv"])
            # Set up SSH config for GitHub
            .with_exec(["mkdir", "/openedx/.ssh"])
            .with_exec(["chown", "app:app", "/openedx/.ssh"])
            .with_exec(["chmod", "0700", "/openedx/.ssh"])
            .with_exec([
                "sh", "-c",
                "ssh-keyscan 'github.com' 'github.mit.edu' >> /openedx/.ssh/known_hosts"
            ])
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
        source: dagger.Directory | None = None,
        platform_repo: str = "https://github.com/openedx/edx-platform",
        platform_branch: str = "master",
        theme_source: dagger.Directory | None = None,
        theme_repo: str | None = None,
        theme_branch: str | None = None,
        python_version: str | None = None,
        node_version: str = "20.18.0",
        locale_version: str = "master",
        translations_repo: str = "mitodl/mitxonline-translations",
        translations_branch: str = "main",
        include_locales: bool = True,
    ) -> dagger.Container:
        """Build a complete openedx-platform image
        
        This chains together all the build steps based on the Earthfile process.
        
        Args:
            deployment_name: Deployment name (e.g., mitx, mitxonline)
            release_name: Release name (e.g., master, sumac, redwood)
            pip_package_lists: Directory with pip requirements files
            pip_package_overrides: Directory with pip override requirements
            custom_settings: Directory with custom settings files
            source: Local edx-platform source (optional)
            platform_repo: Git repo URL (used if source not provided)
            platform_branch: Git branch (used if source not provided)
            theme_source: Local theme source (optional)
            theme_repo: Theme git repo URL (optional)
            theme_branch: Theme git branch (optional)
            python_version: Python version (default: 3.12 for master, 3.11 for others)
            node_version: Node.js version (default: 20.18.0)
            locale_version: openedx-i18n version (default: master, repo is archived)
            translations_repo: Translations repo (default: mitodl/mitxonline-translations)
            translations_branch: Translations branch (default: main)
            include_locales: Include locale files (default: True)
        
        Returns:
            Container ready to be deployed
        """
        # Determine Python version based on release if not explicitly provided
        if python_version is None:
            python_version = "3.12" if release_name == "master" else "3.11"
        
        # Step 1: Create base container with apt packages
        container = self.apt_base(python_version=python_version)
        
        # Step 2: Get locales if needed
        if include_locales:
            container = self.locales(container, locale_version=locale_version)
        
        # Step 3: Get source code
        container = self.get_code(
            container,
            source=source,
            edx_platform_git_repo=platform_repo,
            edx_platform_git_branch=platform_branch,
        )
        
        # Step 4: Install dependencies
        container = self.install_deps(
            container,
            deployment_name=deployment_name,
            release_name=release_name,
            pip_package_lists=pip_package_lists,
            pip_package_overrides=pip_package_overrides,
            node_version=node_version,
        )
        
        # Step 5: Get themes
        if theme_source or theme_repo:
            container = self.themes(
                container,
                deployment_name=deployment_name,
                theme_source=theme_source,
                theme_git_repo=theme_repo,
                theme_git_branch=theme_branch,
            )
        
        # Step 6: Get tutor utilities
        tutor_bin = self.tutor_utils()
        
        # Step 7: Get dockerize binary
        dockerize_bin = self.dockerize()
        
        # Step 8: Collect all artifacts
        container = self.collected(
            container,
            deployment_name=deployment_name,
            dockerize_bin=dockerize_bin,
            tutor_bin=tutor_bin,
            custom_settings=custom_settings,
            include_locales=include_locales,
        )
        
        # Step 9: Fetch and compile translations
        container = self.fetch_translations(
            container,
            translations_repository=translations_repo,
            translations_branch=translations_branch,
        )
        
        # Step 10: Build static assets
        container = self.build_static_assets(container, deployment_name=deployment_name)
        
        # Step 11: Finalize Docker image
        container = self.docker_image(container, deployment_name=deployment_name, release_name=release_name)
        
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
            repository: Repository name (e.g., mitodl/openedx-platform)
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
    async def build_codejail(
        self,
        release_name: str = "master",
        python_version: str | None = None,
        codejail_config: dagger.Directory | None = None,
    ) -> dagger.Container:
        """Build codejail service container
        
        The codejail service provides a sandboxed Python execution environment
        for Open edX. It runs student-submitted code in a secure container.
        
        Args:
            release_name: Open edX release name (e.g., master, sumac, redwood)
            python_version: Python version to use (defaults: master=3.12, others=3.11)
            codejail_config: Directory containing 01-sandbox sudoers file (defaults to ./codejail_config)
        
        Returns:
            Built codejail container
        """
        # Default to codejail_config directory if not provided
        if codejail_config is None:
            codejail_config = dag.current_module().source().directory("codejail_config")
        
        # Auto-detect Python version if not specified
        if python_version is None:
            python_version = "3.12" if release_name == "master" else "3.11"
        
        # Start with Python slim image
        container = (
            dag.container()
            .from_(f"python:{python_version}-slim-trixie")
            .with_exec(["bash", "-c", "echo 'shell configured'"], use_entrypoint=True)
            .with_env_variable("DEBIAN_FRONTEND", "noninteractive")
            .with_env_variable("DEBCONF_NONINTERACTIVE_SEEN", "true")
        )
        
        # Define codejail environment variables
        container = (
            container
            .with_env_variable("CODEJAIL_GROUP", "sandbox")
            .with_env_variable("CODEJAIL_SANDBOX_CALLER", "debian")
            .with_env_variable("CODEJAIL_USER", "sandbox")
            .with_env_variable("CODEJAIL_VENV", "/sandbox/venv")
            .with_env_variable("OPEN_EDX_RELEASE", release_name)
            .with_env_variable("OPEN_EDX_BRANCH", release_name)
        )
        
        # Install system dependencies and create users
        container = (
            container
            .with_exec([
                "apt-get", "update"
            ])
            .with_exec([
                "apt", "install", "-y", "--no-install-recommends",
                "build-essential", "python3-virtualenv", "python3-pip",
                "git", "sudo", "libxslt-dev"
            ])
            .with_exec(["apt", "clean"])
            .with_exec(["rm", "-rf", "/var/lib/apt/lists/*"])
        )
        
        # Create virtualenv
        container = container.with_exec([
            "virtualenv", "-p", f"python{python_version}",
            "--always-copy", "/sandbox/venv"
        ])
        
        # Create sandbox user and group
        container = (
            container
            .with_exec(["addgroup", "sandbox"])
            .with_exec([
                "adduser", "--disabled-login", "--disabled-password",
                "sandbox", "--ingroup", "sandbox"
            ])
            .with_exec(["addgroup", "debian"])
            .with_exec([
                "adduser", "--disabled-login", "--disabled-password",
                "debian", "--ingroup", "debian"
            ])
            .with_exec(["chown", "-R", "sandbox:sandbox", "/sandbox/venv"])
        )
        
        # Update PATH to use virtualenv
        container = container.with_env_variable(
            "PATH",
            "/sandbox/venv/bin:/usr/local/bin:/usr/bin:/bin"
        )
        
        # Clone codejail service
        container = (
            container
            .with_workdir("/codejail")
            .with_exec([
                "git", "clone",
                "https://github.com/eduNEXT/codejailservice/",
                "--branch", "main", "--depth", "1",
                "/codejail"
            ])
        )
        
        # Copy sudoers configuration
        sudoers_file = codejail_config.file("01-sandbox")
        container = container.with_file("/etc/sudoers.d/01-sandbox", sudoers_file)
        
        # Install dependencies
        container = (
            container
            .with_exec([
                "pip", "install", "--no-cache-dir",
                "-r", "requirements/base.txt"
            ])
            .with_exec([
                "pip", "install", "--no-cache-dir", "gunicorn"
            ])
        )
        
        # Install edx-platform sandbox requirements in virtualenv
        # The URL pattern differs based on whether it's a release or master
        sandbox_req_url = (
            f"https://raw.githubusercontent.com/openedx/edx-platform/master/requirements/edx-sandbox/releases/{release_name}.txt"
            if release_name != "master"
            else "https://raw.githubusercontent.com/openedx/edx-platform/master/requirements/edx-sandbox/base.txt"
        )
        
        container = (
            container
            .with_exec([
                "bash", "-c",
                f"source /sandbox/venv/bin/activate && "
                f"pip install --no-cache-dir -r {sandbox_req_url} && "
                f"deactivate"
            ])
        )
        
        # Set permissions and ownership
        container = (
            container
            .with_exec(["chmod", "0440", "/etc/sudoers.d/01-sandbox"])
            .with_exec(["chown", "-R", "debian:debian", "/codejail"])
        )
        
        # Switch to debian user
        container = container.with_user("debian")
        
        # Set entrypoint
        container = container.with_entrypoint([
            "gunicorn", "-b", "0.0.0.0:8000",
            "--workers", "2", "--max-requests=1000",
            "wsgi"
        ])
        
        return container
    
    @function
    async def build_notes(
        self,
        release_name: str = "master",
        python_version: str = "3.11",
        notes_config: dagger.Directory | None = None,
    ) -> dagger.Container:
        """Build edx-notes-api service container
        
        The edx-notes-api service provides student annotation functionality
        for Open edX courses.
        
        Args:
            release_name: Git branch/tag to use (e.g., master, open-release/sumac.master)
            python_version: Python version to use (default: 3.11)
            notes_config: Directory containing env_config.py (defaults to ./notes_config)
        
        Returns:
            Built edx-notes container
        """
        # Default to notes_config directory if not provided
        if notes_config is None:
            notes_config = dag.current_module().source().directory("notes_config")
        # Start with Python slim image
        container = (
            dag.container()
            .from_(f"python:{python_version}-slim")
        )
        
        # Install system dependencies
        container = (
            container
            .with_exec(["apt", "update"])
            .with_exec([
                "apt", "install", "-y",
                "git", "mariadb-client", "default-libmysqlclient-dev",
                "build-essential", "pkg-config"
            ])
            .with_exec(["apt", "clean"])
        )
        
        # Create app user
        container = (
            container
            .with_exec([
                "useradd", "--home-dir", "/app", "--create-home",
                "--shell", "/bin/bash", "--uid", "1000", "app"
            ])
            .with_user("1000")
        )
        
        # Set working directory and PATH
        container = (
            container
            .with_workdir("/app/edx-notes-api")
            .with_env_variable("PATH", "/app/.local/bin:/usr/local/bin:/usr/bin:/bin")
        )
        
        # Clone edx-notes-api
        container = container.with_exec([
            "git", "clone",
            "https://github.com/edx/edx-notes-api",
            "--branch", release_name, "--depth", "1",
            "/app/edx-notes-api"
        ])
        
        # Install Python dependencies
        container = container.with_exec([
            "pip", "install", "--no-cache-dir",
            "-r", "requirements/base.txt"
        ])
        
        # Copy custom env_config.py settings module
        env_config = notes_config.file("env_config.py")
        container = container.with_file(
            "/app/edx-notes-api/notesserver/settings/env_config.py",
            env_config
        )
        
        # Set environment variables
        container = (
            container
            .with_env_variable("APP_PORT", "8000")
            .with_exposed_port(8000)
        )
        
        # Set entrypoint
        container = container.with_entrypoint([
            "gunicorn",
            "--workers=2",
            "--name", "notes",
            "--bind=0.0.0.0:8000",
            "--max-requests=1000",
            "notesserver.wsgi:application"
        ])
        
        return container
    
    @function
    async def build_mfe(
        self,
        mfe_name: str,
        mfe_repo: str,
        mfe_branch: str = "master",
        node_version: str = "20.18.0",
        deployment_name: str = "mitxonline",
        slot_config: dagger.Directory | None = None,
        enable_smoot_design: bool = False,
        enable_ai_drawer: bool = False,
        styles_file: str | None = None,
    ) -> dagger.Directory:
        """Build an Open edX Micro Frontend (MFE)
        
        Args:
            mfe_name: MFE application name (e.g., 'learning', 'discussions', 'account')
            mfe_repo: Git repository URL for the MFE
            mfe_branch: Git branch to build from (default: master)
            node_version: Node.js version to use (default: 20.18.0)
            deployment_name: Deployment name (e.g., 'mitxonline', 'mitx')
            slot_config: Directory containing slot configuration files
            enable_smoot_design: Enable smoot-design bundle (for learning MFE)
            enable_ai_drawer: Enable AI drawer components (for learning MFE)
            styles_file: Deployment-specific styles file to include
        
        Returns:
            Directory containing built MFE dist files
        
        Note:
            Set environment variables using with_env_variable() on the returned container.
            For example:
              dir = await build_mfe(...).with_env_variable("LMS_BASE_URL", "...").directory("/app/mfe/dist")
        """
        if slot_config is None:
            slot_config = dag.current_module().source().directory("mfe_slot_config")
        
        # Start with Node.js base image
        container = (
            dag.container()
            .from_(f"node:{node_version}-trixie-slim")
        )
        
        # Install system dependencies
        container = (
            container
            .with_exec(["apt-get", "update"])
            .with_exec([
                "apt", "install", "-y", "python3", "python-is-python3",
                "build-essential", "git"
            ])
            .with_exec(["apt", "clean"])
        )
        
        # Clone MFE repository
        container = (
            container
            .with_workdir("/app")
            .with_exec([
                "git", "clone",
                "--branch", mfe_branch,
                "--depth", "1",
                mfe_repo,
                "mfe"
            ])
            .with_workdir("/app/mfe")
        )
        
        # Determine config file to use
        is_learning_mfe = mfe_name.lower() == "learning"
        config_file = "learning-mfe-config" if is_learning_mfe else f"{deployment_name}/common-mfe-config"
        
        # Copy Footer.jsx
        footer_file = slot_config.file("Footer.jsx")
        container = container.with_file("/app/mfe/Footer.jsx", footer_file)
        
        # Copy env.config.jsx
        env_config_file = slot_config.file(f"{config_file}.env.jsx")
        container = container.with_file("/app/mfe/env.config.jsx", env_config_file)
        
        # For learning MFE, copy common-mfe-config.env.jsx
        if is_learning_mfe:
            common_config_file = slot_config.file(f"{deployment_name}/common-mfe-config.env.jsx")
            container = container.with_file("/app/mfe/common-mfe-config.env.jsx", common_config_file)
        
        # Copy AI drawer components if enabled
        if enable_ai_drawer and is_learning_mfe:
            ai_drawer_sidebar = slot_config.file("AIDrawerManagerSidebar.jsx")
            container = container.with_file("/app/mfe/AIDrawerManagerSidebar.jsx", ai_drawer_sidebar)
            
            sidebar_coordinator = slot_config.file("SidebarAIDrawerCoordinator.jsx")
            container = container.with_file("/app/mfe/SidebarAIDrawerCoordinator.jsx", sidebar_coordinator)
        
        # Copy styles file if specified
        if styles_file:
            styles = slot_config.file(styles_file)
            container = container.with_file(f"/app/mfe/{styles_file}", styles)
        
        # Install npm dependencies
        container = container.with_exec(["npm", "install"])
        
        # Install openedx-atlas for translations
        container = container.with_exec(["npm", "install", "-g", "@edx/openedx-atlas"])
        
        # Handle smoot-design for learning MFE
        if enable_smoot_design and is_learning_mfe:
            container = (
                container
                .with_exec(["npm", "pack", "@mitodl/smoot-design@^6.12.0"])
                .with_exec(["sh", "-c", "tar -xvzf mitodl-smoot-design*.tgz"])
                .with_exec(["mkdir", "-p", "public/static/smoot-design"])
                .with_exec(["sh", "-c", "cp package/dist/bundles/* public/static/smoot-design/"])
            )
        
        # Install webpack
        container = container.with_exec(["npm", "install", "webpack"])
        
        # Build the MFE
        container = (
            container
            .with_env_variable("NODE_ENV", "production")
            .with_exec(["npm", "run", "build"])
        )
        
        # Return the dist directory
        return container.directory("/app/mfe/dist")
    
    @function
    async def watch_mfe(
        self,
        mfe_source: dagger.Directory,
        slot_config: dagger.Directory | None = None,
        node_version: str = "20.18.0",
        deployment_name: str = "mitxonline",
        mfe_name: str = "learning",
        port: int = 8080,
    ) -> dagger.Service:
        """Run MFE dev server with hot reload for local testing
        
        This creates a watch container for testing slot config changes locally.
        
        Args:
            mfe_source: Directory containing MFE source code
            slot_config: Directory containing slot configuration files
            node_version: Node.js version to use (default: 20.18.0)
            deployment_name: Deployment name for config file selection
            mfe_name: MFE name (e.g., 'learning')
            port: Port to expose the dev server on (default: 8080)
        
        Returns:
            Service running the MFE dev server
        
        Note:
            Set environment variables using with_env_variable() before calling as_service().
            The service will automatically rebuild when slot config files change.
        """
        if slot_config is None:
            slot_config = dag.current_module().source().directory("mfe_slot_config")
        
        # Start with Node.js base image
        container = (
            dag.container()
            .from_(f"node:{node_version}-trixie-slim")
        )
        
        # Install system dependencies
        container = (
            container
            .with_exec(["apt-get", "update"])
            .with_exec([
                "apt", "install", "-y", "python3", "python-is-python3",
                "build-essential", "git"
            ])
            .with_exec(["apt", "clean"])
        )
        
        # Set up work directory and mount source
        container = (
            container
            .with_workdir("/app/mfe")
            .with_directory("/app/mfe", mfe_source)
        )
        
        # Determine config files
        is_learning_mfe = mfe_name.lower() == "learning"
        config_file = "learning-mfe-config" if is_learning_mfe else f"{deployment_name}/common-mfe-config"
        
        # Mount slot config files
        footer_file = slot_config.file("Footer.jsx")
        container = container.with_mounted_file("/app/mfe/Footer.jsx", footer_file)
        
        env_config_file = slot_config.file(f"{config_file}.env.jsx")
        container = container.with_mounted_file("/app/mfe/env.config.jsx", env_config_file)
        
        if is_learning_mfe:
            common_config_file = slot_config.file(f"{deployment_name}/common-mfe-config.env.jsx")
            container = container.with_mounted_file("/app/mfe/common-mfe-config.env.jsx", common_config_file)
        
        # Ensure PORT is set for the dev server
        container = container.with_env_variable("PORT", str(port))
        
        # Install dependencies if package-lock.json exists
        container = (
            container
            .with_exec(["npm", "install"])
            .with_exec(["npm", "install", "-g", "@edx/openedx-atlas"])
        )
        
        # Expose port and start dev server
        container = (
            container
            .with_exposed_port(port)
            .with_exec(["npm", "start"])
        )
        
        return container.as_service()
