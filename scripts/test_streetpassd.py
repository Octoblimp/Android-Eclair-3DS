#!/usr/bin/env python3
"""Build and run the host-side StreetPass protocol/journal regression tests."""

import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "native" / "streetpassd"


def require(text: str, marker: str, label: str) -> None:
    if marker not in text:
        raise AssertionError(f"{label}: missing {marker!r}")


def main() -> None:
    daemon = (SRC / "streetpassd.c").read_text(encoding="utf-8")
    radio = (SRC / "streetpass_radio.c").read_text(encoding="utf-8")
    radio_header = (SRC / "streetpass_radio.h").read_text(encoding="utf-8")
    config = (SRC / "streetpass_config.c").read_text(encoding="utf-8")
    session = (SRC / "streetpass_session.c").read_text(encoding="utf-8")
    for marker in (
        "persist.sys.streetpass.enabled",
        "persist.sys.streetpass.adb",
        "sp_session_receive",
        "sp_session_is_authenticated",
        "sp_adb_proxy_connect",
        "/tmp/streetpass/key",
        "key-material-unavailable",
        "streetpass-transport.conf",
        "SP_RADIO_MANAGED_TCP",
    ):
        require(daemon, marker, "streetpassd contract")
    require(radio, "SP_RADIO_RAW80211", "raw directed-probe backend")
    require(radio, "N3DS_STREETPASS_IOCTL", "ath6kl probe ioctl")
    require(radio, "memcmp(request.peer_mac", "raw peer defense-in-depth")
    require(radio, "Nintendo_3DS_continuous_scan_000", "probe SSID")
    require(radio, "SP_MANAGED_IDENTITY_SIZE", "managed identity preamble")
    require(radio_header, "SP_MANAGED_CONNECT_TIMEOUT_MS", "bounded managed connect")
    require(radio, "poll", "bounded managed connect")
    require(radio, "SO_ERROR", "managed connect result validation")
    require(radio, "EINTR", "managed connect interrupt handling")
    require(config, "sp_parse_mac_address", "strict managed config")
    require(config, "sp_load_raw_config", "strict raw config")
    require(session, "delayed ACKs are harmless", "cumulative ACK contract")
    compiler = os.environ.get("CC", "gcc")
    with tempfile.TemporaryDirectory(prefix="streetpass-test-") as tmp:
        binary = pathlib.Path(tmp) / "streetpass_protocol_test"
        command = [
            compiler,
            "-std=c99",
            "-D_DEFAULT_SOURCE",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-I",
            str(SRC),
            str(SRC / "streetpass_protocol.c"),
            str(SRC / "streetpass_config.c"),
            str(SRC / "streetpass_journal.c"),
            str(SRC / "streetpass_radio.c"),
            str(SRC / "streetpass_adb_proxy.c"),
            str(SRC / "streetpass_session.c"),
            str(SRC / "streetpass_protocol_test.c"),
            "-o",
            str(binary),
        ]
        subprocess.run(command, check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
