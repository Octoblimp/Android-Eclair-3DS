#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
LSTL=$BIONIC/libstdc++
SYSCORE=$TP/system_core
NETUTILS=$SYSCORE/libnetutils
OUT="${ANDROID3DS_ROOT}"/build/libnetutils

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o

CFLAGS="-fno-exceptions -fno-rtti -fno-stack-protector -fno-pic -O2 \
-fno-delete-null-pointer-checks -fno-strict-aliasing \
-D__ARM_EABI__ -DANDROID -DLINUX \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $BIONIC/libc/private \
-I $SYSCORE/include"

echo "=== libnetutils ==="
for f in dhcpclient.c dhcpmsg.c dhcp_utils.c ifc_utils.c packet.c; do
    "$GCC" $CFLAGS -c "$NETUTILS/$f" -o "$OUT/obj/${f%.c}.o"
done

rm -f "$OUT/libnetutils.a"
"$AR" rcs "$OUT/libnetutils.a" "$OUT"/obj/*.o
ls -la "$OUT/libnetutils.a"
