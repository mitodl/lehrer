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
        
        return (
            dag.container()
            .from_(f"python:{python_version}-bookworm")
            .with_env_variable("DEBIAN_FRONTEND", "noninteractive")
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
            Container with edx-platform at /openedx/edx-platform
        """
        if source is not None:
            return container.with_mounted_directory("/openedx/edx-platform", source)
        
        if not edx_platform_git_repo or not edx_platform_git_branch:
            raise ValueError("Must provide either source or both edx_platform_git_repo and edx_platform_git_branch")
        
        return (
            container
            .with_exec([
                "git", "clone", "--depth", "1", "--branch", edx_platform_git_branch,
                edx_platform_git_repo, "/openedx/edx-platform"
            ])
        )

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
        """Install Python and Node.js dependencies
        
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
            # Install base Python dependencies
            .with_exec([
                "pip", "install", "--no-warn-script-location", "--user", "--no-cache-dir",
                "-r", "/root/pip_package_lists/edx_base.txt",
                "-r", "/root/pip_package_lists/edx_assets.txt",
                "-r", f"/root/pip_package_lists/{release_name}/{deployment_name}.txt"
            ])
        )
        
        # Special handling for mitxonline
        if deployment_name == "mitxonline":
            container = container.with_exec(["pip", "uninstall", "--yes", "edx-name-affirmation"])
        
        # Fix lxml/xmlsec compatibility issues
        container = (
            container
            .with_exec(["pip", "uninstall", "--yes", "lxml", "xmlsec"])
            .with_exec([
                "pip", "install", "--no-warn-script-location", "--user", "--no-cache-dir",
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
            .with_env_variable("PATH", "/root/.local/bin:/openedx/nodeenv/bin:/usr/local/bin:/usr/bin:/bin")
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
        container: dagger.Container,
        tutor_version: str = "v19.0.0",
    ) -> dagger.Container:
        """Get utility scripts from Tutor
        
        Args:
            container: Base container
            tutor_version: Tutor version tag (default: v19.0.0)
        
        Returns:
            Container with tutor utils at /openedx/bin
        """
        return (
            container
            .with_exec([
                "git", "clone", "--depth", "1", "--branch", tutor_version,
                "https://github.com/overhangio/tutor.git", "/openedx/tutor"
            ])
        )

    @function
    def collected(
        self,
        container: dagger.Container,
        deployment_name: str,
        dockerize_bin: dagger.File,
        custom_settings: dagger.Directory,
        app_user_id: int = 1000,
        include_locales: bool = True,
    ) -> dagger.Container:
        """Assemble all artifacts and configure the container
        
        Args:
            container: Container with installed dependencies
            deployment_name: Deployment name
            dockerize_bin: Dockerize binary file
            custom_settings: Directory with custom settings and config files
            app_user_id: User ID for app user (default: 1000)
            include_locales: Include locale files (default: True)
        
        Returns:
            Container with all artifacts collected and configured
        """
        if app_user_id == 0:
            raise ValueError("app user may not be root")
        
        # Create app user
        container = (
            container
            .with_exec([
                "useradd", "--home-dir", "/openedx", "--create-home",
                "--shell", "/bin/bash", "--uid", str(app_user_id), "app"
            ])
            .with_user(str(app_user_id))
            .with_mounted_file("/usr/local/bin/dockerize", dockerize_bin)
        )
        
        # Set up PATH
        container = container.with_env_variable(
            "PATH",
            "/openedx/.local/bin:/openedx/bin:/openedx/edx-platform/node_modules/.bin:/openedx/nodeenv/bin:/usr/local/bin:/usr/bin:/bin"
        )
        
        # Make bin directory executable
        container = container.with_exec(["chmod", "-R", "a+x", "/openedx/bin"])
        
        # Install edx-platform in editable mode
        container = (
            container
            .with_workdir("/openedx/edx-platform")
            .with_exec(["pip", "install", "--no-warn-script-location", "--user", "--no-cache-dir", "-e", "."])
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
            .with_exec(["cp", "/tmp/custom_settings/lms_settings.py", "/openedx/edx-platform/lms/envs/lms_settings.py"])
            .with_exec(["cp", "/tmp/custom_settings/cms_settings.py", "/openedx/edx-platform/cms/envs/cms_settings.py"])
            .with_exec(["cp", "/tmp/custom_settings/models.py", "/openedx/edx-platform/openedx/core/djangoapps/settings/models.py"])
            .with_exec(["cp", "/tmp/custom_settings/utils.py", "/openedx/edx-platform/openedx/core/djangoapps/settings/utils.py"])
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
        # Install additional editable dependencies
        container = (
            container
            .with_exec([
                "pip", "install", "--no-warn-script-location", "--user", "--no-cache-dir", "-e",
                "git+https://github.com/openedx/codejail.git@babbe784b48bb9888aa159d8b401cbe5e07f0af4#egg=codejail"
            ])
            .with_exec([
                "pip", "install", "--no-warn-script-location", "--user", "--no-cache-dir", "-e",
                "git+https://github.com/openedx/django-wiki.git@0a1d555a1fa2834cc46367968aad907a5667317b#egg=django_wiki"
            ])
            .with_exec([
                "pip", "install", "--no-warn-script-location", "--user", "--no-cache-dir", "-e",
                "git+https://github.com/openedx/olxcleaner.git@2f0d6c7f126cbd69c9724b7b57a0b2565330a297#egg=olxcleaner"
            ])
        )
        
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
            .with_exec(["python", "-m", "compileall", "-q", "/openedx/edx-platform", "/openedx/.local"])
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
        python_version: str = "3.11",
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
            release_name: Release name (e.g., sumac, redwood)
            pip_package_lists: Directory with pip requirements files
            pip_package_overrides: Directory with pip override requirements
            custom_settings: Directory with custom settings files
            source: Local edx-platform source (optional)
            platform_repo: Git repo URL (used if source not provided)
            platform_branch: Git branch (used if source not provided)
            theme_source: Local theme source (optional)
            theme_repo: Theme git repo URL (optional)
            theme_branch: Theme git branch (optional)
            python_version: Python version (default: 3.11)
            node_version: Node.js version (default: 20.18.0)
            locale_version: openedx-i18n version (default: master, repo is archived)
            translations_repo: Translations repo (default: mitodl/mitxonline-translations)
            translations_branch: Translations branch (default: main)
            include_locales: Include locale files (default: True)
        
        Returns:
            Container ready to be deployed
        """
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
        container = self.tutor_utils(container)
        
        # Step 7: Get dockerize binary
        dockerize_bin = self.dockerize()
        
        # Step 8: Collect all artifacts
        container = self.collected(
            container,
            deployment_name=deployment_name,
            dockerize_bin=dockerize_bin,
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
