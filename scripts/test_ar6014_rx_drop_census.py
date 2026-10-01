#!/usr/bin/env python3
"""Checks for patch_ar6014_rx_drop_census.py.

Asserts the patcher is idempotent, that it rewrites a synthetic fixture built
from its own *_OLD strings, and that the shipped ath6kl.ko -- the copy inside
initramfs.cpio.gz, which is the only one the device ever loads -- carries the
post-patch strings.  That last check is the one that matters: the sdcard
system/lib/modules copies are never loaded, so a driver change can look applied
in the tree and be absent from the running kernel.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHER = Path(__file__).resolve().parent / "patch_ar6014_rx_drop_census.py"

DRIVER_REL = "third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
INITRAMFS = ROOT / "sdcard/linux/initramfs.cpio.gz"
MODULE_IN_CPIO = "n3ds/modules/ath6kl.ko"

failures = []


def check(condition, message):
    if condition:
        print("  ok   %s" % message)
    else:
        print("  FAIL %s" % message)
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location("patch_rx_drop", PATCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture(mod):
    """Build a file out of the patcher's own OLD strings and patch it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / DRIVER_REL
        target.parent.mkdir(parents=True, exist_ok=True)

        body = "\n".join(old for _, old, _ in mod.HUNKS)
        target.write_text(body, encoding="utf-8")

        mod.patch(root)
        patched = target.read_text(encoding="utf-8")

        check(mod.MARKER in patched, "fixture gains the marker")
        for name, _, new in mod.HUNKS:
            check(new in patched, "fixture carries hunk %r" % name)

        # Idempotency: a second run must be a no-op, not a double application.
        mod.patch(root)
        again = target.read_text(encoding="utf-8")
        check(again == patched, "second run leaves the fixture unchanged")
        check(patched.count("atomic_inc(&n3ds_rx_drop_short)") == 1,
              "drop counter is incremented from exactly one site")


def test_tree():
    driver = ROOT / DRIVER_REL
    if not driver.is_file():
        driver = Path(A3DS_ROOT) / DRIVER_REL
    if not driver.is_file():
        check(False, "canonical driver source is required; run in WSL")
        return
    text = driver.read_text(encoding="utf-8", errors="surrogateescape")
    check("N3DS_AR6014_RX_DROP_CENSUS" in text, "tree carries the marker")
    check("n3ds_rx_dump(\"data\"" in text, "tree dumps data-endpoint packets")
    check("short=%d dix=%d aggr=%d down=%d deliv=%d" in text,
          "census report carries the per-site drop counts")
    # The reorder buffer NULLs the pointer on a hold; without this the hold is
    # scored identically to a delivery.
    check("atomic_inc(&n3ds_rx_drop_aggr)" in text,
          "reorder-buffer hold is counted")
    # Guard against the drop counters being reset anywhere but the association
    # reset, which would make a per-link census meaningless.
    check(text.count("atomic_set(&n3ds_rx_drop_short, 0)") == 1,
          "drop counters are reset from exactly one place")


def test_shipped_module():
    if not INITRAMFS.is_file():
        check(False, "release initramfs is required")
        return
    try:
        archive = subprocess.run(
            ["zcat", str(INITRAMFS)], check=True, stdout=subprocess.PIPE
        ).stdout
        blob = subprocess.run(
            ["cpio", "-i", "--to-stdout", MODULE_IN_CPIO],
            input=archive, check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        check(False, "could not read initramfs (%s)" % exc)
        return
    if not blob:
        check(False, "%s missing from initramfs" % MODULE_IN_CPIO)
        return
    check(b"AR6002 rxpkt %s len=%d" in blob,
          "shipped ath6kl.ko carries the rxpkt dump string")
    check(b"short=%d dix=%d aggr=%d down=%d deliv=%d" in blob,
          "shipped ath6kl.ko carries the extended census string")


def main():
    mod = load_patcher()
    print("fixture:")
    test_fixture(mod)
    print("tree:")
    test_tree()
    print("shipped module:")
    test_shipped_module()
    if failures:
        print("\nFAILED (%d)" % len(failures))
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
