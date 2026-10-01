#!/usr/bin/env python3
"""Publish non-secret managed and raw transport templates to SD staging.

Only the release-managed templates directory is updated.  The persistent
namespace is deliberately absent from this script and is never overwritten.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGED_SOURCE = ROOT / "streetpass_bridge/templates/streetpass-transport.conf.example"
MANAGED_DEST = ROOT / "sdcard/linux/android/templates/streetpass-transport.conf.example"
RAW_SOURCE = ROOT / "streetpass_bridge/templates/streetpass-radio.conf.example"
RAW_DEST = ROOT / "sdcard/linux/android/templates/streetpass-radio.conf.example"


def main() -> None:
    template = MANAGED_SOURCE.read_text(encoding="utf-8")
    if "YOUR_MAC_ADDRESS" not in template or "YOUR_PC_IPV4_ADDRESS" not in template:
        raise SystemExit("managed transport template lost its non-secret placeholders")
    raw = RAW_SOURCE.read_text(encoding="utf-8")
    if "YOUR_PC_WIFI_MAC" not in raw or "interface=wlan0" not in raw:
        raise SystemExit("raw transport template lost its peer/interface placeholders")
    MANAGED_DEST.parent.mkdir(parents=True, exist_ok=True)
    MANAGED_DEST.write_text(template, encoding="utf-8")
    RAW_DEST.write_text(raw, encoding="utf-8")
    print(f"transport templates installed: {MANAGED_DEST}, {RAW_DEST}")


if __name__ == "__main__":
    main()
