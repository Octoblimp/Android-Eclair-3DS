#!/bin/bash
# bionic libm for the ARM target. libdvm's interpreter needs sin/cos/sqrt/
# fmod/fmodf (the Math.* intrinsics and the float/double opcodes), so libm
# has to exist before dalvikvm can link.
#
# The source list is read straight out of bionic/libm/Android.mk
# (libm_common_src_files + the TARGET_ARCH==arm block) rather than being
# copied here by hand -- there are ~150 entries and src/ contains extra
# files that are deliberately NOT in the list (long-double variants that
# need an ld80 layout ARM doesn't use).
#
# Note the arm block contributes more than just arm/*.c: src/s_scalbn.c and
# src/s_scalbnf.c live there too (x86 uses hand-written i387 versions
# instead), so it must be scanned for every .c entry, not only arm/ ones.
# Missing them shows up only at final link, as an undefined `scalbn'.
# The arm ifeq's "else" branch holds the x86 (i387) list and the matching
# "endif" is the outer one, so the extracted range is cut at the else --
# otherwise i387/fenv.c gets swept into an ARM build.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LIBM=$BIONIC/libm
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
# MODE=static (default) -> libm.a for static executables, unchanged.
# MODE=shared -> PIC objects plus libm.so for the dynamic linker world.
MODE="${MODE:-static}"
if [ "$MODE" = "shared" ]; then
    OUT="${ANDROID3DS_ROOT}"/build/libm_shared
    PIC_FLAGS="-fPIC"
else
    OUT="${ANDROID3DS_ROOT}"/build/libm
    PIC_FLAGS="-fno-pic"
fi
mkdir -p "$OUT/obj"
LOG="$OUT/build.log"
: > "$LOG"

# Everything between "libm_common_src_files:=" and the first blank line,
# plus the arm/ files from the TARGET_ARCH==arm block. Strips the "\"
# continuations and any comments.
SRCS="$(sed -n '/^libm_common_src_files:=/,/^$/p' "$LIBM/Android.mk" \
        | sed -e 's/libm_common_src_files:=//' -e 's/\\$//' \
        | tr -s ' \t' '\n' | grep '\.c$')
$(sed -n '/^ifeq ($(TARGET_ARCH),arm)/,/^endif/p' "$LIBM/Android.mk" \
        | sed -e '/^else$/,$d' -e 's/\\$//' | tr -s ' \t' '\n' | grep '\.c$')"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -O2 -fno-stack-protector $PIC_FLAGS \
-fno-builtin -DFLT_EVAL_METHOD=0 \
-Wno-attributes -Wno-implicit-function-declaration -Wno-uninitialized \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-isystem $($GCC -print-file-name=include) \
-I $LIBM \
-I $LIBM/include \
-I $LIBM/include/arm \
-I $LIBM/arm \
-I $LIBM/src \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $BIONIC/libc/private \
-I $SYSCORE/include"

OK=0; FAIL=0; FAILED=""
for f in $SRCS; do
    [ -e "$LIBM/$f" ] || { echo "missing source: $f"; continue; }
    obj="$OUT/obj/$(echo "${f%.c}" | tr / _).o"
    extra=""
    # include/arm/fenv.h uses __BEGIN_DECLS/__END_DECLS without pulling in
    # <sys/cdefs.h> itself -- fine when reached via <math.h>, a hard error
    # when arm/fenv.c includes it as the very first header.
    case "$f" in arm/fenv.c) extra="-include sys/cdefs.h" ;; esac
    if "$GCC" $CFLAGS $extra -c "$LIBM/$f" -o "$obj" >>"$LOG" 2>&1; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

echo "libm: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    echo "see $LOG"
fi
rm -f "$OUT/libm.a"
"$AR" rcs "$OUT/libm.a" "$OUT"/obj/*.o
echo "libm.a built: $("$AR" t "$OUT/libm.a" | wc -l) objects"

if [ "$MODE" = "shared" ]; then
    echo "=== linking libm.so ==="
    # --whole-archive so the .so actually exports the math symbols rather
    # than coming out empty (nothing is undefined to pull members in).
    # libgcc with --exclude-libs: libm needs __aeabi_d2lz/__aeabi_f2lz
    # (double/float -> long long), which are NOT in libgcc_compat.c's
    # re-export list and so are not available from libc.so. It therefore
    # takes its own private copy, hidden rather than exported -- which is
    # exactly the case bionic's "add --exclude-libs=libgcc.a to those
    # libraries" warning is about.
    LIBGCC="$("$GCC" -print-libgcc-file-name)"
    "$GCC" -nostdlib -shared -Wl,-soname,libm.so \
        -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
        -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
        -o "$OUT/libm.so" \
        -Wl,--whole-archive "$OUT/libm.a" -Wl,--no-whole-archive \
        -Wl,--exclude-libs=libgcc.a "$LIBGCC" \
        > "$OUT/link.log" 2>&1 || {
            echo "libm.so LINK FAILED"; head -20 "$OUT/link.log"; exit 1; }
    ls -la "$OUT/libm.so"
fi
