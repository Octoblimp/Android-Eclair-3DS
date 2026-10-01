#!/usr/bin/env python3
"""Make the supplicant's first-attempt death legible, and stop causing it.

Two defects, both of which have hidden themselves for several boots:

1. The pre-fork diagnostics (identity, ctrl_interface= line, ls -ld of the
   three wifi directories, wlan0 present/absent) are written only to $LIVE on
   tmpfs.  $LIVE is copied to /mnt/sd at the *end* of the script, which for a
   supplicant that dies in under two seconds means the copy happens long
   before anything interesting and then never again.  Nothing that explains
   *why* attempt 1 died has ever reached a capture.  Mirror the whole prelude
   to /dev/kmsg, the one sink an unflushed FAT volume cannot eat.

2. "ifconfig wlan0 up" runs only between retries, so attempt 1 -- the only
   attempt on the autostart path that matters -- races an interface that is
   registered but still administratively down, and /data/system/wpa_supplicant
   is only ever created by init.rc (which never re-runs if /data was wiped
   after that point).  Do both before the first fork instead.
"""
from a3ds_paths import A3DS_ROOT
import io
import sys

PATH = (f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds"
        "/rootfs_overlay/etc/wpa_supplicant_diag.sh")

src = io.open(PATH, encoding="utf-8").read()
orig = src

# ------------------------------------------------------- 1. prelude->kmsg ---
old = '''} >> "$LIVE"

if [ ! -r /data/misc/wifi/wpa_supplicant.conf ]; then
'''
new = '''} >> "$LIVE"

# N3DS_WPA_PREFORK_KMSG: $LIVE is tmpfs and is only copied to /mnt/sd at the
# very end of this script.  A supplicant that dies in under two seconds means
# that copy never carries anything useful, so every pre-fork fact has been
# invisible in the captures so far.  /dev/kmsg survives an unflushed volume.
while IFS= read -r _line; do
	kmsg "prefork| $_line"
done < "$LIVE"

if [ ! -r /data/misc/wifi/wpa_supplicant.conf ]; then
'''
assert old in src, "prelude anchor missing"
src = src.replace(old, new, 1)

# --------------------------------------------------- 2. preflight bring-up ---
old = '''# Fork the real daemon immediately; nothing above this point touches /mnt/sd.
attempt=1
'''
new = '''# N3DS_WPA_PREFLIGHT: these two used to happen only *between* retries, which
# is useless on the autostart path -- attempt 1 is the one that has to work.
# wlan0 can be registered and still administratively down when the framework
# starts us (ath6kl brings the netdev up from its own worker), and
# /data/system/wpa_supplicant only exists because init.rc made it, so a /data
# that was recreated after init ran leaves the control interface with nowhere
# to bind.  Both are cheap and idempotent; do them before the first fork.
mkdir -p /data/system/wpa_supplicant 2>/dev/null || true
chown wifi:wifi /data/system/wpa_supplicant 2>/dev/null || \\
	chown wifi.wifi /data/system/wpa_supplicant 2>/dev/null || true
chmod 0770 /data/system/wpa_supplicant 2>/dev/null || true
ifconfig wlan0 up 2>/dev/null || true
if [ -r /sys/class/net/wlan0/flags ]; then
	kmsg "preflight wlan0 flags=$(cat /sys/class/net/wlan0/flags 2>/dev/null) operstate=$(cat /sys/class/net/wlan0/operstate 2>/dev/null)"
else
	kmsg "preflight wlan0 has no sysfs entry"
fi

# Fork the real daemon immediately; nothing above this point touches /mnt/sd.
attempt=1
'''
assert old in src, "attempt=1 anchor missing"
src = src.replace(old, new, 1)

if src == orig:
    sys.stderr.write("no changes made\\n")
    sys.exit(1)

io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
print("patched " + PATH)
