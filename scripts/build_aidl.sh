#!/bin/bash
# Build aidl, the Binder .aidl -> Java proxy/stub codegen tool, from
# frameworks/base/tools/aidl. Host tool (BUILD_HOST_EXECUTABLE in the real
# Android.mk) -- runs on the WSL build machine, not the 3DS, so this uses the
# system g++/flex/bison, not the ARM cross toolchain or bionic headers.
#
# Needed to generate IFoo.java proxy/stub classes from the .aidl files that
# framework.jar's real Android.mk source list includes -- see
# docs/HANDOFF.md "Immediate next steps" item 3, stage 1.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

SRC="${ANDROID3DS_ROOT}"/third_party/frameworks/base/tools/aidl
OUT="${ANDROID3DS_ROOT}"/build/aidl
LOG="${ANDROID3DS_ROOT}"/build_aidl.log

rm -rf "$OUT"
mkdir -p "$OUT/gen"

echo "=== generating lexer/parser ==="
bison -d -o "$OUT/gen/aidl_language_y.cpp" "$SRC/aidl_language_y.y" > "$LOG" 2>&1 || {
    echo "FAILED (bison) -- $LOG:"; cat "$LOG"; exit 1;
}
# bison -d emits aidl_language_y.hpp next to the .cpp; the .l file expects
# "aidl_language_y.h" (no p) -- symlink rather than patch the vendored .l.
if [ -f "$OUT/gen/aidl_language_y.hpp" ]; then
    ln -sf aidl_language_y.hpp "$OUT/gen/aidl_language_y.h"
fi

flex -o "$OUT/gen/aidl_language_l.cpp" "$SRC/aidl_language_l.l" >> "$LOG" 2>&1 || {
    echo "FAILED (flex) -- $LOG:"; cat "$LOG"; exit 1;
}

echo "=== compiling aidl ==="
# OS_PATH_SEPARATOR: real AOSP gets this from the host AndroidConfig.h
# (system_core/include/arch/linux-x86) via HOST_GLOBAL_CFLAGS in the make
# build system, which we don't run here -- define it directly instead.
SOURCES="
$SRC/aidl.cpp
$SRC/aidl_language.cpp
$SRC/options.cpp
$SRC/search_path.cpp
$SRC/AST.cpp
$SRC/Type.cpp
$SRC/generate_java.cpp
$OUT/gen/aidl_language_l.cpp
$OUT/gen/aidl_language_y.cpp
"

g++ -std=gnu++98 -g -O2 -Wno-write-strings \
    -DOS_PATH_SEPARATOR="'/'" \
    -I"$SRC" -I"$OUT/gen" \
    $SOURCES \
    -o "$OUT/aidl" >> "$LOG" 2>&1 || {
        echo "FAILED (g++) -- last 60 lines of $LOG:"
        tail -60 "$LOG"
        exit 1
    }

ls -la "$OUT/aidl"
echo "=== aidl smoke test ==="
"$OUT/aidl" 2>&1 | head -5 || true

echo "=== aidl real-file test (android/os/IPowerManager.aidl) ==="
TESTOUT="$OUT/IPowerManager.java"
"$OUT/aidl" "${ANDROID3DS_ROOT}/third_party/frameworks/base/core/java/android/os/IPowerManager.aidl" "$TESTOUT"
test -s "$TESTOUT"
grep -q "public interface IPowerManager" "$TESTOUT"
echo "OK: generated $(wc -l < "$TESTOUT") lines"
