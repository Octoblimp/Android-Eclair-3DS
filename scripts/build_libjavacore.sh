#!/bin/bash
# Build libjavacore.a -- the native half of the core Java class library.
#
# This is what jniRegisterSystemMethods() (libnativehelper/Register.c) calls
# into: ~45 register_*() entry points implementing the JNI natives for
# java.io, java.lang, java.net, java.util.zip, the ICU-backed text/collation
# classes, the OpenSSL-backed crypto and JSSE provider, SQLite and Expat.
#
# Every module's source list comes from its own sub.mk, which the real
# libcore/Android.mk includes -- so this cannot drift from upstream.
#
# Two flags are load-bearing and were not obvious:
#   -I frameworks/base/include        for <utils/Log.h>
#   -include .../AndroidConfig.h      resolves the struct iovec redefinition
#                                     between bionic and cutils/uio.h, and
#                                     supplies MINCORE_POINTER_TYPE (do NOT
#                                     define that yourself, AndroidConfig.h:268
#                                     already does)
#
# java_lang_StrictMath.c does #include "../../external/fdlibm/fdlibm.h", which
# only resolves because -I dalvik/vm is two levels above third_party/external
# (created as symlinks by build_fdlibm.sh), exactly as in an AOSP tree.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
LSTL=$BIONIC/libstdc++
SYSCORE=$TP/system_core
FWBASE=$TP/frameworks/base
DALVIK=$TP/dalvik
LIBCORE=$DALVIK/libcore
NH=$DALVIK/libnativehelper
OUT="${ANDROID3DS_ROOT}"/build/libjavacore
ABI_PATCH="${ANDROID3DS_WIN}/scripts/apply_float_jni_abi.py"

# Dalvik invokes JNI with the base AAPCS, while the Android3DS compiler
# defaults to the hard-float PCS. ICU contains scalar float/double natives
# (notably DecimalFormat.format(double,...)); repair and audit them even when
# this focused builder is invoked outside rebuild_native_stack.sh.
python3 "$ABI_PATCH" --apply \
    "$LIBCORE/luni/src/main/native" \
    "$LIBCORE/icu/src/main/native"

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o "$OUT"/obj/*.log

CFLAGS="-nostdinc -O2 -fno-delete-null-pointer-checks -fno-stack-protector -fno-pic -fno-strict-aliasing \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-attributes \
-Wno-pointer-sign -Wno-discarded-qualifiers \
`# GCC 14 turned -Wincompatible-pointer-types into an error. The only hit is
 # icu/ConverterInterface.c passing "void **" where ICU declares
 # "const void **" (ucnv_getToUCallBack/ucnv_getFromUCallBack) -- a pure
 # const-qualification mismatch in Android's own added cleanup code, which
 # just reads the context pointer back out and free()s it.` \
-Wno-incompatible-pointer-types \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DLINUX \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include \
-I $FWBASE/include \
-I $NH/include/nativehelper \
-I $DALVIK \
-I $DALVIK/vm \
-I $DALVIK/libdex \
-I $TP/zlib \
-I $TP/expat/lib \
-I $TP/sqlite/dist \
-I $TP/openssl/include \
-I $TP/icu4c/common \
-I $TP/icu4c/i18n"

CXX_EXTRA="-nostdinc++ -std=gnu++98 -fno-exceptions -fno-rtti \
-Wno-invalid-offsetof -I $LSTL/include"

extract_srcs() {
python3 - "$1" <<'PYEOF'
import re, sys
text = open(sys.argv[1]).read()
files = []
for m in re.finditer(r"LOCAL_SRC_FILES\s*[:+]?=(.*?)(?=\n[A-Za-z_#]|\n\s*\n|\Z)",
                     text, flags=re.S):
    block = m.group(1).replace("\\\n", " ")
    for tok in block.split():
        if tok.endswith(".c") or tok.endswith(".cpp"):
            files.append(tok)
seen = set()
for f in files:
    if f not in seen:
        seen.add(f)
        print(f)
PYEOF
}

TOTAL=0; OK=0; FAIL=0; FAILED=""
for submk in $(find "$LIBCORE" -name sub.mk | sort); do
    d=$(dirname "$submk")
    mod=$(echo "$d" | sed -E 's|.*/libcore/([^/]+)/.*|\1|')
    for f in $(extract_srcs "$submk"); do
        TOTAL=$((TOTAL+1))
        o="$OUT/obj/${mod}__${f%.*}.o"
        cc="$GCC"; extra=""
        case "$f" in *.cpp) cc="$GXX"; extra="$CXX_EXTRA" ;; esac
        if "$cc" $CFLAGS $extra -I "$d" -c "$d/$f" -o "$o" > "$o.log" 2>&1; then
            OK=$((OK+1))
        else
            FAIL=$((FAIL+1)); FAILED="$FAILED $mod/$f"
        fi
    done
done

echo "libjavacore: total=$TOTAL OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    for x in $FAILED; do
        mod=${x%%/*}; f=${x#*/}
        echo "--- $x"
        grep -m4 -E "error:|fatal error:" "$OUT/obj/${mod}__${f%.*}.o.log" || \
            head -6 "$OUT/obj/${mod}__${f%.*}.o.log"
    done
    exit 1
fi

rm -f "$OUT/libjavacore.a"
"$AR" rcs "$OUT/libjavacore.a" "$OUT"/obj/*.o
ls -la "$OUT/libjavacore.a"
echo "libjavacore.a: $("$AR" t "$OUT/libjavacore.a" | wc -l) objects"
