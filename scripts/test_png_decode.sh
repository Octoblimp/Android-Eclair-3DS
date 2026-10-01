#!/bin/bash
# Verify PngDecode.cpp against an independent decoder (Python's zlib-based
# one in gen_bootanimation.py) on every image the boot animation will actually
# feed it: the two original Eclair assets and every frame of the generated
# bootanimation.zip.
#
# Built for the host, since the decoder has no target dependencies -- this is
# pure pixel math and is the part most likely to be subtly wrong.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

SRC="${ANDROID3DS_ROOT}"/third_party/frameworks/base/cmds/bootanimation
ZLIB="${ANDROID3DS_ROOT}"/third_party/zlib
ASSETS="${ANDROID3DS_ROOT}"/third_party/frameworks/base/core/res/assets/images
T=/tmp/pngtest

rm -rf "$T"; mkdir -p "$T/utils" "$T/imgs"

cat > "$T/utils/Log.h" <<'EOF'
#ifndef HOSTTEST_LOG_H
#define HOSTTEST_LOG_H
#include <stdio.h>
#define LOGE(...) do { fprintf(stderr, "E: " __VA_ARGS__); fprintf(stderr, "\n"); } while (0)
#define LOGI(...) do { fprintf(stderr, "I: " __VA_ARGS__); fprintf(stderr, "\n"); } while (0)
#define LOGD(...) do { } while (0)
#define LOGE_IF(c, ...) do { if (c) LOGE(__VA_ARGS__); } while (0)
#define LOGI_IF(c, ...) do { if (c) LOGI(__VA_ARGS__); } while (0)
#endif
EOF

cat > "$T/main.cpp" <<'EOF'
#include <stdio.h>
#include <stdlib.h>
#include "PngDecode.h"
using namespace android;

int main(int argc, char** argv)
{
    FILE* f = fopen(argv[1], "rb");
    if (!f) { fprintf(stderr, "open %s failed\n", argv[1]); return 2; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    void* buf = malloc(n);
    if (fread(buf, 1, n, f) != (size_t)n) { return 2; }
    fclose(f);

    PngImage img;
    if (!decodePngImage(buf, n, &img)) { fprintf(stderr, "decode failed\n"); return 1; }

    // raw RGBA dump on stdout, preceded by dimensions
    printf("%d %d\n", img.width, img.height);
    fwrite(img.pixels, 1, (size_t)img.width * img.height * 4, stdout);
    freePngImage(&img);
    free(buf);
    return 0;
}
EOF

g++ -O2 -o "$T/pngtest" "$T/main.cpp" "$SRC/PngDecode.cpp" \
    -I "$SRC" -I "$T" -I "$ZLIB" -lz

# Collect images: the two originals plus every generated frame.
cp "$ASSETS/android-logo-mask.png"  "$T/imgs/"
cp "$ASSETS/android-logo-shine.png" "$T/imgs/"
python3 - "$1" "$T/imgs" <<'EOF'
import sys, zipfile, os
zp, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(zp) as z:
    for n in z.namelist():
        if n.endswith(".png"):
            open(os.path.join(out, n.replace("/", "_")), "wb").write(z.read(n))
EOF

python3 - "$T" <<'PYEOF'
import os, subprocess, sys
sys.path.insert(0, os.path.join(os.environ["ANDROID3DS_WIN"], "scripts"))
from gen_bootanimation import read_png

T = sys.argv[1]
imgs = sorted(os.listdir(os.path.join(T, "imgs")))
fails = 0
for name in imgs:
    p = os.path.join(T, "imgs", name)
    w, h, ch, ref = read_png(p)

    out = subprocess.run([os.path.join(T, "pngtest"), p],
                         capture_output=True, check=True).stdout
    nl = out.index(b"\n")
    dw, dh = map(int, out[:nl].split())
    pix = out[nl + 1:]

    if (dw, dh) != (w, h):
        print("FAIL %-28s dims %dx%d != %dx%d" % (name, dw, dh, w, h)); fails += 1; continue
    if len(pix) != w * h * 4:
        print("FAIL %-28s short buffer" % name); fails += 1; continue

    bad = 0
    for i in range(w * h):
        if ch == 4:
            exp = (ref[i*4], ref[i*4+1], ref[i*4+2], ref[i*4+3])
        elif ch == 3:
            exp = (ref[i*3], ref[i*3+1], ref[i*3+2], 255)
        elif ch == 2:
            exp = (ref[i*2], ref[i*2], ref[i*2], ref[i*2+1])
        else:
            exp = (ref[i], ref[i], ref[i], 255)
        got = (pix[i*4], pix[i*4+1], pix[i*4+2], pix[i*4+3])
        if got != exp:
            bad += 1
            if bad == 1:
                print("   first diff at px %d: got %s expected %s" % (i, got, exp))
    if bad:
        print("FAIL %-28s %d/%d pixels differ" % (name, bad, w*h)); fails += 1
    else:
        print("OK   %-28s %dx%d (%d ch)" % (name, w, h, ch))

print()
print("FAILURES: %d / %d" % (fails, len(imgs)))
sys.exit(1 if fails else 0)
PYEOF
