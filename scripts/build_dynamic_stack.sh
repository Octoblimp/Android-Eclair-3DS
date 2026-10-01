#!/bin/bash
# Build the whole dynamic-linking world: the linker plus PIC shared
# libraries, then a dynamically linked test binary.
#
# Dependency order matters. libc.so has exactly one DT_NEEDED -- libdl.so --
# so libdl.so has to exist first. libdl.so's dlopen/dlsym/dlclose/dlerror
# are deliberate stubs that return 0 and are NEVER called: bionic's linker
# (dlfcn.c) builds a synthetic `libdl_info' soinfo, splices it in at the
# head of the solist, and hijacks those names so every lookup lands on the
# linker's real implementations. libdl.so exists purely so the DT_NEEDED
# resolves.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
READELF="$TC/arm-buildroot-linux-gnueabihf-readelf"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
OUT="${ANDROID3DS_ROOT}"/build/bionic_shared
mkdir -p "$OUT/obj"

GCC_INCLUDE="$("$GCC" -print-file-name=include)"
CFLAGS_BASE="-nostdinc -std=gnu89 -fgnu89-inline -O2 -fno-stack-protector -fPIC \
-fno-builtin -Wno-attributes -Wno-implicit-function-declaration \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-isystem $GCC_INCLUDE \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $BIONIC/libc/private \
-I $SYSCORE/include"

echo "############ 1/5  linker ############"
bash "$SCRIPTS/build_linker.sh" | tail -6

echo
echo "############ 2/5  libdl.so ############"
"$GCC" $CFLAGS_BASE -c "$BIONIC/libdl/libdl.c" -o "$OUT/obj/libdl.o"
# No --no-undefined: libdl references __aeabi_unwind_cpp_pr0 from libgcc,
# and libgcc needs symbols from libc, so requiring resolution here would be
# circular. bionic's own Android.mk sets LOCAL_ALLOW_UNDEFINED_SYMBOLS for
# exactly this reason.
"$GCC" -nostdlib -shared -Wl,-soname,libdl.so \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -o "$OUT/libdl.so" "$OUT/obj/libdl.o"
ls -la "$OUT/libdl.so"

echo
echo "############ 3/5  libc.so ############"
MODE=shared bash "$SCRIPTS/build_bionic_libc.sh" | tail -8

echo
echo "############ 4/5  libm.so ############"
MODE=shared bash "$SCRIPTS/build_bionic_libm.sh" | tail -5

echo
echo "############ 5/5  crt for dynamic executables ############"
# Dynamic executables need crtbegin_dynamic.o, not the crtbegin_static.o the
# rest of this port uses. Same crtend.
"$GCC" $CFLAGS_BASE -c "$BIONIC/libc/arch-arm/bionic/crtbegin_dynamic.S" \
    -o "$OUT/crtbegin_dynamic.o"
"$GCC" $CFLAGS_BASE -c "$BIONIC/libc/arch-arm/bionic/crtend.S" \
    -o "$OUT/crtend.o"
ls -la "$OUT/crtbegin_dynamic.o" "$OUT/crtend.o"

echo
echo "############ summary ############"
for f in "${ANDROID3DS_ROOT}"/build/linker/linker \
         "$OUT/libdl.so" "$OUT/libc.so" \
         "${ANDROID3DS_ROOT}"/build/libm_shared/libm.so; do
    if [ -e "$f" ]; then
        printf "%-60s %8s bytes\n" "$f" "$(stat -c%s "$f")"
    else
        echo "MISSING: $f"
    fi
done
