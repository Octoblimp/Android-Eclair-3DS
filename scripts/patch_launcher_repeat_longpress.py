#!/usr/bin/env python3
"""Restore Launcher workspace long-press state after the Add dialog closes."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


LAUNCHER = Path(
    f"{A3DS_ROOT}/third_party/launcher2/src/com/android/launcher2/Launcher.java"
)
MARKER = "N3DS_REPEATABLE_WORKSPACE_LONG_PRESS"


def patch_text(text: str) -> str:
    if MARKER in text:
        return text
    old = """        public void onDismiss(DialogInterface dialog) {
        }
"""
    new = """        public void onDismiss(DialogInterface dialog) {
            /* N3DS_REPEATABLE_WORKSPACE_LONG_PRESS: onLongClick() disables
             * workspace long presses before opening this dialog.  Eclair's
             * original empty callback never restored that latch, so the
             * menu worked exactly once for the life of Launcher. */
            mWorkspace.setAllowLongPress(true);
            mWaitingForResult = false;
        }
"""
    if text.count(old) != 1:
        raise RuntimeError(
            "expected one empty CreateShortcut.onDismiss callback, found "
            + str(text.count(old))
        )
    return text.replace(old, new, 1)


def main() -> None:
    if not LAUNCHER.exists():
        raise SystemExit(f"missing canonical Launcher source: {LAUNCHER}")
    original = LAUNCHER.read_text(encoding="utf-8")
    patched = patch_text(original)
    if patched != original:
        LAUNCHER.write_text(patched, encoding="utf-8")
    print("patch_launcher_repeat_longpress: repeatable Add dialog installed")


if __name__ == "__main__":
    main()
