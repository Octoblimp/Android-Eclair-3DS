#!/usr/bin/env python3
"""Pin smeState-driven cfg80211 disconnect notification (W8).

The proven cause of "associates but never connects": ar6000_connect_event()
clears arConnectPending on association, ar6k_cfg80211_disconnect_event() gated
every notification behind arConnectPending, so after the first success
cfg80211_disconnected() was never called again, wdev->connected stayed set, and
cfg80211_connect() returned -EALREADY for every later attempt (22 of 22 in the
2026-09-01 capture).
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
           "ath6k_legacy/os/linux/cfg80211.c")
DRV = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
           "ath6k_legacy/os/linux/ar6000_drv.c")
INITRAMFS = Path(f"{A3DS_ROOT}/sdcard/linux/initramfs.cpio.gz")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_ar6014_cfg80211_disconnect_notify",
        HERE / "patch_ar6014_cfg80211_disconnect_notify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LINE_COMMENT = re.compile("//[^" + chr(10) + "]*")


def strip_comments(text):
    """Remove C comments so structural assertions cannot be satisfied -- or
    broken -- by prose.  String literals survive, so log-message checks still
    work on the stripped text."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(LINE_COMMENT, "", text)


def function_body(text, name):
    """Return the source of function `name` from its signature to the next
    line that is a lone closing brace in column 0."""
    match = re.search(r"^%s\(" % re.escape(name), text, re.M)
    if not match:
        return None
    end = text.index("\n}\n", match.start())
    return text[match.start():end + 3]


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from cfg80211.c")
    check(patcher.patch_cfg(text) == text, "patcher is not idempotent")

    # W8 deleted the block that used to carry this marker.  The behaviour it
    # named survives, generalised to every reason -- but both
    # verify_release_artifacts.sh and patch_ar6014_direct_reconnect.py's only
    # idempotency guard still key on the name, and losing it makes that
    # patcher re-apply against an anchor W8 removed.
    check("N3DS_AR6014_NO_NETWORK_HANDOFF" in text,
          "the NO_NETWORK_AVAIL handoff marker was dropped; the release "
          "verifier greps for it and patch_ar6014_direct_reconnect.py uses "
          "it as its only idempotency guard")

    connect = function_body(text, "ar6k_cfg80211_connect_event")
    disconnect = function_body(text, "ar6k_cfg80211_disconnect_event")
    if connect is not None:
        connect = strip_comments(connect)
    if disconnect is not None:
        disconnect = strip_comments(disconnect)
    check(connect is not None, "ar6k_cfg80211_connect_event() not found")
    check(disconnect is not None, "ar6k_cfg80211_disconnect_event() not found")
    if connect is None or disconnect is None:
        for message in failures:
            print(f"FAIL: {message}")
        return 1

    # --- the connect side must leave cfg80211 holding a connection --------
    check("ar->smeState = SME_CONNECTED;" in connect,
          "connect event never sets SME_CONNECTED")
    check(connect.count("ar->smeState = SME_CONNECTED;") == 2,
          "SME_CONNECTED must be set on both the first-connect and roam paths")
    check("ar->smeState = SME_DISCONNECTED;" not in connect,
          "connect event still writes SME_DISCONNECTED; that is the bug")

    # The SME state must be published before the notification is queued, so a
    # disconnect racing the connect result cannot read the stale state.
    sme_at = connect.index("ar->smeState = SME_CONNECTED;")
    result_at = connect.index("WLAN_STATUS_SUCCESS")
    check(sme_at < result_at,
          "SME_CONNECTED must be set before cfg80211_connect_result()")

    check("AR6002 connect: connect_result SUCCESS bssid=%pM" in connect,
          "no log at the cfg80211_connect_result(SUCCESS) call site")
    check("AR6002 connect: dropped, iftype %u is not STATION" in connect,
          "the STATION iftype guard still returns silently")
    check("AR6002 connect: dropped, iftype %u is not ADHOC" in connect,
          "the ADHOC iftype guard still returns silently")

    # --- the disconnect side must not gate on arConnectPending ------------
    check("if(true == ar->arConnectPending)" not in disconnect
          and "if (true == ar->arConnectPending)" not in disconnect,
          "disconnect event still gates notification on arConnectPending")
    check("ar->arConnectPending = false;" in disconnect,
          "disconnect event no longer clears arConnectPending")

    check("if (ar->smeState == SME_CONNECTING) {" in disconnect,
          "SME_CONNECTING branch missing")
    check("} else if (ar->smeState == SME_CONNECTED) {" in disconnect,
          "SME_CONNECTED branch missing; disconnects are still swallowed")
    check(disconnect.count("cfg80211_connect_result") == 1,
          "expected exactly one cfg80211_connect_result() in the disconnect event")
    check(disconnect.count("cfg80211_disconnected") == 1,
          "expected exactly one cfg80211_disconnected() in the disconnect event")

    # cfg80211_disconnected() takes an 802.11 reason code, not an ath6kl one.
    disc_at = disconnect.find("cfg80211_disconnected(ar->arNetDev,")
    check(disc_at >= 0, "cfg80211_disconnected() call shape changed")
    if disc_at >= 0:
        call = disconnect[disc_at:disc_at + 200]
        check("protocolReasonStatus" in call,
              "cfg80211_disconnected() is not passed protocolReasonStatus")

    # Every reason code must reach the notification.  There is no branch on
    # `reason` before it other than the DISCONNECT_CMD auto-auth retry and the
    # park command, so assert no reason-specific gate came back.
    check("NO_NETWORK_AVAIL" not in disconnect,
          "a NO_NETWORK_AVAIL special case is back; all reasons must notify")

    # The park command must still fire for target-initiated disconnects.
    check("if (reason != DISCONNECT_CMD) {" in disconnect,
          "target-initiated disconnects no longer park the target")
    park_at = disconnect.index("if (reason != DISCONNECT_CMD) {")
    notify_at = disconnect.index("if (ar->smeState == SME_CONNECTING) {")
    check(park_at < notify_at, "the park command must precede the notification")

    # ...and must not return before notifying (mainline does; NWM does not
    # reliably send the follow-up event that would make that safe).
    park_block = disconnect[park_at:notify_at]
    check("return;" not in park_block,
          "the disconnect event returns before notifying cfg80211")

    # --- the WEP auto-auth retry survives, correctly guarded --------------
    check("ar->arDot11AuthMode = SHARED_AUTH;" in disconnect,
          "the OPEN->SHARED auto-auth retry was dropped")
    check("ar->smeState == SME_CONNECTING &&" in disconnect,
          "the auto-auth retry is not guarded on SME_CONNECTING")
    retry_at = disconnect.index("ar->arDot11AuthMode = SHARED_AUTH;")
    check(retry_at < park_at,
          "the auto-auth retry must be handled before the notification path")
    check("AR6002 connect: OPEN->SHARED auto-auth retry status=%d" in disconnect,
          "the auto-auth retry is silent")

    # --- the invariant this whole change rests on -------------------------
    drv = DRV.read_text(encoding="utf-8")
    connect_call = drv.index("ar6k_cfg80211_connect_event(ar, channel, bssid,")
    connected_set = drv.index("ar->arConnected  = true;")
    check(connect_call < connected_set,
          "ar6000_connect_event() now sets arConnected before calling the "
          "cfg80211 handler; the `false == ar->arConnected` first-connect test "
          "would always be false and every association would look like a roam")

    # The shipped module is what runs (initramfs-only delivery path).
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
            check(b"AR6002 connect: connect_result SUCCESS" in blob,
                  "baked initramfs module predates the disconnect-notify patch")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_cfg80211_disconnect_notify: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
