#!/usr/bin/env python3
"""Keep templates and persistent state inside sdcard/linux/android."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
ROOTS = (
    Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/rootfs_overlay"),
    HERE / "third_party/buildroot/board/nintendo3ds/rootfs_overlay",
    HERE / "sdcard/linux/android",
)


REPLACEMENTS = {
    'mount none /mnt/sd /sdcard bind':
        'mount none /mnt/sd/linux/android /sdcard bind',
    'CARD=/mnt/sd\nif [ -d /sdcard/android ]; then\n\tCARD=/sdcard\nfi\n\n'
    'ROOT="$CARD/android/persistent"':
        'PAYLOAD=/mnt/sd/linux/android\nROOT="$PAYLOAD/persistent"',
    'TEMPLATES="$CARD/android/templates"': 'TEMPLATES="$PAYLOAD/templates"',
    '[ -d "$CARD" ] && grep -q': '[ -d "$PAYLOAD" ] && grep -q',
    'secure_dir "$CARD/android"': 'secure_dir "$PAYLOAD"',
}


def update(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    patched = text
    for old, new in REPLACEMENTS.items():
        patched = patched.replace(old, new)
    if patched != text:
        path.write_text(patched, encoding="utf-8")
    return True


def main() -> None:
    found = 0
    for root in ROOTS:
        found += update(root / "etc/init.rc")
        found += update(root / "etc/android_prefs_init.sh")
    if not found:
        raise SystemExit("no Android payload layout files found")
    print("patch_android_payload_layout: templates/state live under linux/android")


if __name__ == "__main__":
    main()
