#!/usr/bin/env python3
"""Remove windowContentOverlay shadow artifact on Nintendo 3DS 320x240 screen."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(f"{A3DS_ROOT}/third_party/frameworks/base")
THEMES = ROOT / "core/res/res/values/themes.xml"

text = THEMES.read_text()
if "N3DS_NO_WINDOW_CONTENT_OVERLAY" not in text:
    old_overlay = """        <item name="windowContentOverlay">@android:drawable/title_bar_shadow</item>"""
    new_overlay = """        <!-- N3DS_NO_WINDOW_CONTENT_OVERLAY: on 320x240 display, title_bar_shadow
             creates an 8px dark/reddish shadow strip below the status bar.
             Disable it for a clean, seamless desktop and application view. -->
        <item name="windowContentOverlay">@null</item>"""
    if old_overlay in text:
        text = text.replace(old_overlay, new_overlay, 1)
        THEMES.write_text(text)
        print("themes.xml: windowContentOverlay set to @null")
    else:
        print("themes.xml: windowContentOverlay anchor not found")
else:
    print("themes.xml: already patched with N3DS_NO_WINDOW_CONTENT_OVERLAY")
