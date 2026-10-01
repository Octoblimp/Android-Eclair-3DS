#!/bin/bash
# Build the bionic dynamic linker (/system/bin/linker).
#
# This is the piece that makes dlopen() real. Up to now everything in the
# port has been statically linked and bionic's libdl.c stubs made dlopen()
# always return NULL, which means System.loadLibrary() and every JNI shared
# library are impossible. The linker is the prerequisite for libcore.
#
# Three things make this build unlike every other build_*.sh here:
#
#  1. It is a STATIC executable linked at a fixed address (0xB0000100) that
#     is nevertheless position-independent code, because it has to relocate
#     itself before it can relocate anything else. begin.S provides _start,
#     so crtbegin/crtend are deliberately NOT linked in.
#  2. Every symbol gets renamed with --prefix-symbols=__dl_ at the end. The
#     linker carries its own private copy of libc; without the prefix those
#     symbols would collide with the libc.so it is loading on behalf of the
#     program.
#  3. It needs libc/private for <bionic_tls.h>.
#
# Address map sanity (checked against third_party/linux/.config):
#   CONFIG_VMSPLIT_3G=y, PAGE_OFFSET=0xC0000000 => TASK_SIZE ~0xBF000000.
#   Linker text 0xB0000100 + 16MB area  -> 0xB1000000   : fits.
#   Shared libs LIBBASE..LIBLAST 0x80000000..0x90000000 : fits.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
OBJCOPY="$TC/arm-buildroot-linux-gnueabihf-objcopy"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
OUT="${ANDROID3DS_ROOT}"/build/linker
LOG="$OUT/build.log"

rm -rf "$OUT/obj"
mkdir -p "$OUT/obj"
: > "$LOG"

GCC_INCLUDE="$("$GCC" -print-file-name=include)"

LINKER_TEXT_BASE=0xB0000100
LINKER_AREA_SIZE=0x01000000

# -fno-stack-protector is not optional here: the stack guard lives in TLS,
# and the linker runs before TLS is set up for the process.
#
# -fno-jump-tables: jump tables land in .rodata and are referenced through
# absolute addresses, which the linker cannot use before it has relocated
# itself. Upstream gets away without this because the 2009 compiler didn't
# generate them at -O2 for this code; GCC 14 does.
CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector -fno-builtin \
-fno-strict-aliasing -fno-jump-tables -O2 -fPIC \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-return-type \
-Wno-attributes -Wno-builtin-declaration-mismatch \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DUSE_DL_PREFIX \
-DPRELINK -DANDROID_ARM_LINKER \
-DLINKER_TEXT_BASE=$LINKER_TEXT_BASE -DLINKER_AREA_SIZE=$LINKER_AREA_SIZE \
-isystem $GCC_INCLUDE \
-I $BIONIC/linker \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $BIONIC/libc/private \
-I $BIONIC/libm/include \
-I $SYSCORE/include"

SRCS="arch/arm/begin.S linker.c rt.c dlfcn.c debugger.c ba.c"

OK=0; FAIL=0; FAILED_FILES=""
for f in $SRCS; do
    src="$BIONIC/linker/$f"
    [ -e "$src" ] || { echo "MISSING SOURCE: $f"; FAIL=$((FAIL+1)); continue; }
    obj="$OUT/obj/$(echo "${f%.*}" | tr '/' '_').o"
    if "$GCC" $CFLAGS -c "$src" -o "$obj" >>"$LOG" 2>&1; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED_FILES="$FAILED_FILES $f"
    fi
done

echo "compiled OK: $OK"
echo "compiled FAIL: $FAIL"
if [ -n "$FAILED_FILES" ]; then
    echo "failed files:$FAILED_FILES"
    echo "--- first errors ---"
    grep -E "error:" "$LOG" | head -30
    exit 1
fi

echo "=== linking linker ==="
# -Wl,-Ttext places .text at the fixed base. No crtbegin/crtend: begin.S is
# the entry point, so -e _start is explicit.
#
# The --defsym unwind stubs are the same trick link_init.sh uses: libc.a's
# .ARM.exidx sections reference the C++ personality routines even though
# nothing here throws, and libgcc's real ones live in libgcc_eh which a
# -nostdlib link doesn't pull in.
#
# libc.a and libgcc must be in one --start-group: libgcc's __aeabi_idiv0
# calls raise(), which lives in libc, which comes earlier on the line.
LIBGCC="$("$GCC" -print-libgcc-file-name)"
"$GCC" -nostdlib -static -Wl,-Ttext,$LINKER_TEXT_BASE \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    -o "$OUT/linker.elf" \
    "$OUT"/obj/*.o \
    -Wl,--start-group \
      "${ANDROID3DS_ROOT}"/build/libcutils/libcutils.a \
      "${ANDROID3DS_ROOT}"/build/bionic/libc.a \
      "$LIBGCC" \
    -Wl,--end-group \
    > "$OUT/link.log" 2>&1 || {
        echo "LINK FAILED"
        grep -oE "undefined reference to \`[a-zA-Z0-9_.]+'" "$OUT/link.log" | sort -u
        grep -v 'undefined reference to' "$OUT/link.log" | grep -vE '^\s*$' | head -20
        exit 1
    }

echo "=== prefixing symbols with __dl_ ==="
# This is what upstream's Android.mk does by hand after the link. Without it
# the linker's own strcmp/malloc/etc would be visible to (and collide with)
# the libc.so it loads for the program it is starting.
"$OBJCOPY" --prefix-symbols=__dl_ "$OUT/linker.elf" "$OUT/linker"

echo "=== result ==="
ls -la "$OUT/linker"
"$TC/arm-buildroot-linux-gnueabihf-readelf" -h "$OUT/linker" | grep -E "Type|Entry|Machine"
echo "--- unprefixed dynamic symbols (should be none) ---"
"$TC/arm-buildroot-linux-gnueabihf-nm" "$OUT/linker" 2>/dev/null \
    | grep -vE "__dl_|^\s*$" | head -10
