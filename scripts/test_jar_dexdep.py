#!/usr/bin/env python3
"""Regression tests for boot and side-by-side Dalvik dependency checks."""

import importlib.util
import struct
import tempfile
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("jar_dexdep", HERE / "jar_dexdep.py")
JAR_DEXDEP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(JAR_DEXDEP)


def write_cache(path, signature):
    data = bytearray(96)
    data[:8] = b"dey\n035\0"
    struct.pack_into("<IIII", data, 8, 40, 32, 80, 16)
    data[40:48] = b"dex\n035\0"
    data[52:72] = signature
    path.write_bytes(data)


def write_apk(path, year=2025):
    info = zipfile.ZipInfo("classes.dex", (year, 1, 1, 0, 0, 0))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, b"dex\n035\0fixture")


def write_app(path, entries, modwhen=0, crc=0):
    deps = bytearray(struct.pack("<IIII", modwhen, crc, 17, len(entries)))
    for name, signature in entries:
        encoded = name.encode("ascii") + b"\0"
        deps += struct.pack("<I", len(encoded)) + encoded + signature
    data = bytearray(40) + deps
    data[:8] = b"dey\n035\0"
    struct.pack_into("<IIII", data, 8, 0, 0, 40, len(deps))
    path.write_bytes(data)


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        cache = root / "data" / "dalvik-cache"
        app = root / "system" / "app"
        cache.mkdir(parents=True)
        app.mkdir(parents=True)

        expected = []
        for index, jar in enumerate(JAR_DEXDEP.JARS):
            basename = "system@framework@%s@classes.dex" % jar
            signature = bytes([index + 1]) * 20
            write_cache(cache / basename, signature)
            expected.append(("/data/dalvik-cache/" + basename, signature))

        for odex_name, apk_name in JAR_DEXDEP.APP_ARTIFACTS:
            write_apk(app / apk_name)
            modwhen, crc, _cde, _lho = JAR_DEXDEP.read_cde(app / apk_name)
            write_app(app / odex_name, expected, modwhen, crc)
        assert JAR_DEXDEP.verify_apps(str(root)) == 0

        stale = list(expected)
        stale[2] = (stale[2][0], b"X" * 20)
        settings_mod, settings_crc, _cde, _lho = JAR_DEXDEP.read_cde(
            app / "Settings.apk"
        )
        write_app(app / "Settings.odex", stale, settings_mod, settings_crc)
        assert JAR_DEXDEP.verify_apps(str(root)) == 1

        write_app(app / "Settings.odex", expected, settings_mod, settings_crc)
        write_apk(app / "Settings.apk", year=2026)
        assert JAR_DEXDEP.verify_apps(str(root)) == 1

    print("test_jar_dexdep: PASS")


if __name__ == "__main__":
    main()
