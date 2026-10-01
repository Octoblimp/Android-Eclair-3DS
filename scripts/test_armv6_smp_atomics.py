#!/usr/bin/env python3
"""Contract for barrier-correct Android atomics on the ARM11 SMP target."""
from a3ds_paths import A3DS_ROOT

import importlib.util
import re
import tempfile
from pathlib import Path


ROOT = Path(A3DS_ROOT)
SOURCE = ROOT / "third_party/system_core/libcutils/atomic-android-armv6.S"
PATCHER = Path(__file__).with_name("patch_armv6_smp_atomics.py")
BUILD = Path(__file__).with_name("build_liblog_libcutils.sh")
REBUILD = Path(__file__).with_name("rebuild_everything.sh")
VERIFY = Path(__file__).with_name("verify_release_artifacts.sh")
QEMU_TEST = Path(__file__).with_name("test_armv6_smp_atomics_qemu.sh")


def require(text: str, marker: str, where: str) -> None:
    assert marker in text, f"{where}: missing {marker}"


def load_patcher():
    spec = importlib.util.spec_from_file_location("patch_armv6_smp_atomics", PATCHER)
    assert spec is not None and spec.loader is not None, "atomic patcher is not importable"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_patcher_contract() -> None:
    """Exercise both the clean transition and the fail-closed repeat path."""
    patcher = load_patcher()
    original_source = patcher.SOURCE
    try:
        with tempfile.TemporaryDirectory(prefix="android3ds-atomic-") as temp:
            fixture = Path(temp) / "atomic-android-armv6.S"
            fixture.write_text(
                "prefix\n" + patcher.START + "discarded legacy body\n" + patcher.END + "suffix\n",
                encoding="utf-8",
            )
            patcher.SOURCE = fixture
            patcher.main()
            first = fixture.read_bytes()
            patcher.main()
            assert fixture.read_bytes() == first, "atomic patch is not byte-idempotent"

            fixture.write_bytes(first + b"\n/* N3DS_ARMV6_SMP_ATOMICS */\n")
            try:
                patcher.main()
            except RuntimeError as error:
                assert "marker missing or duplicated" in str(error)
            else:
                raise AssertionError("atomic patch accepted a duplicate marker")

            fixture.write_text("prefix\nlegacy source with an unexpected layout\n", encoding="utf-8")
            try:
                patcher.main()
            except RuntimeError as error:
                assert "anchors missing or duplicated" in str(error)
            else:
                raise AssertionError("atomic patch accepted a source with missing anchors")
    finally:
        patcher.SOURCE = original_source


source = SOURCE.read_text(encoding="utf-8")
patcher = PATCHER.read_text(encoding="utf-8")
build = BUILD.read_text(encoding="utf-8")
rebuild = REBUILD.read_text(encoding="utf-8")
verify = VERIFY.read_text(encoding="utf-8")
qemu_test = QEMU_TEST.read_text(encoding="utf-8")

require(source, "N3DS_ARMV6_SMP_ATOMICS", "ARMv6 atomic source")
require(source, "0xffff0fc0", "ARMv6 atomic source")
require(source, "__kuser_cmpxchg", "ARMv6 atomic source")
assert "this file is not safe with SMP systems" not in source

for symbol in (
    "android_atomic_write:",
    "android_atomic_inc:",
    "android_atomic_dec:",
    "android_atomic_add:",
    "android_atomic_and:",
    "android_atomic_or:",
    "android_atomic_swap:",
    "android_atomic_cmpxchg:",
):
    require(source, symbol, "ARMv6 atomic source")

atomic_symbols = (
    "android_atomic_write:",
    "android_atomic_inc:",
    "android_atomic_dec:",
    "android_atomic_add:",
    "android_atomic_and:",
    "android_atomic_or:",
    "android_atomic_swap:",
    "android_atomic_cmpxchg:",
)
for index, symbol in enumerate(atomic_symbols):
    start = source.index(symbol)
    end = source.index(atomic_symbols[index + 1]) if index + 1 < len(atomic_symbols) else len(source)
    body = source[start:end]
    if symbol == "android_atomic_write:":
        require(body, "b       android_atomic_swap", symbol)
    elif symbol == "android_atomic_cmpxchg:":
        require(body, "b       __n3ds_kuser_cmpxchg", symbol)
    else:
        require(body, "bl      __n3ds_kuser_cmpxchg", symbol)
assert not re.search(r"(?im)^\s*(ldrex|strex)\b", source), "raw UP-only exclusive loop remains"

for marker in (
    "N3DS_ARMV6_SMP_ATOMICS",
    "KUSER_CMPXCHG",
    "old value",
    "non-zero",
):
    require(patcher, marker, "atomic patcher")

require(build, "atomic-android-armv6.S", "libcutils build")
require(rebuild, "patch_armv6_smp_atomics.py", "clean rebuild")
require(rebuild, "test_armv6_smp_atomics.py", "clean rebuild")
require(rebuild, "test_armv6_smp_atomics_qemu.sh", "clean rebuild")
require(verify, "N3DS_ARMV6_SMP_ATOMICS", "release verifier")
require(verify, "test_armv6_smp_atomics.py", "release verifier")
require(verify, "test_armv6_smp_atomics_qemu.sh", "release verifier")
require(verify, "CONFIG_KUSER_HELPERS=y", "release verifier")
require(qemu_test, "armv6_atomic_stress.c", "QEMU atomic test")
require(qemu_test, "qemu-arm-static", "QEMU atomic test")
check_patcher_contract()

print("PASS: ARMv6 Android atomics honor the SMP synchronization contract")
