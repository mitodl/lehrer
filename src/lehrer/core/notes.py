"""Generic edx-notes-api service build for Open edX operators."""

import dagger
from dagger import dag, function, object_type


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

        # Set working directory and PATH
        container = container.with_workdir("/app/edx-notes-api").with_env_variable(
            "PATH", "/app/.local/bin:/usr/local/bin:/usr/bin:/bin"
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

        # Install Python dependencies as root (system site-packages), then fix ownership
        container = (
            container.with_exec(
                ["pip", "install", "--no-cache-dir", "-r", "requirements/base.txt"]
            )
            .with_exec(["chown", "-R", "app:app", "/app"])
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
