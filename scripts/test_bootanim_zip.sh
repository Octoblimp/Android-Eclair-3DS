#!/bin/bash
# Exercise the parts of bootanimation that do not need a framebuffer --
# ZipFileRO + FileMap reading bootanimation.zip, the desc.txt parse, and
# decoding every frame -- as a real ARM target binary under qemu.
#
# This is the integration the host PNG test cannot cover: whether upstream's
# zip reader accepts the archive gen_bootanimation.py produces, in particular
# the stored-entries-only rule in movie().
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
QEMU="${ANDROID3DS_ROOT}"/toolchain/qemu/qemu-arm-static

BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LSTL=$BIONIC/libstdc++
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
SRC=$FWBASE/cmds/bootanimation
ZLIB="${ANDROID3DS_ROOT}"/third_party/zlib

BUILD="${ANDROID3DS_ROOT}"/build
BIONIC_OUT=$BUILD/bionic
OUT=$BUILD/bootanim_ziptest
ZIP=${1:-$BUILD/bootanimation/bootanimation.zip}
LIBGCC="$("$GCC" -print-libgcc-file-name)"

mkdir -p "$OUT"

cat > "$OUT/ziptest.cpp" <<'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <utils/ZipFileRO.h>
#include <utils/FileMap.h>
#include <utils/String8.h>
#include "PngDecode.h"

using namespace android;

int main(int argc, char** argv)
{
    int failures = 0;
    ZipFileRO zip;

    if (zip.open(argv[1]) != NO_ERROR) {
        printf("FAIL cannot open %s\n", argv[1]);
        return 1;
    }
    size_t n = zip.getNumEntries();
    printf("entries: %d\n", (int)n);

    ZipEntryRO desc = zip.findEntryByName("desc.txt");
    if (!desc) { printf("FAIL no desc.txt\n"); return 1; }
    FileMap* dm = zip.createEntryFileMap(desc);
    if (!dm) { printf("FAIL desc.txt not mappable\n"); return 1; }

    String8 s((char const*)dm->getDataPtr(), dm->getDataLength());
    printf("desc.txt: %s", s.string());

    int w = 0, h = 0, fps = 0, count = -1, pause = -1;
    char path[256] = "";
    const char* p = s.string();
    for (;;) {
        const char* endl = strstr(p, "\n");
        if (!endl) break;
        String8 line(p, endl - p);
        sscanf(line.string(), "%d %d %d", &w, &h, &fps);
        sscanf(line.string(), "p %d %d %s", &count, &pause, path);
        p = ++endl;
    }
    printf("parsed: %dx%d @%dfps  part count=%d pause=%d path=%s\n",
           w, h, fps, count, pause, path);
    // Frames are full-screen 320x240 so that movie()'s centring maths
    // (xc = yc = 0) cannot misplace the logo -- see gen_bootanimation.py.
    if (w != 320 || h != 240 || fps <= 0) { printf("FAIL bad desc\n"); failures++; }
    if (strcmp(path, "part0") != 0) { printf("FAIL bad part path\n"); failures++; }

    int stored = 0, decoded = 0;
    for (size_t i = 0; i < n; i++) {
        fprintf(stderr, "  [%d] findEntryByIndex...\n", (int)i);
        ZipEntryRO e = zip.findEntryByIndex(i);
        if (!e) { fprintf(stderr, "  [%d] findEntryByIndex -> NULL\n", (int)i); failures++; continue; }
        char name[256];
        if (zip.getEntryFileName(e, name, 256) != 0) continue;
        fprintf(stderr, "  [%d] %s\n", (int)i, name);
        String8 en(name);
        if (en.getPathDir() != String8("part0")) continue;

        int method = 0;
        if (!zip.getEntryInfo(e, &method, 0, 0, 0, 0, 0)) {
            printf("FAIL getEntryInfo %s\n", name); failures++; continue;
        }
        if (method != ZipFileRO::kCompressStored) {
            printf("FAIL %s is not stored (method %d) -- movie() would skip it\n",
                   name, method);
            failures++;
            continue;
        }
        stored++;

        fprintf(stderr, "      createEntryFileMap...\n");
        FileMap* m = zip.createEntryFileMap(e);
        if (!m) { printf("FAIL cannot map %s\n", name); failures++; continue; }

        fprintf(stderr, "      decode (%d bytes)...\n", (int)m->getDataLength());
        PngImage img;
        if (!decodePngImage(m->getDataPtr(), m->getDataLength(), &img)) {
            printf("FAIL cannot decode %s\n", name); failures++;
        } else {
            if (img.width != w || img.height != h) {
                printf("FAIL %s is %dx%d, desc says %dx%d\n",
                       name, img.width, img.height, w, h);
                failures++;
            }
            decoded++;
            freePngImage(&img);
        }
        fprintf(stderr, "      release...\n");
        m->release();
        fprintf(stderr, "      done\n");
    }

    printf("stored frames: %d, decoded: %d\n", stored, decoded);
    if (stored != 32) { printf("FAIL expected 32 frames\n"); failures++; }

    printf(failures ? "=== %d FAILURES ===\n" : "=== ALL PASSED (%d failures) ===\n",
           failures);
    return failures ? 1 : 0;
}
EOF

CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -Wno-attributes -Wno-invalid-offsetof \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include -I $BIONIC/libc/include -I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common -I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include -I $SYSCORE/include -I $ZLIB -I $SRC"

"$GXX" $CXXFLAGS -c "$OUT/ziptest.cpp"   -o "$OUT/ziptest.o"
"$GXX" $CXXFLAGS -c "$SRC/PngDecode.cpp" -o "$OUT/PngDecode.o"

"$GXX" -nostdlib -static \
    "$BIONIC_OUT/crtbegin.o" "$OUT/ziptest.o" "$OUT/PngDecode.o" \
    -Wl,-u,_ZN7android25gDarwinCantLoadAllObjectsE \
    -Wl,--start-group \
        "$BUILD/libutils/libutils.a" "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog_fake/liblog.a" "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/zlib/libz.a" "$BUILD/libm/libm.a" \
        "$BIONIC_OUT/libc.a" "$LIBGCC" \
    -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" \
    -o "$OUT/ziptest" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 2>&1 | grep -v "GNU-stack\|deprecated" || true

echo "=== running under qemu-arm ==="
"$QEMU" "$OUT/ziptest" "$ZIP"
echo "exit status: $?"
