#!/usr/bin/env python3
"""Make malformed AR6014 BSS records harmless to cfg80211.

The firmware can expose a beacon without DS Parameters (and older harvest
code cached it with channel 0).  cfg80211_inform_bss_frame() assumes its
channel argument is a real ieee80211_channel and dereferences it while
updating the BSS table.  A single such record therefore panics the scan
worker.  Keep the parser's HT-Operation fallback and add defensive guards at
both cfg80211 call sites plus the shared WMI node path.

This script targets the canonical WSL checkout used by the release build;
the Windows tree carries a source mirror under scratch/niazlv-linux for
review and tests.  It is intentionally idempotent.
"""
from a3ds_paths import A3DS_ROOT

import re
from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")
CFG = ROOT / "drivers/staging/ath6k_legacy/os/linux/cfg80211.c"
DRV = ROOT / "drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
WMI = ROOT / "drivers/staging/ath6k_legacy/wmi/wmi.c"

CFG_MARKER = "N3DS_CFG80211_BSS_CHANNEL_GUARD"
WMI_MARKER = "N3DS_WMI_BSS_CHANNEL_GUARD"
PARSE_MARKER = "N3DS_AR6014_BSS_CHANNEL_VALIDATION"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_cfg80211() -> None:
    text = CFG.read_text()
    if CFG_MARKER not in text:
        # Match the allocator already used by this checkout.  The legacy
        # mirror uses A_MALLOC_NOWAIT/A_FREE while newer staging revisions
        # use kmalloc/kfree; mixing them is a build-time and runtime bug.
        free_call = "kfree" if re.search(r"\bkfree\s*\(\s*ieeemgmtbuf", text) else "A_FREE"
        def insert_after(pattern, make_guard, label):
            nonlocal text
            matches = list(re.finditer(pattern, text, re.M))
            if len(matches) != 1:
                raise RuntimeError(f"{label}: expected one match, found {len(matches)}")
            match = matches[0]
            indent = match.group(1)
            text = text[:match.end()] + make_guard(indent) + text[match.end():]

        insert_after(
            r"^([ \t]*)channel = ieee80211_get_channel\(wiphy, freq\);\n",
            lambda i: (
                f"{i}/* N3DS_CFG80211_BSS_CHANNEL_GUARD: a partially decoded\n"
                f"{i} * firmware node may have no usable channel.  Never pass\n"
                f"{i} * NULL into cfg80211_inform_bss_frame(), whose internal\n"
                f"{i} * lookup dereferences the channel while publishing BSS. */\n"
                f"{i}if (!channel) {{\n"
                f"{i}    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,\n"
                f"{i}                    (\"%s: dropping BSS with invalid frequency %d\\n\",\n"
                f"{i}                     __func__, freq));\n"
                f"{i}    {free_call}(ieeemgmtbuf);\n"
                f"{i}    return;\n"
                f"{i}}}\n"
            ),
            "scan-node channel guard",
        )
        insert_after(
            r"^([ \t]*)ibss_channel = ieee80211_get_channel\(ar->wdev->wiphy, \(int\)channel\);\n",
            lambda i: (
                f"{i}/* N3DS_CFG80211_BSS_CHANNEL_GUARD: do not let an invalid\n"
                f"{i} * firmware frequency reach cfg80211's BSS lookup. */\n"
                f"{i}if (!ibss_channel) {{\n"
                f"{i}    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,\n"
                f"{i}                    (\"%s: dropping BSS with invalid channel %u\\n\",\n"
                f"{i}                     __func__, channel));\n"
                f"{i}    {free_call}(ieeemgmtbuf);\n"
                f"{i}    return;\n"
                f"{i}}}\n"
            ),
            "connect-event channel guard",
        )
    CFG.write_text(text)


def patch_wmi() -> None:
    text = WMI.read_text()
    if "bih->channel > 2472" in text:
        return
    if WMI_MARKER in text:
        old = """    if (!bih->channel)\n        return A_EINVAL;\n"""
        new = """    if (!bih->channel ||\n        (bih->channel != 2484 &&\n         (bih->channel < 2412 || bih->channel > 2472 ||\n          ((bih->channel - 2412) % 5))))\n        return A_EINVAL;\n"""
        WMI.write_text(replace_once(text, old, new, "WMI range guard"))
        return
    guard = (
        "    /* N3DS_WMI_BSS_CHANNEL_GUARD: only AR6014's valid 2.4-GHz\n"
        "     * frequencies may enter the shared node table. */\n"
        "    if (!bih->channel ||\n"
        "        (bih->channel != 2484 &&\n"
        "         (bih->channel < 2412 || bih->channel > 2472 ||\n"
        "          ((bih->channel - 2412) % 5))))\n"
        "        return A_EINVAL;\n"
    )
    # bih is declared in several WMI handlers.  Anchor specifically to the
    # length check inside wmi_bssInfo_event_rx(), otherwise a fresh checkout
    # has two matches and the patch aborts (or risks modifying the wrong
    # event path).
    anchor = re.compile(
        r"(wmi_bssInfo_event_rx\s*\([^)]*\)\s*\{.*?"
        r"if\s*\(len\s*<=\s*sizeof\(WMI_BSS_INFO_HDR\)\)\s*\{\s*"
        r"return\s+A_EINVAL;\s*\}\s*"
        r")(\s*bih\s*=\s*\(WMI_BSS_INFO_HDR\s*\*\)datap;\s*\n)",
        re.S,
    )
    matches = list(anchor.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            "WMI channel guard: expected one wmi_bssInfo_event_rx anchor, "
            f"found {len(matches)}"
        )
    match = matches[0]
    text = text[:match.end()] + guard + text[match.end():]
    WMI.write_text(text)


def patch_parser() -> None:
    text = DRV.read_text()
    # Current sparse-locator source may already contain the HT fallback and
    # the zero-channel rejection.  The range checks are still mandatory on
    # every run: an older invocation may have left the marker while accepting
    # arbitrary bytes as frequencies.
    if "else if (p[0] == 61" not in text:
        old = ("        if (p[0] == IEEE80211_ELEMID_DSPARMS && p[1] >= 1)\n"
               "            channel_mhz = p[2] == 14 ? 2484 : 2407 + 5 * p[2];\n")
        new = old + ("        else if (p[0] == 61 && p[1] >= 1)"
                     " /* HT Operation primary channel */\n"
                     "            channel_mhz = p[2] == 14 ? 2484 :"
                     " 2407 + 5 * p[2];\n")
        if old in text:
            text = replace_once(text, old, new, "HT operation channel fallback")

    # Both elements carry a one-byte 2.4-GHz channel number.  Do not turn
    # arbitrary bytes into a plausible-looking frequency (e.g. channel 15 ->
    # 2482), because ieee80211_get_channel() then returns NULL.
    if "p[0] == IEEE80211_ELEMID_DSPARMS && p[1] >= 1 && p[2] >= 1 && p[2] <= 14" not in text:
        text = text.replace(
            "p[0] == IEEE80211_ELEMID_DSPARMS && p[1] >= 1",
            "p[0] == IEEE80211_ELEMID_DSPARMS && p[1] >= 1 && p[2] >= 1 && p[2] <= 14",
        )
    if "p[0] == 3 && p[1] >= 1 && p[2] >= 1 && p[2] <= 14" not in text:
        text = text.replace(
            "p[0] == 3 && p[1] >= 1",
            "p[0] == 3 && p[1] >= 1 && p[2] >= 1 && p[2] <= 14",
        )
    if "p[0] == 61 && p[1] >= 1 && p[2] >= 1 && p[2] <= 14" not in text:
        text = text.replace(
            "p[0] == 61 && p[1] >= 1",
            "p[0] == 61 && p[1] >= 1 && p[2] >= 1 && p[2] <= 14",
        )

    if "|| !channel_mhz" not in text:
        old = "    if (body_len <= AR6014_FIXED_LEN)\n        return 0;\n"
        new = ("    /* N3DS_AR6014_BSS_CHANNEL_VALIDATION: cfg80211 must never see\n"
               "     * a cached record whose channel is unknown. */\n"
               "    if (body_len <= AR6014_FIXED_LEN || !channel_mhz)\n"
               "        return 0;\n")
        if old in text:
            text = replace_once(text, old, new, "BSS channel validation")
    if PARSE_MARKER not in text:
        text = "/* N3DS_AR6014_BSS_CHANNEL_VALIDATION */\n" + text
    DRV.write_text(text)


def main() -> None:
    for path in (CFG, DRV, WMI):
        if not path.exists():
            raise SystemExit(f"missing canonical source: {path}")
    patch_cfg80211()
    patch_parser()
    patch_wmi()
    print("patch_wifi_bss_channel_guard: cfg80211/WMI/parser guards installed")


if __name__ == "__main__":
    main()
