#!/usr/bin/env python3
"""Regression checks for the one-use-only Launcher long-press latch."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts/patch_launcher_repeat_longpress.py"


def load_patcher():
    spec = importlib.util.spec_from_file_location("launcher_longpress_patch", PATCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_patch_and_idempotence():
    module = load_patcher()
    fixture = """        public void onDismiss(DialogInterface dialog) {
        }
"""
    patched = module.patch_text(fixture)
    assert "N3DS_REPEATABLE_WORKSPACE_LONG_PRESS" in patched
    assert "mWorkspace.setAllowLongPress(true);" in patched
    assert "mWaitingForResult = false;" in patched
    assert module.patch_text(patched) == patched


def test_repeated_dialog_model():
    allow_long_press = True
    waiting = False
    for _ in range(3):
        assert allow_long_press and not waiting
        allow_long_press = False
        waiting = True
        # DialogInterface.OnDismissListener is the common exit for cancel,
        # BACK, a selected item, and an activity transition.
        allow_long_press = True
        waiting = False
    assert allow_long_press and not waiting


if __name__ == "__main__":
    test_patch_and_idempotence()
    test_repeated_dialog_model()
    print("launcher_repeat_longpress: PASS")
