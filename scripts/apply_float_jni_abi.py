#!/usr/bin/env python3
"""Apply the base-AAPCS attribute to scalar FP JNI entry functions.

Android Eclair's ARM Dalvik bridge passes JNI float/double values using the
base AAPCS. Android3DS uses a hard-float compiler, so each registered native
entry with a scalar F or D in its descriptor needs an explicit boundary PCS.
This is an idempotent, source-level mechanical rewrite.
"""

import argparse
import pathlib
import re
import sys

from audit_float_jni import ENTRY, has_scalar_fp


ATTRIBUTE = '__attribute__((pcs("aapcs")))'


def registered_functions(text: str):
    for match in ENTRY.finditer(text):
        if has_scalar_fp(match.group("signature")):
            yield match.group("function").split("::")[-1]


def annotate(text: str, function: str):
    name = re.escape(function)
    if re.search(r"(?m)^\s*JNIEXPORT\s+" + re.escape(ATTRIBUTE)
                 + r"[^\n]*\n" + name + r"\s*\(", text):
        return text, False, None
    static_declaration = re.compile(
        r"(?m)^(?P<indent>[ \t]*)static[ \t]+"
        r"(?P<rest>[^\n]*\b" + name + r"[ \t]*\()"
    )
    match = static_declaration.search(text)
    if match:
        line = match.group(0)
        if ATTRIBUTE in line or "DALVIK_JNI_ABI" in line:
            return text, False, None
        replacement = (match.group("indent") + "static " + ATTRIBUTE + " "
                       + match.group("rest"))
        return text[:match.start()] + replacement + text[match.end():], True, None

    export_declaration = re.compile(
        r"(?m)^(?P<indent>[ \t]*)JNIEXPORT(?P<type>[^\n]+\n)"
        + name + r"[ \t]*\("
    )
    match = export_declaration.search(text)
    if match:
        replacement = (match.group("indent") + "JNIEXPORT " + ATTRIBUTE
                       + match.group("type") + function + " (")
        return text[:match.start()] + replacement + text[match.end():], True, None

    # N3DS_FLOAT_JNI_SPLIT_DEFINITION: the generated GLES bindings (and
    # AudioTrack) put the return type, the name and the parameter list on
    # separate lines:
    #     static void
    #     android_glTexParameterf__IIF
    #       (JNIEnv *_env, jobject _this, jint target, jint pname, jfloat param)
    split_done = re.compile(
        r"(?m)^[ \t]*static[ \t]+(?:" + re.escape(ATTRIBUTE)
        + r"|DALVIK_JNI_ABI)[^\n]*\n" + name + r"[ \t]*\n?[ \t]*\("
    )
    if split_done.search(text):
        return text, False, None
    split_declaration = re.compile(
        r"(?m)^(?P<indent>[ \t]*)static(?P<type>[ \t]+[^\n;{}()]*)\n"
        r"(?P<name>" + name + r")[ \t]*\n?[ \t]*\("
    )
    match = split_declaration.search(text)
    if match:
        replacement = (match.group("indent") + "static " + ATTRIBUTE
                       + match.group("type") + "\n")
        return (text[:match.start()] + replacement
                + text[match.start("name"):], True, None)
    return text, False, "definition not found"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("roots", nargs="+")
    args = parser.parse_args()
    failures = []
    changed_files = 0
    changed_functions = 0
    for raw_root in args.roots:
        root = pathlib.Path(raw_root)
        for path in sorted(root.rglob("*")):
            if path.suffix not in (".c", ".cc", ".cpp"):
                continue
            original = path.read_text(errors="replace")
            updated = original
            functions = sorted(set(registered_functions(original)))
            for function in functions:
                updated, changed, error = annotate(updated, function)
                changed_functions += int(changed)
                if error:
                    failures.append("{}: {}: {}".format(path, function, error))
            if updated != original:
                changed_files += 1
                if args.apply:
                    path.write_text(updated)
                else:
                    print("would update {}".format(path))
    for failure in failures:
        print("ERROR: " + failure, file=sys.stderr)
    verb = "updated" if args.apply else "identified"
    print("{} {} functions in {} files".format(
        verb, changed_functions, changed_files))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
