#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
PROJECT="${ANDROID3DS_WIN}"
TC=$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX=$TC/arm-buildroot-linux-gnueabihf-g++
GCC=$TC/arm-buildroot-linux-gnueabihf-gcc
QEMU=$ROOT/toolchain/qemu/qemu-arm-static
BIONIC=$ROOT/third_party/bionic
SYSCORE=$ROOT/third_party/system_core
FWBASE=$ROOT/third_party/frameworks/base
BUILD=$ROOT/build
OUT=$BUILD/pixelflinger_codegen_smoke
LIBGCC="$($GCC -print-libgcc-file-name)"

mkdir -p "$OUT"

"$GXX" -nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
    -fno-stack-protector -fno-pic -O2 \
    -D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
    -include "$SYSCORE/include/arch/linux-arm/AndroidConfig.h" \
    -isystem "$($GXX -print-file-name=include)" \
    -I "$BIONIC/libstdc++/include" \
    -I "$BIONIC/libc/include" \
    -I "$BIONIC/libm/include" \
    -I "$BIONIC/libc/kernel/common" \
    -I "$BIONIC/libc/kernel/arch-arm" \
    -I "$BIONIC/libc/arch-arm/include" \
    -I "$FWBASE/include" -I "$SYSCORE/include" \
    -I "$SYSCORE/libpixelflinger" \
    -c "$PROJECT/content/PixelflingerCodeCacheSmoke.cpp" \
    -o "$OUT/smoke.o"

"$GXX" -nostdlib -static \
    "$BUILD/bionic/crtbegin.o" "$OUT/smoke.o" \
    -Wl,--start-group \
        "$BUILD/libpixelflinger/libpixelflinger.a" \
        "$BUILD/libutils/libutils.a" \
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/bionic/libc.a" "$LIBGCC" \
    -Wl,--end-group \
    "$BUILD/bionic/crtend.o" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    -o "$OUT/pixelflinger-codecache-smoke"

LOG=$OUT/run.log
set +e
timeout 15s "$QEMU" "$OUT/pixelflinger-codecache-smoke" >"$LOG" 2>&1
status=$?
set -e
cat "$LOG"
grep -q 'PASS: PixelFlinger register-pressure unwind preserved SP' "$LOG" || {
    echo "FAIL: register-pressure cleanup regression (status=$status)" >&2
    exit 1
}
grep -q 'PASS: Pixelflinger CodeCache executed generated ARM code' "$LOG" || {
    echo "FAIL: generated-code smoke did not complete (status=$status)" >&2
    exit 1
}
