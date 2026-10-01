#!/usr/bin/env python3
"""Merge exact WMI BSS events with a strict, expiring RAM fallback.

The Nintendo firmware can expose only part of a scan through exact
WMI_BSSINFO events.  Those events are authoritative for their BSSID, but a
direct-event count must not hide other APs that are recoverable from target
RAM.  This patch snapshots the direct BSSID set at scan completion, merges the
validated fallback entries, and expires fallback-only entries by scan age.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")
DRV = ROOT / "drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
WMI = ROOT / "drivers/staging/ath6k_legacy/wmi/wmi.c"
HOST = ROOT / "drivers/staging/ath6k_legacy/wmi/wmi_host.h"
API = ROOT / "drivers/staging/ath6k_legacy/include/wmi_api.h"
MARKER = "N3DS_AR6014_DIRECT_BSS_PREFERENCE"
MIXED_MARKER = "N3DS_AR6014_MIXED_BSS_MERGE"
STALE_CACHE_MARKER = "N3DS_AR6014_STALE_CACHE_SKIP"
SNAPSHOT_MARKER = "N3DS_AR6014_HARVEST_SNAPSHOT_ADMISSION"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source anchor, found {count}")
    return text.replace(old, new, 1)


def patch_harvester_merge(drv: str) -> str:
    """Make the already-installed validated harvester BSSID-aware.

    This is deliberately here as a migration step: older clean trees already
    contain the validated-harvest marker, so the validated patcher's early
    idempotence return must not prevent this mixed-source repair from landing.
    """
    if "wmi_n3ds_direct_bss_seen(wmip, frame + 16)" not in drv:
        if "extern int wmi_n3ds_direct_bss_seen" not in drv:
            drv = replace_once(
                drv,
                "static int\nar6014_parse_bss_frame(",
                "extern int wmi_n3ds_direct_bss_seen(struct wmi_t *wmip,\n"
                "                                      const u8 *bssid);\n\n"
                "static int\nar6014_parse_bss_frame(",
                "harvester direct-BSS declaration",
            )
        drv = replace_once(
            drv,
            "static int\nar6014_parse_bss_frame(u8 *frame, int avail, u32 target_offset,\n"
            "                       u32 *seen_lo, u32 *seen_hi)",
            "static int\nar6014_parse_bss_frame(struct wmi_t *wmip, u8 *frame,\n"
            "                       int avail, u32 target_offset,\n"
            "                       u32 *seen_lo, u32 *seen_hi)",
            "harvester parser signature",
        )
        drv = replace_once(
            drv,
            "    ar6014_cache_put(frame + 16, channel_mhz, frame_type,\n"
            "                     frame + AR6014_MGMT_HDR_LEN, body_len);\n",
            "    /* Exact WMI events own their BSSID.  Do not let a guessed RAM\n"
            "     * frame overwrite or refresh that authoritative node. */\n"
            "    if (!wmi_n3ds_direct_bss_seen(wmip, frame + 16))\n"
            "        ar6014_cache_put(frame + 16, channel_mhz, frame_type,\n"
            "                         frame + AR6014_MGMT_HDR_LEN, body_len);\n",
            "harvester direct-BSS cache guard",
        )
        drv = replace_once(
            drv,
            "        if (ar6014_parse_bss_frame(window + i, hi - i, i,\n"
            "                                    &seen_lo, &seen_hi)) {\n",
            "        if (ar6014_parse_bss_frame(ar->arWmi, window + i, hi - i, i,\n"
            "                                    &seen_lo, &seen_hi)) {\n",
            "harvester parser call",
        )

    if (
        "direct_skipped" not in drv
        or "wmi_n3ds_direct_bss_seen(wmip, frame + 16)" not in drv
    ):
        drv = replace_once(
            drv,
            "    int i, found = 0, injected = 0;\n",
            "    int i, found = 0, injected = 0, direct_skipped = 0;\n"
            "    int stale_skipped = 0;\n",
            "harvester direct skip counter",
        )
        drv = replace_once(
            drv,
            "    for (i = 0; i < ar6014_bss_cache_count; i++) {\n"
            "        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];\n"
            "        int status = wmi_inject_bssinfo(ar->arWmi, entry->channel, -50,\n",
            "    for (i = 0; i < ar6014_bss_cache_count; i++) {\n"
            "        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];\n"
            "        int status;\n"
            "        /* N3DS_AR6014_STALE_CACHE_SKIP: expired entries remain as\n"
            "         * TSF tombstones so the same RAM frame cannot be reinjected. */\n"
            "        if (!entry->last_seen_generation) {\n"
            "            stale_skipped++;\n"
            "            continue;\n"
            "        }\n"
            "        if (wmi_n3ds_direct_bss_seen(ar->arWmi, entry->bssid)) {\n"
            "            direct_skipped++;\n"
            "            continue;\n"
            "        }\n"
            "        status = wmi_inject_bssinfo(ar->arWmi, entry->channel, -50,\n",
            "harvester direct-BSS injection guard",
        )
        drv = replace_once(
            drv,
            "        (\"AR6002 scan: validated swept=%d cache=%d injected=%d range=0x%x..0x%x\\n\",\n"
            "         found, ar6014_bss_cache_count, injected, lo, hi));\n",
            "        (\"AR6002 scan: validated swept=%d cache=%d injected=%d direct_skipped=%d stale_skipped=%d range=0x%x..0x%x\\n\",\n"
            "         found, ar6014_bss_cache_count, injected, direct_skipped,\n"
            "         stale_skipped, lo, hi));\n",
            "harvester direct-BSS trace",
        )
    if "int status = wmi_inject_bssinfo" in drv:
        drv = replace_once(
            drv,
            "        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];\n"
            "        if (wmi_n3ds_direct_bss_seen(ar->arWmi, entry->bssid)) {\n"
            "            direct_skipped++;\n"
            "            continue;\n"
            "        }\n"
            "        int status = wmi_inject_bssinfo(ar->arWmi, entry->channel, -50,\n",
            "        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];\n"
            "        int status;\n"
            "        /* N3DS_AR6014_STALE_CACHE_SKIP: expired entries remain as\n"
            "         * TSF tombstones so the same RAM frame cannot be reinjected. */\n"
            "        if (!entry->last_seen_generation) {\n"
            "            stale_skipped++;\n"
            "            continue;\n"
            "        }\n"
            "        if (wmi_n3ds_direct_bss_seen(ar->arWmi, entry->bssid)) {\n"
            "            direct_skipped++;\n"
            "            continue;\n"
            "        }\n"
            "        status = wmi_inject_bssinfo(ar->arWmi, entry->channel, -50,\n",
            "C89 declaration ordering",
        )
    if STALE_CACHE_MARKER not in drv and "direct_skipped" in drv:
        drv = replace_once(
            drv,
            "    int i, found = 0, injected = 0, direct_skipped = 0;\n",
            "    int i, found = 0, injected = 0, direct_skipped = 0;\n"
            "    int stale_skipped = 0;\n",
            "stale cache skip counter migration",
        )
        drv = replace_once(
            drv,
            "        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];\n"
            "        int status;\n"
            "        if (wmi_n3ds_direct_bss_seen(ar->arWmi, entry->bssid)) {\n"
            "            direct_skipped++;\n"
            "            continue;\n"
            "        }\n",
            "        struct ar6014_bss_ent *entry = &ar6014_bss_cache[i];\n"
            "        int status;\n"
            "        /* N3DS_AR6014_STALE_CACHE_SKIP: expired entries remain as\n"
            "         * TSF tombstones so the same RAM frame cannot be reinjected. */\n"
            "        if (!entry->last_seen_generation) {\n"
            "            stale_skipped++;\n"
            "            continue;\n"
            "        }\n"
            "        if (wmi_n3ds_direct_bss_seen(ar->arWmi, entry->bssid)) {\n"
            "            direct_skipped++;\n"
            "            continue;\n"
            "        }\n",
            "stale cache injection migration",
        )
        drv = replace_once(
            drv,
            "        (\"AR6002 scan: validated swept=%d cache=%d injected=%d direct_skipped=%d range=0x%x..0x%x\\n\",\n"
            "         found, ar6014_bss_cache_count, injected, direct_skipped, lo, hi));\n",
            "        (\"AR6002 scan: validated swept=%d cache=%d injected=%d direct_skipped=%d stale_skipped=%d range=0x%x..0x%x\\n\",\n"
            "         found, ar6014_bss_cache_count, injected, direct_skipped,\n"
            "         stale_skipped, lo, hi));\n",
            "stale cache trace migration",
        )
    return drv


def patch_snapshot_admission(drv: str) -> tuple[str, bool]:
    """Admit a harvest before publishing/copying its direct-BSSID snapshot."""
    if SNAPSHOT_MARKER in drv:
        return drv, False
    old = '''void
ar6000_scanComplete_event(struct ar6_softc *ar, int status)
{
    bool deferred = false;
    u32 direct_bss = 0;

    /* N3DS_AR6014_MIXED_BSS_MERGE: direct events are authoritative per BSSID,
     * but a nonzero direct count must not hide BSSIDs that only the validated
     * RAM fallback can recover. */
    if (ar->arVersion.target_ver == AR6014_VERSION) {
        ar6014_cache_begin_scan();
        direct_bss = wmi_n3ds_take_direct_bss_count(ar->arWmi);
        if (ar6014_harvest_scan)
            deferred = ar6014_queue_harvest(ar, status);
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: direct BSS accepted=%u; RAM harvest merge\\n",
             direct_bss));
    }
'''
    new = '''void
ar6000_scanComplete_event(struct ar6_softc *ar, int status)
{
    bool deferred = false;
    u32 direct_bss = 0;

    /* N3DS_AR6014_MIXED_BSS_MERGE: direct events are authoritative per BSSID,
     * but a nonzero direct count must not hide BSSIDs that only the validated
     * RAM fallback can recover. */
    if (ar->arVersion.target_ver == AR6014_VERSION) {
        ar6014_cache_begin_scan();
        /* N3DS_AR6014_HARVEST_SNAPSHOT_ADMISSION: queue admission owns the
         * active snapshot. A loser discards only its pending direct count. */
        if (ar6014_harvest_scan) {
            deferred = ar6014_queue_harvest(ar, status);
            if (deferred)
                direct_bss = ar6014_harvest_direct_bss;
            else
                direct_bss =
                    wmi_n3ds_discard_direct_bss_count(ar->arWmi);
        } else {
            direct_bss = wmi_n3ds_take_direct_bss_count(ar->arWmi);
        }
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: direct BSS accepted=%u; RAM harvest merge\\n",
             direct_bss));
    }
'''
    if old not in drv:
        if "N3DS_AR6014_MIXED_BSS_MERGE" in drv:
            raise SystemExit("direct BSS snapshot admission: scan-completion shape unsupported")
        return drv, False
    return drv.replace(old, new, 1), True


def main() -> None:
    drv = DRV.read_text()
    drv, snapshot_repaired = patch_snapshot_admission(drv)
    wmi = WMI.read_text()
    host = HOST.read_text()
    api = API.read_text()

    # This translation unit uses the C library spelling (`memcpy`/`memcmp`)
    # rather than the ath6kl A_MEM* wrappers.  Migrate the first mixed patch
    # revision before the idempotence check so -Werror builds stay clean.
    wmi = wmi.replace(
        "A_MEMCPY(wmip->wmi_n3ds_harvest_bss,",
        "memcpy(wmip->wmi_n3ds_harvest_bss,",
    )
    wmi = wmi.replace(
        "A_MEMCPY(wmip->wmi_n3ds_direct_bss[",
        "memcpy(wmip->wmi_n3ds_direct_bss[",
    )
    wmi = wmi.replace(
        "A_MEMCMP(wmip->wmi_n3ds_harvest_bss[i],",
        "memcmp(wmip->wmi_n3ds_harvest_bss[i],",
    )

    if (
        MIXED_MARKER in drv
        and "wmi_n3ds_direct_bss_seen" in api
        and "direct_skipped" in drv
        and STALE_CACHE_MARKER in drv
        and "int status = wmi_inject_bssinfo" not in drv
        and SNAPSHOT_MARKER in drv
        and "wmi_n3ds_discard_direct_bss_count" in api
        and "wmi_n3ds_discard_direct_bss_count" in wmi
        and "A_MEMCPY(wmip->wmi_n3ds_" not in wmi
        and "A_MEMCMP(wmip->wmi_n3ds_" not in wmi
    ):
        if snapshot_repaired:
            DRV.write_text(drv)
        if wmi != WMI.read_text():
            WMI.write_text(wmi)
        print("patch_ar6014_direct_bss_preference: already applied")
        return

    # The first version of this patch shipped a counter-only gate.  Upgrade
    # that shape in place when a developer reruns the clean-tree patcher over
    # an already-patched canonical tree.
    if "wmi_n3ds_harvest_bss_count" not in host:
        if "wmi_n3ds_direct_bss_count;" in host:
            host = replace_once(
                host,
                "    u32 wmi_n3ds_direct_bss_count;\n",
                """#define WMI_N3DS_DIRECT_BSS_MAX 64
    u32 wmi_n3ds_direct_bss_count;
    u32 wmi_n3ds_harvest_bss_count;
    u8 wmi_n3ds_direct_bss[WMI_N3DS_DIRECT_BSS_MAX][6];
    u8 wmi_n3ds_harvest_bss[WMI_N3DS_DIRECT_BSS_MAX][6];
""",
                "mixed direct-BSS state upgrade",
            )
        else:
            host = replace_once(
                host,
                "    u8 wmi_keepaliveInterval;\n",
                "    u8 wmi_keepaliveInterval;\n"
                "#define WMI_N3DS_DIRECT_BSS_MAX 64\n"
                "    u32 wmi_n3ds_direct_bss_count;\n"
                "    u32 wmi_n3ds_harvest_bss_count;\n"
                "    u8 wmi_n3ds_direct_bss[WMI_N3DS_DIRECT_BSS_MAX][6];\n"
                "    u8 wmi_n3ds_harvest_bss[WMI_N3DS_DIRECT_BSS_MAX][6];\n",
                "per-device direct BSS state",
            )

    if "wmi_n3ds_direct_bss_seen" not in api:
        if "u32 wmi_n3ds_take_direct_bss_count" in api:
            api = replace_once(
                api,
                "u32 wmi_n3ds_take_direct_bss_count(struct wmi_t *wmip);\n",
                "u32 wmi_n3ds_take_direct_bss_count(struct wmi_t *wmip);\n"
                "int wmi_n3ds_direct_bss_seen(struct wmi_t *wmip, const u8 *bssid);\n"
                "u32 wmi_n3ds_discard_direct_bss_count(struct wmi_t *wmip);\n",
                "direct BSS membership API",
            )
        else:
            api = replace_once(
                api,
                "u16 wmi_ieee2freq (int chan);\n",
                "u32 wmi_n3ds_take_direct_bss_count(struct wmi_t *wmip);\n"
                "int wmi_n3ds_direct_bss_seen(struct wmi_t *wmip, const u8 *bssid);\n"
                "u32 wmi_n3ds_discard_direct_bss_count(struct wmi_t *wmip);\n\n"
                "u16 wmi_ieee2freq (int chan);\n",
                "direct BSS counter API",
            )

    if "wmi_n3ds_discard_direct_bss_count" not in api:
        api = replace_once(
            api,
            "int wmi_n3ds_direct_bss_seen(struct wmi_t *wmip, const u8 *bssid);\n",
            "int wmi_n3ds_direct_bss_seen(struct wmi_t *wmip, const u8 *bssid);\n"
            "u32 wmi_n3ds_discard_direct_bss_count(struct wmi_t *wmip);\n",
            "direct BSS discard API",
        )

    if "wmip->wmi_n3ds_direct_bss_count = 0;" not in wmi:
        wmi = replace_once(
            wmi,
            "    return (wmi_cmd_send(wmip, osbuf, WMI_START_SCAN_CMDID, NO_SYNC_WMIFLAG));\n}\n\nint\nwmi_scanparams_cmd",
            "    /* Count only exact, length-bounded WMI BSSINFO events for this\n"
            "     * scan.  The accepted BSSID list is snapshotted at completion\n"
            "     * before the next START_SCAN can reset the active list. */\n"
            "    wmip->wmi_n3ds_direct_bss_count = 0;\n"
            "    return (wmi_cmd_send(wmip, osbuf, WMI_START_SCAN_CMDID, NO_SYNC_WMIFLAG));\n"
            "}\n\nint\nwmi_scanparams_cmd",
            "scan counter reset",
        )

    if "memcpy(wmip->wmi_n3ds_direct_bss[" not in wmi:
        if "    wmip->wmi_n3ds_direct_bss_count++;\n" in wmi:
            wmi = replace_once(
                wmi,
                "    wmip->wmi_n3ds_direct_bss_count++;\n",
                """    if (wmip->wmi_n3ds_direct_bss_count <
        WMI_N3DS_DIRECT_BSS_MAX) {
        memcpy(wmip->wmi_n3ds_direct_bss[
                   wmip->wmi_n3ds_direct_bss_count],
               bih->bssid, 6);
        wmip->wmi_n3ds_direct_bss_count++;
    }
""",
                "accepted BSS accounting",
            )
        else:
            wmi = replace_once(
                wmi,
                "    wlan_setup_node(&wmip->wmi_scan_table, bss, bih->bssid);\n\n    return 0;\n}\n\nstatic int\nwmi_opt_frame_event_rx",
                "    wlan_setup_node(&wmip->wmi_scan_table, bss, bih->bssid);\n"
                "    if (wmip->wmi_n3ds_direct_bss_count <\n"
                "        WMI_N3DS_DIRECT_BSS_MAX) {\n"
                "        memcpy(wmip->wmi_n3ds_direct_bss[\n"
                "                   wmip->wmi_n3ds_direct_bss_count],\n"
                "                bih->bssid, 6);\n"
                "        wmip->wmi_n3ds_direct_bss_count++;\n"
                "    }\n\n"
                "    return 0;\n}\n\nstatic int\nwmi_opt_frame_event_rx",
                "accepted BSS accounting",
            )

    if "wmi_n3ds_harvest_bss_count = count" not in wmi:
        old_take = """u32
wmi_n3ds_take_direct_bss_count(struct wmi_t *wmip)
{
    u32 count = wmip->wmi_n3ds_direct_bss_count;

    wmip->wmi_n3ds_direct_bss_count = 0;
    return count;
}
"""
        new_take = """u32
wmi_n3ds_take_direct_bss_count(struct wmi_t *wmip)
{
    u32 count = wmip->wmi_n3ds_direct_bss_count;

    if (count > WMI_N3DS_DIRECT_BSS_MAX)
        count = WMI_N3DS_DIRECT_BSS_MAX;
    memcpy(wmip->wmi_n3ds_harvest_bss, wmip->wmi_n3ds_direct_bss,
           count * 6);
    wmip->wmi_n3ds_harvest_bss_count = count;
    wmip->wmi_n3ds_direct_bss_count = 0;
    return count;
}

int
wmi_n3ds_direct_bss_seen(struct wmi_t *wmip, const u8 *bssid)
{
    u32 i;

    for (i = 0; i < wmip->wmi_n3ds_harvest_bss_count; i++) {
        if (memcmp(wmip->wmi_n3ds_harvest_bss[i], bssid, 6) == 0)
            return 1;
    }
    return 0;
}
"""
        if old_take in wmi:
            wmi = replace_once(wmi, old_take, new_take, "direct BSS snapshot")
        else:
            wmi = replace_once(
                wmi,
                "    return (wmip);\n}\n\nvoid\nwmi_qos_state_init",
                "    return (wmip);\n}\n\n" + new_take +
                "\nvoid\nwmi_qos_state_init",
                "direct BSS snapshot implementation",
            )

    if "wmi_n3ds_discard_direct_bss_count" not in wmi:
        discard = """u32
wmi_n3ds_discard_direct_bss_count(struct wmi_t *wmip)
{
    u32 count = wmip->wmi_n3ds_direct_bss_count;

    wmip->wmi_n3ds_direct_bss_count = 0;
    return count;
}

"""
        wmi = replace_once(
            wmi,
            "int\nwmi_n3ds_direct_bss_seen(struct wmi_t *wmip, const u8 *bssid)\n",
            discard +
            "int\nwmi_n3ds_direct_bss_seen(struct wmi_t *wmip, const u8 *bssid)\n",
            "direct BSS discard implementation",
        )

    # The validated harvester runs after direct events and receives the WMI
    # snapshot through wmi_n3ds_direct_bss_seen().  Run this migration even if
    # a prior attempt already installed the scan-completion marker.
    if (
        "direct_skipped" not in drv
        or "wmi_n3ds_direct_bss_seen(wmip, frame + 16)" not in drv
        or "int status = wmi_inject_bssinfo" in drv
        or STALE_CACHE_MARKER not in drv
    ):
        drv = patch_harvester_merge(drv)

    if "N3DS_AR6014_MIXED_BSS_MERGE" not in drv:
        drv = drv.replace(
            "void\nar6000_scanComplete_event(struct ar6_softc *ar, int status)\n"
            "{\n"
            "    bool deferred = false;\n\n"
            "    if (ar6014_harvest_scan &&\n"
            "        ar->arVersion.target_ver == AR6014_VERSION)\n"
            "        deferred = ar6014_queue_harvest(ar, status);\n",
            "void\nar6000_scanComplete_event(struct ar6_softc *ar, int status)\n"
            "{\n"
            "    bool deferred = false;\n"
            "    u32 direct_bss = 0;\n\n"
            "    /* N3DS_AR6014_MIXED_BSS_MERGE: direct events are authoritative\n"
            "     * per BSSID, but a nonzero direct count must not hide BSSIDs\n"
            "     * that only the validated RAM fallback can recover. */\n"
            "    if (ar->arVersion.target_ver == AR6014_VERSION) {\n"
            "        ar6014_cache_begin_scan();\n"
            "        /* N3DS_AR6014_HARVEST_SNAPSHOT_ADMISSION: queue admission\n"
            "         * owns the active snapshot; a loser discards only its\n"
            "         * pending direct count. */\n"
            "        if (ar6014_harvest_scan) {\n"
            "            deferred = ar6014_queue_harvest(ar, status);\n"
            "            if (deferred)\n"
            "                direct_bss = ar6014_harvest_direct_bss;\n"
            "            else\n"
            "                direct_bss =\n"
            "                    wmi_n3ds_discard_direct_bss_count(ar->arWmi);\n"
            "        } else {\n"
            "            direct_bss = wmi_n3ds_take_direct_bss_count(ar->arWmi);\n"
            "        }\n"
            "        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,\n"
            "            (\"AR6002 scan: direct BSS accepted=%u; RAM harvest merge\\n\",\n"
            "             direct_bss));\n"
            "    }\n",
            1,
        )
        if "N3DS_AR6014_MIXED_BSS_MERGE" not in drv:
            # Fresh source may already have the counter-only implementation.
            old = """void
ar6000_scanComplete_event(struct ar6_softc *ar, int status)
{
    bool deferred = false;
    u32 direct_bss = 0;

    /* N3DS_AR6014_DIRECT_BSS_PREFERENCE: the corrected two-byte NWM
     * header exposes real WMI_BSSINFO_EVENTID messages whose payload
     * length is supplied by firmware.  Do not overwrite those parsed
     * nodes with guessed-length frames swept from mutable target RAM.
     * Retain the old harvester only when no direct event parsed. */
    if (ar->arVersion.target_ver == AR6014_VERSION) {
        direct_bss = wmi_n3ds_take_direct_bss_count(ar->arWmi);
        if (!direct_bss) {
            if (ar6014_harvest_scan)
                deferred = ar6014_queue_harvest(ar, status);
        } else {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                (\"AR6002 scan: direct BSS accepted=%u; RAM harvest bypassed\\n\",
                 direct_bss));
        }
    }
"""
            new = """void
ar6000_scanComplete_event(struct ar6_softc *ar, int status)
{
    bool deferred = false;
    u32 direct_bss = 0;

    /* N3DS_AR6014_MIXED_BSS_MERGE: direct events are authoritative per BSSID,
     * but a nonzero direct count must not hide BSSIDs that only the validated
     * RAM fallback can recover. */
    if (ar->arVersion.target_ver == AR6014_VERSION) {
        ar6014_cache_begin_scan();
        /* N3DS_AR6014_HARVEST_SNAPSHOT_ADMISSION: queue admission owns the
         * active snapshot; a loser discards only its pending direct count. */
        if (ar6014_harvest_scan) {
            deferred = ar6014_queue_harvest(ar, status);
            if (deferred)
                direct_bss = ar6014_harvest_direct_bss;
            else
                direct_bss =
                    wmi_n3ds_discard_direct_bss_count(ar->arWmi);
        } else {
            direct_bss = wmi_n3ds_take_direct_bss_count(ar->arWmi);
        }
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            (\"AR6002 scan: direct BSS accepted=%u; RAM harvest merge\\n\",
             direct_bss));
    }
"""
            drv = replace_once(drv, old, new, "mixed direct/fallback merge")

    if "N3DS_AR6014_MIXED_BSS_MERGE" not in drv:
        raise SystemExit("mixed direct/fallback merge: scan-completion anchor not found")

    HOST.write_text(host)
    API.write_text(api)
    WMI.write_text(wmi)
    DRV.write_text(drv)
    print("patch_ar6014_direct_bss_preference: mixed direct/fallback merge applied")


if __name__ == "__main__":
    main()
