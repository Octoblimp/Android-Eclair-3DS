#!/bin/bash
# Build a dynamically linked ARM binary against our bionic .so's and run it
# under qemu-arm-static, so the dynamic linker is proven before it ever has
# to work on hardware.
#
# The test exercises, in order: the linker mapping itself and relocating,
# loading libc.so + libdl.so + libm.so, resolving data and function symbols
# across .so boundaries (printf, malloc, sqrt), and finally dlopen/dlsym on
# a library built specifically for this test.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
READELF="$TC/arm-buildroot-linux-gnueabihf-readelf"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SHARED="${ANDROID3DS_ROOT}"/build/bionic_shared
LIBM="${ANDROID3DS_ROOT}"/build/libm_shared
LINKER="${ANDROID3DS_ROOT}"/build/linker/linker
QEMU="${ANDROID3DS_ROOT}"/toolchain/qemu/qemu-arm-static
OUT="${ANDROID3DS_ROOT}"/build/dyntest
SYSROOT="$OUT/sysroot"

rm -rf "$OUT"
mkdir -p "$OUT" "$SYSROOT/system/bin" "$SYSROOT/system/lib"

CFLAGS="-nostdinc -std=gnu89 -fno-stack-protector -O1 \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $BIONIC/libm/include \
-I $BIONIC/libm/include/arm"

############################################################
# A shared library to dlopen(). Deliberately in its own .so so
# nothing about it can be satisfied at static link time.
############################################################
cat > "$OUT/testlib.c" <<'EOF'
int  dyn_answer(void)      { return 42; }
int  dyn_triple(int x)     { return x * 3; }
EOF

"$GCC" $CFLAGS -fPIC -c "$OUT/testlib.c" -o "$OUT/testlib.o"
"$GCC" -nostdlib -shared -Wl,-soname,libdyntest.so \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -o "$SYSROOT/system/lib/libdyntest.so" "$OUT/testlib.o"

############################################################
# The dynamic executable.
############################################################
cat > "$OUT/main.c" <<'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <dlfcn.h>

int main(int argc, char **argv)
{
    void *h, *p;
    int (*answer)(void);
    int (*triple)(int);
    int failures = 0;

    printf("[dyntest] hello from a dynamically linked bionic binary\n");

    /* cross-.so data + function symbols */
    p = malloc(4096);
    if (!p) { printf("[dyntest] FAIL malloc returned NULL\n"); failures++; }
    else    { memset(p, 0xAB, 4096); printf("[dyntest] OK   malloc/memset\n"); free(p); }

    /* libm.so */
    if (sqrt(144.0) == 12.0) printf("[dyntest] OK   libm sqrt(144)=12\n");
    else { printf("[dyntest] FAIL libm sqrt\n"); failures++; }

    /* printf %f needs -DFLOATING_POINT in libc */
    printf("[dyntest] printf %%f check: %.2f (expect 3.14)\n", 3.14159);

    /* THE point of the whole exercise */
    h = dlopen("libdyntest.so", RTLD_NOW);
    if (!h) {
        printf("[dyntest] FAIL dlopen: %s\n", dlerror());
        failures++;
    } else {
        printf("[dyntest] OK   dlopen returned %p\n", h);
        answer = (int (*)(void)) dlsym(h, "dyn_answer");
        triple = (int (*)(int)) dlsym(h, "dyn_triple");
        if (!answer || !triple) {
            printf("[dyntest] FAIL dlsym: %s\n", dlerror());
            failures++;
        } else if (answer() == 42 && triple(5) == 15) {
            printf("[dyntest] OK   dlsym + call: dyn_answer()=%d dyn_triple(5)=%d\n",
                   answer(), triple(5));
        } else {
            printf("[dyntest] FAIL dlsym'd functions returned wrong values\n");
            failures++;
        }
        dlclose(h);
    }

    printf("[dyntest] === %s (%d failures) ===\n",
           failures ? "FAILED" : "ALL PASSED", failures);
    return failures;
}
EOF

"$GCC" $CFLAGS -c "$OUT/main.c" -o "$OUT/main.o"

# PT_INTERP must name the on-device path of the linker.
#
# -Ttext-segment=0x8000 is required, not cosmetic. With -nostdlib and no
# explicit base, ld lays the first LOAD segment at virtual address 0, so
# page zero would have to be mapped -- it cannot be (mmap_min_addr), and
# the linker then SIGSEGVs the instant it dereferences the executable's
# _DYNAMIC. 0x8000 is the base Android's ARM executables use.
"$GCC" -nostdlib -Wl,-dynamic-linker,/system/bin/linker \
    -Wl,-Ttext-segment=0x8000 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    -o "$SYSROOT/system/bin/dyntest" \
    "$SHARED/crtbegin_dynamic.o" "$OUT/main.o" \
    "$SHARED/libc.so" "$LIBM/libm.so" "$SHARED/libdl.so" \
    "$SHARED/crtend.o"

cp "$LINKER" "$SYSROOT/system/bin/linker"
cp "$SHARED/libc.so" "$SHARED/libdl.so" "$LIBM/libm.so" "$SYSROOT/system/lib/"

echo "=== dyntest ELF ==="
"$READELF" -l "$SYSROOT/system/bin/dyntest" | grep -A1 INTERP | tail -1
"$READELF" -d "$SYSROOT/system/bin/dyntest" | grep NEEDED

echo
echo "=== running under qemu-arm-static ==="
if [ ! -x "$QEMU" ]; then
    echo "SKIP: $QEMU not found"
    exit 0
fi
# -L makes qemu resolve PT_INTERP and the .so paths inside the sysroot.
"$QEMU" -L "$SYSROOT" "$SYSROOT/system/bin/dyntest"
echo "exit status: $?"
