#!/usr/bin/env python3
"""Static contract checks for managed StreetPass transport integration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(text: str, marker: str, label: str) -> None:
    if marker not in text:
        raise AssertionError(f"{label}: missing {marker!r}")


def main() -> None:
    config = (ROOT / "streetpass_bridge/config.py").read_text(encoding="utf-8")
    server = (ROOT / "streetpass_bridge/server.py").read_text(encoding="utf-8")
    transport = (ROOT / "streetpass_bridge/transport.py").read_text(encoding="utf-8")
    native = (ROOT / "native/streetpassd/streetpass_radio.c").read_text(encoding="utf-8")
    native_header = (ROOT / "native/streetpassd/streetpass_radio.h").read_text(encoding="utf-8")
    prefs_source = (ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/android_prefs_init.sh").read_text(encoding="utf-8")
    prefs_staged = (ROOT / "sdcard/linux/android/etc/android_prefs_init.sh").read_text(encoding="utf-8")
    sync = (ROOT / "scripts/sync_android_to_sdcard.sh").read_text(encoding="utf-8")
    template = (ROOT / "streetpass_bridge/templates/streetpass-transport.conf.example").read_text(encoding="utf-8")
    staged_template = (ROOT / "sdcard/linux/android/templates/streetpass-transport.conf.example").read_text(encoding="utf-8")
    readme = (ROOT / "streetpass_bridge/README.md").read_text(encoding="utf-8")

    for marker in ("parse_mac", "managed-tcp-v1", "endpoint", "MAX_CONFIG_BYTES"):
        require(config, marker, "managed config")
    for marker in ("ManagedTransportFactory", "_handle_managed_peer", "127.0.0.1", "managed_config"):
        require(server, marker, "managed server")
    for marker in ("SPM1", "build_managed_identity", "parse_managed_identity", "MAX_PACKET_SIZE"):
        require(transport, marker, "managed framing")
    for marker in ("SP_RADIO_MANAGED_TCP", "SP_MANAGED_IDENTITY_SIZE", "SP_TUNNEL_MAX_FRAME"):
        require(native, marker, "native managed radio")
    require(native_header, "SP_MANAGED_CONNECT_TIMEOUT_MS", "bounded native connect")
    require(server, "16..64 raw bytes", "host key bound")
    require(readme, "The host and", "key documentation")
    require(readme, "target both accept exactly 16–64 raw bytes", "key documentation")
    require(readme, "/mnt/sd/linux/android/persistent/secure/streetpass.key", "SD key provisioning documentation")
    require(readme, "/tmp/streetpass/key", "RAM key provisioning documentation")
    require(readme, "FAT-backed", "SD key trust-boundary documentation")
    require(readme, "Copy-Item", "Windows key provisioning documentation")
    assert "/data/misc/streetpass/key" not in readme
    assert "16–4096" not in readme and "16..4096" not in readme
    assert prefs_source == prefs_staged, "source/staged persistence service drifted"
    require(prefs_source, "PERSIST_STREETPASS_TRANSPORT", "persistent managed config")
    require(sync, "PERSISTENT_STATE", "persistent sync exclusion")
    rsync_lines = [line for line in sync.splitlines() if "rsync" in line]
    assert not any("$DEST/persistent" in line for line in rsync_lines)
    assert template == staged_template
    assert "YOUR_MAC_ADDRESS" in template and "YOUR_PC_IPV4_ADDRESS" in template
    assert "key=" not in template and "psk=" not in template
    print("streetpass_managed: PASS")


if __name__ == "__main__":
    main()
