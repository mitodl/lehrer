"""``lehrer dev`` — manage the local k3d-based Open edX dev environment.

This sub-app replaces the old ``local-dev/scripts/{check-deps,setup,teardown}.sh``
shell scripts.  The cluster lifecycle is:

    lehrer dev setup       # create the k3d cluster + bootstrap secrets (once)
    lehrer dev start       # tilt up — build & deploy the services
    lehrer dev stop        # tilt down — remove deployed resources, keep cluster
    lehrer dev teardown    # delete the cluster and all local state
"""

from __future__ import annotations

import base64
import glob
import json
import os
import re
import shutil
import socket
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import cyclopts

from lehrer.cli import _paths
from lehrer.cli._proc import capture, capture_result, have, pipe, run

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
    # Consumed by the edxapp-provision Job; the username and email it pairs
    # with live in job-provision.yaml, since neither is secret.
    ("PROVISION_SUPERUSER_PASSWORD", "edx"),
)

# Matches PROVISION_SUPERUSER_USERNAME in
# local-dev/manifests/platform/job-provision.yaml.
_SUPERUSER_USERNAME = "edx"


ClusterState = Literal["absent", "stopped", "partial", "running"]


def _cluster_state() -> ClusterState:
    """Classify the lehrer-dev cluster as absent, stopped, partial, or running.

    k3d clusters persist across reboots in a stopped state, so "exists" is not
    the same as "running". A failed ``k3d cluster start`` (e.g. a host-port
    clash on the loadbalancer) can also leave the cluster *partially* up — the
    server/agent containers running but the loadbalancer exited, which makes
    the API unreachable. We inspect every node's running flag so callers can
    tell a healthy cluster from a wedged one.
    """
    out = capture("k3d", "cluster", "list", "-o", "json", check=False)
    try:
        clusters = json.loads(out or "[]")
    except json.JSONDecodeError:
        return "absent"
    for cluster in clusters:
        if cluster.get("name") != CLUSTER:
            continue
        nodes = cluster.get("nodes") or []
        running = sum(1 for n in nodes if n.get("State", {}).get("Running"))
        if running == 0:
            return "stopped"
        if running == len(nodes):
            return "running"
        return "partial"
    return "absent"


def _current_context() -> str:
    return capture("kubectl", "config", "current-context", check=False) or "(none)"


def _required_host_ports() -> list[int]:
    """Host ports the k3d loadbalancer must bind, parsed from k3d-config.yaml.

    Lines look like ``- port: 8000:80`` — the host side is the first number.
    """
    text = _paths.k3d_config().read_text()
    ports: list[int] = []
    for match in re.finditer(r"port:\s*(\d+):\d+", text):
        ports.append(int(match.group(1)))
    return ports


def _port_in_use(port: int) -> bool:
    """Return ``True`` if ``0.0.0.0:port`` cannot be bound (k3d's binding)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))  # noqa: S104 - mirrors k3d's bind
        except OSError:
            return True
    return False


def _preflight_host_ports() -> None:
    """Abort with an actionable error if any required host port is taken.

    k3d's own failure for this is a wall of Docker networking text; catching it
    here turns it into a one-liner that names the port to free.
    """
    busy = [port for port in _required_host_ports() if _port_in_use(port)]
    if not busy:
        return
    ports = ", ".join(str(port) for port in busy)
    raise SystemExit(
        f"Host port(s) already in use: {ports}. The k3d loadbalancer needs "
        "them for the LMS/CMS/MFE/notes ingress.\n"
        f"Find the offender with:  ss -ltnp | grep -E ':({ports.replace(', ', '|')})'\n"
        "Then free the port(s) and re-run `lehrer dev setup`, or remap them in "
        "local-dev/k3d-config.yaml."
    )


def _warn_on_stale_mariadb_secret_ref() -> None:
    """Warn when an existing MariaDB CR predates the openedx-secrets root ref.

    ``spec.rootPasswordSecretKeyRef`` is immutable, so a cluster created before
    the CR pointed at ``openedx-secrets`` rejects the new manifest and Tilt
    fails the ``mysql`` resource with an admission error that says nothing
    about what to do. Recreating the CR drops the databases with it, so the
    call is the developer's, not ours.
    """
    ref = capture(
        "kubectl",
        "--context",
        CONTEXT,
        "-n",
        NAMESPACE,
        "get",
        "mariadb",
        "mysql",
        "-o",
        "jsonpath={.spec.rootPasswordSecretKeyRef.name}",
        check=False,
    )
    if not ref or ref == "openedx-secrets":
        return
    print(
        f"\n!!! The existing MariaDB CR reads its root password from '{ref}',\n"
        "    but the manifest now reads it from openedx-secrets, and the field\n"
        "    is immutable — `lehrer dev start` will fail on the mysql resource.\n"
        "    Recreate the instance (this drops the edxapp databases; the\n"
        "    migrate and provision Jobs rebuild them):\n"
        f"{_RECREATE_MARIADB}"
    )


# Deleting the CR alone is not enough. The operator has no MariaDB finalizer
# and the CR sets no pvcRetentionPolicy, so storage-mysql-0 is retained (the
# CRD's default is "retained until manually deleted"); the replacement mounts
# the same datadir, MariaDB skips initialization on a non-empty one, and both
# the databases and the *old* root password survive. Dropping the claim is
# what makes the promise above true.
#
# --context is not optional in commands this destructive: a kubeconfig usually
# carries real clusters too, and an unqualified delete lands on whichever one
# happens to be current.
_RECREATE_MARIADB = (
    f"        kubectl --context {CONTEXT} -n {NAMESPACE} delete mariadb mysql\n"
    f"        kubectl --context {CONTEXT} -n {NAMESPACE} delete pvc storage-mysql-0\n"
)


def _stored_secret_value(key: str) -> str:
    """Return ``key``'s current value in openedx-secrets, or "" if unset."""
    encoded = capture(
        "kubectl",
        "--context",
        CONTEXT,
        "-n",
        NAMESPACE,
        "get",
        "secret",
        "openedx-secrets",
        "-o",
        f"jsonpath={{.data.{key}}}",
        check=False,
    )
    if not encoded:
        return ""
    return base64.b64decode(encoded).decode()


def _mariadb_datadir_exists() -> bool:
    """Return ``True`` when MariaDB's PVC — and so its datadir — already exists."""
    return bool(
        capture(
            "kubectl",
            "--context",
            CONTEXT,
            "-n",
            NAMESPACE,
            "get",
            "pvc",
            "storage-mysql-0",
            "-o",
            "jsonpath={.metadata.name}",
            check=False,
        )
    )


def _warn_on_init_only_root_password(previous: str, current: str) -> None:
    """Warn when a changed MYSQL_ROOT_PASSWORD cannot reach an existing server.

    MariaDB sets root's password once, when it initializes an empty datadir,
    and nothing rotates it afterwards. Pointing the CR at openedx-secrets makes
    an override work on a *fresh* cluster but silently not on an initialized
    one: the Secret changes, the CR stays valid so no admission error fires,
    and the operator then authenticates as root with a value the server has
    never heard of — surfacing later as failed Grant/Database reconciliation
    that names no cause.
    """
    if not previous or previous == current or not _mariadb_datadir_exists():
        return
    print(
        "\n!!! MYSQL_ROOT_PASSWORD changed, but MariaDB only ever sets root's\n"
        "    password when it initializes an empty datadir — this cluster's is\n"
        "    already initialized, so the server keeps the old one while the\n"
        "    operator starts presenting the new one. Either put the previous\n"
        "    value back, or recreate the instance to re-initialize with it\n"
        "    (this drops the edxapp databases; the migrate and provision Jobs\n"
        "    rebuild them):\n"
        f"{_RECREATE_MARIADB}"
    )


# --- MariaDB schema-collation drift ------------------------------------------
#
# A schema's default collation is stored once, at CREATE DATABASE time, and
# never follows a later change to the server's collation-server setting. Any
# CREATE TABLE that omits an explicit COLLATE inherits whatever the schema was
# created with, so a schema on a stale default quietly accumulates tables on it.
# An FK between two tables on different collations is rejected with errno 150
# ("Foreign key constraint is incorrectly formed") — a migration failure that
# reads like a MariaDB bug and is actually schema metadata drift.
#
# Ported from ol-infrastructure's bin/mariadb-collation-guard, which diagnosed
# this in residential-production and residential-qa. That script reaches its
# instances by `kubectl exec`-ing an application pod holding DB credentials;
# here the server is one pod away, so we exec the MariaDB pod's own client
# instead. The safe-fix boundary carries over unchanged: schema-level ALTER
# DATABASE only, a metadata change that rewrites nothing, and never an
# automatic table conversion or index repair — both of those need a human
# weighing duplicate-row risk.

EXPECTED_CHARACTER_SET = "utf8mb4"
EXPECTED_COLLATION = "utf8mb4_unicode_ci"

# The schemas declared in local-dev/manifests/infra/mariadb.yaml.
_SCHEMAS = ("edxapp", "edxapp_csmh", "notes")

_MARIADB_POD = "mysql-0"

# Collations that are deliberate rather than drift. edx-platform keeps a set of
# columns on utf8mb4_bin for case-sensitive comparison (opaque-key fields,
# MultiCollationCharField, Django's JSONField), and those columns can carry a
# whole table's TABLE_COLLATION with them.
_INTENTIONAL_COLLATIONS = frozenset({"utf8mb4_bin"})

# Columns of a CHECK TABLE row: Table, Op, Msg_type, Msg_text.
_CHECK_TABLE_COLUMNS = 4


def _mysql(sql: str, *, timeout: str = "30s") -> str | None:
    """Run ``sql`` as root inside the MariaDB pod and return its stdout.

    ``None`` means the statement did not run — no password, the pod is
    unreachable, or the server rejected the SQL. That is deliberately distinct
    from ``""``, which is a statement that ran and matched nothing: reporting a
    schema as healthy because the query failed is exactly the way an audit tool
    lies to you.

    The password goes over stdin and is read by the shell before it invokes the
    client, so it never lands in an argv — not the one this process spawns, and
    not the one the container sees.
    """
    password = _stored_secret_value("MYSQL_ROOT_PASSWORD")
    if not password:
        return None
    returncode, out, err = capture_result(
        "kubectl",
        "--context",
        CONTEXT,
        "-n",
        NAMESPACE,
        f"--request-timeout={timeout}",
        "exec",
        "-i",
        _MARIADB_POD,
        "--",
        "sh",
        "-c",
        # IFS= keeps `read` from trimming whitespace off an overridden password.
        "IFS= read -r MYSQL_PWD; export MYSQL_PWD; "
        'exec mariadb -u root --batch --raw --skip-column-names -e "$1"',
        "sh",
        sql,
        input=f"{password}\n",
    )
    if returncode != 0:
        # stderr carries the server's own diagnosis, which beats anything this
        # function could infer from an exit code.
        if err:
            print(f"    {err}")
        return None
    return out


def _schema_defaults() -> dict[str, str] | None:
    """Map each present schema to its stored default collation.

    ``None`` if the query could not run; an empty mapping if it ran and no
    schema exists yet, which is a normal state on a cluster whose MariaDB is up
    before the operator has reconciled the Database resources.
    """
    names = ", ".join(f"'{name}'" for name in _SCHEMAS)
    out = _mysql(
        "SELECT SCHEMA_NAME, DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA "
        f"WHERE SCHEMA_NAME IN ({names})"
    )
    if out is None:
        return None
    defaults: dict[str, str] = {}
    for line in out.splitlines():
        schema, _, collation = line.partition("\t")
        if collation:
            defaults[schema] = collation
    return defaults


def _table_collations() -> dict[tuple[str, str], int]:
    """Count base tables per ``(schema, collation)`` pair."""
    names = ", ".join(f"'{name}'" for name in _SCHEMAS)
    out = _mysql(
        "SELECT TABLE_SCHEMA, TABLE_COLLATION, COUNT(*) FROM information_schema.TABLES "
        f"WHERE TABLE_SCHEMA IN ({names}) AND TABLE_TYPE = 'BASE TABLE' "
        "GROUP BY TABLE_SCHEMA, TABLE_COLLATION"
    )
    counts: dict[tuple[str, str], int] = {}
    for line in (out or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:  # noqa: PLR2004 - schema, collation, count
            counts[(parts[0], parts[1])] = int(parts[2])
    return counts


def _warn_on_uncollated_edxapp_database() -> None:
    """Warn when the operator got to ``mysql-database`` before the manifest did.

    ``characterSet`` and ``collate`` are both immutable, so a cluster whose
    Database was generated by the MariaDB reconciler (on the CRD's utf8
    defaults) rejects the manifest with an admission error naming a field and no
    remedy. Both are compared: the generated resource happens to differ in both,
    but a mismatch in either one alone is equally fatal and equally silent.

    Deleting the resource is safe now that it declares ``cleanupPolicy: Skip`` —
    but only the *replacement* carries that, so the existing one still has to go
    first, and its finalizer would drop edxapp on the way out.
    """
    declared = capture(
        "kubectl",
        "--context",
        CONTEXT,
        "-n",
        NAMESPACE,
        "get",
        "database",
        "mysql-database",
        "-o",
        'jsonpath={.spec.characterSet}{"\\t"}{.spec.collate}',
        check=False,
    )
    character_set, _, collate = declared.partition("\t")
    if not character_set:
        return
    # Both fields are immutable, so either one alone is enough to be rejected.
    if (character_set, collate) == (EXPECTED_CHARACTER_SET, EXPECTED_COLLATION):
        return
    print(
        f"\n!!! The edxapp Database resource declares '{character_set}' /\n"
        f"    '{collate}', but the manifest declares "
        f"'{EXPECTED_CHARACTER_SET}' / '{EXPECTED_COLLATION}' —\n"
        "    the operator generated it before the manifest did. Its characterSet\n"
        "    and collate are both immutable, so `lehrer dev start` will fail on\n"
        "    the mysql-database resource. Detach it from its finalizer first, or\n"
        "    deleting it drops edxapp:\n"
        f"        kubectl --context {CONTEXT} -n {NAMESPACE} patch database"
        " mysql-database \\\n"
        '            -p \'{"spec":{"cleanupPolicy":"Skip"}}\' --type=merge\n'
        f"        kubectl --context {CONTEXT} -n {NAMESPACE} delete database"
        " mysql-database\n"
        "    The schema survives, still on the old collation. `lehrer dev start`\n"
        "    then recreates the resource, and this realigns the default:\n"
        "        lehrer dev db-collation --fix"
    )


def _warn_on_schema_collation_drift() -> None:
    """Warn when an already-initialized datadir carries a drifted schema.

    Only reachable on an existing cluster: the manifests now pin every schema's
    collation at creation, so a datadir initialized after that is right by
    construction. One initialized before it keeps whatever it was created with,
    since the operator skips CREATE DATABASE for a schema that already exists.
    """
    if not _mariadb_datadir_exists():
        return
    defaults = _schema_defaults()
    if not defaults:
        return
    drifted = sorted(s for s, c in defaults.items() if c != EXPECTED_COLLATION)
    if not drifted:
        return
    print(
        f"\n!!! {', '.join(drifted)} — stored default collation is not\n"
        f"    {EXPECTED_COLLATION}. This datadir predates the collation pinned\n"
        "    in the MariaDB manifests, and a schema keeps the default it was\n"
        "    created with. Migrations that add a foreign key across the two\n"
        "    collations fail with errno 150. Realign with:\n"
        "        lehrer dev db-collation --fix"
    )


def mfe_dev_hostnames(deployment_config: Path) -> dict[str, str]:
    """Map each Site Project to the ``baseUrl`` hostname its dev server serves.

    Raises rather than returning a partial map. A check that quietly skips
    what it cannot parse reports success for sites it never looked at, which
    is worse than not running it — and a mistyped ``--deployment-config``
    would otherwise pass by matching nothing at all.
    """
    frontend = deployment_config / "mfe_slot_config" / "frontend"
    if not frontend.is_dir():
        raise SystemExit(f"No Site Projects found: {frontend} is not a directory.")

    configs = sorted(frontend.glob("*/site.config.dev.tsx"))
    if not configs:
        raise SystemExit(f"No site.config.dev.tsx under {frontend}.")

    hostnames: dict[str, str] = {}
    for config in configs:
        match = re.search(r'baseUrl:\s*"([^"]+)"', config.read_text())
        if match is None:
            raise SystemExit(f"No baseUrl in {config}.")
        host = urlsplit(match.group(1)).hostname
        if not host:
            raise SystemExit(f"baseUrl '{match.group(1)}' in {config} has no host.")
        hostnames[config.parent.name] = host
    return hostnames


def _check_mfe_hostnames(deployment_config: Path) -> int:
    """Report Site Project hostnames that do not resolve. Returns the count.

    mit-ol's dev configs use ``*.local.openedx.io``, which upstream Open edX
    publishes as a public wildcard A record pointing at 127.0.0.1 — so this
    normally needs no ``/etc/hosts`` entry and no setup at all. It does mean
    hot reload depends on public DNS: offline, or behind a resolver that
    filters or rewrites the name, it stops resolving and the dev server ends up
    running behind a name the browser cannot look up.
    """
    unresolved = 0
    for site, host in mfe_dev_hostnames(deployment_config).items():
        try:
            socket.gethostbyname(host)
        except OSError:
            print(f"MISSING: {host} (MFE site '{site}') does not resolve")
            unresolved += 1
        else:
            print(f"OK:      {host} — resolves (MFE site '{site}')")
    return unresolved


@app.command(name="check")
def check_deps(*, deployment_config: str | None = None) -> None:
    """Verify that all required CLI tools are installed.

    Parameters
    ----------
    deployment_config
        Also check that the MFE dev hostnames in this deployment config
        resolve. Skipped when omitted, since the hostnames are deployment
        specific and the generic config only uses localhost.
    """
    missing = 0
    for cmd, minimum, flag in _DEPENDENCIES:
        if not have(cmd):
            print(f"MISSING: {cmd} (recommended >= {minimum})")
            missing += 1
            continue
        version = capture(cmd, flag, check=False).splitlines()
        first = version[0] if version else "installed"
        print(f"OK:      {cmd} — {first}")

    unresolved = 0
    if deployment_config is not None:
        unresolved = _check_mfe_hostnames(Path(deployment_config).resolve())

    if missing:
        raise SystemExit(
            f"\n{missing} missing dependency/ies. Install them before "
            "`lehrer dev setup`."
        )
    if unresolved:
        raise SystemExit(
            f"\n{unresolved} MFE hostname(s) do not resolve. `lehrer dev start "
            "--mfe-hot-reload` will serve them, but nothing will be able to "
            "reach them.\n*.local.openedx.io normally resolves to 127.0.0.1 "
            "over public DNS, so this usually means you are offline or your "
            "resolver filters it; map the name to 127.0.0.1 in /etc/hosts to "
            "work without it."
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
        _preflight_host_ports()
        print(f"==> Cluster {CLUSTER} exists but is stopped — starting it.")
        run("k3d", "cluster", "start", CLUSTER)
    elif state == "partial":
        _preflight_host_ports()
        print(f"==> Cluster {CLUSTER} is partially up (a node exited) — restarting it.")
        run("k3d", "cluster", "start", CLUSTER)
    else:
        _preflight_host_ports()
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

    # Read before the Secret is overwritten: comparing the stored value with
    # the one about to replace it is what distinguishes a changed override from
    # a re-run with the same value.
    previous_root_password = _stored_secret_value("MYSQL_ROOT_PASSWORD")

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

    _warn_on_stale_mariadb_secret_ref()
    _warn_on_uncollated_edxapp_database()
    _warn_on_init_only_root_password(
        previous_root_password,
        os.environ.get("MYSQL_ROOT_PASSWORD", "openedx-dev"),
    )
    _warn_on_schema_collation_drift()

    local_dev = _paths.local_dev_dir()
    # Report where the credential came from, never the value — a custom one
    # would otherwise land in terminal scrollback and captured setup logs.
    # Only ever one of the two literals below; naming it for the secret it
    # deliberately does not hold also trips CodeQL's name heuristic.
    credential_origin = (
        "$PROVISION_SUPERUSER_PASSWORD"
        if "PROVISION_SUPERUSER_PASSWORD" in os.environ
        else "the local-dev default"
    )
    print(
        "\n==> Setup complete!\n\n"
        "Start the dev environment with:\n"
        "    lehrer dev start\n\n"
        "Use a custom deployment config:\n"
        f"    lehrer dev start --deployment-config {local_dev}/../deployments/mit-ol\n\n"
        "The edxapp-provision Job creates a superuser once the stack is up:\n"
        f"    username {_SUPERUSER_USERNAME}, password from {credential_origin}\n"
        "Import the demo course by triggering edxapp-demo-course in the Tilt UI\n"
        "(or `tilt trigger edxapp-demo-course`).\n\n"
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
        Open edX release name (matches a ``build_manifest.yaml`` cell).
    deployment_name
        Deployment name (matches a ``build_manifest.yaml`` cell).
    settings_namespace
        Django settings namespace for the assets/i18n modules.
    mfe_hot_reload
        Also start the ``watch_site`` hot-reload dev servers for the MFEs.
    stream
        Stream Tilt logs to the terminal instead of only the web UI.
    """
    # Also checked here, not just in setup(): setup is documented as a one-off,
    # so a developer who already has a cluster and pulls a manifest change
    # reaches Tilt through this command and would otherwise hit the raw
    # immutable-field admission error with no idea what to do about it.
    _warn_on_stale_mariadb_secret_ref()
    _warn_on_uncollated_edxapp_database()

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
    if state == "partial":
        print(
            "A node has exited (often a host-port clash on the loadbalancer); "
            "the API is likely unreachable. Run `lehrer dev setup` to restart "
            "it once the port is free."
        )
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


@app.command(name="db-collation")
def db_collation(*, fix: bool = False, check_tables: bool = False) -> None:
    """Audit MariaDB schema-collation drift, and optionally realign it.

    Parameters
    ----------
    fix
        Run ``ALTER DATABASE ... COLLATE`` on drifted schemas. Metadata only:
        existing tables keep the collation they were built with, so this fixes
        what the *next* CREATE TABLE inherits and rewrites no data.
    check_tables
        Also run ``CHECK TABLE ... QUICK`` over every base table. Slow against a
        populated edxapp, and reports only — repairing a corrupt unique index
        can delete the duplicate rows it was masking, so that stays manual.
    """
    if _cluster_state() != "running":
        print(f"Cluster {CLUSTER} is not running; start it with `lehrer dev setup`.")
        raise SystemExit(1)

    defaults = _schema_defaults()
    if defaults is None:
        print(
            f"Could not reach MariaDB in {NAMESPACE}/{_MARIADB_POD}. The pod may "
            "still be starting, or openedx-secrets may not hold "
            "MYSQL_ROOT_PASSWORD yet."
        )
        raise SystemExit(1)

    counts = _table_collations()
    drifted = sorted(s for s, c in defaults.items() if c != EXPECTED_COLLATION)

    print(f"Expected: {EXPECTED_CHARACTER_SET} / {EXPECTED_COLLATION}\n")
    for schema in _SCHEMAS:
        if schema not in defaults:
            print(f"{schema}: absent")
            continue
        print(
            f"{schema}: {defaults[schema]} [{'DRIFT' if schema in drifted else 'ok'}]"
        )
        for (owner, collation), count in sorted(counts.items()):
            if owner != schema:
                continue
            inherited = (
                collation != EXPECTED_COLLATION
                and collation not in _INTENTIONAL_COLLATIONS
            )
            note = "  <- inherited a drifted default" if inherited else ""
            print(f"    {count:>5} tables  {collation}{note}")

    if not drifted:
        print("\nNo schema-level drift.")
    elif not fix:
        print(
            f"\n{len(drifted)} schema(s) drifted. Re-run with --fix to realign the "
            "schema defaults."
        )
    else:
        print()
        failed = [schema for schema in drifted if not _alter_collation(schema)]
        if failed:
            print(
                f"\n{', '.join(failed)} could not be realigned — see the server "
                "error above.\nRe-run the audit to confirm what is still drifted."
            )
            raise SystemExit(1)
        print(
            "\nSchema defaults realigned, so new tables land on the right "
            "collation. Tables\nbuilt before this keep theirs, and converting "
            "them in place is the risky half of\nthe fix. On a dev cluster the "
            "cheap answer is to recreate the instance and let\nthe migrate and "
            f"provision Jobs rebuild the schema:\n{_RECREATE_MARIADB}"
        )

    if check_tables:
        _report_corrupt_tables(sorted(defaults))


def _alter_collation(schema: str) -> bool:
    """Realign one schema's default collation, reporting whether it took."""
    ran = (
        _mysql(
            f"ALTER DATABASE `{schema}` "
            f"CHARACTER SET {EXPECTED_CHARACTER_SET} COLLATE {EXPECTED_COLLATION}"
        )
        is not None
    )
    outcome = "->" if ran else "FAILED, still"
    print(f"ALTER DATABASE {schema} {outcome} {EXPECTED_COLLATION}")
    return ran


def _report_corrupt_tables(schemas: list[str]) -> None:
    """Run CHECK TABLE across ``schemas`` and print every row not marked OK.

    A query that fails is reported as a failure, never folded into the healthy
    case — "none reporting an error" has to mean the check ran.
    """
    print("\n==> CHECK TABLE (QUICK)")
    for schema in schemas:
        listing = _mysql(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            f"WHERE TABLE_SCHEMA = '{schema}' AND TABLE_TYPE = 'BASE TABLE'",
            timeout="60s",
        )
        if listing is None:
            print(f"{schema}: could not list tables; not checked")
            continue
        tables = [line.strip() for line in listing.splitlines() if line.strip()]
        if not tables:
            print(f"{schema}: no tables")
            continue
        problems: list[str] = []
        unchecked = 0
        # Chunked so one statement stays well inside max_allowed_packet, and so
        # a single unreadable table cannot take the whole scan down with it.
        for start in range(0, len(tables), 50):
            chunk = tables[start : start + 50]
            names = ", ".join(f"`{schema}`.`{table}`" for table in chunk)
            out = _mysql(f"CHECK TABLE {names} QUICK", timeout="300s")
            if out is None:
                unchecked += len(chunk)
                continue
            problems.extend(
                f"    {parts[0]}: {parts[2]} — {parts[3]}"
                for parts in (line.split("\t") for line in out.splitlines())
                if len(parts) == _CHECK_TABLE_COLUMNS and parts[2] != "status"
            )
        checked = len(tables) - unchecked
        if not problems:
            print(f"{schema}: {checked} tables, none reporting an error")
            if unchecked:
                print(f"    {unchecked} table(s) could not be checked; see above")
            continue
        print(f"{schema}: {len(problems)} problem(s) across {checked} checked tables")
        print("\n".join(problems))
        if unchecked:
            print(f"    {unchecked} further table(s) could not be checked")
        print(
            "    Reported only. Repairing a corrupt unique index can delete the "
            "duplicate rows\n    it was masking, so inspect them before running "
            "any REPAIR or ALTER."
        )
