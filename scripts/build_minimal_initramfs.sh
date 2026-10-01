#!/bin/bash
# Assembles the new minimal initramfs: /init + /init.rc (the early-mount
# stage that hands off to sd:/linux/android/etc/init.rc via "import"),
# plus a /bin + /sbin symlink forest for busybox's ~300 applet names
# (sh, mount, grep, ...) and /lib + /lib32 pointing at /usr/lib.
#
# Why the symlink forest lives HERE instead of on the SD card: FAT32
# cannot store a symlink at all, and busybox installs each applet name as
# a symlink to one real busybox binary. A cpio archive has no such
# restriction (the kernel unpacks it straight into tmpfs), so baking
# ~300 tiny symlink dentries here costs a few KB, versus ~300 real copies
# of the busybox binary if they were dereferenced onto the SD card
# instead. The busybox binary itself, and every other real file (musl's
# libs, dalvikvm, servicemanager, ...), still lives on the SD card under
# /usr -- see sync_android_to_sdcard.sh, which deliberately skips
# symlinks for the same reason.
#
# Depends on a buildroot build having already run (reads
# output/target/usr/{bin,sbin} to find the current applet list) and
# build_init.sh + link_init.sh having produced build/init/init.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

ROOT="${ANDROID3DS_ROOT}"
BR_TARGET="$ROOT/third_party/buildroot/output/target"
OVERLAY="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay"
INIT_BIN="$ROOT/build/init/init"
STAGE="$ROOT/build/minimal_initramfs/root"
OUT_CPIO="$ROOT/build/minimal_initramfs/initramfs.cpio.gz"

[ -x "$INIT_BIN" ] || { echo "missing $INIT_BIN -- run build_init.sh + link_init.sh first" >&2; exit 1; }
[ -d "$BR_TARGET/usr/bin" ] || { echo "missing $BR_TARGET/usr/bin -- run a buildroot build first" >&2; exit 1; }
[ -f "$OVERLAY/init.rc" ] || { echo "missing $OVERLAY/init.rc" >&2; exit 1; }

a3ds_sudo rm -rf "$STAGE"
mkdir -p "$STAGE/bin" "$STAGE/sbin"

cp "$INIT_BIN" "$STAGE/init"
chmod 755 "$STAGE/init"
cp "$OVERLAY/init.rc" "$STAGE/init.rc"
chmod 644 "$STAGE/init.rc"

echo "=== building /bin applet symlinks ==="
n=0
for f in "$BR_TARGET/usr/bin/"*; do
    name="$(basename "$f")"
    if [ -L "$f" ]; then
        target="$(readlink "$f")"
        case "$target" in
            *busybox*)
                ln -s /usr/bin/busybox "$STAGE/bin/$name"
                n=$((n+1))
                ;;
        esac
    fi
done
echo "  $n applet symlinks under /bin"

echo "=== building /sbin applet symlinks ==="
n=0
for f in "$BR_TARGET/usr/sbin/"*; do
    name="$(basename "$f")"
    if [ -L "$f" ]; then
        target="$(readlink "$f")"
        case "$target" in
            *busybox*)
                # Buildroot keeps the one real BusyBox executable in
                # /usr/bin even when the applet symlink originated in
                # /usr/sbin (normally ../bin/busybox).  Pointing these at
                # /usr/sbin/busybox made every /sbin applet fail with 127,
                # including the START-button shutdown's /sbin/poweroff.
                ln -s /usr/bin/busybox "$STAGE/sbin/$name"
                n=$((n+1))
                ;;
        esac
    fi
done
echo "  $n applet symlinks under /sbin"

# The Wi-Fi service is defined in the early initramfs init.rc so it cannot
# depend on the SD-card bind mount racing service startup. Keep the actual
# executables at their absolute runtime paths, not just symlinks: the files
# below are all needed before /usr is mounted from FAT32. BusyBox is also
# real content here because every /bin and /sbin applet symlink resolves to
# /usr/bin/busybox.
mkdir -p "$STAGE/usr/bin" "$STAGE/usr/sbin" "$STAGE/usr/lib"
for rel in \
    usr/bin/busybox \
    usr/sbin/wpa_supplicant \
    usr/sbin/iw \
    usr/sbin/servicemanager; do
    src="$BR_TARGET/$rel"
    if [ ! -e "$src" ]; then
        echo "FATAL: missing initramfs runtime binary $src" >&2
        exit 1
    fi
    cp -a "$src" "$STAGE/$rel"
done

# wpa_supplicant and iw are musl/libnl dynamic ARM binaries. Include the
# interpreter and every DT_NEEDED SONAME they report, preserving the SONAME
# symlinks and executable modes from Buildroot. /lib and /lib32 below point
# into this same /usr/lib directory.
for rel in \
    usr/lib/ld-musl-armhf.so.1 \
    usr/lib/libc.so \
    usr/lib/libnl-3.so \
    usr/lib/libnl-3.so.200 \
    usr/lib/libnl-3.so.200.26.0 \
    usr/lib/libnl-genl-3.so \
    usr/lib/libnl-genl-3.so.200 \
    usr/lib/libnl-genl-3.so.200.26.0; do
    src="$BR_TARGET/$rel"
    if [ ! -e "$src" ]; then
        echo "FATAL: missing initramfs runtime library $src" >&2
        exit 1
    fi
    cp -a "$src" "$STAGE/$rel"
done

ln -s /usr/lib "$STAGE/lib"
ln -s /usr/lib "$STAGE/lib32"

# Firmware that must be reachable at /lib/firmware BEFORE /usr is
# bind-mounted from the SD card (which does not happen until init.rc's
# "on init" runs, ~27s into boot -- too late for driver-probe-time
# request_firmware()).
#
#   - 3ds/dspfirm.cdc: the 3DS DSP firmware, requested by ctr_dsp.c at
#     probe (t~2.4s). Without it the boot log shows "Direct firmware load
#     for 3ds/dspfirm.cdc failed with error -2, audio unavailable". It
#     lives in the SD tree under usr/lib/firmware, but that path is not
#     reachable until /usr is mounted. Baking it here (through the /lib ->
#     /usr/lib symlink, which resolves inside the initramfs tmpfs) makes
#     the load succeed at probe time. ~49KB.
#   - regulatory.db + .p7s: cfg80211's regulatory database, requested by
#     the regulatory platform device at t~26.6s, just before /init runs.
#     Without them: "cfg80211: failed to load regulatory.db". ~7KB.
#
# These are also copied onto the SD at usr/lib/firmware by
# sync_android_to_sdcard.sh for the post-/usr-mount case; the copies here
# are the only ones the kernel can see during the early-boot window.
#
# NOTE: they must be staged under $STAGE/usr/lib/firmware (the REAL path),
# NOT under $STAGE/lib/firmware: $STAGE/lib is a symlink to /usr/lib, and
# creating files *through* it during the build would write to the build
# host's /usr/lib. On the device the /lib -> /usr/lib symlink resolves
# inside the initramfs tmpfs (before /usr is bind-mounted), so staging at
# usr/lib/firmware is exactly what request_firmware() will see.
mkdir -p "$STAGE/usr/lib/firmware/3ds"
for f in 3ds/dspfirm.cdc regulatory.db regulatory.db.p7s; do
    src="$OVERLAY/usr/lib/firmware/$f"
    if [ -f "$src" ]; then
        cp "$src" "$STAGE/usr/lib/firmware/$f"
        chmod 644 "$STAGE/usr/lib/firmware/$f"
        echo "  firmware baked: $f"
    else
        echo "  WARNING: missing overlay firmware $src" >&2
    fi
done

if [ -d "$OVERLAY/usr/lib/firmware/ath6k" ]; then
    cp -r "$OVERLAY/usr/lib/firmware/ath6k" "$STAGE/usr/lib/firmware/"
    echo "  firmware baked: ath6k"
fi

# N3DS_WIFI_INITRAMFS_MODULE: both Android Wi-Fi and Mobile Data load the same
# reloadable STA/AP driver. Keep the normal source in tmpfs so a later FAT/vda
# read error cannot make the Wi-Fi toggle fail before wlan0 exists. Do not put
# it below /usr: init.rc bind-mounts the SD-backed Android /usr over that tree,
# which hid #236's usr/lib/modules copy and made every toggle fail with ENOENT.
# /n3ds is an initramfs-owned root that survives all Android bind mounts. The
# staged /system copy remains for release parity and as a bounded fallback.
WIFI_MODULE="$OVERLAY/system/lib/modules/ath6kl.ko"
test -s "$WIFI_MODULE" || {
    echo "FATAL: missing reloadable Wi-Fi module $WIFI_MODULE" >&2
    exit 1
}
# N3DS_SCRUB_BUILD_PATHS: mask the build machine's directories in the overlay
# copy first (sync_android_to_sdcard.sh does the same), so this copy, the
# overlay and the card all stay identical.
python3 "$(dirname "${BASH_SOURCE[0]:-$0}")/scrub_build_paths.py" "$WIFI_MODULE"
mkdir -p "$STAGE/n3ds/modules"
cp "$WIFI_MODULE" "$STAGE/n3ds/modules/ath6kl.ko"
chmod 644 "$STAGE/n3ds/modules/ath6kl.ko"
cmp -s "$WIFI_MODULE" "$STAGE/n3ds/modules/ath6kl.ko" || {
    echo 'FATAL: initramfs Wi-Fi module copy drifted' >&2
    exit 1
}
echo "  Wi-Fi module baked: /n3ds/modules/ath6kl.ko"

a3ds_sudo chown -R root:root "$STAGE"

mkdir -p "$(dirname "$OUT_CPIO")"
# The archive is packed as root (the tree is root-owned). This used to be a
# bare `sudo cpio` with stderr thrown away, which in an unattended run could
# fail at the password prompt and leave a valid-looking empty .gz; pack
# through a3ds_sudo and refuse an archive that has no /init.
a3ds_sudo sh -c 'cd "$1" && find . | cpio -o -H newc --quiet' sh "$STAGE" | gzip -9 > "$OUT_CPIO"
gzip -dc "$OUT_CPIO" | cpio -t --quiet 2>/dev/null | grep -qx '\./init\|init' || {
    echo "FATAL: $OUT_CPIO has no /init (packing failed)" >&2
    exit 1
}

echo "=== $OUT_CPIO ==="
ls -la "$OUT_CPIO"

# This script used to stop after producing the WSL-side archive.  Most callers
# happened to invoke it through scratch_rebuild_rootfs.sh, which copied the
# result afterward, but direct/full rebuild callers silently left the SD card
# staging tree one build behind.  Deploy here, where the artifact is created,
# and require all copies to match before reporting success.
WSL_SD="$ROOT/sdcard/linux/initramfs.cpio.gz"
WIN_SD="${ANDROID3DS_WIN}/sdcard/linux/initramfs.cpio.gz"
mkdir -p "$(dirname "$WSL_SD")" "$(dirname "$WIN_SD")"
cp "$OUT_CPIO" "$WSL_SD"
cp "$OUT_CPIO" "$WIN_SD"
chmod 644 "$WSL_SD" "$WIN_SD"

echo "=== deployed initramfs copies ==="
sha256sum "$OUT_CPIO" "$WSL_SD" "$WIN_SD"
cmp -s "$OUT_CPIO" "$WSL_SD" || {
    echo "FATAL: WSL SD initramfs differs from build output" >&2
    exit 1
}
cmp -s "$OUT_CPIO" "$WIN_SD" || {
    echo "FATAL: Windows SD initramfs differs from build output" >&2
    exit 1
}

test "$(readlink "$STAGE/sbin/poweroff")" = /usr/bin/busybox || {
    echo "FATAL: /sbin/poweroff does not resolve to Buildroot's BusyBox" >&2
    exit 1
}
test -x "$BR_TARGET/usr/bin/busybox" || {
    echo "FATAL: BusyBox target for /sbin/poweroff is missing" >&2
    exit 1
}
