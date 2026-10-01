#!/usr/bin/env python3
"""Install the StreetPass service definition idempotently in the WSL overlay."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


MARKER = "# ANDROID3DS_STREETPASSD_SERVICE"
SERVICE = f"""\n{MARKER}\nservice streetpassd /system/bin/streetpassd --backend unavailable\n    class default\n    user root\n    group root\n\n"""


def update(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text()
    # patch_streetpass_init.py owns the lifecycle block. Never append a
    # daemon-only definition beside an existing service.
    if "service streetpassd " in text:
        return False
    if MARKER in text:
        return False
    path.write_text(text.rstrip() + SERVICE)
    return True


def main() -> None:
    candidates = [
        Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/init.rc"),
        Path(__file__).resolve().parents[1]
        / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/init.rc",
    ]
    changed = False
    for path in candidates:
        changed = update(path) or changed
    if not any(path.is_file() and MARKER in path.read_text() for path in candidates):
        raise SystemExit("integrate_streetpassd_overlay: no init.rc source found")
    print("integrate_streetpassd_overlay: " + ("updated" if changed else "already present"))


if __name__ == "__main__":
    main()
