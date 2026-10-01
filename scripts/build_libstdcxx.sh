#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
OUT="${ANDROID3DS_ROOT}"/build/libstdcxx
LSTL="${ANDROID3DS_ROOT}"/third_party/bionic/libstdc++
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
mkdir -p "$OUT"

# bionic's own minimal C++ runtime stub (NOT a full libstdc++/STL -- just
# operator new/delete, bare-bones typeinfo, the pure-virtual-call trap, and
# static-local-init guards). Eclair's C++ frameworks code uses its own
# String8/Vector/etc instead of STL containers, so this tiny stub is all
# any of it actually needs to link.
CXXFLAGS="-nostdinc++ -fno-exceptions -fno-rtti -fno-stack-protector -fno-pic -fno-delete-null-pointer-checks \
-D__ARM_EABI__ -DANDROID \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include"

for f in new typeinfo pure_virtual one_time_construction; do
    "$GXX" $CXXFLAGS -c "$LSTL/src/$f.cpp" -o "$OUT/$f.o"
done
"$TC/arm-buildroot-linux-gnueabihf-ar" rcs "$OUT/libstdc++.a" "$OUT"/*.o
echo "libstdc++.a built"
