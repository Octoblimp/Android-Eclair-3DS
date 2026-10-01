#!/usr/bin/env python3
"""Mask the build machine's directories inside shipped ELF files.

Static binaries, libc.so and ath6kl.ko carry absolute source paths:
assert() and WARN() messages embed __FILE__, and the debug sections record
each compile directory. Every one of those paths starts with the directory
the checkout lives in, which on most machines is the builder's home
directory and so names the local account.

This rewrites each occurrence of those directories in place, at the same
length ("/home/name/" becomes "/home/xxxx/"), so no offset, size or
section moves and the code is byte-for-byte what was linked. It is
deterministic, so two copies scrubbed separately still compare equal.

Only ELF files are rewritten. Zip-based files (apk, jar) and dex/odex carry
checksums; a hit in one of those is reported and fails --check.

    scrub_build_paths.py PATH...          rewrite ELF files under PATH
    scrub_build_paths.py --check PATH...  exit 1 if anything still matches
"""
import os
import sys

from a3ds_paths import A3DS_ROOT, A3DS_WIN


def _prefixes():
    out = set()
    for root in (A3DS_ROOT, A3DS_WIN):
        parent = os.path.dirname(os.path.abspath(root)).rstrip("/")
        parts = parent.split("/")          # ['', 'home', 'name', ...]
        if len(parts) < 3:
            continue                       # /android3ds: nothing personal
        masked = parts[:2] + ["x" * len(p) for p in parts[2:]]
        out.add(("/".join(parts) + "/", "/".join(masked) + "/"))
    return sorted((a.encode(), b.encode()) for a, b in out)


PREFIXES = _prefixes()


def walk(paths):
    for top in paths:
        if os.path.isfile(top) and not os.path.islink(top):
            yield top
            continue
        for d, _, files in os.walk(top):
            for name in files:
                p = os.path.join(d, name)
                if not os.path.islink(p) and os.path.isfile(p):
                    yield p


def main(argv):
    check = argv[:1] == ["--check"]
    paths = argv[1:] if check else argv
    if not paths:
        sys.exit(__doc__)
    scrubbed = 0
    left = []
    for p in walk(paths):
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError:
            continue
        hits = [a for a, _ in PREFIXES if a in data]
        if not hits:
            continue
        if check or data[:4] != b"\x7fELF":
            left.append(p)
            continue
        for a, b in PREFIXES:
            data = data.replace(a, b)
        st = os.stat(p)
        with open(p, "r+b") as f:
            f.write(data)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
        scrubbed += 1
        print("scrubbed build paths: %s" % p)
    for p in left:
        print("build path still present: %s" % p, file=sys.stderr)
    if check:
        print("build-path check: %d file(s) still name the build machine" % len(left))
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
