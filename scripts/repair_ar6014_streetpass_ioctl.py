#!/usr/bin/env python3
"""Remove a previously applied AR6014 StreetPass ioctl probe patch.

This repair is intentionally limited to the canonical legacy driver source.
It uses the probe's stable marker and bounded anchors, so rerunning it is a
no-op after the StreetPass additions are gone.
"""

from __future__ import annotations
from a3ds_paths import A3DS_ROOT

import re
from pathlib import Path


DRIVER = (
    Path(A3DS_ROOT)
    / "third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
)
ROOT = DRIVER.parents[2]
DRIVER_HEADER = ROOT / "os/linux/include/ar6000_drv.h"
API_HEADER = ROOT / "include/a_drv_api.h"
LINUX_API_HEADER = ROOT / "os/linux/include/ar6xapi_linux.h"
WMI_SOURCE = ROOT / "wmi/wmi.c"
MARKER = "N3DS_AR6014_STREETPASS_PROBE_ABI"


def remove_once(text: str, pattern: str, label: str) -> str:
    updated, count = re.subn(pattern, "", text, count=1, flags=re.M | re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marked block, found {count}")
    return updated


def repair(text: str) -> str:
    # Recover two shapes produced by the first (withdrawn) repair revision.
    text = text.replace(
        "    .ndo_set_rx_mode        = ar6000_set_multicast_list,};\n"
        "    .ndo_do_ioctl           = ar6000_ioctl,\n",
        "    .ndo_set_rx_mode        = ar6000_set_multicast_list,\n};\n",
        1,
    )
    if "\nvoid\nar6000_bssInfo_event_rx" not in text:
        text = text.replace(
            "\n(struct ar6_softc *ar, u8 *datap, int len)\n",
            "\nvoid\nar6000_bssInfo_event_rx"
            "(struct ar6_softc *ar, u8 *datap, int len)\n",
            1,
        )
    if MARKER not in text and "ar6000_streetpass_ioctl" not in text:
        return text

    text = remove_once(
        text,
        r"\n/\* N3DS_AR6014_STREETPASS_PROBE_ABI \*/\n"
        r"static int ar6000_streetpass_ioctl\([^;]+;\n",
        "StreetPass ioctl declaration",
    )
    text = remove_once(
        text,
        r"\n    \.ndo_do_ioctl\s*=\s*ar6000_streetpass_ioctl,\n",
        "StreetPass netdev callback",
    )
    text = remove_once(
        text,
        r"\n    unsigned long flags;\n\s*netif_stop_queue\(dev\);\n\n"
        r"    /\* N3DS_AR6014_STREETPASS_PROBE_ABI: optional mode and queued\n"
        r"     \* peer frames must not survive interface teardown\. \*/\n"
        r".*?    spin_unlock_irqrestore\(&ar->arLock, flags\);\n\n"
        r"    ar6000_disconnect\(ar\);",
        "StreetPass close cleanup",
    )
    text = remove_once(
        text,
        r"\nstatic bool n3ds_streetpass_channel_valid\(u16 mhz\).*?"
        r"\nvoid\nar6000_bssInfo_event_rx",
        "StreetPass ioctl implementation",
    )

    # The canonical legacy driver baseline uses wireless_handlers and has no
    # ndo_do_ioctl slot. Remove the retired private callback completely.
    text = re.sub(
        r"^[ \t]*\.ndo_do_ioctl\s*=.*\n",
        "",
        text,
        flags=re.M,
    )
    if re.search(r"streetpass.*ioctl|ioctl.*streetpass", text, re.I):
        raise RuntimeError("StreetPass ioctl symbol remains after repair")
    return text


def main() -> None:
    if not DRIVER.is_file():
        raise SystemExit(f"missing canonical AR6014 driver source: {DRIVER}")
    original = DRIVER.read_text(encoding="utf-8", errors="replace")
    updated = repair(original)
    if updated != original:
        DRIVER.write_text(updated, encoding="utf-8")
        print("repair_ar6014_streetpass_ioctl: repaired")
    else:
        print("repair_ar6014_streetpass_ioctl: already clean")

    header = DRIVER_HEADER.read_text(encoding="utf-8", errors="replace")
    header = re.sub(
        r"\n/\* N3DS_AR6014_STREETPASS_PROBE_ABI:.*?"
        r"\nstruct ar6_softc \{\n",
        "\nstruct ar6_softc {\n",
        header,
        count=1,
        flags=re.S,
    )
    header = re.sub(
        r"    bool[ \t]+streetpass_enabled;.*?"
        r"[ \t]+streetpass_rx\[N3DS_STREETPASS_RX_SLOTS\];\n",
        "",
        header,
        count=1,
        flags=re.S,
    )
    DRIVER_HEADER.write_text(header, encoding="utf-8")

    api = API_HEADER.read_text(encoding="utf-8", errors="replace")
    api = re.sub(
        r"\n/\* N3DS_AR6014_STREETPASS_PROBE_ABI \*/\n"
        r"#define A_WMI_OPT_FRAME_EVENT_RX.*?\n[ \t]+ar6000_streetpass_opt_event_rx.*?\n",
        "",
        api,
        count=1,
        flags=re.S,
    )
    API_HEADER.write_text(api, encoding="utf-8")

    linux_api = LINUX_API_HEADER.read_text(encoding="utf-8", errors="replace")
    linux_api = re.sub(
        r"/\* N3DS_AR6014_STREETPASS_PROBE_ABI \*/\n"
        r"void ar6000_streetpass_opt_event_rx\([^;]+;\n",
        "",
        linux_api,
        count=1,
    )
    LINUX_API_HEADER.write_text(linux_api, encoding="utf-8")

    wmi = WMI_SOURCE.read_text(encoding="utf-8", errors="replace")
    wmi = re.sub(
        r"    /\* N3DS_AR6014_STREETPASS_PROBE_ABI: deliver.*?"
        r"    A_WMI_OPT_FRAME_EVENT_RX\([^\n]+\);\n",
        "",
        wmi,
        count=1,
        flags=re.S,
    )
    wmi = re.sub(
        r"    /\* N3DS_AR6014_STREETPASS_PROBE_ABI: never overrun.*?"
        r"        return A_EINVAL;\n",
        "",
        wmi,
        count=1,
        flags=re.S,
    )
    WMI_SOURCE.write_text(wmi, encoding="utf-8")


if __name__ == "__main__":
    main()
