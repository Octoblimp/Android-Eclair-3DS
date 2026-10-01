"""Fetch Eclair-era (android-goldfish-2.6.29, the only surviving branch with
these files) Android OS-layer kernel sources for backport onto the real
New 3DS 5.11 tree. These are hardware-agnostic OS subsystems (logging,
low-memory killer, wakelocks/early-suspend, the /dev/alarm ABI) -- nothing
goldfish/emulator-specific is fetched. Not deployed anywhere on its own;
this is reference source for manual porting.
"""
from a3ds_paths import A3DS_ROOT
import base64
import subprocess
import os

BASE = "https://android.googlesource.com/kernel/goldfish/+/refs/heads/android-goldfish-2.6.29"
OUT = f"{A3DS_ROOT}/scratch/android2629"

files = [
    "drivers/staging/android/lowmemorykiller.c",
    "drivers/staging/android/lowmemorykiller.txt",
    "kernel/power/wakelock.c",
    "kernel/power/earlysuspend.c",
    "kernel/power/userwakelock.c",
    "kernel/power/power.h",
    "drivers/rtc/alarm.c",
    "include/linux/android_alarm.h",
    "include/linux/android_power.h",
    "include/linux/earlysuspend.h",
    "include/linux/wakelock.h",
]

os.makedirs(OUT, exist_ok=True)

for f in files:
    url = f"{BASE}/{f}?format=TEXT"
    r = subprocess.run(["curl", "-sS", "--max-time", "20", url], capture_output=True)
    if r.returncode != 0 or not r.stdout.strip():
        print(f"FAILED: {f} (rc={r.returncode})")
        continue
    try:
        content = base64.b64decode(r.stdout)
    except Exception as e:
        print(f"DECODE FAILED: {f}: {e}")
        continue
    outname = f.replace("/", "__")
    with open(os.path.join(OUT, outname), "wb") as fh:
        fh.write(content)
    print(f"{f} -> {outname} ({len(content.splitlines())} lines)")
