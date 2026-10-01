"""Repair the association-IE handling in ar6k_cfg80211_connect_event().

NWM reports ``assocReqLen = 0`` and ``assocRespLen = 0`` in its
WMI_CONNECT_EVENT.  Stock ath6kl subtracts the fixed-field offsets from each
without checking, so both u8 fields wrap: 0 - 4 = 252 and 0 - 6 = 250.  Those
are exactly the ``reqIe=252 respIe=250`` printed on all ten associations in the
build-#254 capture, identical every time.

Two consequences, both real bugs:

1.  cfg80211_connect_result() is handed 252 + 250 bytes read past the end of a
    20-byte event buffer -- a 502-byte kernel out-of-bounds read.
2.  wpa_supplicant parses that garbage, logs "IEEE 802.11 element parse failed"
    and then "WPA: clearing own WPA/RSN IE", which leaves sm->assoc_wpa_ie
    NULL.  Message 2/4 of the 4-way handshake cannot be built without it, so
    even once the handshake starts it could not complete.

This patch clamps both lengths, passes NULL when the target reports no IEs, and
-- because the supplicant genuinely needs its own assoc-request IE back -- keeps
a copy of the blob cfg80211 handed us in connect() (the same bytes already
forwarded to the target as WMI_SET_APPIE/WMI_FRAME_ASSOC_REQ, i.e. what the AP
actually saw) and reports that as req_ie instead.  It also logs the raw event
header once per association so the next capture says whether the association is
real or synthetic.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux/cfg80211.c"

MARKER = "N3DS_AR6014_ASSOC_IE_FIXUP"

DECL_OLD = r"""static int n3ds_connect_latched = -1;
static int n3ds_connect_current = -1;
"""

DECL_NEW = r"""static int n3ds_connect_latched = -1;
static int n3ds_connect_current = -1;

/* N3DS_AR6014_ASSOC_IE_FIXUP: NWM's WMI_CONNECT_EVENT reports assocReqLen = 0,
 * so the association-request IEs the supplicant needs back never arrive with
 * the event.  Keep the blob cfg80211 gave us in connect() -- it is the same
 * RSN IE we forwarded to the target as WMI_FRAME_ASSOC_REQ, which is what the
 * AP actually saw -- and report that instead.  Without it wpa_supplicant
 * clears sm->assoc_wpa_ie and can never build message 2/4. */
static u8 n3ds_assoc_req_ie[256];
static u16 n3ds_assoc_req_ie_len;
"""

STASH_OLD = r"""    status = wmi_set_appie_cmd(ar->arWmi, WMI_FRAME_ASSOC_REQ,
                               (u16)sme->ie_len, (u8 *)sme->ie);
"""

STASH_NEW = r"""    /* N3DS_AR6014_ASSOC_IE_FIXUP: stash before the command, so the copy exists
     * even if the target rejects the IE. */
    n3ds_assoc_req_ie_len = 0;
    if (sme->ie != NULL && sme->ie_len > 0) {
        n3ds_assoc_req_ie_len = (u16)min_t(size_t, sme->ie_len,
                                           sizeof(n3ds_assoc_req_ie));
        memcpy(n3ds_assoc_req_ie, sme->ie, n3ds_assoc_req_ie_len);
    }

    status = wmi_set_appie_cmd(ar->arWmi, WMI_FRAME_ASSOC_REQ,
                               (u16)sme->ie_len, (u8 *)sme->ie);
"""

CLAMP_OLD = r"""    assocReqLen -= assocReqIeOffset;
    assocRespLen -= assocRespIeOffset;
"""

CLAMP_NEW = r"""    /* N3DS_AR6014_ASSOC_IE_FIXUP: log the target's own numbers before they are
     * touched.  beaconInterval reads back the AP's beacon period (~100 TU) on a
     * real association and 0 on a synthetic one, which is the cheapest test of
     * whether NWM actually joined the BSS. */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: nwm evt chan=%u nettype=%u listen=%u beacon=%u "
         "beaconIeLen=%u rawReqLen=%u rawRespLen=%u\n",
         channel, (unsigned int)networkType, listenInterval, beaconInterval,
         beaconIeLen, assocReqLen, assocRespLen));

    /* N3DS_AR6014_ASSOC_IE_FIXUP: stock ath6kl subtracts the fixed-field
     * offsets unconditionally.  NWM reports both lengths as 0, so both u8
     * fields wrapped to 252 and 250 and cfg80211 was handed 502 bytes read off
     * the end of the event buffer.  Clamp, and report no IEs rather than
     * garbage ones. */
    if (assocReqLen >= assocReqIeOffset) {
        assocReqLen -= assocReqIeOffset;
    } else {
        assocReqLen = 0;
        assocReqIe = NULL;
    }
    if (assocRespLen >= assocRespIeOffset) {
        assocRespLen -= assocRespIeOffset;
    } else {
        assocRespLen = 0;
        assocRespIe = NULL;
    }
    if (assocReqIe == NULL && n3ds_assoc_req_ie_len > 0) {
        assocReqIe = n3ds_assoc_req_ie;
        assocReqLen = (u8)min_t(u16, n3ds_assoc_req_ie_len, 255);
    }
"""

HUNKS = (
    ("assoc-req-IE keeper declaration", DECL_OLD, DECL_NEW),
    ("stash the assoc-request IE in connect()", STASH_OLD, STASH_NEW),
    ("clamp the connect-event IE lengths", CLAMP_OLD, CLAMP_NEW),
)


def patch_cfg80211(text):
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, "%s: expected exactly one anchor, found %d" % (
            name,
            text.count(old),
        )
        text = text.replace(old, new)
    return text


def main():
    text = TARGET.read_text()
    patched = patch_cfg80211(text)
    if patched == text:
        print("patch_ar6014_assoc_ie_fixup: already applied")
        return
    TARGET.write_text(patched)
    print("patch_ar6014_assoc_ie_fixup: applied to %s" % TARGET)


if __name__ == "__main__":
    main()
