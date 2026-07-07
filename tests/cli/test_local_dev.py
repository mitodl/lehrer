from __future__ import annotations

import json
import socket

import pytest

from lehrer.cli import local_dev


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
        # Bind to 0.0.0.0, mirroring _port_in_use's own bind (which mirrors
        # k3d's loadbalancer bind) — a short-lived local test socket, not a
        # listener exposed beyond this process.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(("0.0.0.0", 0))  # noqa: S104  # lgtm[py/bind-socket-all-network-interfaces]
            held.listen(1)
            port = held.getsockname()[1]
            assert local_dev._port_in_use(port) is True

    def test_free_port_reports_not_in_use(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("0.0.0.0", 0))  # noqa: S104  # lgtm[py/bind-socket-all-network-interfaces]
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
