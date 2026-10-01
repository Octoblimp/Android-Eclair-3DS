#!/usr/bin/env python3
"""PC latch service and reachability diagnostic for the local ``3DS Telco`` AP.

This is a dependency-free PC-side helper.  It does not join Wi-Fi, manage the
AP's WPA secret, change routing, or claim Nintendo UDS compatibility.  After
the operator has joined the AP, it finds the interface that can reach the
fixed gateway, queries the target's bounded status endpoint, and optionally
invokes ``adb connect`` only for an explicitly advertised AP-bound endpoint.
By default it also serves the current latch state to local consumers on a
loopback-only TCP listener; that listener is status-only and accepts no remote
control or credential material.
"""

from __future__ import annotations

import argparse
import dataclasses
import ipaddress
import json
import os
import re
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
from typing import Callable, Iterable, Mapping, Optional, Sequence


DEFAULT_GATEWAY = "192.168.43.1"
DEFAULT_STATUS_PORT = 4242
DEFAULT_LISTEN_ADDRESS = "127.0.0.1"
DEFAULT_LISTEN_PORT = 43724
MAX_STATUS_BYTES = 4096
MAX_LOCAL_REQUEST_BYTES = 64
MAX_LOCAL_RESPONSE_BYTES = 4096
DEFAULT_MAX_CLIENTS = 4
STATUS_HEADER = "N3DS-TELCO/1"
LOCAL_PROTOCOL = "N3DS-TELCO-PC/1"
STATUS_FIELDS = ("state", "error", "clients", "rssi", "ap_ipv4", "adb",
                 "adb_endpoint")
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")


class TelcoError(RuntimeError):
    """Expected operator/environment error, suitable for a concise CLI."""


class RouteNotFound(TelcoError):
    pass


class AmbiguousRoute(TelcoError):
    pass


@dataclasses.dataclass(frozen=True)
class Route:
    interface: str
    network: ipaddress.IPv4Network
    gateway: ipaddress.IPv4Address
    local_ip: Optional[ipaddress.IPv4Address] = None
    source: str = "unknown"


@dataclasses.dataclass(frozen=True)
class Status:
    state: str
    error: str
    clients: int
    rssi: Optional[int]
    ap_ipv4: ipaddress.IPv4Address
    adb: bool
    adb_endpoint: Optional[str]


class LatchState:
    """Thread-safe, non-command-bearing state exposed by the local service."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: dict[str, object] = {
            "protocol": LOCAL_PROTOCOL,
            "latch": "waiting",
            "message": "waiting for 3DS Telco AP status",
            "target": None,
        }

    def update_waiting(self, message: str) -> None:
        self._update("waiting", message, None)

    def update_error(self, message: str) -> None:
        self._update("error", message, None)

    def update_connected(self, route: Route, status: Status) -> None:
        self._update("connected", "target status reachable",
                     dict(_status_payload(route, status)))

    def _update(self, latch: str, message: str,
                target: Optional[Mapping[str, object]]) -> None:
        safe_message = " ".join(str(message).split())[:160]
        with self._lock:
            self._snapshot = {
                "protocol": LOCAL_PROTOCOL,
                "latch": latch,
                "message": safe_message,
                "target": target,
            }

    def snapshot(self) -> Mapping[str, object]:
        with self._lock:
            return dict(self._snapshot)


def _address(value: str) -> ipaddress.IPv4Address:
    try:
        return ipaddress.IPv4Address(value)
    except ValueError as exc:
        raise TelcoError("invalid IPv4 value: %s" % value) from exc


def _mask_to_prefix(mask: str) -> int:
    try:
        return ipaddress.IPv4Network("0.0.0.0/%s" % mask).prefixlen
    except ValueError as exc:
        raise TelcoError("invalid route netmask: %s" % mask) from exc


def _linux_hex_address(value: str) -> ipaddress.IPv4Address:
    try:
        raw = int(value, 16)
    except ValueError as exc:
        raise TelcoError("invalid Linux route address: %s" % value) from exc
    return ipaddress.IPv4Address(struct.pack("<I", raw))


def parse_linux_routes(text: str) -> list[Route]:
    """Parse ``/proc/net/route`` without shelling out or choosing a route."""
    routes: list[Route] = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8:
            continue
        interface, destination, gateway, flags, _ref, _use, _metric, mask = fields[:8]
        try:
            if int(flags, 16) & 1 == 0:  # route is down
                continue
            network = ipaddress.IPv4Network(
                "%s/%s" % (_linux_hex_address(destination), _mask_to_prefix(
                    str(_linux_hex_address(mask)))), strict=False)
            gateway_ip = _linux_hex_address(gateway)
        except (TelcoError, ValueError):
            continue
        routes.append(Route(interface, network, gateway_ip, source="linux"))
    return routes


def parse_windows_routes(text: str) -> list[Route]:
    """Parse the IPv4 table emitted by ``route print -4``."""
    routes: list[Route] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        try:
            destination = _address(fields[0])
            mask = _address(fields[1])
            gateway_text = fields[2]
            interface = fields[3]
            prefix = ipaddress.IPv4Network("0.0.0.0/%s" % mask).prefixlen
        except (TelcoError, ValueError):
            continue
        if gateway_text.lower() == "on-link":
            gateway = ipaddress.IPv4Address("0.0.0.0")
        else:
            try:
                gateway = _address(gateway_text)
            except TelcoError:
                continue
        routes.append(Route(interface,
                             ipaddress.IPv4Network("%s/%d" % (destination,
                                                               prefix), strict=False),
                             gateway, local_ip=_maybe_address(interface),
                             source="windows"))
    return routes


def _maybe_address(value: str) -> Optional[ipaddress.IPv4Address]:
    try:
        return ipaddress.IPv4Address(value)
    except ValueError:
        return None


def _route_score(route: Route, target: ipaddress.IPv4Address) -> tuple[int, int]:
    # An exact gateway wins over an on-link route; longest-prefix routing is
    # the tie breaker.  A default route through some other gateway is never a
    # valid candidate for the fixed AP endpoint.
    exact = int(route.gateway == target)
    on_link = int(route.gateway.is_unspecified)
    return (3 if exact else 2 if on_link else 0, route.network.prefixlen)


def select_route(routes: Iterable[Route], target: str = DEFAULT_GATEWAY,
                 interface: Optional[str] = None) -> Route:
    target_ip = _address(target)
    candidates = [route for route in routes
                  if target_ip in route.network and
                  (route.gateway == target_ip or route.gateway.is_unspecified) and
                  (interface is None or interface in
                   (route.interface, str(route.local_ip or "")))]
    if not candidates:
        raise RouteNotFound("no interface is routed to %s" % target_ip)
    best_score = max(_route_score(route, target_ip) for route in candidates)
    best = [route for route in candidates if _route_score(route, target_ip) == best_score]
    identities = {(route.interface, str(route.local_ip or "")) for route in best}
    if len(identities) > 1:
        names = ", ".join(sorted("%s(%s)" % identity for identity in identities))
        raise AmbiguousRoute("multiple AP interfaces reach %s: %s; use --interface" %
                             (target_ip, names))
    return best[0]


def _linux_interface_ipv4(interface: str) -> Optional[ipaddress.IPv4Address]:
    if os.name == "nt":
        return None
    try:
        import fcntl  # pylint: disable=import-outside-toplevel
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            request = struct.pack("256s", interface.encode("ascii")[:15])
            value = fcntl.ioctl(sock.fileno(), 0x8915, request)[20:24]
            return ipaddress.IPv4Address(value)
        finally:
            sock.close()
    except (OSError, UnicodeEncodeError, ValueError):
        return None


def detect_route(target: str = DEFAULT_GATEWAY,
                 interface: Optional[str] = None) -> Route:
    if os.name == "nt":
        try:
            output = subprocess.check_output(["route", "print", "-4"],
                                             text=True, stderr=subprocess.STDOUT)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise TelcoError("cannot inspect Windows IPv4 routes: %s" % exc) from exc
        routes = parse_windows_routes(output)
    else:
        try:
            with open("/proc/net/route", "r", encoding="ascii") as stream:
                routes = parse_linux_routes(stream.read())
        except OSError as exc:
            raise TelcoError("cannot inspect Linux IPv4 routes: %s" % exc) from exc
        routes = [dataclasses.replace(route,
                                      local_ip=_linux_interface_ipv4(route.interface))
                  for route in routes]
    return select_route(routes, target, interface)


def _parse_endpoint(value: str, gateway: ipaddress.IPv4Address) -> Optional[str]:
    if not value or value == "none":
        return None
    host, separator, port_text = value.rpartition(":")
    if not separator or _maybe_address(host) != gateway:
        raise TelcoError("ADB endpoint is not bound to the selected AP gateway")
    try:
        port = int(port_text, 10)
    except ValueError as exc:
        raise TelcoError("invalid ADB endpoint port") from exc
    if not 1 <= port <= 65535:
        raise TelcoError("invalid ADB endpoint port")
    return "%s:%d" % (gateway, port)


def parse_status(text: str, gateway: str = DEFAULT_GATEWAY) -> Status:
    """Parse and validate the target's bounded status snapshot."""
    lines = text.splitlines()
    if not lines or lines[0] != STATUS_HEADER:
        raise TelcoError("status endpoint is not a 3DS Telco service")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        key, separator, value = line.partition("=")
        if not separator or key not in STATUS_FIELDS or key in fields:
            raise TelcoError("malformed status field")
        if value and not SAFE_TOKEN.fullmatch(value):
            raise TelcoError("unsafe status field")
        fields[key] = value
    missing = [key for key in STATUS_FIELDS if key not in fields]
    if missing:
        raise TelcoError("status missing: %s" % ",".join(missing))
    state = fields["state"]
    if state not in {"starting", "disconnected", "connected", "error",
                     "stopping", "disabled"}:
        raise TelcoError("unknown Mobile Data state")
    error = fields["error"] or "none"
    try:
        clients = int(fields["clients"], 10)
    except ValueError as exc:
        raise TelcoError("invalid client count") from exc
    if not 0 <= clients <= 255:
        raise TelcoError("invalid client count")
    rssi_text = fields["rssi"]
    if rssi_text in ("", "unknown"):
        rssi = None
    else:
        try:
            rssi = int(rssi_text, 10)
        except ValueError as exc:
            raise TelcoError("invalid RSSI") from exc
        if not -127 <= rssi <= 0:
            raise TelcoError("invalid RSSI")
    ap_ipv4 = _address(fields["ap_ipv4"])
    gateway_ip = _address(gateway)
    if ap_ipv4 != gateway_ip:
        raise TelcoError("status belongs to a different AP gateway")
    if fields["adb"] not in {"0", "1"}:
        raise TelcoError("invalid ADB opt-in flag")
    adb = fields["adb"] == "1"
    endpoint = _parse_endpoint(fields["adb_endpoint"], gateway_ip)
    if endpoint and (not adb or clients < 1):
        raise TelcoError("ADB endpoint advertised without AP-bound opt-in")
    return Status(state, error, clients, rssi, ap_ipv4, adb, endpoint)


def probe(route: Route, gateway: str = DEFAULT_GATEWAY,
          port: int = DEFAULT_STATUS_PORT, timeout: float = 2.0) -> Status:
    """Query one target endpoint while binding to the selected local address."""
    gateway_ip = _address(gateway)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        if route.local_ip:
            sock.bind((str(route.local_ip), 0))
        sock.connect((str(gateway_ip), port))
        sock.sendall(b"STATUS\n")
        chunks: list[bytes] = []
        total = 0
        while total < MAX_STATUS_BYTES:
            chunk = sock.recv(min(512, MAX_STATUS_BYTES - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total >= MAX_STATUS_BYTES:
            raise TelcoError("status response is too large")
        try:
            response = b"".join(chunks).decode("ascii")
        except UnicodeDecodeError as exc:
            raise TelcoError("status response is not ASCII") from exc
        return parse_status(response, gateway)
    except socket.timeout as exc:
        raise TelcoError("timed out reaching %s:%d" % (gateway_ip, port)) from exc
    except OSError as exc:
        raise TelcoError("cannot reach %s:%d: %s" % (gateway_ip, port, exc)) from exc
    finally:
        sock.close()


def _status_payload(route: Route, status: Status) -> Mapping[str, object]:
    return {
        "interface": route.interface,
        "local_ip": str(route.local_ip) if route.local_ip else None,
        "gateway": str(route.gateway),
        "state": status.state,
        "error": status.error,
        "clients": status.clients,
        "rssi": status.rssi,
        "ap_ipv4": str(status.ap_ipv4),
        "adb": status.adb,
        "adb_endpoint": status.adb_endpoint,
    }


def _local_text(snapshot: Mapping[str, object]) -> str:
    """Render the read-only local protocol without accepting any commands."""
    target = snapshot.get("target")
    lines = [
        LOCAL_PROTOCOL,
        "latch=%s" % snapshot.get("latch", "error"),
        "message=%s" % snapshot.get("message", "unavailable"),
    ]
    if isinstance(target, Mapping):
        for key in ("interface", "local_ip", "gateway", "state", "error",
                    "clients", "rssi", "ap_ipv4", "adb", "adb_endpoint"):
            value = target.get(key)
            if value is None:
                value = "none"
            lines.append("target_%s=%s" % (key, value))
    else:
        lines.append("target=none")
    return "\n".join(lines) + "\n"


class _LocalStatusHandler(socketserver.BaseRequestHandler):
    """Bounded one-request handler for local status consumers."""

    def handle(self) -> None:
        server = self.server
        assert isinstance(server, LocalStatusServer)
        self.request.settimeout(server.request_timeout)
        try:
            request = self.request.recv(MAX_LOCAL_REQUEST_BYTES + 1)
        except (OSError, socket.timeout):
            return
        if len(request) > MAX_LOCAL_REQUEST_BYTES:
            self._reply("ERROR request_too_large\n")
            return
        try:
            command = request.decode("ascii").strip()
        except UnicodeDecodeError:
            self._reply("ERROR request_not_ascii\n")
            return
        snapshot = server.state_provider()
        if command in ("STATUS", "STATUS TEXT"):
            payload = _local_text(snapshot)
        elif command == "STATUS JSON":
            payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n"
        else:
            # There is intentionally no SET/EXEC/ADB command.  This service
            # only exposes the outbound latch state to local consumers.
            payload = "ERROR read_only_status\n"
        if len(payload.encode("utf-8")) > MAX_LOCAL_RESPONSE_BYTES:
            payload = "ERROR response_too_large\n"
        self._reply(payload)

    def _reply(self, payload: str) -> None:
        try:
            self.request.sendall(payload.encode("utf-8"))
        except OSError:
            return


class LocalStatusServer(socketserver.ThreadingTCPServer):
    """Loopback-only, bounded status server for local PC consumers."""

    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address: tuple[str, int],
                 state_provider: Callable[[], Mapping[str, object]],
                 max_clients: int = DEFAULT_MAX_CLIENTS,
                 request_timeout: float = 2.0) -> None:
        try:
            listen_ip = ipaddress.ip_address(address[0])
        except ValueError as exc:
            raise TelcoError("--listen must be a numeric loopback address") from exc
        if listen_ip.version != 4 or not listen_ip.is_loopback:
            raise TelcoError("PC status server must bind to IPv4 loopback")
        if not 1 <= max_clients <= 32:
            raise TelcoError("--max-clients must be between 1 and 32")
        if request_timeout <= 0 or request_timeout > 30:
            raise TelcoError("--request-timeout must be between 0 and 30 seconds")
        self.state_provider = state_provider
        self.max_clients = max_clients
        self.request_timeout = request_timeout
        self._client_slots = threading.BoundedSemaphore(max_clients)
        super().__init__(address, _LocalStatusHandler)

    def process_request(self, request: socket.socket,
                        client_address: object) -> None:
        if not self._client_slots.acquire(blocking=False):
            try:
                request.settimeout(self.request_timeout)
                # Drain only the bounded request prefix before replying. If
                # unread client bytes remain when close() runs, Linux may
                # reset the connection and discard ERROR busy.
                try:
                    request.recv(MAX_LOCAL_REQUEST_BYTES + 1)
                except (OSError, socket.timeout):
                    pass
                request.sendall(b"ERROR busy\n")
                request.shutdown(socket.SHUT_WR)
            except (OSError, socket.timeout):
                pass
            finally:
                request.close()
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request: socket.socket,
                               client_address: object) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            # Release the admission slot before closing the response socket.
            # A client that drains the bounded response through EOF can then
            # issue its next sequential request without racing this release.
            self._client_slots.release()
            self.shutdown_request(request)


def _emit(route: Route, status: Optional[Status], message: str,
          json_output: bool) -> None:
    if json_output:
        payload: dict[str, object] = {"message": message}
        if status is not None:
            payload.update(_status_payload(route, status))
        print(json.dumps(payload, sort_keys=True), flush=True)
    elif status is not None:
        rssi = "unknown" if status.rssi is None else str(status.rssi)
        adb = status.adb_endpoint or "off"
        print("3DS Telco: interface=%s gateway=%s state=%s error=%s clients=%d "
              "rssi=%s adb=%s" %
              (route.interface, route.gateway, status.state, status.error,
               status.clients, rssi, adb), flush=True)
    else:
        print("3DS Telco: %s" % message, flush=True)


def _error_route(args: argparse.Namespace) -> Route:
    return Route(args.interface or "unknown",
                 ipaddress.IPv4Network("0.0.0.0/0"),
                 ipaddress.IPv4Address(args.gateway))


def latch_loop(args: argparse.Namespace, state: LatchState,
               stop_event: threading.Event) -> None:
    """Keep the outbound target latch current until Ctrl-C/stop cleanup."""
    last_payload: Optional[str] = None
    adb_endpoint: Optional[str] = None
    while not stop_event.is_set():
        try:
            route = detect_route(args.gateway, args.interface)
            status = probe(route, args.gateway, args.status_port,
                           args.probe_timeout)
            state.update_connected(route, status)
            payload = json.dumps(_status_payload(route, status), sort_keys=True)
            if payload != last_payload:
                _emit(route, status, "reachable", args.json)
                last_payload = payload
            if args.adb:
                if status.adb_endpoint != adb_endpoint:
                    adb_endpoint = status.adb_endpoint
                    if adb_endpoint:
                        _emit(route, None, _adb_connect(args.adb_command,
                                                        adb_endpoint,
                                                        args.probe_timeout),
                              args.json)
        except (TelcoError, OSError) as exc:
            state.update_error(str(exc))
            adb_endpoint = None
            last_payload = None
            _emit(_error_route(args), None, str(exc), args.json)
        stop_event.wait(max(0.05, args.interval))


def run_service(args: argparse.Namespace,
                stop_event: Optional[threading.Event] = None) -> int:
    """Run the safe-default loopback server and outbound target latch."""
    stop = stop_event or threading.Event()
    state = LatchState()
    server = LocalStatusServer((args.listen, args.listen_port), state.snapshot,
                               max_clients=args.max_clients,
                               request_timeout=args.request_timeout)
    server_thread = threading.Thread(target=server.serve_forever,
                                     name="3ds-telco-local-status", daemon=True)
    latch_thread = threading.Thread(target=latch_loop,
                                    args=(args, state, stop),
                                    name="3ds-telco-target-latch", daemon=True)
    server_thread.start()
    latch_thread.start()
    print("3DS Telco PC service listening on %s:%d (STATUS/STATUS JSON; Ctrl-C stops)" %
          (args.listen, server.server_address[1]), flush=True)
    try:
        while not stop.wait(0.25):
            pass
    except KeyboardInterrupt:
        stop.set()
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        latch_thread.join(timeout=max(1.0, args.request_timeout + 1.0))
        server_thread.join(timeout=2.0)
    return 0


def _adb_connect(command: str, endpoint: str, timeout: float) -> str:
    try:
        result = subprocess.run([command, "connect", endpoint],
                                check=False, capture_output=True, text=True,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "ADB connect failed: %s" % exc
    output = (result.stdout or result.stderr or "").strip()
    # The endpoint is already displayed separately; avoid echoing arbitrary
    # command output into a log that an operator might later share.
    safe_output = " ".join(output.split())[:160]
    return "ADB connect %s%s" % ("succeeded" if result.returncode == 0 else
                                 "failed", ": " + safe_output if safe_output else "")


def monitor(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + args.timeout
    last_payload: Optional[str] = None
    adb_endpoint: Optional[str] = None
    while True:
        try:
            route = detect_route(args.gateway, args.interface)
            status = probe(route, args.gateway, args.status_port, args.probe_timeout)
            payload = json.dumps(_status_payload(route, status), sort_keys=True)
            if payload != last_payload or args.once:
                _emit(route, status, "reachable", args.json)
                last_payload = payload
            if args.adb:
                if status.adb_endpoint != adb_endpoint:
                    adb_endpoint = status.adb_endpoint
                    if adb_endpoint:
                        _emit(route, None, _adb_connect(args.adb_command,
                                                        adb_endpoint,
                                                        args.probe_timeout),
                              args.json)
            if args.once:
                return 0
        except (TelcoError, OSError) as exc:
            adb_endpoint = None
            if args.once:
                _emit(Route(args.interface or "unknown",
                            ipaddress.IPv4Network("0.0.0.0/0"),
                            ipaddress.IPv4Address(args.gateway)), None,
                      str(exc), args.json)
                return 1
            _emit(Route(args.interface or "unknown",
                        ipaddress.IPv4Network("0.0.0.0/0"),
                        ipaddress.IPv4Address(args.gateway)), None,
                  str(exc), args.json)
        if time.monotonic() >= deadline:
            return 1
        time.sleep(max(0.05, args.interval))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", help="interface name or local IPv4 address")
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY,
                        help="expected 3DS AP gateway (default: %(default)s)")
    parser.add_argument("--status-port", type=int, default=DEFAULT_STATUS_PORT)
    parser.add_argument("--listen", default=DEFAULT_LISTEN_ADDRESS,
                        help="local service listen address (loopback only; default: %(default)s)")
    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT,
                        help="local service listen port (default: %(default)s)")
    parser.add_argument("--max-clients", type=int, default=DEFAULT_MAX_CLIENTS,
                        help="maximum simultaneous local status clients")
    parser.add_argument("--request-timeout", type=float, default=2.0,
                        help="local status request timeout in seconds")
    parser.add_argument("--timeout", type=float, default=20.0,
                        help="overall wait before failure (seconds)")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="retry interval (seconds)")
    parser.add_argument("--probe-timeout", type=float, default=2.0,
                        help="individual route/status timeout (seconds)")
    parser.add_argument("--once", action="store_true",
                        help="probe once and return success/failure")
    parser.add_argument("--watch", action="store_true",
                        help="legacy console watcher without the local service")
    parser.add_argument("--json", action="store_true", help="emit JSON status lines")
    parser.add_argument("--adb", action="store_true",
                        help="opt in to adb connect only when target advertises it")
    parser.add_argument("--adb-command", default="adb",
                        help="adb executable (default: %(default)s)")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _address(args.gateway)
        _address(args.listen)
    except TelcoError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.status_port < 1 or args.status_port > 65535:
        print("invalid --status-port", file=sys.stderr)
        return 2
    if args.listen_port < 1 or args.listen_port > 65535:
        print("invalid --listen-port", file=sys.stderr)
        return 2
    if args.max_clients < 1 or args.max_clients > 32:
        print("invalid --max-clients", file=sys.stderr)
        return 2
    if args.request_timeout <= 0 or args.request_timeout > 30:
        print("invalid --request-timeout", file=sys.stderr)
        return 2
    try:
        if args.once or args.watch:
            return monitor(args)
        return run_service(args)
    except TelcoError as exc:
        print("3DS Telco: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("3DS Telco: stopped", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
