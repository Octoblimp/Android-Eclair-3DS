#!/usr/bin/env python3
"""List registered JNI methods whose scalar ABI contains float or double."""

import pathlib
import re
import sys


# N3DS_FLOAT_JNI_CAST_WHITESPACE: the cast must tolerate "(void *)" as well
# as "(void*)".  The generated GLES bindings (com_google_android_gles_jni_
# GLImpl.cpp, android_opengl_GLES1*.cpp), CursorWindow, SQLiteProgram and
# AudioTrack all register "(void *) fn"; the old "\(void\*\)" pattern skipped
# every one of them, so their float arguments were read from VFP registers
# Dalvik never loads.  That is why Global Time's glTexParameterf raised
# GL_INVALID_ENUM and glFrustumf/glTranslatef/glRotatef produced a black frame.
ENTRY = re.compile(
    r'\{\s*"(?P<name>[^"]+)"\s*,\s*"(?P<signature>[^"]+)"\s*,'
    r'\s*(?:\(\s*void\s*\*\s*\)\s*)?(?P<function>[A-Za-z_][A-Za-z0-9_:]*)\s*\}'
)


def has_scalar_fp(signature: str) -> bool:
    """Return true for scalar F/D parameters or returns, not arrays/classes."""
    scalar = re.sub(r"\[+(?:L[^;]+;|.)", "A", signature)
    scalar = re.sub(r"L[^;]+;", "L", scalar)
    return "F" in scalar or "D" in scalar


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: audit_float_jni.py SOURCE_DIR [...]", file=sys.stderr)
        return 2
    files_only = "--files" in sys.argv[1:]
    seen_files = set()
    for raw_root in (arg for arg in sys.argv[1:] if arg != "--files"):
        root = pathlib.Path(raw_root)
        for path in sorted(root.rglob("*")):
            if path.suffix not in (".c", ".cc", ".cpp"):
                continue
            text = path.read_text(errors="replace")
            for match in ENTRY.finditer(text):
                signature = match.group("signature")
                if has_scalar_fp(signature):
                    if files_only:
                        seen_files.add(str(path))
                        continue
                    print("{}\t{}\t{}\t{}".format(
                        path, match.group("name"), signature,
                        match.group("function")))
    if files_only:
        for path in sorted(seen_files):
            print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
