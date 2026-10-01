#!/usr/bin/env python3
"""Acceptance contract for the directed, infrastructure-free StreetPass path.

This is intentionally a source/build contract rather than a hardware claim.
The ath6kl implementation is required to expose a bounded raw-frame boundary
before this test can pass; ordinary cfg80211 association and the managed-TCP
engineering tunnel are not substitutes.
"""

from __future__ import annotations
from a3ds_paths import A3DS_ROOT, A3DS_WIN

import hashlib
import re
from pathlib import Path


ROOT = Path(A3DS_ROOT)
WIN_ROOT = Path(A3DS_WIN)
KCONFIG = ROOT / "third_party/linux/.config"
RADIO = WIN_ROOT / "native/streetpassd/streetpass_radio.c"
DAEMON = WIN_ROOT / "native/streetpassd/streetpassd.c"
LED = WIN_ROOT / "native/streetpassd/streetpass_led.c"
LED_TEST = WIN_ROOT / "scripts/test_streetpass_led.py"
INIT_INTEGRATION = WIN_ROOT / "sdcard/linux/android/etc/init.rc"
REBUILD = WIN_ROOT / "scripts/rebuild_everything.sh"
SYNC = ROOT / "scripts/sync_android_to_sdcard.sh"
BUILD_KERNEL = ROOT / "scripts/build_kernel.sh"
BUILD_DAEMON = WIN_ROOT / "scripts/build_streetpassd.sh"
TASKS = WIN_ROOT / "TASKS.md"
README = WIN_ROOT / "streetpass_bridge/README.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read(path: Path) -> str:
    require(path.is_file(), f"missing acceptance input: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_no_association_or_ip() -> None:
    daemon = read(DAEMON)
    radio = read(RADIO)
    init = read(INIT_INTEGRATION)
    tasks = read(TASKS)
    readme = read(README)
    kconfig = read(KCONFIG)

    # Production selects the bounded optional-probe backend and its persistent
    # directed-peer config; managed TCP remains engineering-only.
    require("--backend raw80211" in init, "production init omits the probe backend")
    require("streetpass-radio.conf" in init, "production init omits raw peer config")
    require("--backend managed" not in init, "production init selects managed TCP")
    require("infrastructure-free" in tasks, "active package lost raw-radio objective")
    require("do not require DHCP" in tasks, "active package lost no-DHCP invariant")
    require("not Nintendo StreetPass" in readme, "managed tunnel limitation is undocumented")
    require("CONFIG_ATH6K_LEGACY=y" in kconfig,
            "defconfig no longer selects the deployable AR6014 driver")
    require("# CONFIG_ATH6KL is not set" in kconfig,
            "test accidentally treats upstream ath6kl as deployed")

    # The raw backend may not call the ordinary AF_INET connector. This also
    # guards against accidentally routing the new path through managed TCP.
    managed_call = radio.find("connect_managed(radio)")
    raw_branch = re.search(r"if \(kind != SP_RADIO_MANAGED_TCP\).*?\n\s*}", radio, re.S)
    require(managed_call >= 0 and raw_branch is not None,
            "raw/managed backend boundary is not explicit")
    require(managed_call > raw_branch.end(),
            "raw branch reaches managed connector")
    require("udhcpc" not in daemon and "wpa_cli" not in daemon,
            "streetpassd acquired an IP-association helper")


def test_led_and_pipeline_contract() -> None:
    daemon = read(DAEMON)
    led = read(LED)
    led_test = read(LED_TEST)
    rebuild = read(REBUILD)
    sync = read(SYNC)
    build_kernel = read(BUILD_KERNEL)
    build_daemon = read(BUILD_DAEMON)

    require("SP_STATE_DISABLED" in led and "SP_LED_OFF" in led,
            "disabled LED transition is missing")
    require("SP_STATE_DEGRADED" in led and "SP_LED_SLOW_GREEN" in led,
            "degraded LED transition is missing")
    require("SP_STATE_EXCHANGING" in led and "SP_LED_SOLID_GREEN" in led,
            "authenticated LED transition is missing")
    require("sp_led_close(&led);" in daemon and "2d.mcu-led" in led_test,
            "hinge LED cleanup/device regression is not wired")

    require("run test_ar6014_streetpass_direct.py" in rebuild,
            "directed StreetPass regression is absent from clean rebuild")
    require("-rtLc --delete" in sync,
            "staging sync is not checksum-based and delete-safe")
    require("cp \"$K/arch/arm/boot/zImage\" \"$WIN_SD/zImage\"" in build_kernel,
            "kernel staging does not publish the Windows card mirror")
    require("cp \"$OUT/streetpassd\" \"$WIN_CARD/streetpassd\"" in build_daemon,
            "daemon staging does not publish the Windows card mirror")


def test_patch_idempotence_contract() -> None:
    rebuild = read(REBUILD)
    patch_names = re.findall(r"run (patch_ar6014_[a-z0-9_]+\.py)", rebuild)
    require(patch_names, "no ath6kl patch scripts are in the clean pipeline")
    for name in sorted(set(patch_names)):
        path = WIN_ROOT / "scripts" / name
        text = read(path)
        markers = re.findall(
            r"^\s*((?:[A-Z][A-Z0-9_]*_MARKER)|MARKER)\s*=", text, re.M
        )
        require(markers, f"{name} has no idempotence marker declaration")
        require(any(f"{marker} in text" in text or f"{marker} not in text" in text
                    for marker in markers),
                f"{name} has no already-patched fast path")
    require(rebuild.index("run test_ar6014_streetpass_direct.py") >
            rebuild.index("run patch_ar6014_2ghz_scan.py"),
            "directed StreetPass regression is ordered before ath6kl patches")


def test_staged_hashes_when_present() -> None:
    pairs = (
        (ROOT / "sdcard/linux/zImage", WIN_ROOT / "sdcard/linux/zImage"),
        (ROOT / "sdcard/linux/android/system/bin/streetpassd",
         WIN_ROOT / "sdcard/linux/android/system/bin/streetpassd"),
    )
    for left, right in pairs:
        if left.exists() and right.exists():
            require(sha256(left) == sha256(right), f"staging drift: {left} != {right}")


def main() -> None:
    test_no_association_or_ip()
    test_led_and_pipeline_contract()
    test_patch_idempotence_contract()
    test_staged_hashes_when_present()
    print("ar6014_streetpass_direct: PASS")


if __name__ == "__main__":
    main()
