#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LSTL="${ANDROID3DS_ROOT}"/third_party/bionic/libstdc++
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
KERNEL="${ANDROID3DS_ROOT}"/third_party/linux
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
BINDER=$FWBASE/libs/binder
OUT="${ANDROID3DS_ROOT}"/build/libbinder
mkdir -p "$OUT/obj"

# Same flags as build_libutils.sh (see that script + memory
# project_phase6_cxx_toolchain_libutils.md for why each one is needed),
# plus -DBINDER_IPC_32BIT and the kernel uapi include path, matching the
# ABI fix already verified in project_phase6_binder_abi_and_servicemanager.md.
CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti -fno-stack-protector -fno-pic -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-invalid-offsetof \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DBINDER_IPC_32BIT \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $SYSCORE/include \
-I $KERNEL/include/uapi"

SRCS="Binder.cpp BpBinder.cpp IInterface.cpp IMemory.cpp IPCThreadState.cpp \
IPermissionController.cpp IServiceManager.cpp MemoryBase.cpp MemoryDealer.cpp \
MemoryHeapBase.cpp MemoryHeapPmem.cpp Parcel.cpp Permission.cpp \
ProcessState.cpp Static.cpp"

for f in $SRCS; do
    "$GXX" $CXXFLAGS -c "$BINDER/$f" -o "$OUT/obj/${f%.cpp}.o"
done
"$AR" rcs "$OUT/libbinder.a" "$OUT"/obj/*.o
echo "libbinder.a built"
