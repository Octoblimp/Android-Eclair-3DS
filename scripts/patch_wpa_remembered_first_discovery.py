#!/usr/bin/env python3
"""Ensure the remembered-first directed-scan Buildroot patch is applied.

The patch (0004-n3ds-remembered-first-discovery.patch) modifies
wpa_supplicant/scan.c to emit active probes for each enabled saved SSID
before the final wildcard discovery entry.  On a clean Buildroot extract
the patch is applied automatically from the package dir; on incremental
builds this script confirms the marker is present.

The package patch file is authoritative.  This script only validates
idempotence — it never modifies a source file that already carries the
marker.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

WSL_ROOT = Path(A3DS_ROOT)
ROOT = WSL_ROOT if (WSL_ROOT / "third_party").exists() else Path(__file__).resolve().parents[1]
BUILDROOT = ROOT / "third_party/buildroot"
PACKAGE_PATCH = (
    BUILDROOT
    / "package/wpa_supplicant/0004-n3ds-remembered-first-discovery.patch"
)
SCAN_C = BUILDROOT / "output/build/wpa_supplicant-2.10/wpa_supplicant/scan.c"
MARKER = "N3DS_REMEMBERED_FIRST_DISCOVERY"

if not PACKAGE_PATCH.is_file():
    raise SystemExit(f"missing package patch: {PACKAGE_PATCH}")
patch_text = PACKAGE_PATCH.read_text()
if MARKER not in patch_text:
    raise SystemExit(f"package patch is missing expected marker {MARKER!r}")

if SCAN_C.is_file():
    src = SCAN_C.read_text()
    if MARKER not in src:
        raise SystemExit(
            f"incremental source {SCAN_C} lacks {MARKER!r}; "
            "remove the build directory and let Buildroot reapply all patches"
        )
    print("patch_wpa_remembered_first_discovery: already applied")
else:
    # Clean-tree path: the package patch exists and will be applied by
    # Buildroot when the source tree is extracted.  Nothing more to do here.
    print(
        "patch_wpa_remembered_first_discovery: package patch present; "
        "will be applied on clean Buildroot extract"
    )
