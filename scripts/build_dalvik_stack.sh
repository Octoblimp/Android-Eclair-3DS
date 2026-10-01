#!/bin/bash
# Build everything the Dalvik VM needs, in dependency order, then link the
# dalvikvm launcher. Convenience driver -- each step is also runnable on its
# own via the individual scripts/build_*.sh.
set -e
S="$(cd "$(dirname "$0")" && pwd)"

echo "=== bionic libc ==="
bash "$S/build_bionic_libc.sh" 2>&1 | tail -4
echo "=== bionic libm ==="
bash "$S/build_bionic_libm.sh" 2>&1 | tail -3
echo "=== bionic libdl ==="
bash "$S/build_libdl.sh" 2>&1 | tail -1
echo "=== liblog + libcutils ==="
bash "$S/build_liblog_libcutils.sh" 2>&1 | tail -1
echo "=== zlib ==="
bash "$S/build_zlib.sh" 2>&1 | tail -1
echo "=== libdex ==="
bash "$S/build_libdex.sh" 2>&1 | tail -2
echo "=== libnativehelper ==="
bash "$S/build_libnativehelper.sh" 2>&1 | grep -E 'built|not compile'
echo "=== libdvm ==="
bash "$S/build_libdvm.sh" 2>&1 | tail -2
echo "=== link dalvikvm ==="
bash "$S/link_dalvikvm.sh"
