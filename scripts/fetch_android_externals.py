#!/usr/bin/env python3
"""Fetch the external native libraries libcore/libjavacore links against.

dalvik/libcore's native half needs five libraries that are not vendored in
this tree. Each is fetched from the real AOSP repo at the Eclair release tag,
so they match the libcore sources rather than being modern upstream versions
with different APIs:

  fdlibm   java_lang_StrictMath.c  (expects AOSP's ieee_* renamed entry points)
  expat    xml   (ExpatParser)
  sqlite   sql   (SQLite.Database / Vm / Stmt / Blob / FunctionContext)
  openssl  openssl + x-net  (NativeBN, NativeCrypto, OpenSSLSocketImpl, ...)
  icu4c    icu   (NativeCollator/NativeConverter/NativeRegEx/UCharacter/...)

ICU is the one that cannot be skipped even for a minimal boot:
java.lang.Character, String case mapping and java.util.Locale all route into
com.ibm.icu4jni.* natives.

Everything lands in third_party/<name>/, matching AOSP's external/<name>.
"""
from a3ds_paths import A3DS_ROOT

import os
import subprocess
import sys
import tarfile

BRANCH = "eclair-release"
BASE = "https://android.googlesource.com/platform"
DEST = f"{A3DS_ROOT}/third_party"

# A bare name means platform/external/<name>, which is where everything used to
# come from. Anything else in the AOSP tree can be given as its full path --
# e.g. "hardware/libhardware_legacy" for the power/gps/wifi/uevent headers that
# frameworks/base/core/jni includes. It still lands in third_party/<basename>.
def repo_path(name):
    return name if "/" in name else "external/" + name

# Ordered cheapest-first so a failure late on still leaves the easy wins in
# place.
REPOS = ["fdlibm", "expat", "sqlite", "openssl", "icu4c"]


def fetch(name):
    short = os.path.basename(name)
    out = os.path.join(DEST, short)
    if os.path.isdir(out) and os.listdir(out):
        print("  %-22s already present, skipping" % short)
        return True

    url = "%s/%s/+archive/refs/heads/%s.tar.gz" % (BASE, repo_path(name), BRANCH)
    tgz = "/tmp/aosp_%s.tar.gz" % short

    print("  %-22s fetching..." % short, end="", flush=True)
    r = subprocess.run(["curl", "-sS", "--max-time", "600", "-o", tgz, url],
                       capture_output=True)
    if r.returncode != 0 or not os.path.exists(tgz) or os.path.getsize(tgz) < 1024:
        print(" FAILED (curl rc=%d)" % r.returncode)
        if r.stderr:
            print("    %s" % r.stderr.decode(errors="replace").strip())
        return False

    size = os.path.getsize(tgz)
    os.makedirs(out, exist_ok=True)
    try:
        with tarfile.open(tgz, "r:gz") as t:
            n = len(t.getnames())
            t.extractall(out)
    except Exception as e:
        print(" FAILED to extract: %s" % e)
        return False

    print(" %.1f MB, %d entries -> %s" % (size / 1048576.0, n, out))
    os.remove(tgz)
    return True


def main():
    wanted = sys.argv[1:] or REPOS
    print("fetching AOSP externals (%s) into %s" % (BRANCH, DEST))
    failed = []
    for name in wanted:
        if not fetch(name):
            failed.append(name)
    print()
    if failed:
        print("FAILED: %s" % ", ".join(failed), file=sys.stderr)
        return 1
    print("all %d fetched" % len(wanted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
