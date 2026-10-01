#!/usr/bin/env python3
"""Two source fixes libcore needs to compile under JDK 8's javac.

Eclair's libcore was built with javac 5/6. Two constructs it relies on were
tightened in Java 7 and now fail outright. Both fixes are semantics-preserving
-- they change how the code is *spelled*, not what it does.

Run before scripts/build_core_jar.sh. Idempotent.
"""
from a3ds_paths import A3DS_ROOT

import sys

LIBCORE = f"{A3DS_ROOT}/third_party/dalvik/libcore"

PATCHES = [
    (
        LIBCORE + "/luni/src/main/java/java/lang/Enum.java",
        "        return ordinal - o.ordinal;\n",
        "        // o is of type E (a type variable bounded by Enum<E>), not Enum,\n"
        "        // and javac 7+ no longer lets a private field be reached through a\n"
        "        // type variable. ordinal() is the public final accessor for exactly\n"
        "        // this field, so this is the same read.\n"
        "        return ordinal - o.ordinal();\n",
        "Enum.compareTo: private field access through a type variable",
    ),
    (
        LIBCORE + "/luni/src/main/java/java/util/EnumMap.java",
        "            return type.get(new MapEntry(enumMap.keys[prePosition],\n"
        "                    enumMap.values[prePosition]));\n",
        "            // new MapEntry(...) is a raw type, which makes this an unchecked\n"
        "            // invocation; from Java 7 on that erases the result to Object\n"
        "            // instead of E. The method is already @SuppressWarnings\n"
        "            // (\"unchecked\"), so restore the old result type explicitly.\n"
        "            return (E) type.get(new MapEntry(enumMap.keys[prePosition],\n"
        "                    enumMap.values[prePosition]));\n",
        "EnumMap.EnumMapIterator.next: raw-type call erased to Object",
    ),
]


def main():
    changed = 0
    for path, old, new, what in PATCHES:
        src = open(path).read()
        if new in src:
            print("already patched: %s" % what)
            continue
        if old not in src:
            print("ERROR: pattern not found for %s\n  in %s" % (what, path),
                  file=sys.stderr)
            return 1
        open(path, "w").write(src.replace(old, new, 1))
        print("patched: %s" % what)
        changed += 1
    print("%d file(s) changed" % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
