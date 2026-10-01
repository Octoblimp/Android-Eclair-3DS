#!/usr/bin/env python3
"""Ensure only the bounded Mobile Data netdev ioctl survives rebuilds."""

from __future__ import annotations
from a3ds_paths import A3DS_ROOT

import re
from pathlib import Path


DRIVER = (
    Path(A3DS_ROOT)
    / "third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
)


def main() -> None:
    if not DRIVER.is_file():
        raise SystemExit(f"missing canonical AR6014 driver source: {DRIVER}")

    source = DRIVER.read_text(encoding="utf-8", errors="replace")
    ioctl_assignments = re.findall(
        r"\.ndo_do_ioctl\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*,", source
    )
    expected = (["ar6000_ioctl"] if
                "N3DS_AR6014_MOBILE_DATA_DIRECT_IOCTL" in source else [])
    if ioctl_assignments != expected:
        raise AssertionError(
            "canonical AR6014 has an unexpected ndo_do_ioctl contract; "
            f"unexpected assignments: {ioctl_assignments!r}"
        )

    forbidden = re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*streetpass[A-Za-z0-9_]*ioctl[A-Za-z0-9_]*\b",
        source,
        flags=re.IGNORECASE,
    )
    for marker in (
        "N3DS_AR6014_STREETPASS_PROBE_ABI",
        "N3DS_STREETPASS_IOCTL",
        "ar6000_streetpass_opt_event_rx",
    ):
        if marker in source:
            forbidden.append(marker)
    if forbidden:
        raise AssertionError(
            "retired StreetPass ioctl/probe symbols remain in canonical "
            f"AR6014 source: {sorted(set(forbidden))!r}"
        )

    print("ar6014_ioctl_contract: PASS")


if __name__ == "__main__":
    main()
