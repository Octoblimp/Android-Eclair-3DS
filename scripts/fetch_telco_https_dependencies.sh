#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
DOWNLOADS="$ROOT/third_party/downloads"
mkdir -p "$DOWNLOADS"

fetch() {
    name="$1" url="$2" expected="$3" path="$DOWNLOADS/$name"
    if [ ! -f "$path" ] || [ "$(sha256sum "$path" | cut -d' ' -f1)" != "$expected" ]; then
        rm -f "$path"
        curl -fL --retry 3 -o "$path" "$url"
    fi
    echo "$expected  $path" | sha256sum -c -
}

fetch mbedtls-3.6.5.tar.bz2 \
    https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-3.6.5/mbedtls-3.6.5.tar.bz2 \
    4a11f1777bb95bf4ad96721cac945a26e04bf19f57d905f241fe77ebeddf46d8
fetch curl-8.18.0.tar.xz \
    https://curl.se/download/curl-8.18.0.tar.xz \
    40df79166e74aa20149365e11ee4c798a46ad57c34e4f68fd13100e2c9a91946
