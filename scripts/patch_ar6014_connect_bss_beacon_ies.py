#!/usr/bin/env python3
"""Build the connect-time BSS from NWM's beacon IEs, not the assoc-request IEs.

Build #256 fired `WARNING at net/wireless/sme.c:757` six times.  That line is
`if (WARN_ON(!cr->bss)) return;` in __cfg80211_connect_result(), reached after
cfg80211_connect_result() has been queued through cfg80211_event_work.  It
means cfg80211 could not find, by SSID, the BSS the driver claims to have
connected to -- so wdev->current_bss is never set and
cfg80211_upload_connect_keys() is skipped along with it.

The driver synthesizes that BSS itself, one line above, by handing
cfg80211_inform_bss_frame() a beacon whose variable part is
assocReqIe/assocReqLen.  That was already dubious in stock ath6kl -- an
association request is not a beacon -- but the assoc-IE fixup (F23) made it
actively wrong: NWM reports assocReqLen as 0, so the fixup substitutes the
host's own 40-byte RSN blob, which contains no SSID element at all.  The
published BSS therefore has no SSID, cfg80211_get_bss() misses, and cr->bss
comes back NULL.

NWM does hand us the AP's real beacon IEs -- `beaconIeLen=207` in every #256
connect event -- in the first beaconIeLen bytes of assocInfo, immediately
before the assoc-request fixed fields the capability word is already read
from.  Use those.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
CFG = ROOT / "os/linux/cfg80211.c"

MARKER = "N3DS_AR6014_CONNECT_BSS_BEACON_IES"

BEACON_OLD = '''    } else {
            capability = *(u16 *)(&assocInfo[beaconIeLen]);
            memcpy(source_mac, bssid, ATH_MAC_LEN);
            ptr_ie_buf = assocReqIe;
            ie_buf_len = assocReqLen;
    }
'''

BEACON_NEW = '''    } else {
            capability = *(u16 *)(&assocInfo[beaconIeLen]);
            memcpy(source_mac, bssid, ATH_MAC_LEN);
            /* N3DS_AR6014_CONNECT_BSS_BEACON_IES: what is being built here is
             * a *beacon*, and cfg80211 looks the resulting BSS back up by
             * SSID in __cfg80211_connect_result().  Stock ath6kl fills it
             * with the association-request IEs, which after the assoc-IE
             * fixup is the host's own RSN blob -- no SSID element at all.
             * cfg80211_get_bss() then missed, cr->bss came back NULL, and
             * net/wireless/sme.c:757 WARNed six times in #256, taking
             * wdev->current_bss and the pending-key upload down with it.
             * NWM supplies the AP's real beacon IEs in the first beaconIeLen
             * bytes of assocInfo; prefer those, and keep the old behaviour
             * only for a target that sent none. */
            if (assocInfo != NULL && beaconIeLen > 0) {
                ptr_ie_buf = assocInfo;
                ie_buf_len = beaconIeLen;
                AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                    ("AR6002 connect: bss ie src=beacon len=%u\\n",
                     ie_buf_len));
            } else {
                ptr_ie_buf = assocReqIe;
                ie_buf_len = assocReqLen;
                AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                    ("AR6002 connect: bss ie src=assocreq len=%u\\n",
                     ie_buf_len));
            }
    }
'''

HUNKS = (
    ("beacon ie source", BEACON_OLD, BEACON_NEW),
)


def patch_cfg(text: str) -> str:
    """Point the synthesized connect-time beacon at NWM's beacon IEs.

    Idempotent: an already-patched tree is returned untouched so the patcher
    can be re-run after an unrelated driver change.
    """
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, f"{name}: expected exactly one match"
        text = text.replace(old, new)
    return text


def main() -> None:
    original = CFG.read_text(encoding="utf-8")
    patched = patch_cfg(original)
    if patched == original:
        print("ar6014_connect_bss_beacon_ies: already applied")
        return
    CFG.write_text(patched, encoding="utf-8")
    print(f"ar6014_connect_bss_beacon_ies: patched {CFG}")


if __name__ == "__main__":
    main()
