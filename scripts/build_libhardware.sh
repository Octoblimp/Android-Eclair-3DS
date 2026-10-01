#!/bin/bash
# Build libhardware.a (hw_get_module -- the dlopen-based HAL loader used by
# lights/sensors, see hal/) and libhardware_legacy.a (power.c wakelock
# wrapper -- talks to the /sys/power/wake_lock driver Phase 3 already ported
# -- uevent.c, the coldboot/hotplug netlink listener -- and vibrator.c, a
# real /sys/class/timed_output/vibrator/enable writer: the New 3DS has no
# rumble motor, so this genuinely returns ENOENT at runtime rather than
# faking success, same "real driver, real failure" preference as everything
# else in this project).
#
# Deliberately NOT built here: gps (no GPS radio), flashlight/camera flash
# (no camera flash), wifi.c (WiFi is parked, see docs/HANDOFF.md) -- their
# JNI registrations are cut in AndroidRuntime.cpp instead of stubbed.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
SYSCORE=$TP/system_core
BUILD="${ANDROID3DS_ROOT}"/build

BASE_CFLAGS="-nostdinc -O2 -fno-stack-protector -fno-pic -std=gnu89 -fgnu89-inline \
-Wno-implicit-function-declaration -Wno-attributes -Wno-pointer-sign \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include \
-I $TP/frameworks/base/include"

# ----------------------------------------------------------- libhardware ----
HW=$TP/libhardware
OUT=$BUILD/libhardware
mkdir -p "$OUT/obj"; rm -f "$OUT"/obj/*.o

echo "=== libhardware (hw_get_module) ==="
"$GCC" $BASE_CFLAGS -I "$HW/include" -c "$HW/hardware.c" -o "$OUT/obj/hardware.o"
rm -f "$OUT/libhardware.a"
"$AR" rcs "$OUT/libhardware.a" "$OUT"/obj/*.o
ls -la "$OUT/libhardware.a"

# ---------------------------------------------------- libhardware_legacy ----
HWL=$TP/libhardware_legacy
OUT=$BUILD/libhardware_legacy
mkdir -p "$OUT/obj"; rm -f "$OUT"/obj/*.o

HWL_CFLAGS="$BASE_CFLAGS -I $HWL/include -I $HWL -I $HW/include"

WPA_DIR=$TP/buildroot/output/build/wpa_supplicant-2.10/src
WPA_CFLAGS="-I$WPA_DIR/common -I$WPA_DIR/utils -I$WPA_DIR -DCONFIG_CTRL_IFACE -DCONFIG_CTRL_IFACE_UNIX"

echo "=== libhardware_legacy (power, uevent, vibrator, wifi) ==="
"$GCC" $HWL_CFLAGS -c "$HWL/power/power.c" -o "$OUT/obj/power.o"
"$GCC" $HWL_CFLAGS -c "$HWL/uevent/uevent.c" -o "$OUT/obj/uevent.o"
"$GCC" $HWL_CFLAGS -c "$HWL/vibrator/vibrator.c" -o "$OUT/obj/vibrator.o"
"$GCC" $HWL_CFLAGS -c "$HWL/wifi/wifi.c" -o "$OUT/obj/wifi.o"
"$GCC" $HWL_CFLAGS $WPA_CFLAGS -c "$WPA_DIR/common/wpa_ctrl.c" -o "$OUT/obj/wpa_ctrl.o"
rm -f "$OUT/libhardware_legacy.a"
"$AR" rcs "$OUT/libhardware_legacy.a" "$OUT"/obj/*.o
ls -la "$OUT/libhardware_legacy.a"
