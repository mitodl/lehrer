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
