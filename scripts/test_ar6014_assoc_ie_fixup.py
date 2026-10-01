#!/usr/bin/env python3
"""Pin the association-IE underflow repair (W12/W13/W14).

``reqIe=252 respIe=250`` was printed identically on all ten associations in the
build-#254 capture.  252 is (u8)(0-4) and 250 is (u8)(0-6): NWM reports both IE
lengths as zero and stock ath6kl subtracts the fixed-field offsets without
checking, wrapping both u8 fields.  That is a 502-byte kernel out-of-bounds read
handed to cfg80211, and it is what makes wpa_supplicant clear its own RSN IE --
without which message 2/4 of the 4-way handshake cannot be built at all.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
           "ath6k_legacy/os/linux/cfg80211.c")
INITRAMFS = Path(f"{A3DS_ROOT}/sdcard/linux/initramfs.cpio.gz")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_ar6014_assoc_ie_fixup", HERE / "patch_ar6014_assoc_ie_fixup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from cfg80211.c")
    check(patcher.patch_cfg80211(text) == text, "patcher is not idempotent")

    # The whole point: the unguarded subtraction must be gone.  Anything that
    # reintroduces it reintroduces the out-of-bounds read.
    check("    assocReqLen -= assocReqIeOffset;\n"
          "    assocRespLen -= assocRespIeOffset;\n" not in text,
          "the unguarded stock subtraction is back; both u8 lengths will wrap "
          "again when the target reports zero-length IEs")
    check("if (assocReqLen >= assocReqIeOffset) {" in text,
          "assocReqLen is subtracted without checking it is large enough")
    check("if (assocRespLen >= assocRespIeOffset) {" in text,
          "assocRespLen is subtracted without checking it is large enough")

    # When the target reports nothing, report nothing -- not garbage.
    check("assocRespIe = NULL;" in text,
          "the response-IE pointer is not cleared when there are no IEs, so "
          "cfg80211 still gets a pointer past the end of the event buffer")

    # The supplicant needs its own assoc-request IE back or it clears
    # sm->assoc_wpa_ie; ours is the blob we forwarded as WMI_FRAME_ASSOC_REQ.
    check("static u8 n3ds_assoc_req_ie[256];" in text,
          "the assoc-request IE keeper is missing")
    check("memcpy(n3ds_assoc_req_ie, sme->ie, n3ds_assoc_req_ie_len);" in text,
          "connect() no longer stashes the assoc-request IE")
    check("if (assocReqIe == NULL && n3ds_assoc_req_ie_len > 0) {" in text,
          "the stashed assoc-request IE is never reported back to cfg80211")

    # The stash has to happen even if the target rejects the IE, so it must
    # precede the command that can fail.
    stash_at = text.index("memcpy(n3ds_assoc_req_ie, sme->ie,")
    appie_at = text.index("status = wmi_set_appie_cmd(ar->arWmi, "
                          "WMI_FRAME_ASSOC_REQ,")
    check(stash_at < appie_at,
          "the IE is stashed after wmi_set_appie_cmd(); a target rejection "
          "would leave the supplicant with no assoc-request IE at all")

    # The copy is bounded by the buffer, not by the caller's length.
    check("min_t(size_t, sme->ie_len," in text,
          "the assoc-request IE copy is not bounded by the buffer size")

    # The raw header log must read the target's numbers before they are
    # clamped, or it reports our own arithmetic back to us.
    check("AR6002 connect: nwm evt chan=%u nettype=%u listen=%u beacon=%u" in text,
          "raw connect-event header log missing; the capture instructions "
          "name this line")
    log_at = text.index("AR6002 connect: nwm evt chan=")
    clamp_at = text.index("if (assocReqLen >= assocReqIeOffset) {")
    check(log_at < clamp_at,
          "the raw-header log runs after the clamp, so it prints our clamped "
          "values rather than what NWM actually reported")

    if not INITRAMFS.is_file():
        failures.append(f"initramfs not found at {INITRAMFS}")
    else:
        blob = subprocess.run(
            ["bash", "-c",
             f"gzip -dc {INITRAMFS} | cpio -i --to-stdout "
             f"n3ds/modules/ath6kl.ko 2>/dev/null"],
            capture_output=True).stdout
        check(len(blob) > 0, "could not extract ath6kl.ko from the initramfs")
        if blob:
            check(b"AR6002 connect: nwm evt chan=" in blob,
                  "baked initramfs module predates the assoc-IE fixup")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_assoc_ie_fixup: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
