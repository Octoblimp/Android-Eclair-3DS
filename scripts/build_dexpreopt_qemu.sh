#!/bin/bash
# Host-side dexpreopt: pre-bake /data/dalvik-cache for the three bootclasspath
# jars (core.jar, framework.jar, services.jar) under qemu-arm-static, so the
# device never has to cold-dexopt them on first boot.
#
# 2026-08-04 (even later): a boot from a fully empty dalvik-cache had to
# cold-dexopt four jars back to back on a 256 MB/no-swap device and
# soft-locked with an rcu_sched stall; a boot with a warm cache did not. This
# removes the single biggest, riskiest chunk of that on-device work (the
# three bootclasspath jars -- Launcher2.apk is small and not implicated,
# see docs/HANDOFF.md) by running the REAL ARM dexopt/dvm binaries -- same
# toolchain, same libdvm.a, same object files as the on-device build, so the
# produced .odex is bit-identical to what real hardware would produce -- just
# with libcutils' ashmem-dev.c swapped for system_core's own ashmem-host.c
# (upstream's simulator-target ashmem: a plain O_EXCL temp file + ftruncate,
# no /dev/ashmem ioctls, which is exactly what qemu-arm-static can't emulate
# and exactly why every previous attempt to run dalvikvm/dexopt under qemu
# failed with "Can't create VM heap ... errno=2"). mspace.c's
# create_contiguous_mspace_with_name() only ever mmap(MAP_PRIVATE)s the
# ashmem fd and closes it immediately -- it never needed cross-process
# sharing, so this swap is semantically exact, not an approximation.
#
# Dalvik's dependency check (DexOptimize.c: dvmCheckOptHeaderAndDependencies)
# verifies the source jar's "modWhen" and CRC against what's recorded in the
# .odex. CRC is content-based and therefore automatically correct. modWhen is
# NOT -- and, crucially, it is NOT the jar's filesystem mtime: it is the raw
# 4-byte DOS date+time out of the jar's CENTRAL DIRECTORY entry for
# classes.dex (JarFile.c -> ZipArchive.c:dexZipGetEntryInfo,
# get4LE(ptr + kCDEModWhen)).
#
# This script used to `touch -d @PIN_MTIME` the jars, which sets exactly the
# metadata Dalvik never reads, so it silently did nothing for months. The
# 2026-08-05 boot burned 4 min 11 s cold-optimizing a core.jar whose content
# had not changed at all, and that write storm starved the SD path badly
# enough to freeze the boot animation. See docs/HANDOFF.md.
#
# The real fix is scripts/jar_dexdep.py:
#   pin    rewrites classes.dex's central-directory (and local-header) DOS
#          timestamp to a fixed constant, so repackaging identical content
#          stops changing modWhen. Applied below to the rootfs_overlay copy
#          (the source of truth -- sync_android_to_sdcard.sh rsyncs overlay
#          over the SD tree, so pinning only the SD copy would be undone on
#          the next sync), to the SD copy, and to the fakeroot copy, all
#          before dexopt runs, so every layer records the same value.
#   verify re-reads modWhen+CRC from the deployed jar and from the deployed
#          .odex's dependency record and fails if they disagree. Run as the
#          last step here, and safe to run standalone at any time:
#              python3 scripts/jar_dexdep.py verify <sd>/linux/android
#
# Re-run this whenever core.jar/framework.jar/services.jar changes content.
# If it's NOT re-run after such a change, the CRC mismatch makes Dalvik
# correctly fall back to on-device dexopt for the changed jar(s) -- stale
# is safe, just not free.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
DALVIK="${ANDROID3DS_ROOT}"/third_party/dalvik
BUILD="${ANDROID3DS_ROOT}"/build
BIONIC_OUT=$BUILD/bionic
QEMU="${ANDROID3DS_ROOT}"/toolchain/qemu/qemu-arm-static
LIBGCC="$("$GCC" -print-libgcc-file-name)"

SCRIPTS="${ANDROID3DS_WIN}/scripts"
OVERLAY="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector -fno-pic -fno-builtin \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-return-type -Wno-attributes \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include"

echo "=== 1. libcutils_qemu.a (ashmem-host.c instead of ashmem-dev.c) ==="
CUTILS_OUT=$BUILD/libcutils_qemu
mkdir -p "$CUTILS_OUT/obj"
"$GCC" $CFLAGS -I "$SYSCORE/include" -c "$SYSCORE/libcutils/ashmem-host.c" -o "$CUTILS_OUT/obj/ashmem-host.o"
# Everything else: reuse the exact same objects the real libcutils.a was
# built from (see build_liblog_libcutils.sh) -- only ashmem differs.
for f in "$BUILD/libcutils/obj"/*.o; do
    base=$(basename "$f")
    [ "$base" = "ashmem-dev.o" ] && continue
    cp "$f" "$CUTILS_OUT/obj/$base"
done
"$AR" rcs "$CUTILS_OUT/libcutils.a" "$CUTILS_OUT"/obj/*.o
echo "built $CUTILS_OUT/libcutils.a"

link_qemu_bin() {
    local objfile="$1" outname="$2"
    "$GXX" -nostdlib -static \
        "$BIONIC_OUT/crtbegin.o" \
        "$objfile" \
        -Wl,-u,_ZN7android25gDarwinCantLoadAllObjectsE \
        -Wl,--start-group \
            "$BUILD/libdvm/libdvm.a" \
            "$BUILD/libdex/libdex.a" \
            "$BUILD/libnativehelper/libnativehelper.a" \
            "$BUILD/libnativehelper/libnativehelper_register.a" \
            "$BUILD/libjavacore/libjavacore.a" \
            "$BUILD/icu4c/libicui18n.a" \
            "$BUILD/icu4c/libicuuc.a" \
            "$BUILD/icu4c/libicudata.a" \
            "$BUILD/openssl/libssl.a" \
            "$BUILD/openssl/libcrypto.a" \
            "$BUILD/sqlite/libsqlite.a" \
            "$BUILD/expat/libexpat.a" \
            "$BUILD/fdlibm/libfdlibm.a" \
            "$BUILD/bionic_compat/libbionic_compat.a" \
            "$BUILD/libutils/libutils.a" \
            "$CUTILS_OUT/libcutils.a" \
            "$BUILD/liblog_fake/liblog.a" \
            "$BUILD/libstdcxx/libstdc++.a" \
            "$BUILD/zlib/libz.a" \
            "$BUILD/libm/libm.a" \
            "$BUILD/libdl/libdl.a" \
            "$BIONIC_OUT/libc.a" \
            "$LIBGCC" \
        -Wl,--end-group \
        "$BIONIC_OUT/crtend.o" \
        -o "$outname" \
        -Wl,-e,_start -Wl,--no-warn-mismatch \
        -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
        -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
        -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
        2>&1 | grep -v "GNU-stack\|deprecated" || true
    if [ ! -f "$outname" ]; then
        echo "LINK FAILED: $outname"
        exit 1
    fi
    ls -la "$outname"
}

echo "=== 2. dalvikvm_qemu ==="
link_qemu_bin "$BUILD/dalvikvm/obj/Main.o" "$BUILD/dalvikvm/dalvikvm_qemu"

echo "=== 3. dexopt_qemu ==="
link_qemu_bin "$BUILD/dexopt/obj/OptMain.o" "$BUILD/dexopt/dexopt_qemu"

echo "=== 4. fakeroot ==="
FAKEROOT=$BUILD/dexpreopt_fakeroot
SD="${ANDROID3DS_WIN}"/sdcard/linux/android
WSL_SD="${ANDROID3DS_ROOT}"/sdcard/linux/android
rm -rf "$FAKEROOT"
mkdir -p "$FAKEROOT/system/framework" "$FAKEROOT/system/bin" "$FAKEROOT/data/dalvik-cache"

# N3DS_DEXPREOPT_STAGING_FRESHNESS: this script optimizes the jars in the SD
# *staging* tree, but build_framework_jar.sh/build_services_jar.sh and their
# deploy_*.sh only write the buildroot overlay -- sync_android_to_sdcard.sh is
# what carries them to staging. Running dexpreopt before that sync silently
# optimizes the PREVIOUS jar, and the step-9 gate still passes because it
# compares the cache against that same stale staging jar. That is exactly how
# a stale services.jar@classes.dex shipped on 2026-09-10. Fail loudly instead.
echo "--- checking overlay/staging bootclasspath freshness ---"
for required in     system/framework/core.jar     system/framework/framework.jar     system/framework/services.jar; do
    if ! cmp -s "$OVERLAY/$required" "$SD/$required"; then
        echo "FATAL: $required in the buildroot overlay differs from SD staging." >&2
        echo "       The overlay is newer -- dexpreopt would bake the OLD jar." >&2
        echo "       Run scripts/sync_android_to_sdcard.sh first, then re-run this." >&2
        exit 1
    fi
done

echo "--- checking Windows/WSL bootclasspath staging parity ---"
for required in \
    system/framework/core.jar \
    system/framework/framework.jar \
    system/framework/services.jar; do
    test -s "$SD/$required"
    test -s "$WSL_SD/$required"
    cmp -s "$SD/$required" "$WSL_SD/$required" || {
        echo "FATAL: Windows and canonical WSL staging differ for $required" >&2
        echo "       run scripts/sync_android_to_sdcard.sh first" >&2
        exit 1
    }
done

# Pin classes.dex's zip timestamp in the overlay (source of truth) and on the
# SD card BEFORE anything is copied or optimized, so all three copies -- and
# the dependency record dexopt is about to write -- agree by construction.
echo "--- pinning classes.dex zip timestamps (jar_dexdep.py pin) ---"
python3 "$SCRIPTS/jar_dexdep.py" pin \
    "$OVERLAY/system/framework"/core.jar \
    "$OVERLAY/system/framework"/framework.jar \
    "$OVERLAY/system/framework"/services.jar
python3 "$SCRIPTS/jar_dexdep.py" pin \
    "$SD/system/framework"/core.jar \
    "$SD/system/framework"/framework.jar \
    "$SD/system/framework"/services.jar
python3 "$SCRIPTS/jar_dexdep.py" pin \
    "$WSL_SD/system/framework"/core.jar \
    "$WSL_SD/system/framework"/framework.jar \
    "$WSL_SD/system/framework"/services.jar

# N3DS_PIN_MTIME_PARITY: pin rewrites each jar in place, so a jar that actually
# needed pinning (i.e. one rebuilt since the last run) gets three different
# file mtimes, milliseconds apart. Content is identical, but the Windows-copy
# release gate compares Windows vs WSL staging with rsync -t and fails on the
# mtime alone (.f..t...... framework/framework.jar, 2026-09-30). Dalvik only
# reads the zip central-directory time, never the file mtime, so copying the
# Windows staging mtime onto the WSL mirror is safe and restores exactly what
# sync_android_to_sdcard.sh established.
for jar in core.jar framework.jar services.jar; do
    touch -r "$SD/system/framework/$jar" "$WSL_SD/system/framework/$jar"
done

cp "$SD/system/framework/core.jar" "$FAKEROOT/system/framework/core.jar"
cp "$SD/system/framework/framework.jar" "$FAKEROOT/system/framework/framework.jar"
cp "$SD/system/framework/services.jar" "$FAKEROOT/system/framework/services.jar"
cp "$BUILD/dexopt/dexopt_qemu" "$FAKEROOT/system/bin/dexopt"
chmod 755 "$FAKEROOT/system/bin/dexopt"
cp "$QEMU" "$FAKEROOT/qemu-arm-static"

echo "=== 5. binfmt_misc registration for qemu-arm (needed for dexopt's own execv) ==="
# dvmContinueOptimization() forks and execv()s $ANDROID_ROOT/bin/dexopt directly
# -- it does not know or care that it's running under emulation, so the child
# execv() only works if the *kernel* knows how to run a foreign ARM ELF, i.e.
# binfmt_misc has qemu-arm registered. Without this, dalvikvm_qemu itself runs
# fine (we invoke it via qemu-arm-static explicitly) but every dexopt child
# fails with "execv '/system/bin/dexopt' failed: Exec format error" and the
# VM falls back to reporting every bootclasspath entry as unusable. Idempotent
# -- skips if already registered (e.g. by a previous run this session).
if [ ! -e /proc/sys/fs/binfmt_misc/qemu-arm ]; then
    REGFILE=$(mktemp)
    printf ':qemu-arm:M::\\x7fELF\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\x28\\x00:\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xfe\\xff\\xff\\xff:%s:F\n' "$QEMU" > "$REGFILE"
    a3ds_sudo bash -c "cat '$REGFILE' > /proc/sys/fs/binfmt_misc/register"
    rm -f "$REGFILE"
fi
cat /proc/sys/fs/binfmt_misc/qemu-arm

echo "=== 6. run dalvikvm_qemu under qemu-arm-static in a private mount namespace ==="
# Bind fakeroot's system/ and data/ onto the real / temporarily, inside a new
# mount namespace (unshare --mount) so nothing outside this one command sees
# it and nothing needs manual cleanup -- the mounts vanish the moment the
# namespace's process exits, whether it succeeds or fails. Written to a real
# script file rather than inlined -- multi-layer shell quoting (this script
# -> sudo -S -> unshare -- bash -c) reliably mangles nested $VAR expansion.
RUNSCRIPT="$FAKEROOT/run_preopt.sh"
cat > "$RUNSCRIPT" <<EOF
#!/bin/bash
set -e
mkdir -p /system /data
mount --bind "$FAKEROOT/system" /system
mount --bind "$FAKEROOT/data" /data
export ANDROID_ROOT=/system
export ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
"$QEMU" "$BUILD/dalvikvm/dalvikvm_qemu" -Xbootclasspath:\$BOOTCLASSPATH
EOF
chmod 755 "$RUNSCRIPT"
a3ds_sudo unshare --mount -- "$RUNSCRIPT" || true
a3ds_sudo chown "$(id -u)":"$(id -g)" "$FAKEROOT/data/dalvik-cache"/*.dex 2>/dev/null || true

echo "=== 7. result ==="
ls -la "$FAKEROOT/data/dalvik-cache/"
for f in "$FAKEROOT/data/dalvik-cache"/*.dex; do
    head -c 8 "$f" | od -c | head -1
done

echo "=== 8. deploy to SD staging (data/ is runtime state -- sync_android_to_sdcard.sh never touches it, so this is the only path that writes it) ==="
mkdir -p "$SD/data/dalvik-cache"
cp -v "$FAKEROOT/data/dalvik-cache"/*.dex "$SD/data/dalvik-cache/"
mkdir -p "$WSL_SD/data/dalvik-cache"
cp -v "$FAKEROOT/data/dalvik-cache"/*.dex "$WSL_SD/data/dalvik-cache/"

echo "=== 9. gate: does the deployed cache actually match the deployed jars? ==="
# Reads modWhen+CRC back out of the bytes on the card, both sides. This is the
# check that would have caught the 4-minute cold-dexopt of an unchanged
# core.jar; a non-zero exit here means the next boot will NOT be pre-optimized.
python3 "$SCRIPTS/jar_dexdep.py" verify "$SD"
python3 "$SCRIPTS/jar_dexdep.py" verify "$WSL_SD"
