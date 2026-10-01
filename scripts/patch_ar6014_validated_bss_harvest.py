#!/usr/bin/env python3
"""Replace temporal sparse probing with the hardware-measured BSS window."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


DRV = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c")
MARKER = "N3DS_AR6014_VALIDATED_TARGET_BSS"
QUEUE_MARKER = "N3DS_AR6014_HARVEST_QUEUE_SERIALIZATION"
SNAPSHOT_MARKER = "N3DS_AR6014_HARVEST_SNAPSHOT_SERIALIZATION"
TRUNCATED_IE_MARKER = "N3DS_AR6014_TRUNCATED_IE_FAIL_CLOSED"


QUEUE_OLD = r'''static bool
ar6014_queue_harvest(struct ar6_softc *ar, int status)
{
    ar6014_harvest_ar = ar;
    ar6014_harvest_status = status;
    if (atomic_cmpxchg(&ar6014_harvest_busy, 0, 1) != 0)
        return false;
    schedule_work(&ar6014_harvest_work);
    return true;
}
'''


QUEUE_NEW = r'''static bool
ar6014_queue_harvest(struct ar6_softc *ar, int status)
{
    /* N3DS_AR6014_HARVEST_QUEUE_SERIALIZATION:
     * N3DS_AR6014_HARVEST_SNAPSHOT_SERIALIZATION: claim the single worker
     * before publishing its owner and completion status.  A scan completion
     * that races an active sweep must not overwrite the globals consumed by
     * that sweep and then return false.  Only the admitted completion copies
     * the pending direct-BSSID list into the active harvest snapshot. */
    if (atomic_cmpxchg(&ar6014_harvest_busy, 0, 1) != 0)
        return false;
    ar6014_harvest_ar = ar;
    ar6014_harvest_status = status;
    ar6014_harvest_direct_bss =
        wmi_n3ds_take_direct_bss_count(ar->arWmi);
    schedule_work(&ar6014_harvest_work);
    return true;
}
'''


QUEUE_CURRENT = r'''static bool
ar6014_queue_harvest(struct ar6_softc *ar, int status)
{
    /* N3DS_AR6014_HARVEST_QUEUE_SERIALIZATION: claim the single worker
     * before publishing its owner and completion status.  A scan completion
     * that races an active sweep must not overwrite the globals consumed by
     * that sweep and then return false. */
    if (atomic_cmpxchg(&ar6014_harvest_busy, 0, 1) != 0)
        return false;
    ar6014_harvest_ar = ar;
    ar6014_harvest_status = status;
    schedule_work(&ar6014_harvest_work);
    return true;
}
'''


CONSTANTS = r'''#define AR6014_HARVEST_CHUNK         4096
#define AR6014_HARVEST_HOLDOFF_MS    3000
/* N3DS_AR6014_VALIDATED_TARGET_BSS: physical logs from this exact Nintendo
 * type-4 image recovered real beacon nodes around target 0x53c6a0.  Read the
 * containing 16 KiB on every completed RF scan: sparse phases were temporal
 * and locked onto database bytes at 0x53fea8 before a real beacon arrived. */
#define AR6014_HARVEST_BOOT_LO       0x00010000
#define AR6014_HARVEST_BOOT_HI       0x0001fe00
#define AR6014_HARVEST_MARGIN        (4 * 1024)
#define AR6014_HARVEST_NARROW_RUNS   32
'''


FUNCTION = r'''static int
ar6014_security_suite_oui(const u8 *suite, int is_wpa)
{
    return suite[0] == 0 &&
           suite[1] == (is_wpa ? 0x50 : 0x0f) &&
           suite[2] == (is_wpa ? 0xf2 : 0xac);
}

static int
ar6014_valid_security_ie(const u8 *ie, int ie_len, int is_wpa)
{
    int pos, count, i;

    if (is_wpa) {
        if (ie_len < 4 || ie[0] != 0x00 || ie[1] != 0x50 ||
            ie[2] != 0xf2 || ie[3] != 0x01)
            return 0;
        pos = 4;
    } else {
        pos = 0;
    }
    if (ie_len - pos < 2 + 4 + 2)
        return 0;
    if (ie[pos] != 1 || ie[pos + 1] != 0)
        return 0;
    pos += 2;
    if (!ar6014_security_suite_oui(ie + pos, is_wpa))
        return 0;
    pos += 4;

    if (ie_len - pos < 2)
        return 0;
    count = ie[pos] | (ie[pos + 1] << 8);
    if (!count || count > (ie_len - pos - 2) / 4)
        return 0;
    pos += 2;
    for (i = 0; i < count; i++) {
        if (!ar6014_security_suite_oui(ie + pos, is_wpa))
            return 0;
        pos += 4;
    }

    if (ie_len - pos < 2)
        return 0;
    count = ie[pos] | (ie[pos + 1] << 8);
    if (!count || count > (ie_len - pos - 2) / 4)
        return 0;
    pos += 2;
    for (i = 0; i < count; i++) {
        if (!ar6014_security_suite_oui(ie + pos, is_wpa))
            return 0;
        pos += 4;
    }

    /* WPA vendor IEs end after the AKM list.  RSN permits capabilities,
     * PMKIDs, and the optional group-management cipher in that order. */
    if (is_wpa)
        return pos == ie_len;
    if (pos == ie_len)
        return 1;
    if (ie_len - pos < 2)
        return 0;
    pos += 2;
    if (pos == ie_len)
        return 1;
    if (ie_len - pos < 2)
        return 0;
    count = ie[pos] | (ie[pos + 1] << 8);
    if (count > (ie_len - pos - 2) / 16)
        return 0;
    pos += 2 + count * 16;
    if (pos == ie_len)
        return 1;
    if (ie_len - pos != 4 ||
        !ar6014_security_suite_oui(ie + pos, is_wpa))
        return 0;
    return 1;
}

extern int wmi_n3ds_direct_bss_seen(struct wmi_t *wmip,
                                      const u8 *bssid);

static int
ar6014_parse_bss_frame(struct wmi_t *wmip, u8 *frame, int avail, u32 target_offset,
                       u32 *seen_lo, u32 *seen_hi)
{
    u8 *ie, *p, *end;
    u8 frame_control, frame_type, ssid_len;
    u16 channel_mhz = 0;
    u16 beacon_interval, capability;
    int body_len;
    int privacy, has_security_ie = 0;
    bool rates = false;

    if (avail < AR6014_MGMT_HDR_LEN + AR6014_FIXED_LEN + 2)
        return 0;
    frame_control = frame[0];
    if ((frame_control != 0x80 && frame_control != 0x50) || (frame[1] & 0x03))
        return 0;

    /* N3DS_AR6014_BSS_CHANNEL_VALIDATION: validate the complete frame shape,
     * not just a channel-looking IE.  A valid infrastructure beacon/probe
     * response has transmitter == BSSID,
     * and the BSSID must be a nonzero unicast address.  This rejects the
     * 52:45:00:44:00:00 database-text false positive from the latest trace. */
    if (memcmp(frame + 10, frame + 16, ETH_ALEN) ||
        (frame[16] & 0x01) ||
        !(frame[16] | frame[17] | frame[18] |
          frame[19] | frame[20] | frame[21]))
        return 0;
    if (frame_control == 0x80 &&
        memcmp(frame + 4, "\xff\xff\xff\xff\xff\xff", ETH_ALEN))
        return 0;

    memcpy(&beacon_interval, frame + AR6014_MGMT_HDR_LEN + 8,
           sizeof(beacon_interval));
    if (!beacon_interval || beacon_interval > 10000)
        return 0;
    capability = frame[AR6014_MGMT_HDR_LEN + 10] |
                 (frame[AR6014_MGMT_HDR_LEN + 11] << 8);
    privacy = capability & 0x0010;

    ie = frame + AR6014_MGMT_HDR_LEN + AR6014_FIXED_LEN;
    if (ie[0] != IEEE80211_ELEMID_SSID)
        return 0;
    ssid_len = ie[1];
    if (!ssid_len || ssid_len > IEEE80211_NWID_LEN)
        return 0;

    end = frame + avail;
    if (ie + AR6014_CACHE_BODY - AR6014_FIXED_LEN < end)
        end = ie + AR6014_CACHE_BODY - AR6014_FIXED_LEN;
    p = ie;
    while (p + 2 <= end) {
        if (p + 2 + p[1] > end) {
            /* N3DS_AR6014_TRUNCATED_IE_FAIL_CLOSED: without a complete
             * element walk, bytes after this element cannot prove that an
             * open result has no hidden WPA/RSN IE.  Reject every truncated
             * element, not only elements whose ID is already security-like. */
            return 0;
        }
        if ((p[0] == IEEE80211_ELEMID_RATES || p[0] == IEEE80211_ELEMID_XRATES) &&
            p[1] >= 1 && p[1] <= 16)
            rates = true;
        else if (p[0] == IEEE80211_ELEMID_DSPARMS &&
                 p[1] >= 1 && p[2] >= 1 && p[2] <= 14)
            channel_mhz = p[2] == 14 ? 2484 : 2407 + 5 * p[2];
        else if (p[0] == 61 && p[1] >= 1 &&
                 p[2] >= 1 && p[2] <= 14)
            channel_mhz = p[2] == 14 ? 2484 : 2407 + 5 * p[2];
        else if (p[0] == IEEE80211_ELEMID_RSN) {
            /* N3DS_AR6014_SECURITY_VALIDATION: malformed RSN data must not
             * become a scan result that supplicant later treats as open. */
            if (!ar6014_valid_security_ie(p + 2, p[1], 0))
                return 0;
            has_security_ie = 1;
        } else if (p[0] == IEEE80211_ELEMID_VENDOR && p[1] >= 4 &&
                   p[2] == 0x00 && p[3] == 0x50 && p[4] == 0xf2 &&
                   p[5] == 0x01) {
            if (!ar6014_valid_security_ie(p + 2, p[1], 1))
                return 0;
            has_security_ie = 1;
        }
        p += 2 + p[1];
    }
    /* Privacy clear + WPA/RSN is internally inconsistent.  Privacy set with
     * no WPA/RSN remains a legacy protected (for example WEP) result; its
     * capability bit is preserved in the body and it is never an open AP. */
    if (!privacy && has_security_ie)
        return 0;
    body_len = AR6014_FIXED_LEN + (int)(p - ie);
    if (body_len <= AR6014_FIXED_LEN || !channel_mhz || !rates)
        return 0;

    frame_type = frame_control == 0x80 ? BEACON_FTYPE : PROBERESP_FTYPE;
    /* A direct WMI event has a firmware-supplied length and has already
     * installed the authoritative node for this BSSID.  Keep scanning RAM so
     * fallback-only BSSIDs are still recovered, but never let a guessed frame
     * replace the exact node or refresh its fallback cache entry. */
    if (!wmi_n3ds_direct_bss_seen(wmip, frame + 16))
        ar6014_cache_put(frame + 16, channel_mhz, frame_type,
                         frame + AR6014_MGMT_HDR_LEN, body_len);
    if (target_offset < *seen_lo)
        *seen_lo = target_offset;
    if (target_offset + AR6014_MGMT_HDR_LEN + body_len > *seen_hi)
        *seen_hi = target_offset + AR6014_MGMT_HDR_LEN + body_len;
    return 1;
}

static int
ar6014_harvest_bss_sync(struct ar6_softc *ar)
{
    static unsigned long last_jiffies;
    static int last_injected;
    u8 *window;
    u32 offset, lo, hi;
    u32 seen_lo = AR6014_RAM_SIZE, seen_hi = 0;
    int i, found = 0, injected = 0, direct_skipped = 0;

    if (!ar->arHifDevice || !ar->arWmi)
        return 0;
    if (last_jiffies &&
        time_before(jiffies, last_jiffies +
                    msecs_to_jiffies(AR6014_HARVEST_HOLDOFF_MS)))
        return last_injected;

    if (!ar6014_harvest_window) {
        ar6014_harvest_window = vmalloc(AR6014_RAM_SIZE);
        if (!ar6014_harvest_window)
            return 0;
    }
    window = ar6014_harvest_window;
    lo = AR6014_HARVEST_BOOT_LO;
    hi = AR6014_HARVEST_BOOT_HI;

    for (offset = lo; offset < hi; offset += AR6014_HARVEST_CHUNK) {
        if (ar6000_ReadDataDiag(ar->arHifDevice, AR6014_HI + offset,
                                window + offset,
                                AR6014_HARVEST_CHUNK) != 0) {
            hi = offset;
            break;
        }
    }
    for (i = lo;
         i + AR6014_MGMT_HDR_LEN + AR6014_FIXED_LEN + 2 < (int)hi;
         i++) {
        if (ar6014_parse_bss_frame(ar->arWmi, window + i, hi - i, i,
                                    &seen_lo, &seen_hi)) {
            found++;
            i += AR6014_MGMT_HDR_LEN;
        }
    }

    if (found) {
        ar6014_harvest_lo = seen_lo;
        ar6014_harvest_hi = seen_hi;
        ar6014_harvest_narrow = AR6014_HARVEST_NARROW_RUNS;
    } else {
        ar6014_harvest_lo = 0;
        ar6014_harvest_hi = 0;
        ar6014_harvest_narrow = 0;
    }

    for (i = 0; i < ar6014_bss_cache_count; i++) {
        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];
        int status;
        if (wmi_n3ds_direct_bss_seen(ar->arWmi, entry->bssid)) {
            direct_skipped++;
            continue;
        }
        status = wmi_inject_bssinfo(ar->arWmi, entry->channel, -50,
                                    entry->bssid, entry->frame_type,
                                    entry->body, entry->body_len);
        if (status == 0)
            injected++;
        else
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 scan: reject cached bssid=%pM status=%d\n",
                 entry->bssid, status));
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 scan: validated swept=%d cache=%d injected=%d direct_skipped=%d range=0x%x..0x%x\n",
         found, ar6014_bss_cache_count, injected, direct_skipped, lo, hi));
    if (found)
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: result span=0x%x..0x%x target=0x%x..0x%x\n",
             seen_lo, seen_hi, AR6014_HI + seen_lo,
             AR6014_HI + seen_hi));
    last_jiffies = jiffies;
    last_injected = injected;
    return injected;
}
'''


def install_security_parser(text: str) -> str:
    # A previous revision already carried the broad security marker but
    # stopped at generic truncated IEs.  Treat only the explicit fail-closed
    # marker and exactly one helper definition as current.  This also repairs
    # a partially migrated tree where the old helpers precede a new parser.
    suite_name = "static int\nar6014_security_suite_oui("
    valid_name = "static int\nar6014_valid_security_ie("
    if (
        TRUNCATED_IE_MARKER in text
        and text.count(suite_name) == 1
        and text.count(valid_name) == 1
    ):
        return text
    func_start = text.index("static int\nar6014_parse_bss_frame(")
    func_end = text.index("\nstatic int\nar6002_nwm_write_blob", func_start)
    block_start = text.rfind(
        "extern int wmi_n3ds_direct_bss_seen(struct wmi_t *wmip,",
        0,
        func_start,
    )
    helper_starts = [
        pos for pos in (
            text.find(suite_name, 0, func_start),
            text.find(valid_name, 0, func_start),
        ) if pos >= 0
    ]
    if helper_starts:
        block_start = min(helper_starts + ([block_start] if block_start >= 0 else []))
    elif block_start < 0:
        block_start = func_start
    return text[:block_start] + FUNCTION + text[func_end:]


def repair_harvest_queue(text: str) -> tuple[str, bool]:
    """Publish deferred-harvest ownership only after the busy claim."""
    if SNAPSHOT_MARKER in text:
        return text, False
    if QUEUE_CURRENT in text:
        text = text.replace(QUEUE_CURRENT, QUEUE_NEW, 1)
        changed = True
    elif QUEUE_OLD in text:
        text = text.replace(QUEUE_OLD, QUEUE_NEW, 1)
        changed = True
    else:
        if "ar6014_queue_harvest(struct ar6_softc *ar, int status)" in text:
            raise SystemExit("harvest queue: unsupported serialization shape")
        return text, False
    if "static u32 ar6014_harvest_direct_bss;" not in text:
        anchor = "static int ar6014_harvest_status;\n"
        if anchor not in text:
            raise SystemExit("harvest queue: snapshot counter anchor not found")
        text = text.replace(
            anchor,
            anchor + "static u32 ar6014_harvest_direct_bss;\n",
            1,
        )
    return text, changed


def main() -> None:
    text = DRV.read_text()
    text, queue_repaired = repair_harvest_queue(text)
    security_installed = False
    suite_name = "static int\nar6014_security_suite_oui("
    valid_name = "static int\nar6014_valid_security_ie("
    if (
        TRUNCATED_IE_MARKER not in text
        or text.count(suite_name) != 1
        or text.count(valid_name) != 1
    ):
        if "static int\nar6014_parse_bss_frame(" not in text:
            raise SystemExit("security validation: parser anchor not found")
        old_text = text
        text = install_security_parser(text)
        security_installed = text != old_text
    if "AR6014_HARVEST_BOOT_LO       0x00010000" in text and "IEEE80211_ELEMID_XRATES" in text and "(frame[1] & 0x03)" in text:
        if security_installed or queue_repaired:
            DRV.write_text(text)
            if security_installed and queue_repaired:
                print("patch_ar6014_validated_bss_harvest: security validation and queue serialization installed")
            elif security_installed:
                print("patch_ar6014_validated_bss_harvest: security validation installed")
            else:
                print("patch_ar6014_validated_bss_harvest: queue serialization installed")
            return
        print("patch_ar6014_validated_bss_harvest: already applied")
        return
    if MARKER in text:
        text = text.replace(
            "#define AR6014_HARVEST_BOOT_LO       0x0001a000\n#define AR6014_HARVEST_BOOT_HI       0x0001e000",
            "#define AR6014_HARVEST_BOOT_LO       0x00010000\n#define AR6014_HARVEST_BOOT_HI       0x0001fe00",
            1,
        )
        text = text.replace(
            "if ((frame_control != 0x80 && frame_control != 0x50) || frame[1])",
            "if ((frame_control != 0x80 && frame_control != 0x50) || (frame[1] & 0x03))",
            1,
        )
        text = text.replace(
            "IEEE80211_ELEMID_EXTRATES",
            "IEEE80211_ELEMID_XRATES",
            1,
        )
        text = text.replace(
            "if (p[0] == IEEE80211_ELEMID_RATES && p[1] >= 1 && p[1] <= 8)",
            "if ((p[0] == IEEE80211_ELEMID_RATES || p[0] == IEEE80211_ELEMID_XRATES) &&\n            p[1] >= 1 && p[1] <= 16)",
            1,
        )
        DRV.write_text(text)
        print("patch_ar6014_validated_bss_harvest: updated to 64 KiB harvest window")
        return

    const_start = text.index("#define AR6014_HARVEST_CHUNK")
    const_end = text.index("#define AR6014_MGMT_HDR_LEN", const_start)
    text = text[:const_start] + CONSTANTS + text[const_end:]
    text = text.replace("static u32 ar6014_locator_phase;\n", "", 1)
    func_start = text.index("static int\nar6014_parse_bss_frame(")
    func_end = text.index("\nstatic int\nar6002_nwm_write_blob", func_start)
    text = text[:func_start] + FUNCTION + text[func_end:]
    if "AR6014_LOCATOR_" in text or "ar6014_locator_phase" in text:
        raise SystemExit("sparse locator survived validated-harvest replacement")
    DRV.write_text(text)
    print("patch_ar6014_validated_bss_harvest: hardware window installed")


if __name__ == "__main__":
    main()
