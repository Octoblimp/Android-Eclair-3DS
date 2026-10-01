#!/bin/bash
# Link the dalvikvm command-line launcher statically against libdvm and its
# deps. Static because there is no dynamic linker in this initramfs yet --
# same choice already made for init and servicemanager.
#
# Prints the sorted unique list of undefined references rather than a wall of
# linker output, so the remaining porting work is visible at a glance.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
DALVIK="${ANDROID3DS_ROOT}"/third_party/dalvik
BUILD="${ANDROID3DS_ROOT}"/build
OUT=$BUILD/dalvikvm
LIBGCC="$("$GCC" -print-libgcc-file-name)"
mkdir -p "$OUT/obj"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -O2 -fno-stack-protector -fno-pic \
-Wno-attributes -Wno-implicit-function-declaration \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $SYSCORE/include \
-I $DALVIK/include \
-I $DALVIK/libnativehelper/include/nativehelper"

"$GCC" $CFLAGS -c "$DALVIK/dalvikvm/Main.c" -o "$OUT/obj/Main.o" || exit 1

"$GCC" -nostdlib -static \
    "$BIONIC/../../build/bionic/crtbegin.o" \
    "$OUT/obj/Main.o" \
    `# Force libutils' Static.o into the link. It holds the only instance of
     # LibUtilsFirstStatics, whose constructor calls initialize_string8() /
     # initialize_string16(). Nothing references Static.o, so a static link
     # leaves it in the archive and those never run -- after which
     # gEmptyStringBuf is NULL and *any* empty or default-constructed String8
     # dereferences NULL. AOSP builds libutils as a shared library, so it
     # never hits this; the gDarwinCantLoadAllObjects symbol exists upstream
     # for exactly this purpose.` \
    -Wl,-u,_ZN7android25gDarwinCantLoadAllObjectsE \
    -Wl,--start-group \
        "$BUILD/libdvm/libdvm.a" \
        "$BUILD/libdex/libdex.a" \
        "$BUILD/libnativehelper/libnativehelper.a" \
        `# The real Register.c now, not android3ds_register_stub.c: libjavacore
         # and all five of its external libraries are built, so the ~45
         # register_*() entry points it calls actually resolve.` \
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
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/zlib/libz.a" \
        "$BUILD/libm/libm.a" \
        "$BUILD/libdl/libdl.a" \
        "$BUILD/bionic/libc.a" \
        "$LIBGCC" \
    -Wl,--end-group \
    "$BUILD/bionic/crtend.o" \
    -o "$OUT/dalvikvm" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    2>"$OUT/link.log"

# Undefined references are the interesting, actionable part -- summarise them
# uniquely instead of dumping one line per referencing object. Anything else
# the linker said is shown verbatim, otherwise a non-undefined-symbol failure
# (which is what an empty summary plus a missing binary means) is invisible.
grep -oE "undefined reference to \`[a-zA-Z0-9_.]+'" "$OUT/link.log" | sort -u
grep -v 'undefined reference to' "$OUT/link.log" | grep -vE '^\s*$' | head -20

if [ -f "$OUT/dalvikvm" ]; then
    ls -la "$OUT/dalvikvm"
else
    echo "LINK FAILED -- no binary produced (full output: $OUT/link.log)"
fi

# dalvikvm_debug: identical, but linked against the FAKE_LOG_DEVICE liblog,
# which sends LOG*/LOGE output to stderr instead of /dev/log/*.
#
# This is what makes the boot smoke test readable: etc/dalvik_smoketest.sh
# captures stdout+stderr and funnels it into /dev/kmsg so it lands in
# dmesg (and therefore in boot_log_latest.txt). With the real liblog the VM's
# diagnostics would disappear into the logger driver with nothing to read
# them back out yet.
#
# It is built HERE, in the same script and from the same objects, on purpose:
# it was previously produced by hand, which meant that rebuilding libc left a
# dalvikvm_debug linked against a different libc than everything else --
# exactly the stale-binary trap that has already cost this port a boot cycle.
echo "=== dalvikvm_debug (FAKE_LOG_DEVICE liblog -> stderr) ==="
"$GCC" -nostdlib -static \
    "$BUILD/bionic/crtbegin.o" \
    "$OUT/obj/Main.o" \
    `# Force libutils' Static.o into the link. It holds the only instance of
     # LibUtilsFirstStatics, whose constructor calls initialize_string8() /
     # initialize_string16(). Nothing references Static.o, so a static link
     # leaves it in the archive and those never run -- after which
     # gEmptyStringBuf is NULL and *any* empty or default-constructed String8
     # dereferences NULL. AOSP builds libutils as a shared library, so it
     # never hits this; the gDarwinCantLoadAllObjects symbol exists upstream
     # for exactly this purpose.` \
    -Wl,-u,_ZN7android25gDarwinCantLoadAllObjectsE \
    -Wl,--start-group \
        "$BUILD/libdvm/libdvm.a" \
        "$BUILD/libdex/libdex.a" \
        "$BUILD/libnativehelper/libnativehelper.a" \
        `# The real Register.c now, not android3ds_register_stub.c: libjavacore
         # and all five of its external libraries are built, so the ~45
         # register_*() entry points it calls actually resolve.` \
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
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog_fake/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/zlib/libz.a" \
        "$BUILD/libm/libm.a" \
        "$BUILD/libdl/libdl.a" \
        "$BUILD/bionic/libc.a" \
        "$LIBGCC" \
    -Wl,--end-group \
    "$BUILD/bionic/crtend.o" \
    -o "$OUT/dalvikvm_debug" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    2>"$OUT/link_debug.log"

grep -oE "undefined reference to \`[a-zA-Z0-9_.]+'" "$OUT/link_debug.log" | sort -u
if [ -f "$OUT/dalvikvm_debug" ]; then
    ls -la "$OUT/dalvikvm_debug"
else
    echo "dalvikvm_debug LINK FAILED (full output: $OUT/link_debug.log)"
fi
