#!/usr/bin/env python3
"""Honor Nintendo's probed-SSID slot ABI and evict stale harvested BSSes."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")
DRV = ROOT / "drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
CFG = ROOT / "drivers/staging/ath6k_legacy/os/linux/cfg80211.c"
MARKER = "N3DS_NWM_PROBED_SSID_SLOTS"
FRAME_IDENTITY_MARKER = "N3DS_AR6014_FRAME_IDENTITY"
TOMBSTONE_MARKER = "N3DS_AR6014_CACHE_TOMBSTONE"


FRAME_IDENTITY_HELPER = '''/* N3DS_AR6014_FRAME_IDENTITY: the RAM sweep can expose the
 * same old beacon body on every scan.  The 8-byte 802.11 TSF at body[0..7]
 * is the freshness identity; body changes with an identical TSF must not
 * revive a stale entry. */
static int
ar6014_cache_same_tsf(const struct ar6014_bss_ent *entry,
                      const u8 *body, int body_len)
{
    if (entry->body_len < 8 || body_len < 8)
        return 0;
    return memcmp(entry->body, body, 8) == 0;
}
'''


FRAME_IDENTITY_OLD_HELPER = '''/* N3DS_AR6014_FRAME_IDENTITY: the RAM sweep can expose the
 * same old beacon body on every scan.  Compare the 8-byte 802.11 TSF at
 * body[0..7] and the complete captured body before refreshing freshness; an
 * unchanged snapshot must expire even when the sweep rediscovers it. */
static int
ar6014_cache_same_frame(const struct ar6014_bss_ent *entry,
                        u16 channel, u8 frame_type,
                        const u8 *body, int body_len)
{
    if (entry->channel != channel || entry->frame_type != frame_type ||
        entry->body_len < 8 || body_len < 8 ||
        memcmp(entry->body, body, 8) ||
        entry->body_len != body_len)
        return 0;
    return memcmp(entry->body, body, body_len) == 0;
}
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source anchor, found {count}")
    return text.replace(old, new, 1)


def patch_cache(text: str) -> str:
    if "last_seen_generation" not in text:
        text = replace_once(
            text,
            "#define AR6014_CACHE_MAX             32\n",
            """/* The #179 capture reached 32 entries and then silently discarded every
 * newly discovered AP.  Keep a session cache large enough for the measured
 * environment and replace its stalest entry if it still fills. */
#define AR6014_CACHE_MAX             64
""",
            "cache capacity",
        )
        text = replace_once(
            text,
            """    u16 body_len;
    u8 body[AR6014_CACHE_BODY];
};
""",
            """    u16 body_len;
    u32 last_seen_generation;
    u8 body[AR6014_CACHE_BODY];
};
""",
            "cache generation field",
        )
        text = replace_once(
            text,
            """static struct ar6014_bss_ent ar6014_bss_cache[AR6014_CACHE_MAX];
static int ar6014_bss_cache_count;
""",
            """static struct ar6014_bss_ent ar6014_bss_cache[AR6014_CACHE_MAX];
static int ar6014_bss_cache_count;
static u32 ar6014_cache_generation;
""",
            "cache generation global",
        )
        old = '''static void
ar6014_cache_put(const u8 *bssid, u16 channel, u8 frame_type,
                 const u8 *body, int body_len)
{
    int i;

    if (body_len <= 0 || body_len > AR6014_CACHE_BODY)
        return;
    for (i = 0; i < ar6014_bss_cache_count; i++) {
        if (!memcmp(ar6014_bss_cache[i].bssid, bssid, ETH_ALEN))
            break;
    }
    if (i == ar6014_bss_cache_count) {
        if (ar6014_bss_cache_count >= AR6014_CACHE_MAX)
            return;
        ar6014_bss_cache_count++;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: AP %pM channel=%u\\n", bssid, channel));
    }
    memcpy(ar6014_bss_cache[i].bssid, bssid, ETH_ALEN);
    ar6014_bss_cache[i].channel = channel;
    ar6014_bss_cache[i].frame_type = frame_type;
    ar6014_bss_cache[i].body_len = body_len;
    memcpy(ar6014_bss_cache[i].body, body, body_len);
}
'''
        new = '''static void
ar6014_cache_put(const u8 *bssid, u16 channel, u8 frame_type,
                 const u8 *body, int body_len)
{
    int i;

    if (body_len <= 0 || body_len > AR6014_CACHE_BODY)
        return;
    for (i = 0; i < ar6014_bss_cache_count; i++) {
        if (!memcmp(ar6014_bss_cache[i].bssid, bssid, ETH_ALEN))
            break;
    }
    if (i == ar6014_bss_cache_count) {
        if (ar6014_bss_cache_count < AR6014_CACHE_MAX) {
            ar6014_bss_cache_count++;
        } else {
            int candidate;

            i = 0;
            for (candidate = 1; candidate < AR6014_CACHE_MAX;
                 candidate++) {
                if (ar6014_bss_cache[candidate].last_seen_generation <
                    ar6014_bss_cache[i].last_seen_generation)
                    i = candidate;
            }
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 scan: evict stale %pM for %pM\\n",
                 ar6014_bss_cache[i].bssid, bssid));
        }
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: AP %pM channel=%u\\n", bssid, channel));
    }
    memcpy(ar6014_bss_cache[i].bssid, bssid, ETH_ALEN);
    ar6014_bss_cache[i].channel = channel;
    ar6014_bss_cache[i].frame_type = frame_type;
    ar6014_bss_cache[i].body_len = body_len;
    ar6014_bss_cache[i].last_seen_generation = ar6014_cache_generation;
    memcpy(ar6014_bss_cache[i].body, body, body_len);
}
'''
        text = replace_once(text, old, new, "cache insertion")

    if "N3DS_AR6014_CACHE_FRESHNESS" not in text:
        text = replace_once(
            text,
            "static u32 ar6014_cache_generation;\n",
            """static u32 ar6014_cache_generation;

/* N3DS_AR6014_CACHE_FRESHNESS: a harvested BSS is a recovery hint, not a
 * permanent scan result.  Advance the generation once per completed scan and
 * retain a fallback entry for only two later scans.  Direct WMI events are
 * merged separately and never refresh or overwrite this cache. */
#define AR6014_CACHE_FRESH_SCANS     2

static void
ar6014_cache_begin_scan(void)
{
    ar6014_cache_generation++;
    if (!ar6014_cache_generation)
        ar6014_cache_generation++;
}

static void
ar6014_cache_prune(void)
{
    int i = 0;

    while (i < ar6014_bss_cache_count) {
        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];
        u32 age = ar6014_cache_generation - entry->last_seen_generation;

        if (!entry->last_seen_generation || age > AR6014_CACHE_FRESH_SCANS) {
            ar6014_bss_cache_count--;
            if (i != ar6014_bss_cache_count)
                ar6014_bss_cache[i] =
                    ar6014_bss_cache[ar6014_bss_cache_count];
            continue;
        }
        i++;
    }
}
""",
            "cache freshness helpers",
        )

    if "ar6014_cache_prune();" not in text:
        plain_anchor = """    window = ar6014_harvest_window;
    lo = AR6014_HARVEST_BOOT_LO;
"""
        legacy_anchor = """    window = ar6014_harvest_window;
    ar6014_cache_generation++;
    if (!ar6014_cache_generation)
        ar6014_cache_generation++;
    lo = AR6014_HARVEST_BOOT_LO;
"""
        if legacy_anchor in text:
            text = replace_once(
                text,
                legacy_anchor,
                """    window = ar6014_harvest_window;
    ar6014_cache_prune();
    lo = AR6014_HARVEST_BOOT_LO;
""",
                "cache expiry before fallback merge (legacy generation)",
            )
        else:
            text = replace_once(
                text,
                plain_anchor,
                """    window = ar6014_harvest_window;
    ar6014_cache_prune();
    lo = AR6014_HARVEST_BOOT_LO;
""",
                "cache expiry before fallback merge",
            )

    if FRAME_IDENTITY_MARKER not in text:
        text = replace_once(
            text,
            "static void\nar6014_cache_put(",
            FRAME_IDENTITY_HELPER + "\nstatic void\nar6014_cache_put(",
            "cache frame identity helper",
        )
        text = replace_once(
            text,
            "    memcpy(ar6014_bss_cache[i].bssid, bssid, ETH_ALEN);\n",
            """    if (i < ar6014_bss_cache_count &&
        ar6014_cache_same_tsf(&ar6014_bss_cache[i], body, body_len))
        return;
    memcpy(ar6014_bss_cache[i].bssid, bssid, ETH_ALEN);
""",
            "unchanged RAM frame freshness guard",
        )
    elif "ar6014_cache_same_frame(" in text:
        text = replace_once(
            text,
            FRAME_IDENTITY_OLD_HELPER,
            FRAME_IDENTITY_HELPER,
            "TSF identity migration",
        )
        text = replace_once(
            text,
            """        ar6014_cache_same_frame(&ar6014_bss_cache[i], channel,
                                frame_type, body, body_len))
""",
            """        ar6014_cache_same_tsf(&ar6014_bss_cache[i], body, body_len))
""",
            "TSF identity call migration",
        )

    if TOMBSTONE_MARKER not in text:
        old_slots = '''    if (i == ar6014_bss_cache_count) {
        if (ar6014_bss_cache_count < AR6014_CACHE_MAX) {
            ar6014_bss_cache_count++;
        } else {
            int candidate;

            i = 0;
            for (candidate = 1; candidate < AR6014_CACHE_MAX;
                 candidate++) {
                if (ar6014_bss_cache[candidate].last_seen_generation <
                    ar6014_bss_cache[i].last_seen_generation)
                    i = candidate;
            }
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 scan: evict stale %pM for %pM\\n",
                 ar6014_bss_cache[i].bssid, bssid));
        }
'''
        new_slots = '''    if (i == ar6014_bss_cache_count) {
        if (ar6014_bss_cache_count < AR6014_CACHE_MAX) {
            i = ar6014_bss_cache_count;
            ar6014_bss_cache_count++;
        } else {
            int candidate;

            i = -1;
            for (candidate = 0; candidate < AR6014_CACHE_MAX;
                 candidate++) {
                if (!ar6014_bss_cache[candidate].last_seen_generation) {
                    i = candidate;
                    break;
                }
            }
            if (i < 0) {
                i = 0;
                for (candidate = 1; candidate < AR6014_CACHE_MAX;
                     candidate++) {
                    if (ar6014_bss_cache[candidate].last_seen_generation <
                        ar6014_bss_cache[i].last_seen_generation)
                        i = candidate;
                }
            }
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 scan: evict stale/oldest %pM for %pM\\n",
                 ar6014_bss_cache[i].bssid, bssid));
        }
'''
        text = replace_once(text, old_slots, new_slots,
                            "tombstone-aware cache slot selection")
        old_prune = '''static void
ar6014_cache_prune(void)
{
    int i = 0;

    while (i < ar6014_bss_cache_count) {
        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];
        u32 age = ar6014_cache_generation - entry->last_seen_generation;

        if (!entry->last_seen_generation || age > AR6014_CACHE_FRESH_SCANS) {
            ar6014_bss_cache_count--;
            if (i != ar6014_bss_cache_count)
                ar6014_bss_cache[i] =
                    ar6014_bss_cache[ar6014_bss_cache_count];
            continue;
        }
        i++;
    }
}
'''
        new_prune = '''static void
ar6014_cache_prune(void)
{
    int i;

    /* N3DS_AR6014_CACHE_TOMBSTONE: retain the BSSID and TSF identity after
     * expiry so the same stale RAM frame cannot be re-added by this sweep. */
    for (i = 0; i < ar6014_bss_cache_count; i++) {
        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];
        u32 age = ar6014_cache_generation - entry->last_seen_generation;

        if (entry->last_seen_generation && age > AR6014_CACHE_FRESH_SCANS)
            entry->last_seen_generation = 0;
    }
}
'''
        text = replace_once(text, old_prune, new_prune,
                            "tombstone cache pruning")

    if (
        "N3DS_AR6014_STALE_CACHE_SKIP" not in text
        and "direct_skipped" in text
    ):
        text = replace_once(
            text,
            "    int i, found = 0, injected = 0, direct_skipped = 0;\n",
            "    int i, found = 0, injected = 0, direct_skipped = 0;\n"
            "    int stale_skipped = 0;\n",
            "stale cache skip counter",
        )
        text = replace_once(
            text,
            """        if (wmi_n3ds_direct_bss_seen(ar->arWmi, entry->bssid)) {
            direct_skipped++;
            continue;
        }
""",
            """        /* N3DS_AR6014_STALE_CACHE_SKIP: expired entries remain as
         * TSF tombstones so the same RAM frame cannot be reinjected. */
        if (!entry->last_seen_generation) {
            stale_skipped++;
            continue;
        }
        if (wmi_n3ds_direct_bss_seen(ar->arWmi, entry->bssid)) {
            direct_skipped++;
            continue;
        }
""",
            "stale cache injection guard",
        )
        text = replace_once(
            text,
            """        ("AR6002 scan: validated swept=%d cache=%d injected=%d direct_skipped=%d range=0x%x..0x%x\\n",
         found, ar6014_bss_cache_count, injected, direct_skipped, lo, hi));
""",
            """        ("AR6002 scan: validated swept=%d cache=%d injected=%d direct_skipped=%d stale_skipped=%d range=0x%x..0x%x\\n",
         found, ar6014_bss_cache_count, injected, direct_skipped,
         stale_skipped, lo, hi));
""",
            "stale cache injection trace",
        )
    return text


def patch_cfg(text: str) -> str:
    if MARKER in text:
        return patch_cfg_start_failure_cleanup(text)
    function_anchor = "static int\nar6k_cfg80211_scan(struct wiphy *wiphy,"
    text = replace_once(
        text,
        function_anchor,
        """/* N3DS_NWM_PROBED_SSID_SLOTS: full NWM decompilation at 0x00136528
 * proves command 10 is a 35-byte {index, flag, length, ssid[32]} payload and
 * accepts indices 0..5. NWM uses slot 0 for connect setup, leaving 1..5 for
 * cfg80211 active probes. */
#define N3DS_MAX_SCAN_PROBED_SSIDS 5

static int
ar6k_cfg80211_scan(struct wiphy *wiphy,""",
        "cfg80211 ABI marker",
    )
    old_program = '''    if(request->n_ssids &&
       request->ssids[0].ssid_len) {
        u8 i;

        if(request->n_ssids > (MAX_PROBED_SSID_INDEX - 1)) {
            request->n_ssids = MAX_PROBED_SSID_INDEX - 1;
        }

        for (i = 0; i < request->n_ssids; i++) {
            wmi_probedSsid_cmd(ar->arWmi, i+1, SPECIFIC_SSID_FLAG,
                               request->ssids[i].ssid_len,
                               request->ssids[i].ssid);
        }
    }

    if(ar->arConnected) {
'''
    new_program = '''    if(ar->arConnected) {
'''
    text = replace_once(text, old_program, new_program, "old probe programming")
    old_owner = '''    if (cmpxchg(&ar->scan_request, NULL, request) != NULL)
        return -EBUSY;

    /* N3DS_BOUNDED_CFG80211_SCAN_TRACE: prove framework-to-driver scan
'''
    new_owner = '''    if (cmpxchg(&ar->scan_request, NULL, request) != NULL)
        return -EBUSY;

    {
        u8 i, programmed = 0;

        for (i = 0; i < request->n_ssids &&
                    programmed < N3DS_MAX_SCAN_PROBED_SSIDS; i++) {
            if (!request->ssids[i].ssid_len)
                continue;
            if (wmi_probedSsid_cmd(ar->arWmi, programmed + 1,
                                   SPECIFIC_SSID_FLAG,
                                   request->ssids[i].ssid_len,
                                   request->ssids[i].ssid) != 0) {
                while (programmed)
                    wmi_probedSsid_cmd(ar->arWmi, programmed--,
                                       DISABLE_SSID_FLAG, 0, NULL);
                cmpxchg(&ar->scan_request, request, NULL);
                return -EIO;
            }
            programmed++;
        }
    }

    /* N3DS_BOUNDED_CFG80211_SCAN_TRACE: prove framework-to-driver scan
'''
    text = replace_once(text, old_owner, new_owner, "scan ownership/programming")
    text = replace_once(
        text,
        '''            ("AR6002 scan: cfg80211 request ssids=%u channels=%u\\n",
             request->n_ssids, request->n_channels));
''',
        '''            ("AR6002 scan: cfg80211 request ssids=%u first_len=%u channels=%u\\n",
             request->n_ssids,
             request->n_ssids ? request->ssids[0].ssid_len : 0,
             request->n_channels));
''',
        "bounded scan trace",
    )
    old_disable = '''    if(request->n_ssids && request->ssids[0].ssid_len) {
        u8 i;

        for (i = 0; i < request->n_ssids; i++) {
            wmi_probedSsid_cmd(ar->arWmi, i+1, DISABLE_SSID_FLAG,
                               0, NULL);
        }
    }
'''
    new_disable = '''    {
        u8 i, programmed = 0;

        for (i = 0; i < request->n_ssids &&
                    programmed < N3DS_MAX_SCAN_PROBED_SSIDS; i++) {
            if (!request->ssids[i].ssid_len)
                continue;
            programmed++;
            wmi_probedSsid_cmd(ar->arWmi, programmed,
                               DISABLE_SSID_FLAG, 0, NULL);
        }
    }
'''
    text = replace_once(text, old_disable, new_disable, "probe cleanup")
    text = replace_once(
        text,
        "    wdev->wiphy->max_scan_ssids = MAX_PROBED_SSID_INDEX;\n",
        "    wdev->wiphy->max_scan_ssids = N3DS_MAX_SCAN_PROBED_SSIDS;\n",
        "advertised scan SSIDs",
    )
    return patch_cfg_start_failure_cleanup(text)


def patch_cfg_start_failure_cleanup(text: str) -> str:
    if "N3DS_SCAN_START_FAILURE_CLEANUP" in text:
        return text
    old = '''    if(wmi_startscan_cmd(ar->arWmi, WMI_LONG_SCAN, forceFgScan, false, \\
                         0, 0, 0, NULL) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("%s: wmi_startscan_cmd failed\\n", __func__));
        cmpxchg(&ar->scan_request, request, NULL);
        ret = -EIO;
'''
    new = '''    if(wmi_startscan_cmd(ar->arWmi, WMI_LONG_SCAN, forceFgScan, false, \\
                         0, 0, 0, NULL) != 0) {
        u8 i, programmed = 0;

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("%s: wmi_startscan_cmd failed\\n", __func__));
        /* N3DS_SCAN_START_FAILURE_CLEANUP: command 10 slots were armed
         * before START_SCAN, so a rejected start must not leave stale probes. */
        for (i = 0; i < request->n_ssids &&
                    programmed < N3DS_MAX_SCAN_PROBED_SSIDS; i++) {
            if (!request->ssids[i].ssid_len)
                continue;
            programmed++;
            wmi_probedSsid_cmd(ar->arWmi, programmed,
                               DISABLE_SSID_FLAG, 0, NULL);
        }
        cmpxchg(&ar->scan_request, request, NULL);
        ret = -EIO;
'''
    return replace_once(text, old, new, "START_SCAN failure cleanup")


def main() -> None:
    drv = DRV.read_text()
    cfg = CFG.read_text()
    updated_drv = patch_cache(drv)
    updated_cfg = patch_cfg(cfg)
    DRV.write_text(updated_drv)
    CFG.write_text(updated_cfg)
    print("patch_ar6014_scan_priority: cache and NWM probe slots applied")


if __name__ == "__main__":
    main()
