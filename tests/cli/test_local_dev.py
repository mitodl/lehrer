from __future__ import annotations

import ast
import json
import re
import socket
from typing import Any

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
        provisioned = {key for key, _ in local_dev._SECRET_DEFAULTS}
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
    environment override in ``_SECRET_DEFAULTS``, leaving the operator's
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
        assert ref["key"] in {key for key, _ in local_dev._SECRET_DEFAULTS}

    def test_mongodb_user_password_comes_from_openedx_secrets(self) -> None:
        mongodb = next(
            d for d in self._docs("mongodb.yaml") if d["kind"] == "MongoDBCommunity"
        )
        ref = mongodb["spec"]["users"][0]["passwordSecretRef"]
        assert ref["name"] == "openedx-secrets"
        assert ref["key"] in {key for key, _ in local_dev._SECRET_DEFAULTS}

    def test_no_infra_manifest_ships_its_own_password_secret(self) -> None:
        for name in ("mariadb.yaml", "mongodb.yaml"):
            secrets = [d for d in self._docs(name) if d["kind"] == "Secret"]
            assert secrets == [], f"{name} still defines its own Secret"


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
