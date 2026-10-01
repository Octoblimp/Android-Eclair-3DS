#!/usr/bin/env python3
"""Keep the pre-baked /data/dalvik-cache and the deployed bootclasspath jars
agreeing about what "unchanged" means.

Background
----------
Dalvik decides whether a cached .odex is still valid in
DexOptimize.c:dvmCheckOptHeaderAndDependencies(), which compares two values
recorded in the .odex's dependency section against the live jar:

    modWhen   the raw 4-byte DOS date+time from the jar's CENTRAL DIRECTORY
              entry for "classes.dex" (JarFile.c -> ZipArchive.c:
              dexZipGetEntryInfo, get4LE(ptr + kCDEModWhen))
    crc       that same entry's CRC-32

It does NOT look at the jar file's filesystem mtime. build_dexpreopt_qemu.sh
used to `touch -d @PIN_MTIME` the jars, which sets exactly the metadata Dalvik
ignores -- so it silently never worked, and one boot burned 4 min 11 s
cold-optimizing a core.jar whose contents had not changed at all (see
docs/HANDOFF.md, 2026-08-05).

The CRC check is correct and wanted: different content really must be
re-optimized. The modWhen check is the problem -- repackaging identical
content stamps a fresh timestamp and invalidates the cache for nothing.

Two subcommands
---------------
  pin <jar>...      rewrite classes.dex's DOS date+time (central directory AND
                    local file header) to a fixed constant, so rebuilding a jar
                    with unchanged content no longer changes modWhen. Idempotent.

  verify <sd-root>  read modWhen+crc out of each deployed jar's central
                    directory and out of the matching dalvik-cache .odex's
                    dependency record, and fail if they disagree -- i.e. fail
                    if the next boot would cold-dexopt.

Exit status is 0 only when everything agrees, so this is usable as a build gate.
"""

import os
import struct
import sys

# 2025-01-01 00:00:00 in DOS date+time, packed as ZIP stores it: the low 16
# bits are the time, the high 16 bits the date. Arbitrary but fixed; the only
# property that matters is that it never changes.
DOS_TIME = 0
DOS_DATE = ((2025 - 1980) << 9) | (1 << 5) | 1
PINNED_MODWHEN = (DOS_DATE << 16) | DOS_TIME

JARS = ("core.jar", "framework.jar", "services.jar")
ENTRY = b"classes.dex"
APP_ARTIFACTS = (
    ("Launcher2.odex", "Launcher2.apk"),
    ("Browser.odex", "Browser.apk"),
    ("SettingsProvider.odex", "SettingsProvider.apk"),
    ("TelephonyProvider.odex", "TelephonyProvider.apk"),
    ("ContactsProvider.odex", "ContactsProvider.apk"),
    ("MediaProvider.odex", "MediaProvider.apk"),
    ("Phone.odex", "Phone.apk"),
    ("Mms.odex", "Mms.apk"),
    ("Settings.odex", "Settings.apk"),
    ("TouchDiagnostic.odex", "TouchDiagnostic.apk"),
    ("GlobalTime.odex", "GlobalTime.apk"),
    ("GPU-Z.odex", "GPU-Z.apk"),
    ("LatinIME.odex", "LatinIME.apk"),
    ("Development.odex", "Development.apk"),
    ("N3dsDialer.odex", "N3dsDialer.apk"),
    ("Camera.odex", "Camera.apk"),
    ("MicTest.odex", "MicTest.apk"),
)
APP_ODEX = tuple(odex for odex, _apk in APP_ARTIFACTS)
# N3DS_NO_STOCK_CONTACTS: retired apps must be absent, not merely unlisted --
# buildroot's output/target is additive, so a deleted APK comes back from it
# unless something refuses it.
# N3DSKeyboard: the custom keyboard, replaced by AOSP LatinIME.
RETIRED_APPS = ("Contacts.apk", "Contacts.odex",
                "N3DSKeyboard.apk", "N3DSKeyboard.odex")
DEX_SIGNATURE_LENGTH = 20


def _find_eocd(data):
    i = data.rfind(b"PK\x05\x06")
    if i < 0:
        raise ValueError("no end-of-central-directory record")
    return i


def read_cde(path, entry=ENTRY):
    """Return (modWhen, crc, cde_offset, local_header_offset) for `entry`."""
    with open(path, "rb") as f:
        data = f.read()
    eocd = _find_eocd(data)
    count = struct.unpack_from("<H", data, eocd + 10)[0]
    p = struct.unpack_from("<I", data, eocd + 16)[0]
    for _ in range(count):
        if data[p:p + 4] != b"PK\x01\x02":
            raise ValueError("%s: corrupt central directory at %d" % (path, p))
        modwhen = struct.unpack_from("<I", data, p + 12)[0]
        crc = struct.unpack_from("<I", data, p + 16)[0]
        nlen, elen, clen = struct.unpack_from("<HHH", data, p + 28)
        lho = struct.unpack_from("<I", data, p + 42)[0]
        name = data[p + 46:p + 46 + nlen]
        if name == entry:
            return modwhen, crc, p, lho
        p += 46 + nlen + elen + clen
    raise ValueError("%s: no %s entry" % (path, entry.decode()))


def _read_opt_header(path):
    """Return the fixed-size DexOptHeader fields needed by the checks."""
    with open(path, "rb") as f:
        head = f.read(40)
    if len(head) != 40 or head[:4] != b"dey\n":
        raise ValueError("%s: not an optimized dex (short/bad header)" % path)
    dex_off, dex_len, deps_off, deps_len = struct.unpack_from("<IIII", head, 8)
    return dex_off, dex_len, deps_off, deps_len


def read_odex_deps(path):
    """Return (modWhen, crc) from an optimized dex's dependency record.

    Layout is DexOptHeader (DexFile.h): magic[8], dexOffset, dexLength,
    depsOffset, depsLength, optOffset, optLength, flags, checksum -- then the
    dependency section opens with modWhen then crc, both native-endian u4.
    """
    _dex_off, _dex_len, deps_off, deps_len = _read_opt_header(path)
    if deps_len < 8:
        raise ValueError("%s: dependency section is too short" % path)
    with open(path, "rb") as f:
        f.seek(deps_off)
        data = f.read(8)
        if len(data) != 8:
            raise ValueError("%s: truncated dependency record" % path)
        modwhen, crc = struct.unpack("<II", data)
    return modwhen, crc


def read_app_deps(path):
    """Return source metadata and boot dependencies for an app odex.

    The dependency header carries the APK classes.dex central-directory
    modWhen/CRC before the VM build and bootclasspath records.  Fresh hardware
    proved Settings validates these words at launch, so the release gate must
    check both source metadata and the bootclasspath signatures.
    """
    _dex_off, _dex_len, deps_off, deps_len = _read_opt_header(path)
    if deps_len < 16 or deps_len > 4096:
        raise ValueError("%s: invalid dependency length %d" % (path, deps_len))
    with open(path, "rb") as f:
        f.seek(deps_off)
        data = f.read(deps_len)
    if len(data) != deps_len:
        raise ValueError("%s: truncated dependency section" % path)

    pos = 0

    def take_u4():
        nonlocal pos
        if pos + 4 > len(data):
            raise ValueError("%s: truncated dependency u4" % path)
        value = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        return value

    modwhen = take_u4()
    crc = take_u4()
    vm_build = take_u4()
    count = take_u4()
    entries = []
    for _ in range(count):
        name_len = take_u4()
        if name_len < 1 or pos + name_len + DEX_SIGNATURE_LENGTH > len(data):
            raise ValueError("%s: invalid dependency name length" % path)
        raw_name = data[pos:pos + name_len]
        pos += name_len
        if raw_name[-1:] != b"\0":
            raise ValueError("%s: dependency name is not NUL-terminated" % path)
        try:
            name = raw_name[:-1].decode("ascii")
        except UnicodeDecodeError:
            raise ValueError("%s: dependency name is not ASCII" % path)
        signature = data[pos:pos + DEX_SIGNATURE_LENGTH]
        pos += DEX_SIGNATURE_LENGTH
        entries.append((name, signature))
    if pos != len(data):
        raise ValueError("%s: spurious dependency bytes" % path)
    return modwhen, crc, vm_build, entries


def _dex_signature(path):
    """Read the SHA-1 signature from a cached DEX's header."""
    dex_off, _dex_len, _deps_off, _deps_len = _read_opt_header(path)
    with open(path, "rb") as f:
        f.seek(dex_off + 12)  # DexHeader.signature follows checksum.
        signature = f.read(DEX_SIGNATURE_LENGTH)
    if len(signature) != DEX_SIGNATURE_LENGTH:
        raise ValueError("%s: cached DEX signature is truncated" % path)
    return signature


def _boot_cache_deps(sd_root):
    cache_root = os.path.join(sd_root, "data", "dalvik-cache")
    deps = []
    for jar in JARS:
        cache_basename = "system@framework@%s@classes.dex" % jar
        path = os.path.join(cache_root, cache_basename)
        if not os.path.exists(path):
            raise ValueError("missing boot cache %s" % path)
        # Dalvik serializes getCacheFileName(), which is the runtime absolute
        # path, rather than the basename used by the SD directory.
        runtime_name = "/data/dalvik-cache/" + cache_basename
        deps.append((runtime_name, _dex_signature(path)))
    return deps


def verify_apps(sd_root):
    """Verify every bundled side-by-side app odex against boot dex caches."""
    app_root = os.path.join(sd_root, "system", "app")
    try:
        expected = _boot_cache_deps(sd_root)
    except (OSError, ValueError) as exc:
        print("FATAL: cannot read boot cache dependencies: %s" % exc)
        return 1

    bad = 0
    for retired in RETIRED_APPS:
        retired_path = os.path.join(app_root, retired)
        if os.path.exists(retired_path):
            print("RETIRED  %s is still staged" % retired_path)
            bad += 1
    for odex_name, apk_name in APP_ARTIFACTS:
        odex_path = os.path.join(app_root, odex_name)
        apk_path = os.path.join(app_root, apk_name)
        if not os.path.exists(odex_path):
            print("MISSING  %s" % odex_path)
            bad += 1
            continue
        if not os.path.exists(apk_path):
            print("MISSING  %s" % apk_path)
            bad += 1
            continue
        try:
            source_modwhen, source_crc, vm_build, actual = read_app_deps(
                odex_path
            )
            apk_modwhen, apk_crc, _cde, _lho = read_cde(apk_path)
        except (OSError, ValueError) as exc:
            print("INVALID  %-24s %s" % (odex_name, exc))
            bad += 1
            continue
        source_current = (
            source_modwhen == apk_modwhen and source_crc == apk_crc
        )
        deps_current = actual == expected
        if source_current and deps_current:
            print("OK       %-24s vm=%d modWhen=0x%08x crc=0x%08x "
                  "source/deps=current" %
                  (odex_name, vm_build, apk_modwhen, apk_crc))
            continue
        if not source_current:
            print("STALE    %-24s APK(modWhen=0x%08x crc=0x%08x) != "
                  "odex(modWhen=0x%08x crc=0x%08x)" %
                  (odex_name, apk_modwhen, apk_crc,
                   source_modwhen, source_crc))
        if not deps_current:
            print("STALE    %-24s app dependency signatures/names do not match "
                  "the deployed boot cache" % odex_name)
            for index, (want, got) in enumerate(zip(expected, actual)):
                if want != got:
                    print("         dep[%d] expected=%s/%s got=%s/%s" %
                          (index, want[0], want[1].hex(), got[0], got[1].hex()))
            if len(expected) != len(actual):
                print("         expected %d deps, found %d" %
                      (len(expected), len(actual)))
        bad += 1
    if bad:
        print("\n%d stale/missing/invalid app odex file(s): regenerate every "
              "bundled app odex after changing a bootclasspath jar." % bad)
        return 1
    print("\nall bundled app odex dependency records are current")
    return 0


def pin(paths):
    changed = 0
    for path in paths:
        modwhen, _crc, cde, lho = read_cde(path)
        if modwhen == PINNED_MODWHEN:
            print("  %-52s already pinned" % os.path.basename(path))
            continue
        with open(path, "r+b") as f:
            # Central directory entry: time at +12, date at +14.
            f.seek(cde + 12)
            f.write(struct.pack("<HH", DOS_TIME, DOS_DATE))
            # Local file header: time at +10, date at +12. Dalvik never reads
            # it, but leaving the two disagreeing would make unzip(1) and
            # jarsigner complain, so keep them consistent.
            f.seek(lho)
            if f.read(4) == b"PK\x03\x04":
                f.seek(lho + 10)
                f.write(struct.pack("<HH", DOS_TIME, DOS_DATE))
        print("  %-52s 0x%08x -> 0x%08x"
              % (os.path.basename(path), modwhen, PINNED_MODWHEN))
        changed += 1
    print("pinned %d of %d jar(s)" % (changed, len(paths)))
    return 0


def verify(sd_root):
    fw = os.path.join(sd_root, "system", "framework")
    dc = os.path.join(sd_root, "data", "dalvik-cache")
    bad = 0
    for jar in JARS:
        jp = os.path.join(fw, jar)
        op = os.path.join(dc, "system@framework@%s@classes.dex" % jar)
        if not os.path.exists(jp):
            print("MISSING  %s" % jp)
            bad += 1
            continue
        if not os.path.exists(op):
            print("MISSING  %s  -- device will cold-dexopt %s" % (op, jar))
            bad += 1
            continue
        jm, jc, _, _ = read_cde(jp)
        om, oc = read_odex_deps(op)
        if jm == om and jc == oc:
            print("OK       %-14s modWhen=0x%08x crc=0x%08x" % (jar, jm, jc))
        else:
            print("STALE    %-14s jar(modWhen=0x%08x crc=0x%08x) != "
                  "odex(modWhen=0x%08x crc=0x%08x)" % (jar, jm, jc, om, oc))
            bad += 1
    if bad:
        print("\n%d stale/missing entry(ies): the next boot WILL cold-dexopt, "
              "which has cost >4 minutes and starved the SD write path badly "
              "enough to freeze the boot animation. Re-run "
              "scripts/build_dexpreopt_qemu.sh." % bad)
        return 1
    print("\nall three bootclasspath jars are pre-optimized and current")
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == "pin":
        if len(argv) < 3:
            print("usage: jar_dexdep.py pin <jar>...")
            return 2
        return pin(argv[2:])
    if argv[1] == "verify":
        if len(argv) != 3:
            print("usage: jar_dexdep.py verify <android-root>")
            return 2
        return verify(argv[2])
    if argv[1] == "verify-apps":
        if len(argv) != 3:
            print("usage: jar_dexdep.py verify-apps <android-root>")
            return 2
        return verify_apps(argv[2])
    print("unknown subcommand %r" % argv[1])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
