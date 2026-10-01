#!/bin/bash
# Build libfdlibm.a -- the freely distributable IEEE 754 math library that
# java.lang.StrictMath is defined in terms of.
#
# libcore's java_lang_StrictMath.c does
#     #include "../../external/fdlibm/fdlibm.h"
# which only resolves if the tree looks like AOSP's, i.e. if there is an
# "external" directory two levels above dalvik/vm. This script creates
# third_party/external/ as symlinks so that relative include works unmodified
# rather than patching upstream sources.
#
# Source list and flags come straight from external/fdlibm/Android.mk.
# -D_IEEE_LIBM guarantees the IEEE core functions are used, which is the whole
# point of StrictMath (bit-for-bit reproducible results across platforms).
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
FDLIBM=$TP/fdlibm
OUT="${ANDROID3DS_ROOT}"/build/fdlibm

# AOSP-style external/ layout, so upstream's relative includes resolve.
mkdir -p "$TP/external"
for n in fdlibm expat sqlite openssl icu4c zlib; do
    ln -sfn "../$n" "$TP/external/$n"
done

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o

CFLAGS="-nostdinc -O2 -fno-stack-protector -fno-pic -std=gnu89 \
-D_IEEE_LIBM -D__LITTLE_ENDIAN \
-Wno-implicit-function-declaration -Wno-attributes \
-D__ARM_EABI__ -DANDROID \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FDLIBM"

SRCS="k_standard.c k_rem_pio2.c k_cos.c k_sin.c k_tan.c \
e_acos.c e_acosh.c e_asin.c e_atan2.c e_atanh.c e_cosh.c e_exp.c e_fmod.c \
e_gamma.c e_gamma_r.c e_hypot.c e_j0.c e_j1.c e_jn.c e_lgamma.c e_lgamma_r.c \
e_log.c e_log10.c e_pow.c e_rem_pio2.c e_remainder.c e_scalb.c e_sinh.c \
e_sqrt.c w_acos.c w_acosh.c w_asin.c w_atan2.c w_atanh.c w_cosh.c w_exp.c \
w_fmod.c w_gamma.c w_gamma_r.c w_hypot.c w_j0.c w_j1.c w_jn.c w_lgamma.c \
w_lgamma_r.c w_log.c w_log10.c w_pow.c w_remainder.c w_scalb.c w_sinh.c \
w_sqrt.c s_asinh.c s_atan.c s_cbrt.c s_ceil.c s_copysign.c s_cos.c s_erf.c \
s_expm1.c s_fabs.c s_finite.c s_floor.c s_frexp.c s_ilogb.c s_isnan.c \
s_ldexp.c s_lib_version.c s_log1p.c s_logb.c s_matherr.c s_modf.c \
s_nextafter.c s_rint.c s_scalbn.c s_signgam.c s_significand.c s_sin.c \
s_tan.c s_tanh.c"

OK=0; FAIL=0; FAILED=""
for f in $SRCS; do
    if "$GCC" $CFLAGS -c "$FDLIBM/$f" -o "$OUT/obj/${f%.c}.o" 2>"$OUT/obj/${f%.c}.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done
echo "fdlibm: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    for f in $FAILED; do echo "--- $f"; head -8 "$OUT/obj/${f%.c}.log"; done
    exit 1
fi

rm -f "$OUT/libfdlibm.a"
"$AR" rcs "$OUT/libfdlibm.a" "$OUT"/obj/*.o
ls -la "$OUT/libfdlibm.a"
echo "libfdlibm.a: $("$AR" t "$OUT/libfdlibm.a" | wc -l) objects"
