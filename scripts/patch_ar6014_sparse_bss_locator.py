#!/usr/bin/env python3
"""Replace the guessed AR6014 BSS window with a bounded whole-RAM locator.

Nintendo's firmware keeps complete beacon/probe frames in target RAM but the
table address is not an ABI.  Reading every byte takes about 144 seconds on a
3DS.  The table slots are 568 bytes apart and naturally aligned, so probing one
word every 32 bytes finds a frame in the observed six-record table using the
same 4096 diagnostic reads as the former guessed 16 KiB window.  Once found,
normal narrow contiguous reads recover all records around the real table.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


DRV = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c")


text = DRV.read_text()

old_constants = """#define AR6014_HARVEST_CHUNK         4096
#define AR6014_HARVEST_HOLDOFF_MS    3000
/* N3DS_AR6014_TARGETED_BSS_HARVEST: decoded Nintendo scan nodes have been
 * observed around 0x53c6a0 (offset 0x1c6a0 in this 128 KiB RAM window).  A
 * full diagnostic sweep costs ~144 seconds on real 3DS hardware; this 16 KiB
 * window covers the firmware's approximately 8 KiB fixed-stride BSS table
 * and completes before nl80211's scan timeout. */
#define AR6014_HARVEST_BOOT_LO       0x0001a000
#define AR6014_HARVEST_BOOT_HI       0x0001e000
#define AR6014_HARVEST_MARGIN        (4 * 1024)
#define AR6014_HARVEST_NARROW_RUNS   32
"""
new_constants = """#define AR6014_HARVEST_CHUNK         4096
#define AR6014_HARVEST_HOLDOFF_MS    3000
/* N3DS_AR6014_SPARSE_BSS_LOCATOR: the table address is firmware-private and
 * cannot be borrowed from a different hardware capture.  Probe one aligned
 * word per 32 target bytes across the complete 128 KiB RAM window.  Nintendo's
 * 568-byte slot stride advances by 24 modulo 32, so an aligned four-record run
 * necessarily crosses a probe.  This costs the same 4096 diagnostic reads as
 * the old guessed 16 KiB contiguous window, then narrows around real frames. */
#define AR6014_LOCATOR_STRIDE        32
#define AR6014_LOCATOR_FRAME_READ    448
#define AR6014_LOCATOR_MAX_HINTS     64
#define AR6014_HARVEST_MARGIN        (4 * 1024)
#define AR6014_HARVEST_NARROW_RUNS   32
"""
if old_constants not in text:
    if "N3DS_AR6014_SPARSE_BSS_LOCATOR" in text:
        print("patch_ar6014_sparse_bss_locator: already applied")
        raise SystemExit(0)
    raise SystemExit("targeted-harvest constants not found")
text = text.replace(old_constants, new_constants, 1)

old_globals = """static u32 ar6014_harvest_hi;
static int ar6014_harvest_narrow;
static struct ar6014_bss_ent ar6014_bss_cache[AR6014_CACHE_MAX];
"""
new_globals = """static u32 ar6014_harvest_hi;
static int ar6014_harvest_narrow;
/* Advance by one word only after an empty locator pass.  Phase zero matches
 * the observed Nintendo table alignment; the remaining phases make the
 * locator robust to a different four-byte-aligned firmware allocation. */
static u32 ar6014_locator_phase;
static struct ar6014_bss_ent ar6014_bss_cache[AR6014_CACHE_MAX];
"""
if text.count(old_globals) != 1:
    raise SystemExit("harvest globals hunk not found exactly once")
text = text.replace(old_globals, new_globals, 1)

old_function = text[text.index("static int\nar6014_harvest_bss_sync(struct ar6_softc *ar)\n{"):text.index("\nstatic int\nar6002_nwm_write_blob", text.index("static int\nar6014_harvest_bss_sync(struct ar6_softc *ar)\n{"))]

new_function = r'''static int
ar6014_parse_bss_frame(u8 *frame, int avail, u32 target_offset,
                       u32 *seen_lo, u32 *seen_hi)
{
    u8 *ie, *p, *end;
    u8 frame_control, frame_type, ssid_len;
    u16 channel_mhz = 0;
    int body_len;

    if (avail < AR6014_MGMT_HDR_LEN + AR6014_FIXED_LEN + 2)
        return 0;
    frame_control = frame[0];
    if ((frame_control != 0x80 && frame_control != 0x50) || frame[1])
        return 0;
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
    while (p + 2 <= end && p + 2 + p[1] <= end) {
        if (p[0] == IEEE80211_ELEMID_DSPARMS && p[1] >= 1)
            channel_mhz = p[2] == 14 ? 2484 : 2407 + 5 * p[2];
        else if (p[0] == 61 && p[1] >= 1) /* HT Operation primary channel */
            channel_mhz = p[2] == 14 ? 2484 : 2407 + 5 * p[2];
        p += 2 + p[1];
    }
    body_len = AR6014_FIXED_LEN + (int)(p - ie);
    if (body_len <= AR6014_FIXED_LEN || !channel_mhz)
        return 0;

    frame_type = frame_control == 0x80 ? BEACON_FTYPE : PROBERESP_FTYPE;
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
    u32 offset, lo = 0, hi = 0;
    u32 seen_lo = AR6014_RAM_SIZE, seen_hi = 0;
    int i, found = 0, injected = 0;
    bool locator;

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
    locator = !(ar6014_harvest_hi > ar6014_harvest_lo &&
                ar6014_harvest_narrow > 0);

    if (locator) {
        u32 probe_word;
        int hints = 0;

        /* Do not hold cfg80211 hostage to a guessed table address.  Four
         * bytes every 32 bytes covers all RAM with 1/8 of a blind sweep. */
        for (offset = ar6014_locator_phase;
             offset + sizeof(probe_word) <= AR6014_RAM_SIZE;
             offset += AR6014_LOCATOR_STRIDE) {
            u8 *probe = (u8 *)&probe_word;
            u32 avail;

            if (ar6000_ReadDataDiag(ar->arHifDevice, AR6014_HI + offset,
                                    probe, sizeof(probe_word)) != 0)
                break;
            if ((probe[0] != 0x80 && probe[0] != 0x50) || probe[1])
                continue;
            if (++hints > AR6014_LOCATOR_MAX_HINTS)
                break;

            /* Reject code/data false positives after only the fixed header;
             * fetch the bounded frame body only for an SSID-shaped record. */
            avail = AR6014_RAM_SIZE - offset;
            if (avail > AR6014_MGMT_HDR_LEN + AR6014_FIXED_LEN + 2)
                avail = AR6014_MGMT_HDR_LEN + AR6014_FIXED_LEN + 2;
            if (ar6000_ReadDataDiag(ar->arHifDevice, AR6014_HI + offset,
                                    window, avail) != 0)
                continue;
            if (window[AR6014_MGMT_HDR_LEN + AR6014_FIXED_LEN] !=
                    IEEE80211_ELEMID_SSID ||
                !window[AR6014_MGMT_HDR_LEN + AR6014_FIXED_LEN + 1] ||
                window[AR6014_MGMT_HDR_LEN + AR6014_FIXED_LEN + 1] >
                    IEEE80211_NWID_LEN)
                continue;

            avail = AR6014_RAM_SIZE - offset;
            if (avail > AR6014_LOCATOR_FRAME_READ)
                avail = AR6014_LOCATOR_FRAME_READ;
            if (ar6000_ReadDataDiag(ar->arHifDevice, AR6014_HI + offset,
                                    window, avail) != 0)
                continue;
            found += ar6014_parse_bss_frame(window, avail, offset,
                                             &seen_lo, &seen_hi);
        }
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: locator phase=0x%x hints=%d frames=%d\n",
             ar6014_locator_phase, hints, found));
        if (!found)
            ar6014_locator_phase =
                (ar6014_locator_phase + 4) &
                (AR6014_LOCATOR_STRIDE - 1);
    } else {
        lo = ar6014_harvest_lo > AR6014_HARVEST_MARGIN ?
             ar6014_harvest_lo - AR6014_HARVEST_MARGIN : 0;
        hi = ar6014_harvest_hi + AR6014_HARVEST_MARGIN;
        ar6014_harvest_narrow--;
        lo &= ~(u32)(AR6014_HARVEST_CHUNK - 1);
        hi = (hi + AR6014_HARVEST_CHUNK - 1) &
             ~(u32)(AR6014_HARVEST_CHUNK - 1);
        if (hi > AR6014_RAM_SIZE)
            hi = AR6014_RAM_SIZE;

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
            if (ar6014_parse_bss_frame(window + i, hi - i, i,
                                        &seen_lo, &seen_hi)) {
                found++;
                i += AR6014_MGMT_HDR_LEN;
            }
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

        if (wmi_inject_bssinfo(ar->arWmi, entry->channel, -50,
                               entry->bssid, entry->frame_type,
                               entry->body, entry->body_len) == 0)
            injected++;
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 scan: swept=%d cache=%d injected=%d mode=%s range=0x%x..0x%x\n",
         found, ar6014_bss_cache_count, injected,
         locator ? "locator" : "narrow", lo, hi));
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

text = text.replace(old_function, new_function, 1)
DRV.write_text(text)
print("patch_ar6014_sparse_bss_locator: bounded whole-RAM locator installed")
