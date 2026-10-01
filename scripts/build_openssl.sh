#!/bin/bash
# Build libcrypto.a and libssl.a for the target.
#
# libcore's openssl and x-net modules need both: NativeBN (java.math.BigInteger
# is backed by OpenSSL BN), NativeCrypto, and the OpenSSLSocketImpl /
# OpenSSLServerSocketImpl / OpenSSLSessionImpl JSSE provider.
#
# The source lists come out of external/openssl's own crypto/Android.mk and
# ssl/Android.mk rather than being hand-written, so they cannot drift. The
# build-time configuration (which ciphers are compiled out) comes from
# android-config.mk -- these MUST match what the headers were generated with,
# because include/openssl/opensslconf.h is checked in pre-generated and
# disagreeing about, say, OPENSSL_NO_BF changes struct layouts.
#
# The ARM assembly implementations (bn/armv4-mont.s, aes/aes-armv4.s, the SHA
# ones) are used, matching AOSP: they are a large speed win on a 268 MHz ARM11.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
SYSCORE=$TP/system_core
SSL=$TP/openssl
OUT="${ANDROID3DS_ROOT}"/build/openssl

mkdir -p "$OUT/obj/crypto" "$OUT/obj/ssl" "$OUT/gen"
rm -f "$OUT"/obj/crypto/*.o "$OUT"/obj/ssl/*.o

# crypto/cversion.c #includes buildinf.h, which openssl's own Makefile
# generates at build time (it is what SSLeay_version(SSLEAY_CFLAGS) reports).
# Nothing reads these strings on this device, but the file has to exist.
cat > "$OUT/gen/buildinf.h" <<EOF
#define CFLAGS "compiler: arm-buildroot-linux-gnueabihf-gcc"
#define PLATFORM "linux-generic32"
#define DATE "$(date -u '+%a %b %e %H:%M:%S %Y')"
EOF

# Pull LOCAL_SRC_FILES out of an Android.mk, keeping the TARGET_ARCH==arm
# branch and dropping the else branch.
extract_srcs() {
python3 - "$1" <<'PYEOF'
import re, sys
text = open(sys.argv[1]).read()

# Drop the non-arm side of "ifeq ($(TARGET_ARCH),arm) ... else ... endif".
def strip_else(m):
    return m.group(1)
text = re.sub(r"ifeq \(\$\(TARGET_ARCH\),arm\)(.*?)else.*?endif",
              strip_else, text, flags=re.S)

files = []
for m in re.finditer(r"LOCAL_SRC_FILES\s*[:+]?=(.*?)(?=\n[A-Za-z_]|\n\s*\n|\Z)",
                     text, flags=re.S):
    block = m.group(1)
    block = block.replace("\\\n", " ")
    for tok in block.split():
        if tok.endswith(".c") or tok.endswith(".s") or tok.endswith(".S"):
            files.append(tok)
seen = set()
for f in files:
    if f not in seen:
        seen.add(f)
        print(f)
PYEOF
}

# From android-config.mk -- the exact configuration opensslconf.h was made for.
CONF="-DOPENSSL_THREADS -D_REENTRANT -DDSO_DLFCN -DHAVE_DLFCN_H -DL_ENDIAN \
-DOPENSSL_NO_HW -DOPENSSL_NO_BF -DOPENSSL_NO_CAMELLIA -DOPENSSL_NO_CAST \
-DOPENSSL_NO_CMS -DOPENSSL_NO_GMP -DOPENSSL_NO_IDEA -DOPENSSL_NO_MDC2 \
-DOPENSSL_NO_RC5 -DOPENSSL_NO_RFC3779 -DOPENSSL_NO_SEED -DOPENSSL_NO_TLSEXT \
-DOPENSSL_NO_MD2"

ARM_ASM="-DOPENSSL_BN_ASM_MONT -DAES_ASM -DSHA1_ASM -DSHA256_ASM -DSHA512_ASM"

# -std=gnu89 -fgnu89-inline is not optional with bionic's headers: ctype.h
# declares isalnum/isalpha/... as plain `inline` functions. Under C99/gnu17
# semantics that emits an external definition in every translation unit, so
# linking libcrypto.a and libsqlite.a together fails with "multiple definition
# of isalnum". gnu89 inline semantics (what these 2009 headers were written
# for) emit none. Same flags every other C target here uses.
CFLAGS="-nostdinc -O2 -fno-stack-protector -fno-pic -std=gnu89 -fgnu89-inline \
-Wno-implicit-function-declaration -Wno-attributes -Wno-pointer-sign \
-Wno-discarded-qualifiers -Wno-int-conversion \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
$CONF $ARM_ASM \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include \
-I $SSL \
-I $SSL/include \
-I $SSL/crypto \
-I $SSL/crypto/asn1 \
-I $SSL/crypto/evp \
-I $OUT/gen"

build_lib() {
    local dir="$1" name="$2"
    local srcs
    srcs=$(extract_srcs "$SSL/$dir/Android.mk")
    local n=0 ok=0 fail=0 failed=""
    for f in $srcs; do
        n=$((n+1))
        local o="$OUT/obj/$dir/$(echo "$f" | tr '/' '_')"
        o="${o%.*}.o"
        local extra=""
        if [ "$f" = "ui/ui_openssl.c" ]; then
            # This file picks its terminal API from the platform: on Linux it
            # forces TERMIO and includes <termio.h>, which bionic does not
            # have (it only ships termios.h). -Ulinux skips that branch and
            # -DTERMIOS selects the POSIX termios path instead, which bionic
            # does implement. Only used by OpenSSL's interactive password
            # prompt, which nothing here calls, but ui_lib.c references the
            # symbol so it cannot simply be dropped.
            extra="-Ulinux -DTERMIOS"
        fi
        if "$GCC" $CFLAGS $extra -I "$SSL/$dir" -c "$SSL/$dir/$f" -o "$o" \
                > "$o.log" 2>&1; then
            ok=$((ok+1))
        else
            fail=$((fail+1)); failed="$failed $f"
        fi
    done
    echo "$name: total=$n OK=$ok FAIL=$fail"
    if [ -n "$failed" ]; then
        echo "  failed:$failed" | head -c 2000; echo
        for f in $failed; do
            local o="$OUT/obj/$dir/$(echo "$f" | tr '/' '_')"; o="${o%.*}.o"
            echo "--- $f"; grep -m3 "error:" "$o.log" || head -5 "$o.log"
        done
        return 1
    fi
    rm -f "$OUT/lib$name.a"
    "$AR" rcs "$OUT/lib$name.a" "$OUT"/obj/$dir/*.o
    ls -la "$OUT/lib$name.a"
}

echo "=== libcrypto ==="
build_lib crypto crypto
echo
echo "=== libssl ==="
build_lib ssl ssl
