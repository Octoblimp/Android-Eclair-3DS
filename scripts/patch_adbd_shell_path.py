#!/usr/bin/env python3
"""Point Eclair adbd at the shell provided by the Android3DS rootfs."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


SOURCE = Path(f"{A3DS_ROOT}/third_party/system_core/adb/services.c")
OLD = '#define SHELL_COMMAND "/system/bin/sh"'
NEW = '''/* N3DS_ADBD_ROOTFS_SHELL: Android is hosted below the Buildroot rootfs. */
#define SHELL_COMMAND "/bin/sh"'''


text = SOURCE.read_text()
if "N3DS_ADBD_ROOTFS_SHELL" not in text:
    if text.count(OLD) != 1:
        raise SystemExit("unexpected adbd SHELL_COMMAND definition")
    SOURCE.write_text(text.replace(OLD, NEW))
elif '#define SHELL_COMMAND "/bin/sh"' not in text:
    raise SystemExit("adbd shell marker exists without the expected /bin/sh path")

print("patch_adbd_shell_path: PASS")
