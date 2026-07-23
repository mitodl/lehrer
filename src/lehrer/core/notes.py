"""Generic edx-notes-api service build for Open edX operators."""

import dagger
from dagger import dag, function, object_type

from lehrer.core.pip_compile_bridge import python_deps_install_script


@object_type
class OpenedxNotes:
    """Build the edx-notes-api annotation service for Open edX.

    Usage::

        dagger call notes build \\
          --release-name open-release/sumac.master \\
          --notes-repo https://github.com/openedx/edx-notes-api \\
          --notes-config ./my-operator/notes_config
    """

    @function
    async def build(
        self,
        release_name: str = "master",
        python_version: str = "3.11",
        notes_code: dagger.Directory | None = None,
        notes_repo: str | None = None,
        notes_config: dagger.Directory | None = None,
    ) -> dagger.Container:
        """Build edx-notes-api service container

        The edx-notes-api service provides student annotation functionality
        for Open edX courses.

        Args:
            release_name: Git branch/tag to use (e.g., master, open-release/sumac.master)
            python_version: Python version to use (default: 3.11)
            notes_code: Local directory with edx-notes-api source (optional)
            notes_repo: Git repository URL (required if notes_code not provided)
            notes_config: Directory containing env_config.py (defaults to


        Returns:
            Built edx-notes container
        """
        return await self._build(
            release_name=release_name,
            python_version=python_version,
            notes_code=notes_code,
            notes_repo=notes_repo,
            notes_config=notes_config,
        )

    async def _build(
        self,
        release_name: str = "master",
        python_version: str = "3.11",
        notes_code: dagger.Directory | None = None,
        notes_repo: str | None = None,
        notes_config: dagger.Directory | None = None,
    ) -> dagger.Container:
        """Assemble the edx-notes-api container (shared by ``build`` and ``test``).

        Kept undecorated so other methods can ``await`` it: the ``@function``
        decorator's type erases the coroutine return, making a decorated
        ``build`` un-awaitable from within the module.
        """
        # Default to notes_config directory if not provided
        if notes_config is None:
            raise ValueError(
                "notes_config is required — pass the directory containing env_config.py "
                "for this build (see your operator config) "
                "(e.g. --notes-config /path/to/notes_config)"
            )
        # Start with Python slim image
        container = dag.container().from_(f"python:{python_version}-slim")

        # Install system dependencies
        container = (
            container.with_exec(["apt", "update"])
            .with_exec(
                [
                    "apt",
                    "install",
                    "-y",
                    "git",
                    "mariadb-client",
                    "default-libmysqlclient-dev",
                    "build-essential",
                    "pkg-config",
                ]
            )
            .with_exec(["apt", "clean"])
        )

        # Create app user
        container = container.with_exec(
            [
                "useradd",
                "--home-dir",
                "/app",
                "--create-home",
                "--shell",
                "/bin/bash",
                "--uid",
                "1000",
                "app",
            ]
        )

        # Set working directory and PATH. /opt/notes-venv holds the app's own
        # deps -- a real venv (not just system site-packages) is what
        # `uv sync --active` needs a target for, should edx-notes-api's own
        # requirements ever migrate to uv.lock. See python_deps_install_script.
        container = (
            container.with_workdir("/app/edx-notes-api")
            .with_exec(["python3", "-m", "venv", "/opt/notes-venv"])
            .with_env_variable(
                "PATH",
                "/opt/notes-venv/bin:/app/.local/bin:/usr/local/bin:/usr/bin:/bin",
            )
            .with_env_variable("VIRTUAL_ENV", "/opt/notes-venv")
        )

        # Get edx-notes-api source from local directory or Git
        if notes_code is not None:
            container = container.with_directory("/app/edx-notes-api", notes_code)
        elif notes_repo:
            container = container.with_exec(
                [
                    "git",
                    "clone",
                    notes_repo,
                    "--branch",
                    release_name,
                    "--depth",
                    "1",
                    "/app/edx-notes-api",
                ]
            )
        else:
            raise ValueError("Must provide either notes_code or notes_repo")

        # Install Python dependencies (uv sync against a uv.lock, or the
        # legacy pip-compile requirements/base.txt, whichever the checkout
        # has -- see python_deps_install_script), then fix ownership.
        container = (
            container.with_exec(
                [
                    "sh",
                    "-c",
                    python_deps_install_script(
                        workdir="/app/edx-notes-api",
                        legacy_requirements=["requirements/base.txt"],
                        ensure_uv=True,
                    ),
                ]
            )
            .with_exec(["chown", "-R", "app:app", "/app", "/opt/notes-venv"])
            .with_user("1000")
        )

        # Copy custom env_config.py settings module
        env_config = notes_config.file("env_config.py")
        container = container.with_file(
            "/app/edx-notes-api/notesserver/settings/env_config.py", env_config
        )

        # Set environment variables
        container = container.with_env_variable("APP_PORT", "8000").with_exposed_port(
            8000
        )

        # Set entrypoint
        container = container.with_entrypoint(
            [
                "gunicorn",
                "--workers=2",
                "--name",
                "notes",
                "--bind=0.0.0.0:8000",
                "--max-requests=1000",
                "notesserver.wsgi:application",
            ]
        )

        return container

    @function
    async def test(
        self,
        release_name: str = "master",
        python_version: str = "3.11",
        notes_code: dagger.Directory | None = None,
        notes_repo: str | None = None,
        notes_config: dagger.Directory | None = None,
        test_paths: list[str] | None = None,
        settings_module: str = "notesserver.settings.test",
        elasticsearch_image: str = "docker.io/elasticsearch:7.17.9",
    ) -> str:
        """Run the edx-notes-api test suite inside the built image.

        The notes suite is small and runs wholesale in the build container.
        edx-notes-api's test settings use sqlite for the database but require an
        Elasticsearch backend (``ELASTICSEARCH_URL``), so a single-node ES
        service is provisioned and wired in.

        Args:
            release_name: Git branch/tag (e.g., master, open-release/sumac.master).
            python_version: Python version (default: 3.11).
            notes_code: Local edx-notes-api source (optional).
            notes_repo: Git repository URL (required if notes_code not provided).
            notes_config: Directory containing env_config.py.
            test_paths: pytest target paths (default: auto-discover from the repo
                root at ``/app/edx-notes-api``).
            settings_module: Django settings module for the run
                (default: ``notesserver.settings.test``).
            elasticsearch_image: Elasticsearch image for the search service.

        Returns:
            The pytest stdout (a failing suite exits non-zero and fails the call).
        """
        container = await self._build(
            release_name=release_name,
            python_version=python_version,
            notes_code=notes_code,
            notes_repo=notes_repo,
            notes_config=notes_config,
        )
        elasticsearch = (
            dag.container()
            .from_(elasticsearch_image)
            .with_env_variable("discovery.type", "single-node")
            .with_env_variable("xpack.security.enabled", "false")
            .with_env_variable("ES_JAVA_OPTS", "-Xms512m -Xmx512m")
            .with_exposed_port(9200)
            .as_service(use_entrypoint=True)
        )
        # Install as root (system site-packages), then drop back to the
        # non-root `app` user the service actually runs as, so the suite runs
        # under the same permissions as production rather than masking
        # permission issues by running as root.
        return await (
            container.with_user("root")
            .with_workdir("/app/edx-notes-api")
            .with_exec(
                [
                    "sh",
                    "-c",
                    "if [ -f requirements/test.txt ]; then "
                    "pip install --no-cache-dir -r requirements/test.txt; "
                    "else pip install --no-cache-dir pytest pytest-django; fi",
                ]
            )
            .with_user("app")
            .with_service_binding("elasticsearch", elasticsearch)
            .with_env_variable("ELASTICSEARCH_URL", "elasticsearch:9200")
            .with_env_variable("DJANGO_SETTINGS_MODULE", settings_module)
            .with_exec(
                [
                    "python",
                    "-m",
                    "pytest",
                    *(test_paths if test_paths is not None else []),
                ]
            )
            .stdout()
        )
