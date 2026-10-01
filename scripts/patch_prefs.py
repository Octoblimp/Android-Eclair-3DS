#!/usr/bin/env python3
"""Compatibility entry point for the reviewed update-safe preferences patch.

Antigravity's original version edited only the WSL overlay and attempted a
target-side settings database mutation with a binary that is not shipped.
Keep the old command name harmless for anyone with it in local notes.
"""

from pathlib import Path
import runpy


runpy.run_path(
    str(Path(__file__).with_name("patch_update_safe_prefs.py")),
    run_name="__main__",
)
