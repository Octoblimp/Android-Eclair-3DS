#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
PROJECT="${ANDROID3DS_WIN}"
DOWNLOADS="$ROOT/third_party/downloads"
SRC="$ROOT/third_party/telco_https"
MBED="$SRC/mbedtls-3.6.5"
CURL="$SRC/curl-8.18.0"
OUT="$ROOT/build/telco_https"
TOOLCHAIN="$ROOT/third_party/buildroot/output/host/bin"
CC="$TOOLCHAIN/arm-linux-gcc"
AR="$TOOLCHAIN/arm-linux-ar"
RANLIB="$TOOLCHAIN/arm-linux-ranlib"
STRIP="$TOOLCHAIN/arm-linux-strip"
CA_SOURCE=/etc/ssl/certs/ca-certificates.crt

bash "$PROJECT/scripts/fetch_telco_https_dependencies.sh"
test -x "$CC"
test -s "$CA_SOURCE"
rm -rf "$SRC" "$OUT"
mkdir -p "$SRC" "$OUT"
tar -xjf "$DOWNLOADS/mbedtls-3.6.5.tar.bz2" -C "$SRC"
tar -xJf "$DOWNLOADS/curl-8.18.0.tar.xz" -C "$SRC"

make -C "$MBED" -j"$(nproc)" lib \
    CC="$CC" AR="$AR" CFLAGS='-Os -march=armv6 -mfloat-abi=hard -fPIC'

(
    cd "$CURL"
    CC="$CC" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$MBED/include" \
    LDFLAGS="-L$MBED/library" \
    ./configure \
        --host=arm-buildroot-linux-musleabihf \
        --build="$(gcc -dumpmachine)" \
        --disable-shared --enable-static --with-mbedtls="$MBED" \
        --without-zlib --without-brotli --without-zstd --without-libpsl \
        --without-libidn2 --without-libssh2 --without-nghttp2 \
        --disable-ldap --disable-ldaps --disable-rtsp --disable-dict \
        --disable-file --disable-ftp --disable-gopher --disable-imap \
        --disable-mqtt --disable-pop3 --disable-smb --disable-smtp \
        --disable-telnet --disable-tftp --disable-manual --disable-docs
    make -C lib -j"$(nproc)" libcurl.la
)

"$CC" -Os -march=armv6 -mfloat-abi=hard -static \
    -I"$CURL/include" -I"$MBED/include" \
    "$ROOT/native/telco_https.c" "$CURL/lib/.libs/libcurl.a" \
    "$MBED/library/libmbedtls.a" "$MBED/library/libmbedx509.a" \
    "$MBED/library/libmbedcrypto.a" -lpthread -lm -o "$OUT/telco_https"
"$STRIP" "$OUT/telco_https"
cp "$CA_SOURCE" "$OUT/cacert.pem"
chmod 755 "$OUT/telco_https"
chmod 644 "$OUT/cacert.pem"

file "$OUT/telco_https" | grep -F 'ARM'
file "$OUT/telco_https" | grep -F 'statically linked'
strings "$OUT/telco_https" | grep -F 'N3DS-TELCO-HTTPS/1'
grep -F 'BEGIN CERTIFICATE' "$OUT/cacert.pem" >/dev/null

if [ "${STAGE_TELCO_HTTPS:-0}" = 1 ]; then
    for root in \
        "$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay" \
        "$ROOT/third_party/buildroot/output/target" \
        "$ROOT/sdcard/linux/android" \
        "${ANDROID3DS_WIN}/sdcard/linux/android"; do
        mkdir -p "$root/system/bin" "$root/system/etc/security"
        cp "$OUT/telco_https" "$root/system/bin/telco_https"
        cp "$OUT/cacert.pem" "$root/system/etc/security/cacert.pem"
        chmod 755 "$root/system/bin/telco_https"
        chmod 644 "$root/system/etc/security/cacert.pem"
    done
fi

sha256sum "$OUT/telco_https" "$OUT/cacert.pem"
echo 'build_telco_https: ALL OK'
