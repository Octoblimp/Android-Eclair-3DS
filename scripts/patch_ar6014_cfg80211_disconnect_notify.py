#!/usr/bin/env python3
"""Drive cfg80211 disconnect notification from smeState, not arConnectPending.

Build #253 associated for the first time.  It still never produced a usable
connection, and the 2026-09-01 capture says why in one line, repeated:

    nl80211: MLME connect failed: ret=-114 (Operation already in progress)

Twenty-two supplicant connect attempts, twenty-two -EALREADY, and exactly two
connects in the whole boot that ever reached the driver -- 128.173 s and
257.619 s, each immediately after a module load recreated the wdev.  Both of
those associated.

`cfg80211_connect()` returns -EALREADY whenever `wdev->connected` is set, and
the *only* thing that clears `wdev->connected` is the driver calling
`cfg80211_disconnected()`.  `cfg80211_disconnect()` / `rdev_disconnect()` does
not clear it; it just asks the driver to disconnect and waits to be told.

Our fork never told it.  `ar6000_connect_event()` clears `arConnectPending` the
moment the target associates, and `ar6k_cfg80211_disconnect_event()` gated
every notification behind `if (true == ar->arConnectPending)`.  So a successful
association permanently disarmed the notification path: the first success was
also the last connect the stack would ever accept.  #253's association is what
made this latent bug fatal.

Two smaller defects in the same block:

  * there was no branch at all for LOST_LINK, AUTH_FAILED, ASSOC_FAILED or
    BSS_DISCONNECTED -- only NO_NETWORK_AVAIL and DISCONNECT_CMD -- so those
    reasons were swallowed even while a connect was pending;
  * `cfg80211_disconnected()` was handed the ath6kl reason (1-8) where an
    802.11 reason code belongs; mainline passes `protocolReasonStatus`.

The fix is mainline ath6kl's own structure: `SME_CONNECTING` completes the
pending request with a failure, `SME_CONNECTED` reports a disconnection,
`SME_DISCONNECTED` reports nothing, and the connect event sets `SME_CONNECTED`
instead of the `SME_DISCONNECTED` our fork wrote there.

Unlike mainline we do not send `wmi_disconnect_cmd()` and then *return* to wait
for a follow-up DISCONNECT_CMD event before notifying: NWM does not reliably
send one, which is exactly what the older NO_NETWORK_AVAIL handoff was working
around.  Notifying immediately is safe in both directions -- if a follow-up
event does arrive it finds smeState already SME_DISCONNECTED and notifies
nothing twice.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
CFG = ROOT / "os/linux/cfg80211.c"

MARKER = "N3DS_AR6014_DISCONNECT_NOTIFY"

# --- connect event: publish SME_CONNECTED, and say so out loud ------------

CONNECT_OLD = '''    if (false == ar->arConnected) {
        /* inform connect result to cfg80211 */
        ar->smeState = SME_DISCONNECTED;
        cfg80211_connect_result(ar->arNetDev, bssid,
                                assocReqIe, assocReqLen,
                                assocRespIe, assocRespLen,
                                WLAN_STATUS_SUCCESS, GFP_KERNEL);
    } else {
'''

CONNECT_NEW = '''    if (false == ar->arConnected) {
        /* N3DS_AR6014_DISCONNECT_NOTIFY: cfg80211 has to be left holding
         * SME_CONNECTED, because ar6k_cfg80211_disconnect_event() keys its
         * notification off this field.  Writing SME_DISCONNECTED here (what
         * this fork did) meant a successful association permanently disarmed
         * the disconnect path, wdev->connected was never cleared again, and
         * every later cfg80211_connect() short-circuited with -EALREADY
         * before this driver was reached. */
        ar->smeState = SME_CONNECTED;
        cfg80211_connect_result(ar->arNetDev, bssid,
                                assocReqIe, assocReqLen,
                                assocRespIe, assocRespLen,
                                WLAN_STATUS_SUCCESS, GFP_KERNEL);
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: connect_result SUCCESS bssid=%pM reqIe=%u "
             "respIe=%u\\n", bssid, assocReqLen, assocRespLen));
    } else {
'''

ROAM_OLD = '''        cfg80211_roamed(ar->arNetDev, &roam_info, GFP_KERNEL);
    }
}
'''

ROAM_NEW = '''        cfg80211_roamed(ar->arNetDev, &roam_info, GFP_KERNEL);
        ar->smeState = SME_CONNECTED;
    }
}
'''

# The two iftype guards sit between the "ASSOCIATED" print and the
# cfg80211_connect_result() call, and both return silently at ATH_DEBUG_INFO.
# An association that never became a connection looked identical to one that
# was dropped here, so promote them.
IFTYPE_ADHOC_OLD = '''        if(NL80211_IFTYPE_ADHOC != ar->wdev->iftype) {
            AR_DEBUG_PRINTF(ATH_DEBUG_INFO,
                            ("%s: ath6k not in ibss mode\\n", __func__));
            return;
        }
    }

    if((INFRA_NETWORK & networkType)) {
        if(NL80211_IFTYPE_STATION != ar->wdev->iftype) {
            AR_DEBUG_PRINTF(ATH_DEBUG_INFO,
                            ("%s: ath6k not in station mode\\n", __func__));
            return;
        }
    }
'''

IFTYPE_ADHOC_NEW = '''        if(NL80211_IFTYPE_ADHOC != ar->wdev->iftype) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 connect: dropped, iftype %u is not ADHOC\\n",
                 ar->wdev->iftype));
            return;
        }
    }

    if((INFRA_NETWORK & networkType)) {
        if(NL80211_IFTYPE_STATION != ar->wdev->iftype) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 connect: dropped, iftype %u is not STATION\\n",
                 ar->wdev->iftype));
            return;
        }
    }
'''

HUNKS = (
    ("connect success SME state", CONNECT_OLD, CONNECT_NEW),
    ("roam SME state", ROAM_OLD, ROAM_NEW),
    ("connect iftype guards", IFTYPE_ADHOC_OLD, IFTYPE_ADHOC_NEW),
)

# --- disconnect event: replace the whole arConnectPending-gated block -----
#
# The span is located by its first and last lines rather than transcribed
# literally, because the body it replaces is a mix of tab- and space-indented
# code inherited from two upstream generations.

BLOCK_HEAD = "    if(true == ar->arConnectPending) {\n"
BLOCK_TAIL = ("    } else {\n"
              "\t    if (reason != DISCONNECT_CMD)\n"
              "\t\t    wmi_disconnect_cmd(ar->arWmi);\n"
              "    }\n"
              "}\n")

BLOCK_NEW = '''    /* N3DS_AR6014_DISCONNECT_NOTIFY: notification is driven by smeState the
     * way mainline ath6kl does it, not by arConnectPending.
     *
     * ar6000_connect_event() clears arConnectPending as soon as the target
     * associates, and the old gate here was `if (true == ar->arConnectPending)`.
     * So after a successful association no disconnect ever reached cfg80211,
     * wdev->connected stayed set forever, and every later cfg80211_connect()
     * failed with -EALREADY before this driver was called at all -- 22 of 22
     * supplicant attempts in the 2026-09-01 capture.  Only
     * cfg80211_disconnected() clears wdev->connected; rdev_disconnect() does
     * not.  The old gate also had no branch for LOST_LINK, AUTH_FAILED,
     * ASSOC_FAILED or BSS_DISCONNECTED, so those were swallowed even while a
     * connect was pending. */

    if (reason == DISCONNECT_CMD && ar->arAutoAuthStage &&
        ar->smeState == SME_CONNECTING &&
        ar->arDot11AuthMode == OPEN_AUTH) {
        /* WEP auto-auth: open-system was refused, so retry the same profile
         * with shared-key auth.  The connect is still pending -- cfg80211
         * must not be told anything yet. */
        struct ar_key *key = &ar->keys[ar->arDefTxKeyIndex];

        if (down_interruptible(&ar->arSem)) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                            ("%s: busy, couldn't get access\\n", __func__));
            return;
        }

        ar->arDot11AuthMode = SHARED_AUTH;
        ar->arAutoAuthStage = AUTH_IDLE;

        wmi_addKey_cmd(ar->arWmi, ar->arDefTxKeyIndex,
                       ar->arPairwiseCrypto,
                       GROUP_USAGE | TX_USAGE,
                       key->key_len,
                       NULL,
                       key->key, KEY_OP_INIT_VAL, NULL,
                       NO_SYNC_WMIFLAG);

        status = wmi_connect_cmd(ar->arWmi,
                                 ar->arNetworkType,
                                 ar->arDot11AuthMode,
                                 ar->arAuthMode,
                                 ar->arPairwiseCrypto,
                                 ar->arPairwiseCryptoLen,
                                 ar->arGroupCrypto,
                                 ar->arGroupCryptoLen,
                                 ar->arSsidLen,
                                 ar->arSsid,
                                 ar->arReqBssid,
                                 ar->arChannelHint,
                                 ar->arConnectCtrlFlags);
        up(&ar->arSem);

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: OPEN->SHARED auto-auth retry status=%d\\n",
             status));
        return;
    }

    /* A disconnect the host did not ask for leaves the target still trying on
     * its own; park it.  Unlike mainline we do not then return and wait for a
     * follow-up DISCONNECT_CMD event before notifying, because NWM does not
     * reliably send one.  Notifying now is safe either way: a follow-up event
     * finds smeState already SME_DISCONNECTED and notifies nothing twice.
     *
     * N3DS_AR6014_NO_NETWORK_HANDOFF: this subsumes the old handoff that ran
     * for NO_NETWORK_AVAIL alone.  That block parked the target and completed
     * the pending cfg80211 request for reason 1 only, so supplicant would not
     * wait out its unrelated ten-second timer; every other reason fell through
     * silently.  The same handoff now runs for every reason, and reports
     * protocolReasonStatus rather than the driver's own reason code, which is
     * what cfg80211_disconnected() is documented to take. */
    if (reason != DISCONNECT_CMD) {
        wmi_disconnect_cmd(ar->arWmi);
    }

    ar->arConnectPending = false;

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: disconnect reason=%u proto=%u sme=%u bssid=%pM\\n",
         reason, protocolReasonStatus, ar->smeState, bssid));

    if (ar->smeState == SME_CONNECTING) {
        cfg80211_connect_result(ar->arNetDev, bssid,
                                NULL, 0, NULL, 0,
                                WLAN_STATUS_UNSPECIFIED_FAILURE,
                                GFP_KERNEL);
    } else if (ar->smeState == SME_CONNECTED) {
        cfg80211_disconnected(ar->arNetDev, protocolReasonStatus,
                              NULL, 0, false, GFP_KERNEL);
    }

    ar->smeState = SME_DISCONNECTED;
}
'''


def patch_cfg(text: str) -> str:
    """Apply the smeState-driven disconnect notification to cfg80211.c text.

    Idempotent: an already-patched tree is returned untouched.
    """
    if MARKER in text:
        return text

    for name, old, new in HUNKS:
        assert text.count(old) == 1, f"{name}: expected exactly one match"
        text = text.replace(old, new)

    assert text.count(BLOCK_HEAD) == 1, "disconnect block head not unique"
    assert text.count(BLOCK_TAIL) == 1, "disconnect block tail not unique"
    start = text.index(BLOCK_HEAD)
    end = text.index(BLOCK_TAIL, start) + len(BLOCK_TAIL)
    old_block = text[start:end]

    # The span really is the arConnectPending-gated notification block.
    assert "NO_NETWORK_AVAIL == reason" in old_block, "wrong span: no NO_NETWORK_AVAIL"
    assert "arDot11AuthMode == SHARED_AUTH" in old_block, "wrong span: no auto-auth"
    assert old_block.count("cfg80211_connect_result") == 2, "wrong span: connect_result count"
    assert old_block.count("cfg80211_disconnected") == 2, "wrong span: disconnected count"

    return text[:start] + BLOCK_NEW + text[end:]


def main() -> None:
    original = CFG.read_text(encoding="utf-8")
    patched = patch_cfg(original)
    if patched == original:
        print("ar6014_cfg80211_disconnect_notify: already applied")
        return
    CFG.write_text(patched, encoding="utf-8")
    print(f"ar6014_cfg80211_disconnect_notify: patched {CFG}")


if __name__ == "__main__":
    main()
