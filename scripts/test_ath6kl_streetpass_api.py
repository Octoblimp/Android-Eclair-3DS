#!/usr/bin/env python3
"""Check the canonical ath6k_legacy source boundary and raw config contract.

This verifier intentionally does not substitute another driver mirror when the
WSL/build tree is unavailable.  Exit status 2 is a source-access blocker.
"""

from __future__ import annotations
from a3ds_paths import A3DS_ROOT

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = Path(
    f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy"
)
DOC = ROOT / "docs" / "ATH6KL_STREETPASS_API.md"
RAW_TEMPLATE = ROOT / "streetpass_bridge" / "raw-radio-config.example"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    doc = DOC.read_text(encoding="utf-8")
    raw_template = RAW_TEMPLATE.read_text(encoding="ascii")
    for marker in (
        "CONFIG_ATH6K_LEGACY=y",
        "ath6k_legacy",
        "mgmt_tx",
        "Remain-on-channel",
        "peer_mac=e0:c2:64:00:53:86",
        "--raw-config",
    ):
        require(marker in doc, f"documentation missing {marker!r}")
    require("scratch" not in doc.lower(), "documentation contains stale corpus reference")
    for marker in ("schema=1", "interface=", "peer_mac=e0:c2:64:00:53:86", "channel=1"):
        require(marker in raw_template, f"raw template missing {marker!r}")
    for forbidden in ("endpoint=", "port=", "protocol="):
        require(forbidden not in raw_template, f"raw template contains {forbidden!r}")

    if not CANONICAL.is_dir():
        print(
            "ath6kl_streetpass_api: BLOCKED: canonical source unavailable: "
            f"{CANONICAL}",
            file=sys.stderr,
        )
        return 2

    source_files = tuple(CANONICAL.rglob("*.c")) + tuple(CANONICAL.rglob("*.h"))
    require(source_files, f"canonical source has no C/H files: {CANONICAL}")
    source = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in source_files)
    findings = {
        "mgmt_tx": "mgmt_tx" in source,
        "remain_on_channel": "remain_on_channel" in source,
        "cancel_remain_on_channel": "cancel_remain_on_channel" in source,
        "WMI_OPT": "WMI_OPT" in source,
    }
    print(f"ath6kl_streetpass_api: canonical={CANONICAL}")
    print("ath6kl_streetpass_api: capability tokens=" + repr(findings))
    print("ath6kl_streetpass_api: PASS (source available; tokens require manual ABI review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
