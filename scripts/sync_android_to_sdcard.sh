#!/bin/bash
# Mirrors buildroot's built output (system/etc/usr) onto the SD-card
# staging folder at sdcard/linux/android/, which is what the New 3DS
# actually boots from -- see docs/HANDOFF.md, "everything off the
# initramfs". This is the ONLY thing that should ever write under
# sdcard/linux/android/{system,etc,usr}: run it after every
# `buildroot make` so the SD-side copy tracks source exactly --
# replaces changed files, adds new ones, deletes ones that no longer
# exist in the build output. It never touches sdcard/linux/android/data
# (pure runtime state, no build-source counterpart) or anything else on
# the card (zImage, dtb, initramfs.cpio.gz, luma/, ...).
#
# SYMLINK HANDLING -- READ THIS BEFORE CHANGING ANY rsync FLAG BELOW.
# FAT32 cannot store a symlink at all, so every symlink in the source
# tree has to be resolved one of three ways. Getting this wrong does not
# produce an obvious error; it produces `execve(): No such file or
# directory` on files that visibly exist, which is what the 2026-08-04
# first-boot failure actually was (see docs/HANDOFF.md).
#
#   1. busybox applet names (~275 of them: sh, mount, grep, ash, ...,
#      all symlinks to one busybox binary under usr/bin + usr/sbin) ->
#      EXCLUDED here. Copying each as a real file would multiply a ~1 MB
#      binary ~275x. They are baked into the initramfs cpio instead as
#      tiny symlink dentries (cpio has no FAT32 restriction), see
#      build_minimal_initramfs.sh.
#
#   2. Library soname symlinks (ld-musl-armhf.so.1 -> ../lib/libc.so,
#      libstdc++.so.6 -> libstdc++.so.6.0.28, the libnl ones, ...) ->
#      DEREFERENCED into real files by -L, deliberately accepting the
#      duplication (a few MB on a 15 GB card). These are load-bearing:
#      the SONAME *is* the filename the loader opens. In particular
#      ld-musl-armhf.so.1 is busybox's PT_INTERP -- if it is missing the
#      kernel fails execve with ENOENT and reports it against the
#      *binary*, not the interpreter, which is exactly the confusing
#      symptom that cost a hardware boot cycle to track down. Do not
#      "optimize" these back into skips.
#
#   3. Symlinks whose target is runtime-only or would capture host state
#      (etc/mtab -> ../proc/self/mounts, etc/resolv.conf ->
#      ../tmp/resolv.conf) -> EXCLUDED explicitly. They are dangling at
#      build time, so -L would both error out (rsync exit 23) and, for
#      mtab, risk materializing the *build host's* mount table as a
#      static file. Nothing in the boot path needs them (busybox falls
#      back to /proc/mounts). If they ever become necessary they have to
#      be created at runtime by init.rc/a boot script, not stored on vfat.
#
#      resolv.conf since became necessary, and is handled exactly that
#      way. It is the only resolver musl reads, so the statically linked
#      telco_https cannot reach 3dstelco.divergen.io without it, and no
#      Android property is a substitute. /etc/android_resolvconf.sh
#      writes a real file there on every DHCP bound/renew (and the same
#      servers into net.dns1..4 for bionic). It stays excluded here for
#      the original reason -- the buildroot entry is a dangling symlink
#      into /tmp that vfat cannot store -- and the exclusion doubles as
#      protection from --delete, so a lease written on the device is not
#      wiped by the next sync.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
A3DS_SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

SRC="${ANDROID3DS_ROOT}"/third_party/buildroot/output/target
OVERLAY="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay
DEST="${ANDROID3DS_WIN}/sdcard/linux/android"
WSL_DEST="${ANDROID3DS_ROOT}"/sdcard/linux/android
# N3DS_UPDATE_SAFE_PREFS: templates and durable state belong to the Android
# payload at sdcard/linux/android.  The managed rsyncs below target only the
# system/etc/usr children, so this sibling namespace is never traversed or
# deleted during an update.
PERSISTENT_STATE="$DEST/persistent"
EXCL=/tmp/sync_android_excludes

if [ ! -d "$SRC/system" ] || [ ! -d "$SRC/etc" ] || [ ! -d "$SRC/usr" ]; then
    echo "sync_android_to_sdcard: $SRC missing system/etc/usr -- run a buildroot build first" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Make the overlay win over output/target BEFORE anything is rsynced.
#
# init.rc and the /etc service scripts are hand-written, not build products.
# buildroot only copies rootfs_overlay into output/target during a full
# `make`, and output/target is additive (see docs/HANDOFF.md), so between
# builds the overlay copy and the output/target copy drift apart -- and the
# rsync below then pushes the *stale* output/target copy to the card.
#
# Worse, until 2026-08-04 nothing pushed init.rc at all and the SD-card copy
# was hand-edited in place, so it was the only copy of several load-bearing
# settings. The overlay and the SD card had already drifted by 1.7 KB by the
# time anyone checked.
#
# Refreshing output/target from the overlay here makes the overlay the single
# source of truth with no buildroot rebuild required, and keeps the "one
# rsync, --delete, source tracks destination exactly" property of this script.
# ---------------------------------------------------------------------------
echo "=== refreshing output/target from rootfs_overlay ==="
if [ ! -d "$OVERLAY" ]; then
    echo "sync_android_to_sdcard: $OVERLAY missing" >&2
    exit 1
fi
# -c (checksum) rather than mtime: files edited through the \\wsl$ UNC path
# from Windows can land with odd timestamps. No --delete: output/target holds
# plenty of legitimate buildroot output the overlay knows nothing about.
rsync -rlc "$OVERLAY/" "$SRC/"
# A prior Buildroot output can retain the retired daemon even after its
# historical package/source is no longer in the overlay. It must never cross
# the release boundary again: remove only this exact generated/staged binary,
# leaving historical research and source evidence untouched.
for stale in \
    "$SRC/system/bin/streetpassd" \
    "$DEST/system/bin/streetpassd" \
    "$WSL_DEST/system/bin/streetpassd"; do
    if [ -e "$stale" ]; then
        echo "=== pruning retired generated/staged StreetPass binary: $stale ==="
        rm -f "$stale"
    fi
done
# GCC installs a gdb pretty-printer script next to libstdc++. Nothing on the
# device runs gdb, and the script embeds the build machine's toolchain path.
# Removing it from output/target lets the --delete rsyncs below prune it.
rm -f "$SRC"/usr/lib/libstdc++.so.*-gdb.py

# N3DS_SCRUB_BUILD_PATHS: assert()/WARN() __FILE__ strings and debug info in
# the ELF files embed the build machine's directories, which name the local
# account. Mask them in place, at the same length, in the overlay and in
# output/target before anything reaches the card, so every copy (overlay,
# target, card, initramfs) stays byte-identical. Idempotent.
echo "=== masking build-machine paths in shipped ELF files ==="
python3 "$A3DS_SCRIPTS/scrub_build_paths.py" \
    "$OVERLAY" "$SRC/system" "$SRC/etc" "$SRC/usr"
# Writing through \\wsl$ resets the executable bit to 0644, and init does
# stat() then execve() -- a 0644 service script fails at execve with EACCES,
# silently, because it is a service. Re-assert it on both copies.
# (docs/HANDOFF.md: "Trap that nearly re-broke this".)
chmod 755 "$OVERLAY"/etc/*.sh "$SRC"/etc/*.sh 2>/dev/null || true
ls -la "$SRC/etc/init.rc"

mkdir -p "$DEST/system" "$DEST/etc" "$DEST/usr" "$DEST/data"
mkdir -p "$WSL_DEST/system" "$WSL_DEST/etc" "$WSL_DEST/usr"

if [ -d "$PERSISTENT_STATE" ]; then
    echo "=== preserving update-safe sdcard/linux/android/persistent (not sync-managed) ==="
fi

# Build the per-module exclude list (category 1 above: busybox applets).
# Paths are anchored with a leading / so they are relative to each
# rsync transfer root, not matched anywhere in the tree.
gen_excludes() {
    local sub="$1" out="$2"
    : > "$out"
    find "$SRC/$sub" -type l | while read -r f; do
        case "$(readlink "$f")" in
            *busybox*) echo "/${f#$SRC/$sub/}" >> "$out" ;;
        esac
    done
}

# -r recurse, -t preserve mtimes, -L dereference symlinks into real files
# (see the block above), -c compare content rather than trusting size+mtime,
# which can be identical across two byte-different pre-baked odex revisions,
# --delete prune files removed from the source. No -p/-g/-o: vfat has no
# real POSIX permission storage -- the SD card is mounted with
# fmask=0000,dmask=0000 at boot (see boot_log*.txt), which makes
# everything uniformly readable/writable/executable regardless of what is
# "stored", so preserving bits here would be meaningless and produces
# noisy warnings writing through the Windows-side NTFS staging folder.
RS="rsync -rtLc --delete --stats"

echo "=== syncing system/ ==="
gen_excludes system "$EXCL.system"
$RS --exclude-from="$EXCL.system" "$SRC/system/" "$DEST/system/"

echo "=== syncing etc/ ==="
gen_excludes etc "$EXCL.etc"
# category 3: runtime-only / host-state symlinks. resolv.conf is written
# on the device by /etc/android_resolvconf.sh at DHCP time; excluding it
# keeps --delete from removing that file on the next sync.
printf '/mtab\n/resolv.conf\n' >> "$EXCL.etc"
$RS --exclude-from="$EXCL.etc" "$SRC/etc/" "$DEST/etc/"

echo "=== syncing usr/ ==="
gen_excludes usr "$EXCL.usr"
# usr/lib32 -> lib is a buildroot merged-/usr artifact; dereferencing it
# would duplicate the entire lib tree for nothing. The initramfs cpio
# already provides /lib and /lib32 pointing at /usr/lib.
printf '/lib32\n' >> "$EXCL.usr"
$RS --exclude-from="$EXCL.usr" "$SRC/usr/" "$DEST/usr/"

echo "=== verifying the load-bearing interpreter actually landed ==="
# busybox's PT_INTERP. If this is missing every dynamically linked binary
# fails execve with a misleading ENOENT and nothing in userspace runs.
if [ ! -f "$DEST/usr/lib/ld-musl-armhf.so.1" ]; then
    echo "FATAL: $DEST/usr/lib/ld-musl-armhf.so.1 missing after sync" >&2
    exit 1
fi
ls -la "$DEST/usr/lib/ld-musl-armhf.so.1"

echo "=== sync_android_to_sdcard: done ==="
du -sh "$DEST/system" "$DEST/etc" "$DEST/usr" "$DEST/data"

# Fail closed on the exact stale-binary regression that caused the 2026-08-08
# zygote loop.  The build artifact is unstripped while the deployed copy is
# stripped, so normalize it before comparing all three source/deploy layers.
APP_BUILD="${ANDROID3DS_ROOT}"/build/app_process/app_process
APP_OVERLAY="$OVERLAY/system/bin/app_process"
APP_TARGET="$SRC/system/bin/app_process"
APP_CARD="$DEST/system/bin/app_process"
STRIP="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-strip
if [ -f "$APP_BUILD" ]; then
    APP_EXPECTED=$(mktemp /tmp/android3ds-app-process.XXXXXX)
    trap 'rm -f "$APP_EXPECTED"' EXIT
    "$STRIP" -o "$APP_EXPECTED" "$APP_BUILD"
    # The deployed copies were path-masked above; mask the expectation too.
    python3 "$A3DS_SCRIPTS/scrub_build_paths.py" "$APP_EXPECTED" > /dev/null
    for deployed in "$APP_OVERLAY" "$APP_TARGET" "$APP_CARD"; do
        if ! cmp -s "$APP_EXPECTED" "$deployed"; then
            echo "FATAL: stale app_process at $deployed" >&2
            echo "       rebuild with scripts/build_app_process.sh before syncing" >&2
            exit 1
        fi
    done
    echo "=== app_process build/overlay/target/card match ==="
    sha256sum "$APP_EXPECTED" "$APP_OVERLAY" "$APP_TARGET" "$APP_CARD"
    rm -f "$APP_EXPECTED"
    trap - EXIT
fi

# Keep the canonical native WSL release tree synchronized with the Windows
# deployable mirror. Only managed system/etc/usr namespaces are copied;
# runtime data and update-safe preferences remain private to each destination.
echo "=== mirroring managed system/etc/usr to canonical WSL sdcard ==="
for sub in system etc usr; do
    rsync -rtLc --delete "$DEST/$sub/" "$WSL_DEST/$sub/"
done

echo "=== verifying Windows/WSL managed staging parity ==="
for sub in system etc usr; do
    MIRROR_DIFF="$(rsync -rtLc --delete --dry-run --itemize-changes \
        "$DEST/$sub/" "$WSL_DEST/$sub/")"
    if [ -n "$MIRROR_DIFF" ]; then
        echo "FATAL: managed staging differs after mirror ($sub)" >&2
        printf '%s\n' "$MIRROR_DIFF" >&2
        exit 1
    fi
done
for required in \
    system/framework/core.jar \
    system/framework/framework.jar \
    system/framework/services.jar; do
    test -s "$DEST/$required"
    test -s "$WSL_DEST/$required"
    cmp -s "$DEST/$required" "$WSL_DEST/$required" || {
        echo "FATAL: canonical WSL copy differs for $required" >&2
        exit 1
    }
    sha256sum "$DEST/$required" "$WSL_DEST/$required"
done
echo "=== Windows/WSL managed staging parity: OK (data/ and persistent/ untouched) ==="
