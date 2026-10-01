#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SRC="$ROOT/third_party/libxml2"
OUT="$ROOT/build/libxml2_webkit"
TC="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin"
CC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="$ROOT/third_party/bionic"
SYSCORE="$ROOT/third_party/system_core"

test -f "$SRC/Android.mk" || {
    echo "build_libxml2_webkit: run scripts/fetch_webkit_dependencies.sh first" >&2
    exit 1
}

SOURCES='SAX.c entities.c encoding.c error.c parserInternals.c parser.c tree.c
hash.c list.c xmlIO.c xmlmemory.c uri.c valid.c xlink.c HTMLparser.c
HTMLtree.c debugXML.c xpath.c xpointer.c xinclude.c nanohttp.c nanoftp.c
DOCBparser.c catalog.c globals.c threads.c c14n.c xmlstring.c xmlregexp.c
xmlschemas.c xmlschemastypes.c xmlunicode.c xmlreader.c relaxng.c dict.c SAX2.c
legacy.c chvalid.c pattern.c xmlsave.c xmlmodule.c xmlwriter.c schematron.c'

# N3DS_WEBKIT_HARD_FLOAT: this used to pass Eclair's -msoft-float, which on
# this gnueabihf GCC is a different calling convention from the rest of
# app_process (see build_webkit.py).  The objects are only rebuilt when their
# source is newer, so a stamp records the ABI they were built for.
STAMP="$OUT/obj/N3DS_FLAGS"
STAMP_TEXT="N3DS_WEBKIT_HARD_FLOAT"
mkdir -p "$OUT/obj"
if [ "$(cat "$STAMP" 2>/dev/null)" != "$STAMP_TEXT" ]; then
    rm -f "$OUT"/obj/*.o
fi
objects=
for source in $SOURCES; do
    object="$OUT/obj/${source%.c}.o"
    if [ ! -s "$object" ] || [ "$SRC/$source" -nt "$object" ]; then
        "$CC" -std=gnu99 -O2 -fPIC -fvisibility=hidden \
            -DANDROID -include "$SYSCORE/include/arch/linux-arm/AndroidConfig.h" \
            -I"$BIONIC/libc/arch-arm/include" -I"$BIONIC/libc/include" \
            -I"$BIONIC/libc/kernel/common" -I"$BIONIC/libc/kernel/arch-arm" \
            -I"$BIONIC/libm/include" -I"$SRC/include" -I"$SRC" \
            -c "$SRC/$source" -o "$object"
    fi
    objects="$objects $object"
done

rm -f "$OUT/libxml2.a"
# shellcheck disable=SC2086 -- the object list is intentionally word-split.
"$AR" rcs "$OUT/libxml2.a" $objects
test -s "$OUT/libxml2.a"
echo "$STAMP_TEXT" > "$STAMP"
file "$OUT/libxml2.a"
echo "build_libxml2_webkit: $OUT/libxml2.a"
