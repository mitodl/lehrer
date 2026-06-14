"""``lehrer dev`` — manage the local k3d-based Open edX dev environment.

This sub-app replaces the old ``local-dev/scripts/{check-deps,setup,teardown}.sh``
shell scripts.  The cluster lifecycle is:

    lehrer dev setup       # create the k3d cluster + bootstrap secrets (once)
    lehrer dev start       # tilt up — build & deploy the services
    lehrer dev stop        # tilt down — remove deployed resources, keep cluster
    lehrer dev teardown    # delete the cluster and all local state
"""

from __future__ import annotations

import glob
import json
import os
import shutil
from pathlib import Path
from typing import Literal

import cyclopts

from lehrer.cli import _paths
from lehrer.cli._proc import capture, have, pipe, run

app = cyclopts.App(
    name="dev",
    help="Manage the local k3d Open edX development environment.",
)

CLUSTER = "lehrer-dev"
CONTEXT = "k3d-lehrer-dev"
NAMESPACE = "openedx"

# Required tooling: (command, recommended minimum version, version flag).
_DEPENDENCIES: tuple[tuple[str, str, str], ...] = (
    ("k3d", "5.0", "version"),
    ("kubectl", "1.26", "version"),
    ("tilt", "0.33", "version"),
    ("helm", "3.12", "version"),
    ("dagger", "0.9", "version"),
    ("docker", "24.0", "--version"),
)

# Helm repositories needed to install the in-cluster infra operators.
_HELM_REPOS: tuple[tuple[str, str], ...] = (
    ("opensearch-helm", "https://opensearch-project.github.io/helm-charts"),
    ("mariadb", "https://helm.mariadb.com/mariadb-operator"),
    ("mongodb", "https://mongodb.github.io/helm-charts"),
    ("valkey", "https://valkey.io/valkey-helm/"),
)

# Safe local-dev secret defaults; override via the matching environment vars.
_SECRET_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("MYSQL_ROOT_PASSWORD", "openedx-dev"),
    ("MYSQL_PASSWORD", "openedx-dev"),
    ("DJANGO_SECRET_KEY", "insecure-local-dev-key-change-for-staging"),
    ("MONGO_PASSWORD", "openedx-dev"),
    ("NOTES_OAUTH_CLIENT_ID", "notes"),
    ("NOTES_OAUTH_CLIENT_SECRET", "notes-dev-secret"),
)


ClusterState = Literal["absent", "stopped", "running"]


def _cluster_state() -> ClusterState:
    """Return whether the lehrer-dev cluster is absent, stopped, or running.

    k3d clusters persist across reboots in a stopped state, so "exists" is not
    the same as "running": a stopped cluster has zero servers running.
    """
    out = capture("k3d", "cluster", "list", "-o", "json", check=False)
    try:
        clusters = json.loads(out or "[]")
    except json.JSONDecodeError:
        return "absent"
    for cluster in clusters:
        if cluster.get("name") == CLUSTER:
            return "running" if cluster.get("serversRunning", 0) else "stopped"
    return "absent"


def _current_context() -> str:
    return capture("kubectl", "config", "current-context", check=False) or "(none)"


@app.command(name="check")
def check_deps() -> None:
    """Verify that all required CLI tools are installed."""
    missing = 0
    for cmd, minimum, flag in _DEPENDENCIES:
        if not have(cmd):
            print(f"MISSING: {cmd} (recommended >= {minimum})")
            missing += 1
            continue
        version = capture(cmd, flag, check=False).splitlines()
        first = version[0] if version else "installed"
        print(f"OK:      {cmd} — {first}")

    if missing:
        raise SystemExit(
            f"\n{missing} missing dependency/ies. Install them before "
            "`lehrer dev setup`."
        )
    print("\nAll dependencies present.")


@app.command
def setup() -> None:
    """Create the k3d cluster, namespace, helm repos, and bootstrap secrets.

    Idempotent: safe to re-run. Reads secret values from the environment
    (``MYSQL_ROOT_PASSWORD``, ``DJANGO_SECRET_KEY``, ...) falling back to
    local-dev defaults.
    """
    check_deps()

    state = _cluster_state()
    if state == "running":
        print(f"==> Cluster {CLUSTER} already running — skipping creation.")
    elif state == "stopped":
        print(f"==> Cluster {CLUSTER} exists but is stopped — starting it.")
        run("k3d", "cluster", "start", CLUSTER)
    else:
        run("k3d", "cluster", "create", "--config", str(_paths.k3d_config()))

    run("kubectl", "config", "use-context", CONTEXT)
    run(
        "kubectl",
        "wait",
        "--for=condition=Ready",
        "nodes",
        "--all",
        "--timeout=120s",
    )

    run("kubectl", "apply", "-f", str(_paths.namespace_manifest()))

    print("==> Adding Helm repositories...")
    for name, url in _HELM_REPOS:
        run("helm", "repo", "add", name, url, check=False)
    run("helm", "repo", "update")

    print("==> Creating openedx-secrets Secret...")
    secret_args = [
        f"--from-literal={key}={os.environ.get(key, default)}"
        for key, default in _SECRET_DEFAULTS
    ]
    # DB_PASSWORD mirrors MYSQL_PASSWORD (kept in sync with the old setup.sh).
    secret_args.append(
        f"--from-literal=DB_PASSWORD={os.environ.get('MYSQL_PASSWORD', 'openedx-dev')}"
    )
    pipe(
        [
            "kubectl",
            "-n",
            NAMESPACE,
            "create",
            "secret",
            "generic",
            "openedx-secrets",
            *secret_args,
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        ["kubectl", "apply", "-f", "-"],
    )

    local_dev = _paths.local_dev_dir()
    print(
        "\n==> Setup complete!\n\n"
        "Start the dev environment with:\n"
        "    lehrer dev start\n\n"
        "Use a custom deployment config:\n"
        f"    lehrer dev start --deployment-config {local_dev}/../deployments/mit-ol\n\n"
        "Tear down with:\n"
        "    lehrer dev teardown"
    )


@app.command(name="start")
def start(
    *,
    deployment_config: str | None = None,
    release_name: str | None = None,
    deployment_name: str | None = None,
    settings_namespace: str | None = None,
    mfe_hot_reload: bool = False,
    stream: bool = False,
) -> None:
    """Start the dev environment (``tilt up``).

    Parameters
    ----------
    deployment_config
        Path to a deployment config directory (default: the generic config).
    release_name
        Open edX release name (matches a ``pip_package_lists`` subdir).
    deployment_name
        Deployment name (matches a ``pip_package_lists`` filename).
    settings_namespace
        Django settings namespace for the assets/i18n modules.
    mfe_hot_reload
        Also start the ``watch_site`` hot-reload dev servers for the MFEs.
    stream
        Stream Tilt logs to the terminal instead of only the web UI.
    """
    tilt_args: list[str] = []
    if deployment_config is not None:
        # Resolve to an absolute path relative to the current working directory
        # so the value is unambiguous no matter where `lehrer` is invoked from
        # (the Tiltfile otherwise resolves it relative to Tilt's own cwd).
        resolved = Path(deployment_config).resolve()
        tilt_args += ["--deployment-config", str(resolved)]
    if release_name is not None:
        tilt_args += ["--release-name", release_name]
    if deployment_name is not None:
        tilt_args += ["--deployment-name", deployment_name]
    if settings_namespace is not None:
        tilt_args += ["--settings-namespace", settings_namespace]
    if mfe_hot_reload:
        tilt_args += ["--mfe-hot-reload"]

    cmd = ["tilt", "up", "--file", str(_paths.tiltfile())]
    if stream:
        cmd += ["--stream"]
    if tilt_args:
        cmd += ["--", *tilt_args]
    run(*cmd)


@app.command(name="stop")
def stop() -> None:
    """Stop the dev environment (``tilt down``), keeping the cluster intact."""
    run("tilt", "down", "--file", str(_paths.tiltfile()), check=False)


@app.command
def teardown() -> None:
    """Delete the k3d cluster and clean up all local state."""
    print("==> Stopping Tilt (if running)...")
    run("tilt", "down", "--file", str(_paths.tiltfile()), check=False)

    print(f"==> Deleting k3d cluster {CLUSTER}...")
    run("k3d", "cluster", "delete", CLUSTER, check=False)

    print("==> Removing kubeconfig entries...")
    run("kubectl", "config", "delete-context", CONTEXT, check=False, echo=False)
    run("kubectl", "config", "delete-cluster", CONTEXT, check=False, echo=False)
    run(
        "kubectl",
        "config",
        "delete-user",
        f"admin@{CONTEXT}",
        check=False,
        echo=False,
    )

    print("==> Removing Helm repositories...")
    for name, _ in _HELM_REPOS:
        run("helm", "repo", "remove", name, check=False, echo=False)

    print("==> Cleaning up temp build artifacts...")
    _clean_temp_artifacts()

    print("==> Done. Run `lehrer dev setup` to create a fresh environment.")


def _clean_temp_artifacts() -> None:
    shutil.rmtree("/tmp/lehrer-mfe-dist", ignore_errors=True)  # noqa: S108
    for pattern in (
        "/tmp/lehrer-platform-*.tar",  # noqa: S108
        "/tmp/lehrer-codejail-*.tar",  # noqa: S108
        "/tmp/lehrer-notes-*.tar",  # noqa: S108
    ):
        for path in glob.glob(pattern):
            Path(path).unlink(missing_ok=True)


@app.command
def status() -> None:
    """Show the state of the local dev cluster."""
    state = _cluster_state()
    print(f"Cluster {CLUSTER}: {state}")

    if state == "absent":
        print("Run `lehrer dev setup` to create it.")
        return
    if state == "stopped":
        print("Run `lehrer dev setup` to start it.")
        return

    print(f"kubectl context: {_current_context()}")
    print()
    run(
        "kubectl",
        "--context",
        CONTEXT,
        "-n",
        NAMESPACE,
        "get",
        "pods",
        check=False,
    )
