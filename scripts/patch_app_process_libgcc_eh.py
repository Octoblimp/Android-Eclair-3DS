#!/usr/bin/env python3
"""Add libgcc_eh.a to app_process's link line.

libutils' CallStack.cpp calls _Unwind_Backtrace() and _Unwind_VRS_Get().
On ARM those live in libgcc_eh.a, not in the libgcc.a that
"gcc -print-libgcc-file-name" reports, and a static link has to name it
explicitly.

Nothing referenced CallStack.o until libui entered the link with the
compositor, which is why this only started mattering now.

Idempotent.
"""
from a3ds_paths import A3DS_WIN
import sys

SCRIPTS = [
    f"{A3DS_WIN}/"
    "scripts/build_app_process.sh",
    f"{A3DS_WIN}/"
    "scripts/build_app_process_debug.sh",
]

DEF_OLD = 'LIBGCC="$("$GCC" -print-libgcc-file-name)"'
DEF_NEW = DEF_OLD + """
# libutils' CallStack.cpp calls _Unwind_Backtrace/_Unwind_VRS_Get. On ARM
# those live in libgcc_eh.a, not the libgcc.a -print-libgcc-file-name
# reports, and a static link has to name it explicitly. Nothing referenced
# CallStack.o until libui entered the link with the compositor.
LIBGCC_EH="$("$GCC" -print-file-name=libgcc_eh.a)\""""

USE_OLD = '        "$LIBGCC" \\\n    -Wl,--end-group'
USE_NEW = '        "$LIBGCC" \\\n        "$LIBGCC_EH" \\\n    -Wl,--end-group'


def main():
    rc = 0
    for path in SCRIPTS:
        name = path.split("/")[-1]
        try:
            src = open(path).read()
        except IOError as e:
            print("MISSING %s: %s" % (name, e))
            rc = 1
            continue

        if "LIBGCC_EH" in src:
            print("%s: already patched" % name)
            continue

        if DEF_OLD not in src:
            print("FAIL %s: LIBGCC definition not found" % name)
            rc = 1
            continue
        if USE_OLD not in src:
            print("FAIL %s: end-group anchor not found" % name)
            rc = 1
            continue

        src = src.replace(DEF_OLD, DEF_NEW, 1)
        src = src.replace(USE_OLD, USE_NEW, 1)
        open(path, "w").write(src)
        print("%s: libgcc_eh.a added" % name)
    return rc


if __name__ == "__main__":
    sys.exit(main())
