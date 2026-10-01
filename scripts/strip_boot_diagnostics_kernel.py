#!/usr/bin/env python3
"""Kernel-side half of the "stop paying for diagnostics we don't use" pass.

Per user direction (2026-08-04): WiFi is parked (Phase 2), yet every boot
still pays for it -- the legacy ath6k driver power-cycles the chip, runs a
full SDIO enumeration, then dumps ~250 lines of AR6002 DUMP/PROBE/DIAG
instrumentation into the kernel log before finally failing on a missing
firmware file. That is log space, SDIO transactions, RAM for the driver's
buffers and real boot time spent on a subsystem nothing uses.

Changes:
  CONFIG_ATH6K_LEGACY   y -> n   the whole legacy AR6002 driver
  CONFIG_MMC_DEBUG      y -> n   per-command mmc debug spam
  CONFIG_DETECT_HUNG_TASK  n -> y  so a task blocked in D state for 120s is
                                   reported with a backtrace. The lockups
                                   this project keeps hitting print soft-lockup
                                   BUGs for *spinning* tasks only; anything
                                   stuck in uninterruptible sleep is currently
                                   invisible, which is half the search space.

Everything here is a one-line revert if WiFi work resumes.
"""
from a3ds_paths import A3DS_ROOT
import re
import sys

CONFIG = f"{A3DS_ROOT}/third_party/linux/.config"

WANT = {
    "CONFIG_ATH6K_LEGACY": None,          # None => "# CONFIG_x is not set"
    "CONFIG_MMC_DEBUG": None,
    "CONFIG_DETECT_HUNG_TASK": "y",
    "CONFIG_DEFAULT_HUNG_TASK_TIMEOUT": "120",
    "CONFIG_BOOTPARAM_HUNG_TASK_PANIC": None,
}

lines = open(CONFIG).read().splitlines()
seen = set()
out = []

for line in lines:
    m = re.match(r"^(?:# )?(CONFIG_[A-Z0-9_]+)(?: is not set|=)", line)
    key = m.group(1) if m else None
    if key in WANT:
        seen.add(key)
        val = WANT[key]
        out.append("# %s is not set" % key if val is None
                   else "%s=%s" % (key, val))
    else:
        out.append(line)

for key, val in WANT.items():
    if key not in seen:
        out.append("# %s is not set" % key if val is None
                   else "%s=%s" % (key, val))

open(CONFIG, "w").write("\n".join(out) + "\n")

for key in WANT:
    for line in out:
        if line.startswith(key + "=") or line == "# %s is not set" % key:
            print(line)
            break
