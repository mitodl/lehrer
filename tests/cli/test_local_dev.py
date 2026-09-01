from __future__ import annotations

import ast
import json
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

from lehrer.cli import _paths, local_dev


def _cluster_json(nodes_running: list[bool]) -> str:
    return json.dumps(
        [
            {
                "name": local_dev.CLUSTER,
                "nodes": [{"State": {"Running": running}} for running in nodes_running],
            }
        ]
    )


class TestClusterState:
    def test_absent_when_no_cluster_matches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(local_dev, "capture", lambda *a, **k: "[]")
        assert local_dev._cluster_state() == "absent"

    def test_absent_on_unparseable_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(local_dev, "capture", lambda *a, **k: "not json")
        assert local_dev._cluster_state() == "absent"

    def test_stopped_when_no_nodes_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            local_dev, "capture", lambda *a, **k: _cluster_json([False, False])
        )
        assert local_dev._cluster_state() == "stopped"

    def test_running_when_all_nodes_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            local_dev, "capture", lambda *a, **k: _cluster_json([True, True])
        )
        assert local_dev._cluster_state() == "running"

    def test_partial_when_some_nodes_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            local_dev, "capture", lambda *a, **k: _cluster_json([True, False])
        )
        assert local_dev._cluster_state() == "partial"


class TestRequiredHostPorts:
    def test_parses_host_side_of_port_mappings(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        config = tmp_path / "k3d-config.yaml"
        config.write_text(
            "ports:\n- port: 8000:80\n  nodeFilters: [loadbalancer]\n- port: 8090:80\n"
        )
        monkeypatch.setattr(local_dev._paths, "k3d_config", lambda: config)
        assert local_dev._required_host_ports() == [8000, 8090]

    def test_no_ports_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        config = tmp_path / "k3d-config.yaml"
        config.write_text("metadata:\n  name: lehrer-dev\n")
        monkeypatch.setattr(local_dev._paths, "k3d_config", lambda: config)
        assert local_dev._required_host_ports() == []


class TestPortInUse:
    def test_bound_port_reports_in_use(self) -> None:
        # A loopback-only bind still blocks _port_in_use's own 0.0.0.0 bind
        # attempt on the same port (the wildcard address can't be bound while
        # any specific address already holds that port), so this avoids
        # binding to all interfaces in test code without weakening the check.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            port = held.getsockname()[1]
            assert local_dev._port_in_use(port) is True

    def test_free_port_reports_not_in_use(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        assert local_dev._port_in_use(port) is False


class TestPreflightHostPorts:
    def test_raises_naming_busy_ports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(local_dev, "_required_host_ports", lambda: [8000, 8090])
        monkeypatch.setattr(local_dev, "_port_in_use", lambda port: port == 8090)
        with pytest.raises(SystemExit, match="8090"):
            local_dev._preflight_host_ports()

    def test_passes_when_all_ports_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(local_dev, "_required_host_ports", lambda: [8000, 8090])
        monkeypatch.setattr(local_dev, "_port_in_use", lambda port: False)
        local_dev._preflight_host_ports()


def _manifest(name: str) -> dict[str, Any]:
    path = _paths.local_dev_dir() / "manifests" / "platform" / name
    return yaml.safe_load(path.read_text())


class TestProvisioningManifests:
    """Guard the CLI<->manifest coupling the provisioning Job depends on.

    The superuser username lives in job-provision.yaml while its password comes
    from the Secret the CLI bootstraps.  Nothing at runtime would notice those
    drifting apart, so pin them here.
    """

    def test_superuser_username_matches_the_manifest(self) -> None:
        container = _manifest("job-provision.yaml")["spec"]["template"]["spec"][
            "containers"
        ][0]
        env = {item["name"]: item["value"] for item in container["env"]}
        assert env["PROVISION_SUPERUSER_USERNAME"] == local_dev._SUPERUSER_USERNAME

    def test_secret_supplies_every_env_var_the_job_requires(self) -> None:
        provisioned = {key for key, _ in local_dev._load_secret_defaults()[0]}
        # provision.py indexes these directly rather than defaulting them.
        assert {
            "PROVISION_SUPERUSER_PASSWORD",
            "NOTES_OAUTH_CLIENT_ID",
            "NOTES_OAUTH_CLIENT_SECRET",
        } <= provisioned

    def test_provision_script_is_valid_python(self) -> None:
        script = _paths.local_dev_dir() / "provision" / "provision.py"
        ast.parse(script.read_text())

    def test_waffle_flags_match_the_set_waffle_flags_schema(self) -> None:
        path = _paths.local_dev_dir() / "provision" / "waffle-flags.yaml"
        waffles = yaml.safe_load(path.read_text())["waffles"]
        assert waffles
        for argument_set in waffles:
            assert all(isinstance(argument, str) for argument in argument_set)


class TestOperatorSecretRefs:
    """The infra operators must read their passwords from openedx-secrets.

    A CR carrying its own hardcoded password silently ignores the matching
    environment override in ``secret-defaults.yaml``, leaving the operator's
    account disagreeing with the value every other component is handed.
    """

    @staticmethod
    def _docs(name: str) -> list[dict[str, Any]]:
        path = _paths.local_dev_dir() / "manifests" / "infra" / name
        return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]

    def test_mariadb_root_password_comes_from_openedx_secrets(self) -> None:
        mariadb = next(d for d in self._docs("mariadb.yaml") if d["kind"] == "MariaDB")
        ref = mariadb["spec"]["rootPasswordSecretKeyRef"]
        assert ref["name"] == "openedx-secrets"
        assert ref["key"] in {key for key, _ in local_dev._load_secret_defaults()[0]}

    def test_mongodb_user_password_comes_from_openedx_secrets(self) -> None:
        mongodb = next(
            d for d in self._docs("mongodb.yaml") if d["kind"] == "MongoDBCommunity"
        )
        ref = mongodb["spec"]["users"][0]["passwordSecretRef"]
        assert ref["name"] == "openedx-secrets"
        assert ref["key"] in {key for key, _ in local_dev._load_secret_defaults()[0]}

    def test_no_infra_manifest_ships_its_own_password_secret(self) -> None:
        for name in ("mariadb.yaml", "mongodb.yaml"):
            secrets = [d for d in self._docs(name) if d["kind"] == "Secret"]
            assert secrets == [], f"{name} still defines its own Secret"


class TestSchemaCollation:
    """Every schema must be created on utf8mb4 / utf8mb4_unicode_ci.

    A schema's default collation is fixed at CREATE DATABASE time and does not
    follow a later collation-server change, so a table created without an
    explicit COLLATE inherits it forever and an FK across the two collations
    fails with errno 150. The Database CRD defaults to utf8/utf8_general_ci,
    which the operator writes into an explicit CHARACTER SET clause — so
    omitting these fields is not "inherit the server default", it is "get 3-byte
    utf8".
    """

    @staticmethod
    def _databases() -> list[dict[str, Any]]:
        path = _paths.local_dev_dir() / "manifests" / "infra" / "mariadb.yaml"
        docs = [doc for doc in yaml.safe_load_all(path.read_text()) if doc]
        return [doc for doc in docs if doc["kind"] == "Database"]

    def test_every_database_pins_the_expected_collation(self) -> None:
        databases = self._databases()
        assert databases
        for database in databases:
            spec = database["spec"]
            name = spec.get("name", database["metadata"]["name"])
            assert spec["characterSet"] == local_dev.EXPECTED_CHARACTER_SET, name
            assert spec["collate"] == local_dev.EXPECTED_COLLATION, name

    def test_no_database_can_be_deleted_out_from_under_its_schema(self) -> None:
        """The finalizer runs DROP DATABASE, and Delete is the CRD's default."""
        for database in self._databases():
            assert database["spec"]["cleanupPolicy"] == "Skip", database["metadata"][
                "name"
            ]

    def test_every_audited_schema_is_declared(self) -> None:
        declared = {
            d["spec"].get("name", d["metadata"]["name"]) for d in self._databases()
        }
        assert set(local_dev._SCHEMAS) == declared

    def test_edxapp_database_uses_the_key_the_operator_adopts(self) -> None:
        """``<mariadb>-database`` is where the MariaDB reconciler looks first.

        It only builds its own (collation-less) Database when that key is
        absent, so renaming this resource silently hands edxapp back to the CRD
        defaults with nothing failing.
        """
        edxapp = next(d for d in self._databases() if d["spec"].get("name") == "edxapp")
        assert edxapp["metadata"]["name"] == "mysql-database"

    def test_the_initial_user_fields_stay_together(self) -> None:
        """IsInitialUserEnabled() needs all three, or no edxapp user is made."""
        path = _paths.local_dev_dir() / "manifests" / "infra" / "mariadb.yaml"
        docs = [doc for doc in yaml.safe_load_all(path.read_text()) if doc]
        spec = next(d for d in docs if d["kind"] == "MariaDB")["spec"]
        assert spec["database"] == "edxapp"
        assert spec["username"] == "edxapp"
        assert spec["passwordSecretKeyRef"]["name"] == "openedx-secrets"


class TestMariaDBTiltGrouping:
    """Every CR in mariadb.yaml must join the `mysql` resource group.

    That group is what carries ``resource_deps=["mariadb-operator"]``. A CR left
    out of it becomes its own Tilt resource with no dependency, so on a fresh
    cluster Tilt can apply it before the chart has installed the CRDs and it
    fails with "no matches for kind". Nothing in the manifest hints that the
    Starlark has to be edited alongside it, so pin the two together here.
    """

    def test_every_mariadb_cr_is_in_the_resource_group(self) -> None:
        path = _paths.local_dev_dir() / "manifests" / "infra" / "mariadb.yaml"
        declared = {
            f"{doc['metadata']['name']}:{doc['kind']}:{doc['metadata']['namespace']}"
            for doc in yaml.safe_load_all(path.read_text())
            if doc
        }
        star = (_paths.local_dev_dir() / "lehrer-core.star").read_text()
        grouped = set(re.findall(r'"([\w-]+:(?:MariaDB|Database|Grant):[\w-]+)"', star))
        assert declared == grouped

    def test_the_group_depends_on_the_operator(self) -> None:
        star = (_paths.local_dev_dir() / "lehrer-core.star").read_text()
        assert 'resource_deps=["mariadb-operator"]' in star


class TestMigrationJobsDoNotRetry:
    """MariaDB DDL is not transactional, so a Job-level retry compounds damage.

    A migration that dies partway leaves what it already created behind; running
    it again fails on "table already exists" and buries the original error.
    """

    @pytest.mark.parametrize(
        "manifest",
        [("platform", "job-migrate.yaml"), ("notes", "job-migrate.yaml")],
    )
    def test_backoff_limit_is_zero(self, manifest: tuple[str, str]) -> None:
        path = _paths.local_dev_dir() / "manifests" / manifest[0] / manifest[1]
        assert yaml.safe_load(path.read_text())["spec"]["backoffLimit"] == 0


class TestStaleMariaDBSecretRefWarning:
    """The guard steering developers off the immutable-field admission error.

    Its output tells them to delete a database, so the quiet branches have to
    stay quiet and the loud one has to stay context-qualified.
    """

    @staticmethod
    def _run(
        monkeypatch: pytest.MonkeyPatch, ref: str
    ) -> tuple[str, list[tuple[str, ...]]]:
        calls: list[tuple[str, ...]] = []

        def fake_capture(*argv: str, **_kwargs: object) -> str:
            calls.append(argv)
            return ref

        printed: list[str] = []
        monkeypatch.setattr(local_dev, "capture", fake_capture)
        monkeypatch.setattr("builtins.print", lambda *a: printed.append(" ".join(a)))
        local_dev._warn_on_stale_mariadb_secret_ref()
        return "\n".join(printed), calls

    def test_silent_when_no_mariadb_cr_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `kubectl get` on a missing CR (or an unreachable cluster) captures
        # empty output under check=False.
        output, _ = self._run(monkeypatch, "")
        assert output == ""

    def test_silent_when_ref_is_already_current(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output, _ = self._run(monkeypatch, "openedx-secrets")
        assert output == ""

    def test_warns_and_names_the_stale_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output, _ = self._run(monkeypatch, "mariadb-root-secret")
        assert "mariadb-root-secret" in output
        assert "immutable" in output

    def test_recovery_command_is_pinned_to_the_local_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Unqualified, this deletes from whatever cluster is current — a
        # kubeconfig normally holds real ones alongside k3d.
        output, _ = self._run(monkeypatch, "mariadb-root-secret")
        assert (
            f"kubectl --context {local_dev.CONTEXT} -n {local_dev.NAMESPACE} "
            "delete mariadb mysql"
        ) in output

    def test_recovery_also_deletes_the_retained_pvc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without this the replacement reattaches the datadir, keeping the
        # databases and the old root password — so the CR delete alone leaves
        # the developer worse off than before following the instruction.
        output, _ = self._run(monkeypatch, "mariadb-root-secret")
        assert (
            f"kubectl --context {local_dev.CONTEXT} -n {local_dev.NAMESPACE} "
            "delete pvc storage-mysql-0"
        ) in output

    def test_probe_targets_the_local_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, calls = self._run(monkeypatch, "openedx-secrets")
        assert len(calls) == 1
        assert "--context" in calls[0]
        assert calls[0][calls[0].index("--context") + 1] == local_dev.CONTEXT


class TestInitOnlyRootPasswordWarning:
    """MariaDB root is set at datadir init, so a later override never lands.

    The Secret and the operator both move to the new value while the server
    keeps the old one, and nothing in the CR is invalid — so without this
    warning the only symptom is Grant/Database reconciliation failing on auth.
    """

    @staticmethod
    def _run(
        monkeypatch: pytest.MonkeyPatch,
        previous: str,
        current: str,
        *,
        datadir: bool,
    ) -> str:
        printed: list[str] = []
        monkeypatch.setattr(local_dev, "_mariadb_datadir_exists", lambda: datadir)
        monkeypatch.setattr("builtins.print", lambda *a: printed.append(" ".join(a)))
        local_dev._warn_on_init_only_root_password(previous, current)
        return "\n".join(printed)

    def test_warns_when_an_initialized_datadir_cannot_take_the_new_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = self._run(monkeypatch, "openedx-dev", "hunter2", datadir=True)
        assert "init-only" in output or "initializes an empty datadir" in output
        assert "delete pvc storage-mysql-0" in output

    def test_silent_on_a_fresh_cluster_with_no_datadir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A first `setup` is exactly when an override *does* work.
        assert self._run(monkeypatch, "openedx-dev", "hunter2", datadir=False) == ""

    def test_silent_when_the_value_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._run(monkeypatch, "openedx-dev", "openedx-dev", datadir=True) == ""

    def test_silent_when_there_is_no_stored_value_to_compare(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._run(monkeypatch, "", "hunter2", datadir=True) == ""

    def test_never_prints_either_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = self._run(monkeypatch, "openedx-dev", "hunter2", datadir=True)
        assert "hunter2" not in output
        assert "openedx-dev" not in output


class TestUncollatedEdxappDatabaseWarning:
    """The guard for a Database the operator generated on the CRD's utf8 default.

    Its output tells developers to delete a resource whose finalizer drops
    edxapp, so the detach step has to come first and stay in the message.
    """

    @staticmethod
    def _run(
        monkeypatch: pytest.MonkeyPatch, character_set: str, collate: str = ""
    ) -> str:
        printed: list[str] = []
        declared = f"{character_set}\t{collate}" if character_set else ""
        monkeypatch.setattr(local_dev, "capture", lambda *a, **k: declared)
        monkeypatch.setattr("builtins.print", lambda *a: printed.append(" ".join(a)))
        local_dev._warn_on_uncollated_edxapp_database()
        return "\n".join(printed)

    def test_silent_when_no_database_resource_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._run(monkeypatch, "") == ""

    def test_silent_when_both_fields_already_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            self._run(
                monkeypatch,
                local_dev.EXPECTED_CHARACTER_SET,
                local_dev.EXPECTED_COLLATION,
            )
            == ""
        )

    def test_warns_when_only_the_collation_differs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Either field alone is immutable, so charset agreeing is not enough."""
        output = self._run(
            monkeypatch, local_dev.EXPECTED_CHARACTER_SET, "utf8mb4_general_ci"
        )
        assert "utf8mb4_general_ci" in output
        assert "delete database" in output

    def test_reports_both_declared_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = self._run(monkeypatch, "utf8", "utf8_general_ci")
        assert "utf8_general_ci" in output
        assert local_dev.EXPECTED_COLLATION in output

    def test_detaches_the_finalizer_before_deleting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = self._run(monkeypatch, "utf8", "utf8_general_ci")
        patch = output.index("patch database")
        delete = output.index("delete database")
        assert patch < delete, "deleting first drops edxapp"
        assert "cleanupPolicy" in output
        assert "lehrer dev db-collation --fix" in output

    def test_recovery_commands_are_pinned_to_the_local_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = self._run(monkeypatch, "utf8", "utf8_general_ci")
        for line in output.splitlines():
            if "kubectl" in line:
                assert f"--context {local_dev.CONTEXT}" in line


class TestSchemaCollationDriftWarning:
    """The guard for datadirs created before the manifests pinned a collation.

    It runs on every ``setup``, so silence is the default and the loud branch
    has to name a schema and a way out.
    """

    @staticmethod
    def _run(
        monkeypatch: pytest.MonkeyPatch,
        defaults: dict[str, str] | None,
        *,
        datadir: bool = True,
    ) -> str:
        printed: list[str] = []
        monkeypatch.setattr(local_dev, "_mariadb_datadir_exists", lambda: datadir)
        monkeypatch.setattr(local_dev, "_schema_defaults", lambda: defaults)
        monkeypatch.setattr("builtins.print", lambda *a: printed.append(" ".join(a)))
        local_dev._warn_on_schema_collation_drift()
        return "\n".join(printed)

    def test_names_the_drifted_schema_and_the_repair(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = self._run(
            monkeypatch,
            {"edxapp": "utf8_general_ci", "notes": local_dev.EXPECTED_COLLATION},
        )
        assert "edxapp" in output
        assert "notes" not in output
        assert "lehrer dev db-collation --fix" in output

    def test_silent_when_every_schema_is_aligned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        aligned = dict.fromkeys(local_dev._SCHEMAS, local_dev.EXPECTED_COLLATION)
        assert self._run(monkeypatch, aligned) == ""

    def test_silent_on_a_fresh_cluster_with_no_datadir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Nothing to drift from: the manifests pin the collation at creation.
        assert (
            self._run(monkeypatch, {"edxapp": "utf8_general_ci"}, datadir=False) == ""
        )

    def test_silent_when_the_server_is_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # MariaDB is routinely still starting during `setup`; a probe that
        # cannot connect is not evidence of drift.
        assert self._run(monkeypatch, None) == ""


class TestMysqlExec:
    """``_mysql`` must keep the root password out of every argv.

    A password passed as an argument shows up in the container's own process
    table and in whatever the CLI echoes, so it goes over stdin instead.
    """

    @staticmethod
    def _stub(
        monkeypatch: pytest.MonkeyPatch,
        result: tuple[int, str, str] = (0, "edxapp\tutf8mb4_unicode_ci", ""),
    ) -> dict[str, Any]:
        seen: dict[str, Any] = {}

        def fake_capture_result(*argv: str, **kwargs: Any) -> tuple[int, str, str]:
            seen["argv"] = argv
            seen["kwargs"] = kwargs
            return result

        monkeypatch.setattr(local_dev, "_stored_secret_value", lambda _key: "hunter2")
        monkeypatch.setattr(local_dev, "capture_result", fake_capture_result)
        return seen

    def test_password_travels_on_stdin_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._stub(monkeypatch)
        local_dev._mysql("SELECT 1")
        assert seen["kwargs"]["input"] == "hunter2\n"
        assert not any("hunter2" in arg for arg in seen["argv"])

    def test_exec_is_pinned_to_the_local_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._stub(monkeypatch)
        local_dev._mysql("SELECT 1")
        argv = seen["argv"]
        assert "--context" in argv
        assert argv[argv.index("--context") + 1] == local_dev.CONTEXT
        assert local_dev.NAMESPACE in argv

    def test_returns_none_when_the_secret_has_no_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(local_dev, "_stored_secret_value", lambda _key: "")
        monkeypatch.setattr(
            local_dev,
            "capture_result",
            lambda *a, **k: pytest.fail("must not exec without a password"),
        )
        assert local_dev._mysql("SELECT 1") is None

    def test_a_failed_statement_is_none_not_empty_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The distinction the whole audit rests on: failed != found nothing."""
        self._stub(monkeypatch, (1, "", "ERROR 1049: Unknown database"))
        assert local_dev._mysql("SELECT 1") is None

    def test_a_successful_statement_matching_nothing_is_empty_not_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub(monkeypatch, (0, "", ""))
        assert local_dev._mysql("SELECT 1") == ""

    def test_the_server_error_is_surfaced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        printed: list[str] = []
        self._stub(monkeypatch, (1, "", "ERROR 1049: Unknown database"))
        monkeypatch.setattr("builtins.print", lambda *a: printed.append(" ".join(a)))
        local_dev._mysql("SELECT 1")
        assert "ERROR 1049" in "\n".join(printed)


class TestCollationRepairReportsFailure:
    """A repair that did not run must never print as though it did."""

    @staticmethod
    def _alter(monkeypatch: pytest.MonkeyPatch, result: str | None) -> str:
        printed: list[str] = []
        monkeypatch.setattr(local_dev, "_mysql", lambda *a, **k: result)
        monkeypatch.setattr("builtins.print", lambda *a: printed.append(" ".join(a)))
        ran = local_dev._alter_collation("edxapp")
        return f"{ran}\n" + "\n".join(printed)

    def test_a_successful_alter_reports_the_new_collation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = self._alter(monkeypatch, "")
        assert output.startswith("True")
        assert "FAILED" not in output
        assert local_dev.EXPECTED_COLLATION in output

    def test_a_failed_alter_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        output = self._alter(monkeypatch, None)
        assert output.startswith("False")
        assert "FAILED" in output


class TestCorruptTableScanReportsFailure:
    """ "None reporting an error" has to mean the check actually ran."""

    @staticmethod
    def _scan(monkeypatch: pytest.MonkeyPatch, responses: list[str | None]) -> str:
        printed: list[str] = []
        remaining = list(responses)
        monkeypatch.setattr(local_dev, "_mysql", lambda *a, **k: remaining.pop(0))
        monkeypatch.setattr("builtins.print", lambda *a: printed.append(" ".join(a)))
        local_dev._report_corrupt_tables(["edxapp"])
        return "\n".join(printed)

    def test_a_failed_listing_is_not_a_clean_bill_of_health(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = self._scan(monkeypatch, [None])
        assert "not checked" in output
        assert "none reporting an error" not in output

    def test_a_failed_check_counts_as_unchecked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Table listing succeeds; the CHECK TABLE over them does not.
        output = self._scan(monkeypatch, ["auth_user\ncourse_overviews", None])
        assert "could not be checked" in output
        assert "0 tables, none reporting an error" in output

    def test_a_clean_scan_reads_clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        output = self._scan(
            monkeypatch,
            ["auth_user", "edxapp.auth_user\tcheck\tstatus\tOK"],
        )
        assert "1 tables, none reporting an error" in output
        assert "could not be checked" not in output

    def test_a_corrupt_table_is_reported_without_a_repair_suggestion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        output = self._scan(
            monkeypatch,
            ["auth_user", "edxapp.auth_user\tcheck\terror\tIndex is corrupted"],
        )
        assert "Index is corrupted" in output
        assert "inspect them before running" in output


class TestSetupContract:
    """The Tiltfile and lehrer-core.star must agree on setup()'s key set.

    Every ``cfg[...]`` access is unconditional, so the two directions fail
    differently and both matter: an extra key is dead config that looks
    tunable, while a missing one is a KeyError the moment Tilt loads.
    """

    @staticmethod
    def _key_sets() -> tuple[set[str], set[str]]:
        local_dev_dir = _paths.local_dev_dir()
        passed = set(
            re.findall(
                r'^\s*"([a-z_]+)":', (local_dev_dir / "Tiltfile").read_text(), re.M
            )
        )
        read = set(
            re.findall(
                r'cfg\["([a-z_]+)"\]', (local_dev_dir / "lehrer-core.star").read_text()
            )
        )
        return passed, read

    def test_tiltfile_passes_no_keys_lehrer_core_ignores(self) -> None:
        passed, read = self._key_sets()
        assert passed, "no setup() keys parsed out of the Tiltfile"
        assert passed - read == set(), f"dead setup() keys: {sorted(passed - read)}"

    def test_tiltfile_passes_every_key_lehrer_core_reads(self) -> None:
        passed, read = self._key_sets()
        assert read, "no cfg[...] reads parsed out of lehrer-core.star"
        assert read - passed == set(), (
            f"setup() keys read but never passed: {sorted(read - passed)}"
        )


def _deployments() -> list[Path]:
    root = _paths.repo_root() / "deployments"
    return [d for d in sorted(root.iterdir()) if (d / "mfe_slot_config").is_dir()]


def _sites(deployment: Path) -> set[str]:
    frontend = deployment / "mfe_slot_config" / "frontend"
    return {
        d.name
        for d in frontend.iterdir()
        if d.is_dir() and d.name not in {"shared", "src"}
    }


def _declared_ports(deployment: Path) -> dict[str, int]:
    path = deployment / "mfe_slot_config" / "frontend" / "dev-ports.yaml"
    return yaml.safe_load(path.read_text())


def _base_url_ports(deployment: Path) -> dict[str, int | None]:
    """Per site, the port in its dev baseUrl — None for a sub-path URL."""
    frontend = deployment / "mfe_slot_config" / "frontend"
    ports: dict[str, int | None] = {}
    for config in sorted(frontend.glob("*/site.config.dev.tsx")):
        match = re.search(r'baseUrl:\s*"([^"]+)"', config.read_text())
        assert match is not None, f"{config} has no baseUrl"
        ports[config.parent.name] = urlsplit(match.group(1)).port
    return ports


class TestMFEDevServerPorts:
    """Every Site Project's dev server needs a host port it can actually bind.

    The port is declared in dev-ports.yaml rather than read out of baseUrl,
    because an MFE served as a sub-path of the LMS — how ol-infrastructure
    deploys them — has no port of its own to read. k3d's loadbalancer holds
    its ports for the life of the cluster, and two sites naming the same port
    cannot both listen.
    """

    def test_every_site_has_a_declared_dev_port(self) -> None:
        for deployment in _deployments():
            assert set(_declared_ports(deployment)) == _sites(deployment)

    def test_no_dev_port_collides_with_the_k3d_loadbalancer(self) -> None:
        reserved = set(local_dev._required_host_ports())
        for deployment in _deployments():
            for site, port in _declared_ports(deployment).items():
                assert port not in reserved, (
                    f"{deployment.name}/{site} wants dev port {port}, which "
                    "k3d's loadbalancer binds"
                )

    def test_sites_in_a_deployment_do_not_share_a_dev_port(self) -> None:
        for deployment in _deployments():
            ports = _declared_ports(deployment)
            assert len(set(ports.values())) == len(ports), (
                f"{deployment.name} has duplicate dev ports: {ports}"
            )

    def test_a_base_url_that_names_a_port_agrees_with_the_declared_one(
        self,
    ) -> None:
        # Only applies when the site owns a host; a sub-path baseUrl carries
        # the LMS origin and has nothing to reconcile.
        for deployment in _deployments():
            declared = _declared_ports(deployment)
            for site, base_port in _base_url_ports(deployment).items():
                if base_port is None:
                    continue
                assert base_port == declared[site], (
                    f"{deployment.name}/{site}: baseUrl points at {base_port} "
                    f"but dev-ports.yaml declares {declared[site]}"
                )


class TestMFEDevHostnamesFailLoudly:
    """A partial map would report success for sites it never looked at."""

    def test_a_mistyped_deployment_config_is_an_error(self, tmp_path) -> None:
        with pytest.raises(SystemExit, match="not a directory"):
            local_dev.mfe_dev_hostnames(tmp_path / "typo")

    def test_a_deployment_with_no_site_projects_is_an_error(self, tmp_path) -> None:
        (tmp_path / "mfe_slot_config" / "frontend").mkdir(parents=True)
        with pytest.raises(SystemExit, match="No site.config.dev.tsx"):
            local_dev.mfe_dev_hostnames(tmp_path)

    def test_a_config_without_a_base_url_is_an_error(self, tmp_path) -> None:
        site = tmp_path / "mfe_slot_config" / "frontend" / "thing"
        site.mkdir(parents=True)
        (site / "site.config.dev.tsx").write_text("const siteConfig = {};\n")
        with pytest.raises(SystemExit, match="No baseUrl"):
            local_dev.mfe_dev_hostnames(tmp_path)

    def test_a_base_url_without_a_host_is_an_error(self, tmp_path) -> None:
        site = tmp_path / "mfe_slot_config" / "frontend" / "thing"
        site.mkdir(parents=True)
        (site / "site.config.dev.tsx").write_text('baseUrl: "/just/a/path",\n')
        with pytest.raises(SystemExit, match="has no host"):
            local_dev.mfe_dev_hostnames(tmp_path)


class TestMFEDevHostnames:
    def test_hostnames_are_parsed_per_site(self) -> None:
        hostnames = local_dev.mfe_dev_hostnames(
            _paths.repo_root() / "deployments/mit-ol"
        )
        assert hostnames
        assert set(hostnames.values()) == {"apps.local.openedx.io"}

    def test_generic_stays_on_localhost(self) -> None:
        # The generic deployment must not depend on any name resolution.
        hostnames = local_dev.mfe_dev_hostnames(
            _paths.repo_root() / "deployments/generic"
        )
        assert set(hostnames.values()) == {"localhost"}


class TestSharedSecretDefaults:
    """secret-defaults.yaml is the one definition both consumers read.

    The CLI loads it here; ``setup()``'s ``manage_secrets`` in
    lehrer-core.star reads the same file so a Tilt caller composing this
    stack into its own cluster creates an identical Secret. These tests pin
    the contract between the two, since only one of them is exercised by the
    Python suite.
    """

    def test_star_and_cli_read_the_same_file(self) -> None:
        star = (_paths.local_dev_dir() / "lehrer-core.star").read_text()
        assert '"/secret-defaults.yaml"' in star
        assert _paths.secret_defaults().exists()

    def test_mirrors_resolve_to_their_source_value(self) -> None:
        defaults, mirrors = local_dev._load_secret_defaults()
        keys = {key for key, _ in defaults}
        for key, source in mirrors:
            # A mirror naming a missing source would silently KeyError at
            # cluster-creation time, long after the edit that caused it.
            assert source in keys, f"{key} mirrors unknown key {source}"
            assert key not in keys, f"{key} is both a default and a mirror"

    def test_db_password_mirrors_mysql_password(self) -> None:
        # Kept from the setup.sh this CLI replaced; edxapp reads DB_PASSWORD
        # while the MariaDB Grant reads MYSQL_PASSWORD, and they must agree.
        _, mirrors = local_dev._load_secret_defaults()
        assert ("DB_PASSWORD", "MYSQL_PASSWORD") in mirrors
