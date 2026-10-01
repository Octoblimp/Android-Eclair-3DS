#!/usr/bin/env python3
"""Reject obsolete 3DSTelco registration paths in source mirrors."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
REL = Path("content/stock-app-overlays/Phone/src/com/android/phone/TelcoService.java")
TARGETS = [HERE / REL, Path(A3DS_ROOT) / REL]
CANONICAL = "/sdcard/persistent/shared/mobile_registration.conf"
OBSOLETE = (
    "/sdcard/linux/mobile_registration.conf",
    "/sdcard/linux/android/persistent/shared/mobile_registration.conf",
)


found = False
for path in dict.fromkeys(TARGETS):
    if not path.is_file():
        continue
    found = True
    content = path.read_text(encoding="utf-8")
    for old in OBSOLETE:
        content = content.replace(old, CANONICAL)
    if CANONICAL not in content:
        raise SystemExit(f"canonical registration path missing: {path}")
    if any(old in content for old in OBSOLETE):
        raise SystemExit(f"obsolete registration path remains: {path}")
    path.write_text(content, encoding="utf-8")
    print(f"patch_telco_service: canonical registration path ready in {path}")

if not found:
    raise SystemExit("patch_telco_service: no TelcoService source found")
