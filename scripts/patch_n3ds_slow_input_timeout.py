#!/usr/bin/env python3
"""Give the 105 MHz ARM11 enough time to finish key dispatch work.

Eclair's five-second activity key timeout is calibrated for contemporary
phones.  On this software-rendered single-core port, normal Launcher drawing
and Binder work can exceed it, producing a false Launcher2 ANR before the
selected Settings activity can appear.  The instrumentation timeout already
uses 60 seconds; use 30 seconds for ordinary activities on this target.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


AMS = Path(f"{A3DS_ROOT}/third_party/frameworks/base/services/java/com/android/server/am/ActivityManagerService.java")

text = AMS.read_text()
old = "    static final int KEY_DISPATCHING_TIMEOUT = 5*1000;\n"
new = (
    "    // N3DS_SLOW_CPU_KEY_DISPATCH_TIMEOUT: avoid false Launcher ANRs on\n"
    "    // the 105 MHz ARM11 while software rendering/Binder work completes.\n"
    "    static final int KEY_DISPATCHING_TIMEOUT = 30*1000;\n"
)
if "N3DS_SLOW_CPU_KEY_DISPATCH_TIMEOUT" not in text:
    if text.count(old) != 1:
        raise SystemExit("slow input timeout: expected Eclair 5-second constant once")
    text = text.replace(old, new, 1)

if "static final int KEY_DISPATCHING_TIMEOUT = 30*1000;" not in text:
    raise SystemExit("slow input timeout: 30-second constant absent")
AMS.write_text(text)

print("patch_n3ds_slow_input_timeout: activity key timeout 5s -> 30s")
