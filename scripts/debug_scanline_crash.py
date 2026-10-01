from a3ds_paths import A3DS_ROOT
import subprocess

script = f"""#!/bin/bash
set -euo pipefail
ROOT={A3DS_ROOT}
TC=$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX=$TC/arm-buildroot-linux-gnueabihf-g++
GCC=$TC/arm-buildroot-linux-gnueabihf-gcc
QEMU=$ROOT/toolchain/qemu/qemu-arm-static
BIONIC=$ROOT/third_party/bionic
SYSCORE=$ROOT/third_party/system_core
FWBASE=$ROOT/third_party/frameworks/base
BUILD=$ROOT/build
LIBGCC="$($GCC -print-libgcc-file-name)"

mkdir -p {A3DS_ROOT}/build/inspect_scanline

cat << 'INNER_EOF' > {A3DS_ROOT}/build/inspect_scanline/inspect.cpp
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <pixelflinger/pixelflinger.h>
#include "codeflinger/CodeCache.h"
#include "codeflinger/GGLAssembler.h"
#include "codeflinger/ARMAssembler.h"

using namespace android;

int main() {{
    needs_t needs;
    needs.n = 0x00000077;
    needs.p = 0x03545404;
    needs.t[0] = 0x00000A04;
    needs.t[1] = 0x00000000;

    GGLContext* ggl = NULL;
    gglInit(&ggl);
    context_t* c = (context_t*)ggl;

    sp<Assembly> a = new Assembly(4096);
    GGLAssembler assembler(new ARMAssembler(a));

    int err = assembler.scanline(needs, c);
    printf("assembler.scanline returned %d, size=%d\\n", err, (int)a->size());
    uint32_t* code = a->base();
    size_t count = a->size() / 4;
    for (size_t i = 0; i < count; i++) {{
        printf("0x%04x: %08x\\n", (unsigned)(i * 4), code[i]);
    }}
    return 0;
}}
INNER_EOF

"$GXX" -nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
    -fno-stack-protector -fno-pic -O2 \
    -D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
    -include "$SYSCORE/include/arch/linux-arm/AndroidConfig.h" \
    -isystem "$($GXX -print-file-name=include)" \
    -I "$BIONIC/libstdc++/include" \
    -I "$BIONIC/libc/include" \
    -I "$BIONIC/libm/include" \
    -I "$BIONIC/libc/kernel/common" \
    -I "$BIONIC/libc/kernel/arch-arm" \
    -I "$BIONIC/libc/arch-arm/include" \
    -I "$FWBASE/include" -I "$SYSCORE/include" \
    -I "$SYSCORE/libpixelflinger" \
    -c {A3DS_ROOT}/build/inspect_scanline/inspect.cpp \
    -o {A3DS_ROOT}/build/inspect_scanline/inspect.o

"$GXX" -nostdlib -static \
    "$BUILD/bionic/crtbegin.o" {A3DS_ROOT}/build/inspect_scanline/inspect.o \
    -Wl,--start-group \
        "$BUILD/libpixelflinger/libpixelflinger.a" \
        "$BUILD/libutils/libutils.a" \
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/bionic/libc.a" "$LIBGCC" \
    -Wl,--end-group \
    "$BUILD/bionic/crtend.o" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    -o {A3DS_ROOT}/build/inspect_scanline/inspect

"$QEMU" {A3DS_ROOT}/build/inspect_scanline/inspect
"""

with open(f"{A3DS_ROOT}/scratch_inspect.sh", "w") as f:
    f.write(script)
subprocess.run(["bash", f"{A3DS_ROOT}/scratch_inspect.sh"], check=True)
