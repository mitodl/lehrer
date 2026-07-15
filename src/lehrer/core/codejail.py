"""Generic codejail service build for Open edX operators."""

import dagger
from dagger import dag, function, object_type


@object_type
class OpenedxCodejail:
    """Build the codejail sandboxed execution service for Open edX.

    Usage::

        dagger call codejail build \\
          --release-name sumac \\
          --codejail-config ./my-operator/codejail_config
    """

    @function
    async def build(
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
            codejail_config: Directory containing 01-sandbox sudoers file


        Returns:
            Built codejail container
        """
        return await self._build(
            release_name=release_name,
            python_version=python_version,
            codejail_config=codejail_config,
        )

    async def _build(
        self,
        release_name: str = "master",
        python_version: str | None = None,
        codejail_config: dagger.Directory | None = None,
    ) -> dagger.Container:
        """Assemble the codejail container (shared by ``build`` and ``test``).

        Kept undecorated so other methods can ``await`` it: the ``@function``
        decorator's type erases the coroutine return, making a decorated
        ``build`` un-awaitable from within the module.
        """
        # Default to codejail_config directory if not provided
        if codejail_config is None:
            raise ValueError(
                "codejail_config is required — pass the directory containing the "
                "01-sandbox sudoers file (see your operator config) "
                "(e.g. --codejail-config /path/to/codejail_config)"
            )

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
            container.with_env_variable("CODEJAIL_GROUP", "sandbox")
            .with_env_variable("CODEJAIL_SANDBOX_CALLER", "debian")
            .with_env_variable("CODEJAIL_USER", "sandbox")
            .with_env_variable("CODEJAIL_VENV", "/sandbox/venv")
            .with_env_variable("OPEN_EDX_RELEASE", release_name)
            .with_env_variable("OPEN_EDX_BRANCH", release_name)
        )

        # Install system dependencies and create users
        container = (
            container.with_exec(["apt-get", "update"])
            .with_exec(
                [
                    "apt",
                    "install",
                    "-y",
                    "--no-install-recommends",
                    "build-essential",
                    "python3-virtualenv",
                    "python3-pip",
                    "git",
                    "sudo",
                    "libxslt-dev",
                ]
            )
            .with_exec(["apt", "clean"])
            .with_exec(["rm", "-rf", "/var/lib/apt/lists/*"])
        )

        # Create virtualenv
        container = container.with_exec(
            [
                "virtualenv",
                "-p",
                f"python{python_version}",
                "--always-copy",
                "/sandbox/venv",
            ]
        )

        # Create sandbox user and group
        container = (
            container.with_exec(["addgroup", "sandbox"])
            .with_exec(
                [
                    "adduser",
                    "--disabled-login",
                    "--disabled-password",
                    "sandbox",
                    "--ingroup",
                    "sandbox",
                ]
            )
            .with_exec(["addgroup", "debian"])
            .with_exec(
                [
                    "adduser",
                    "--disabled-login",
                    "--disabled-password",
                    "debian",
                    "--ingroup",
                    "debian",
                ]
            )
            .with_exec(["chown", "-R", "sandbox:sandbox", "/sandbox/venv"])
        )

        # Update PATH to use virtualenv
        container = container.with_env_variable(
            "PATH", "/sandbox/venv/bin:/usr/local/bin:/usr/bin:/bin"
        )

        # Clone codejail service
        container = container.with_workdir("/codejail").with_exec(
            [
                "git",
                "clone",
                "https://github.com/eduNEXT/codejailservice/",
                "--branch",
                "main",
                "--depth",
                "1",
                "/codejail",
            ]
        )

        # Copy sudoers configuration
        sudoers_file = codejail_config.file("01-sandbox")
        container = container.with_file("/etc/sudoers.d/01-sandbox", sudoers_file)

        # Install dependencies
        container = container.with_exec(
            ["pip", "install", "--no-cache-dir", "-r", "requirements/base.txt"]
        ).with_exec(["pip", "install", "--no-cache-dir", "gunicorn"])

        # Install edx-platform sandbox requirements in virtualenv
        # The URL pattern differs based on whether it's a release or master
        sandbox_req_url = (
            f"https://raw.githubusercontent.com/openedx/edx-platform/master/requirements/edx-sandbox/releases/{release_name}.txt"
            if release_name != "master"
            else "https://raw.githubusercontent.com/openedx/edx-platform/master/requirements/edx-sandbox/base.txt"
        )

        import shlex

        container = container.with_exec(
            [
                "bash",
                "-c",
                f"source /sandbox/venv/bin/activate && "
                f"pip install --no-cache-dir -r {shlex.quote(sandbox_req_url)} && "
                f"deactivate",
            ]
        )

        # Set permissions and ownership
        container = container.with_exec(
            ["chmod", "0440", "/etc/sudoers.d/01-sandbox"]
        ).with_exec(["chown", "-R", "debian:debian", "/codejail"])

        # Switch to debian user
        container = container.with_user("debian")

        # Set entrypoint
        container = container.with_entrypoint(
            [
                "gunicorn",
                "-b",
                "0.0.0.0:8000",
                "--workers",
                "2",
                "--max-requests=1000",
                "wsgi",
            ]
        )

        return container

    @function
    async def test(
        self,
        release_name: str = "master",
        python_version: str | None = None,
        codejail_config: dagger.Directory | None = None,
        test_paths: list[str] | None = None,
    ) -> str:
        """Run the codejailservice test suite inside the built image.

        The codejail suite is small, so it runs wholesale in the same container
        a build produces — verifying the service actually imports and passes its
        own tests under the release's pinned sandbox requirements, rather than
        only that the image assembles.

        Args:
            release_name: Open edX release name (e.g., master, sumac, redwood).
            python_version: Python version (defaults: master=3.12, others=3.11).
            codejail_config: Directory containing the 01-sandbox sudoers file.
            test_paths: pytest target paths (default: auto-discover from the repo
                root at ``/codejail``).

        Returns:
            The pytest stdout (a failing suite exits non-zero and fails the call).
        """
        container = await self._build(
            release_name=release_name,
            python_version=python_version,
            codejail_config=codejail_config,
        )
        return await (
            container.with_user("root")
            .with_workdir("/codejail")
            .with_exec(
                [
                    "sh",
                    "-c",
                    "if [ -f requirements/test.txt ]; then "
                    "pip install --no-cache-dir -r requirements/test.txt; "
                    "else pip install --no-cache-dir pytest; fi",
                ]
            )
            .with_exec(["python", "-m", "pytest", *(test_paths or [])])
            .stdout()
        )
