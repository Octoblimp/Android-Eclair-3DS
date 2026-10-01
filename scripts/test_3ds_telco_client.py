#!/usr/bin/env python3
"""Offline regressions for the 3DS Telco PC diagnostic helper."""

from __future__ import annotations

import importlib.util
import ipaddress
import json
from pathlib import Path
import socket
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/3ds_telco_client.py"
SERVICE = ROOT / "tools/3ds_telco_service.py"
SPEC = importlib.util.spec_from_file_location("telco_client", TOOL)
assert SPEC and SPEC.loader
CLIENT = importlib.util.module_from_spec(SPEC)
sys.modules["telco_client"] = CLIENT
SPEC.loader.exec_module(CLIENT)


def route(interface: str, network: str, gateway: str,
          local_ip: str | None = None) -> object:
    return CLIENT.Route(interface, ipaddress.IPv4Network(network),
                        ipaddress.IPv4Address(gateway),
                        ipaddress.IPv4Address(local_ip) if local_ip else None,
                        source="fixture")


def status(adb: str = "0", endpoint: str = "", clients: str = "0") -> str:
    return ("N3DS-TELCO/1\nstate=connected\nerror=none\nclients=%s\n"
            "rssi=-50\nap_ipv4=192.168.43.1\nadb=%s\nadb_endpoint=%s\n" %
            (clients, adb, endpoint))


def main() -> None:
    linux = CLIENT.parse_linux_routes(
        "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
        "wlan0 002BA8C0 00000000 0001 0 0 0 00FFFFFF 0 0 0\n")
    assert len(linux) == 1
    assert str(linux[0].network) == "192.168.43.0/24"
    windows = CLIENT.parse_windows_routes(
        "Network Destination Netmask Gateway Interface Metric\n"
        "192.168.43.0 255.255.255.0 On-link 192.168.43.20 281\n")
    assert len(windows) == 1
    assert windows[0].local_ip == ipaddress.IPv4Address("192.168.43.20")

    selected = CLIENT.select_route(
        [route("ethernet", "0.0.0.0/0", "10.0.0.1", "10.0.0.4"),
         route("wlan0", "192.168.43.0/24", "0.0.0.0", "192.168.43.20")])
    assert selected.interface == "wlan0"
    try:
        CLIENT.select_route([route("wlan0", "192.168.43.0/24", "0.0.0.0"),
                             route("wlan1", "192.168.43.0/24", "0.0.0.0")])
    except CLIENT.AmbiguousRoute:
        pass
    else:
        raise AssertionError("multiple AP interfaces must be rejected")
    try:
        CLIENT.select_route([route("wlan0", "10.0.0.0/24", "0.0.0.0")])
    except CLIENT.RouteNotFound:
        pass
    else:
        raise AssertionError("wrong network must be rejected")

    parsed = CLIENT.parse_status(status(), "192.168.43.1")
    assert parsed.clients == 0 and not parsed.adb and parsed.rssi == -50
    parsed = CLIENT.parse_status(status("1", "192.168.43.1:5555", "1"),
                                 "192.168.43.1")
    assert parsed.adb_endpoint == "192.168.43.1:5555"
    for bad in (status("1", "10.0.0.1:5555", "1"),
                status("1", "192.168.43.1:5555", "0"),
                status().replace("N3DS-TELCO/1", "HTTP/1.0")):
        try:
            CLIENT.parse_status(bad)
        except CLIENT.TelcoError:
            pass
        else:
            raise AssertionError("malformed/wrong status was accepted")
    args = CLIENT.build_parser().parse_args(["--once", "--adb", "--json"])
    assert args.once and args.adb and args.json
    defaults = CLIENT.build_parser().parse_args([])
    assert defaults.listen == "127.0.0.1"
    assert not defaults.watch and not defaults.once

    # The default local service is loopback-only, read-only, bounded, and
    # exposes state transitions without opening a second target protocol.
    state = CLIENT.LatchState()
    server = CLIENT.LocalStatusServer(("127.0.0.1", 0), state.snapshot,
                                      max_clients=1, request_timeout=0.25)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    address = ("127.0.0.1", server.server_address[1])

    def ask(request: bytes) -> bytes:
        with socket.create_connection(address, timeout=1.0) as sock:
            sock.sendall(request)
            chunks = []
            total = 0
            while total <= CLIENT.MAX_LOCAL_RESPONSE_BYTES:
                chunk = sock.recv(min(512, CLIENT.MAX_LOCAL_RESPONSE_BYTES + 1 - total))
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                total += len(chunk)
            raise AssertionError("local status response exceeded test bound")

    assert b"latch=waiting" in ask(b"STATUS\n")
    state.update_error("wrong network; retrying")
    error_payload = json.loads(ask(b"STATUS JSON\n").decode("ascii"))
    assert error_payload["latch"] == "error"
    connected_route = route("wlan0", "192.168.43.0/24", "0.0.0.0",
                            "192.168.43.20")
    state.update_connected(connected_route, parsed)
    connected_payload = json.loads(ask(b"STATUS JSON\n").decode("ascii"))
    assert connected_payload["latch"] == "connected"
    assert connected_payload["target"]["adb_endpoint"] == "192.168.43.1:5555"
    for _ in range(8):
        assert b"latch=connected" in ask(b"STATUS\n")
        repeated_payload = json.loads(ask(b"STATUS JSON\n").decode("ascii"))
        assert repeated_payload["latch"] == "connected"
        assert repeated_payload["target"]["adb_endpoint"] == "192.168.43.1:5555"
    assert ask(b"SET adb 1\n").startswith(b"ERROR read_only_status")
    assert ask(b"x" * (CLIENT.MAX_LOCAL_REQUEST_BYTES + 1)).startswith(
        b"ERROR request_too_large")

    # Hold one bounded request slot without sending data; a second consumer
    # receives a bounded busy response instead of creating unbounded threads.
    held = socket.create_connection(address, timeout=1.0)
    time.sleep(0.05)
    assert ask(b"STATUS\n").startswith(b"ERROR busy")
    assert ask(b"x" * (CLIENT.MAX_LOCAL_REQUEST_BYTES + 1)).startswith(
        b"ERROR busy")
    held.close()
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=2.0)
    assert not server_thread.is_alive()
    try:
        socket.create_connection(address, timeout=0.2)
    except OSError:
        pass
    else:
        raise AssertionError("local service did not cleanly close its listener")
    try:
        CLIENT.LocalStatusServer(("0.0.0.0", 0), state.snapshot)
    except CLIENT.TelcoError:
        pass
    else:
        raise AssertionError("non-loopback status server bind was accepted")

    # Service stop/cleanup is deterministic even while the outbound latch is
    # retrying a wrong/missing interface.
    stop = threading.Event()
    service_args = CLIENT.build_parser().parse_args([
        "--interface", "missing-test-interface", "--listen-port", "0",
        "--interval", "0.05", "--probe-timeout", "0.05"])
    service_thread = threading.Thread(target=CLIENT.run_service,
                                      args=(service_args, stop), daemon=True)
    service_thread.start()
    time.sleep(0.1)
    stop.set()
    service_thread.join(timeout=3.0)
    assert not service_thread.is_alive()

    tool_text = TOOL.read_text(encoding="utf-8").lower()
    service_text = SERVICE.read_text(encoding="utf-8")
    assert "3ds_telco_client.py" in service_text
    service_spec = importlib.util.spec_from_file_location("telco_service", SERVICE)
    assert service_spec and service_spec.loader
    service_module = importlib.util.module_from_spec(service_spec)
    service_spec.loader.exec_module(service_module)
    assert service_module.LocalStatusServer.__name__ == "LocalStatusServer"
    assert callable(service_module.run_service)
    assert "mobiledata.passphrase" not in tool_text
    assert "wpa_supplicant.conf" not in tool_text
    print("3ds_telco_client: PASS (routes/latch/loopback server/cleanup offline)")


if __name__ == "__main__":
    main()
