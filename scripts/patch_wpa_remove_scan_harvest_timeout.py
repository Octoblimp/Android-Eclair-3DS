#!/usr/bin/env python3
"""Remove the generated supplicant timeout patch that existed for RAM harvest."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PACKAGE = Path(
    f"{A3DS_ROOT}/third_party/buildroot/package/wpa_supplicant/"
    "0002-n3ds-ar6014-scan-harvest-timeout.patch"
)

if PACKAGE.exists():
    PACKAGE.unlink()
    print(f"Removed obsolete RAM-harvest timeout patch: {PACKAGE}")
else:
    print("patch_wpa_remove_scan_harvest_timeout: already absent")
