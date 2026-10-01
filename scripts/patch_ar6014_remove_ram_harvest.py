#!/usr/bin/env python3
"""Remove target-RAM BSS harvesting and use Nintendo's direct WMI layout.

Kernel #202 proves NWM emits ordinary WMI_BSSINFO events using the full
16-byte WMI_BSS_INFO_HDR.  Treating those payloads as the generic 12-byte
HDR2 shifts the BSSID/body by four bytes; the later security validator then
rejects every real event.  The RAM sweep merely injected a shrinking cache of
old frames and delayed scan completion by about 14 seconds.

This idempotent migration removes the worker/cache/target-memory fallback,
keeps a small direct-result counter for diagnostics, and selects the full
header only after the already-proven 16-byte Nintendo READY event.
"""
from a3ds_paths import A3DS_ROOT

import re
from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")
DRV = ROOT / "drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
WMI = ROOT / "drivers/staging/ath6k_legacy/wmi/wmi.c"
HOST = ROOT / "drivers/staging/ath6k_legacy/wmi/wmi_host.h"
API = ROOT / "drivers/staging/ath6k_legacy/include/wmi_api.h"

MARKER = "N3DS_AR6014_DIRECT_WMI_ONLY"
LAYOUT_MARKER = "N3DS_NWM_FULL_BSS_HEADER"

NWM_WRITE_BLOB = r'''static int
ar6002_nwm_write_blob(struct ar6_softc *ar, struct device *dev,
                      const char *name, u32 address, bool compressed)
{
    const struct firmware *fw_entry;
    int status;

    if (A_REQUEST_FIRMWARE(&fw_entry, name, dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002: request firmware failed %s\n", name));
        return A_ERROR;
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002: loading %s addr=0x%08x size=%zu%s\n",
         name, address, fw_entry->size, compressed ? " LZ" : ""));

    if (compressed)
        status = BMIFastDownload(ar->arHifDevice, address,
                                 (u8 *)fw_entry->data, fw_entry->size);
    else
        status = BMIWriteMemory(ar->arHifDevice, address,
                                (u8 *)fw_entry->data, fw_entry->size);

    A_RELEASE_FIRMWARE(fw_entry);
    if (status != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002: load failed %s status=%d\n", name, status));
        return A_ERROR;
    }

    return 0;
}

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_driver(text: str) -> str:
    text = text.replace(
        "static bool ar6014_harvest_scan = true;\n"
        "module_param(ar6014_harvest_scan, bool, 0644);\n"
        "MODULE_PARM_DESC(ar6014_harvest_scan,\n"
        "                 \"harvest Nintendo AR6014 scan results from target RAM\");\n\n",
        "",
    )

    start = text.find("/* Nintendo's firmware receives and caches beacons but never sends the stock\n")
    helper_anchor = "static int\nar6002_nwm_write_blob("
    boot_anchor = "static int\nar6000_ar6002_boot_firmware(struct ar6_softc *ar)\n"
    if start >= 0:
        # The firmware blob loader immediately follows the historical harvest
        # block and is part of boot, not scanning.  Preserve that boundary.
        end = text.find(helper_anchor, start)
        if end < 0:
            end = text.find(boot_anchor, start)
        if end < 0:
            raise RuntimeError("RAM harvest block: firmware-loader boundary missing")
        text = text[:start] + text[end:]

    # Repair trees touched by the earlier over-broad removal revision.  This
    # helper is reconstructed from the #202 symbol's complete instruction
    # range and its request/load/failure strings.
    if helper_anchor not in text:
        if boot_anchor not in text:
            raise RuntimeError("Nintendo boot function missing")
        text = text.replace(boot_anchor, NWM_WRITE_BLOB + boot_anchor, 1)

    cleanup = """    if (ar->arVersion.target_ver == AR6014_VERSION) {
        cancel_work_sync(&ar6014_harvest_work);
        ar6014_harvest_ar = NULL;
        atomic_set(&ar6014_harvest_busy, 0);
        if (ar6014_harvest_window) {
            vfree(ar6014_harvest_window);
            ar6014_harvest_window = NULL;
        }
        ar6014_bss_cache_count = 0;
    }

"""
    text = text.replace(cleanup, "")

    scan_re = re.compile(
        r"void\nar6000_scanComplete_event\(struct ar6_softc \*ar, int status\)\n"
        r"\{.*?\n\}\n\nvoid\nar6000_targetStats_event",
        re.S,
    )
    matches = list(scan_re.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(f"scan completion: expected one function, found {len(matches)}")
    direct = """void
ar6000_scanComplete_event(struct ar6_softc *ar, int status)
{
    /* N3DS_AR6014_DIRECT_WMI_ONLY: #202 proves Nintendo emits full-header
     * WMI_BSSINFO events.  Complete cfg80211 immediately after those direct
     * events; never scan target RAM or replay a private stale cache. */
    if (ar->arVersion.target_ver == AR6014_VERSION) {
        u32 direct_bss = wmi_n3ds_take_direct_bss_count(ar->arWmi);

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: direct BSS accepted=%u; no RAM harvest\\n",
             direct_bss));
    }

    ar6k_cfg80211_scanComplete_event(ar, status);

    if (!ar->arUserBssFilter) {
        wmi_bssfilter_cmd(ar->arWmi, NONE_BSS_FILTER, 0);
    }
    if (ar->scan_triggered) {
        if (status== 0) {
            union iwreq_data wrqu;
            A_MEMZERO(&wrqu, sizeof(wrqu));
            wireless_send_event(ar->arNetDev, SIOCGIWSCAN, &wrqu, NULL);
        }
        ar->scan_triggered = 0;
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_WLAN_SCAN,( "AR6000 scan complete: %d\\n", status));
}

void
ar6000_targetStats_event"""
    # A callable replacement is required: re.sub otherwise interprets the
    # C string's backslash-n as a literal source newline.
    text = scan_re.sub(lambda _match: direct, text, count=1)

    forbidden = (
        "ar6014_harvest", "AR6014_HARVEST", "AR6014_CACHE_",
        "wmi_inject_bssinfo", "N3DS_AR6014_MIXED_BSS_MERGE",
    )
    for token in forbidden:
        if token in text:
            raise RuntimeError(f"RAM harvest token survived in driver: {token}")
    return text


def patch_host(text: str) -> str:
    old = """#define WMI_N3DS_DIRECT_BSS_MAX 64
    u32 wmi_n3ds_direct_bss_count;
    u32 wmi_n3ds_harvest_bss_count;
    u8 wmi_n3ds_direct_bss[WMI_N3DS_DIRECT_BSS_MAX][6];
    u8 wmi_n3ds_harvest_bss[WMI_N3DS_DIRECT_BSS_MAX][6];
"""
    new = """#define WMI_N3DS_DIRECT_BSS_MAX 64
    u32 wmi_n3ds_direct_bss_count;
    bool wmi_n3ds_full_bss_header;
"""
    if old in text:
        text = replace_once(text, old, new, "WMI harvest state removal")
    elif "wmi_n3ds_direct_bss_count" not in text:
        anchor = "    u8 wmi_keepaliveInterval;\n"
        text = replace_once(text, anchor, anchor + new, "WMI direct state insertion")
    if "wmi_n3ds_harvest" in text or "wmi_n3ds_direct_bss[" in text:
        raise RuntimeError("WMI harvest arrays survived")
    return text


def patch_api(text: str) -> str:
    text = text.replace(
        "u32 wmi_n3ds_take_direct_bss_count(struct wmi_t *wmip);\n"
        "int wmi_n3ds_direct_bss_seen(struct wmi_t *wmip, const u8 *bssid);\n"
        "u32 wmi_n3ds_discard_direct_bss_count(struct wmi_t *wmip);\n",
        "u32 wmi_n3ds_take_direct_bss_count(struct wmi_t *wmip);\n",
    )
    if "wmi_n3ds_take_direct_bss_count" not in text:
        anchor = "void wmi_shutdown(struct wmi_t *wmip);\n"
        text = replace_once(
            text, anchor,
            anchor + "u32 wmi_n3ds_take_direct_bss_count(struct wmi_t *wmip);\n",
            "direct count API insertion",
        )
    for token in ("wmi_n3ds_direct_bss_seen", "wmi_n3ds_discard_direct_bss_count"):
        if token in text:
            raise RuntimeError(f"harvest API survived: {token}")
    return text


def patch_wmi(text: str) -> str:
    count_re = re.compile(
        r"u32\nwmi_n3ds_take_direct_bss_count\(struct wmi_t \*wmip\)\n"
        r"\{.*?\n\}\n\nvoid\nwmi_qos_state_init",
        re.S,
    )
    simple_count = """u32
wmi_n3ds_take_direct_bss_count(struct wmi_t *wmip)
{
    u32 count = wmip->wmi_n3ds_direct_bss_count;

    wmip->wmi_n3ds_direct_bss_count = 0;
    return count;
}

void
wmi_qos_state_init"""
    if count_re.search(text):
        text = count_re.sub(simple_count, text, count=1)
    elif "wmi_n3ds_take_direct_bss_count" not in text:
        anchor = "void\nwmi_qos_state_init(struct wmi_t *wmip)\n"
        text = replace_once(text, anchor, simple_count, "direct count implementation")

    inject_start = text.find("/* Nintendo's AR6014 firmware keeps completed scan frames in target RAM")
    validator_anchor = "/* N3DS_WMI_DIRECT_BSS_SECURITY_INTEGRITY: direct firmware BSSINFO is\n"
    if inject_start >= 0:
        inject_end = text.find(validator_anchor, inject_start)
        if inject_end < 0:
            raise RuntimeError("WMI injection removal boundary missing")
        text = text[:inject_start] + text[inject_end:]

    old_store = """    if (wmip->wmi_n3ds_direct_bss_count <
        WMI_N3DS_DIRECT_BSS_MAX) {
        memcpy(wmip->wmi_n3ds_direct_bss[
                      wmip->wmi_n3ds_direct_bss_count],
                  bih->bssid, 6);
        wmip->wmi_n3ds_direct_bss_count++;
    }
"""
    new_store = """    if (wmip->wmi_n3ds_direct_bss_count <
        WMI_N3DS_DIRECT_BSS_MAX)
        wmip->wmi_n3ds_direct_bss_count++;
"""
    if old_store in text:
        text = replace_once(text, old_store, new_store, "direct count simplification")
    elif "wmip->wmi_n3ds_direct_bss_count++" not in text:
        anchor = "    wlan_setup_node(&wmip->wmi_scan_table, bss, bih->bssid);\n"
        text = replace_once(text, anchor, anchor + new_store, "direct count insertion")

    if "wmip->wmi_n3ds_direct_bss_count = 0;" not in text:
        anchor = "    sc->numChannels = numChan;\n"
        text = replace_once(
            text, anchor,
            anchor + "    wmip->wmi_n3ds_direct_bss_count = 0;\n",
            "scan direct count reset",
        )

    ready_anchor = """        wmip->wmi_ready = true;
        A_WMI_READY_EVENT(wmip->wmi_devt, nwm->macaddr,
"""
    ready_new = """        wmip->wmi_ready = true;
        /* N3DS_NWM_FULL_BSS_HEADER: this exact READY layout identifies the
         * Nintendo event ABI, whose BSSINFO payload uses the full 16-byte
         * header (including s16 RSSI and u32 ieMask), not HDR2. */
        wmip->wmi_n3ds_full_bss_header = true;
        A_WMI_READY_EVENT(wmip->wmi_devt, nwm->macaddr,
"""
    if LAYOUT_MARKER not in text:
        text = replace_once(text, ready_anchor, ready_new, "Nintendo BSS layout flag")

    case_re = re.compile(
        r"    case \(WMI_BSSINFO_EVENTID\):\n.*?        break;\n"
        r"    case \(WMI_REGDOMAIN_EVENTID\):",
        re.S,
    )
    case_new = """    case (WMI_BSSINFO_EVENTID):
        A_DPRINTF(DBG_WMI, (DBGFMT "WMI_BSSINFO_EVENTID\\n", DBGARG));
        if (wmip->wmi_n3ds_full_bss_header) {
            /* N3DS_NWM_FULL_BSS_HEADER: do not apply the generic HDR2
             * expansion.  #202's bytes otherwise become RSSI-prefixed
             * fake BSSIDs and a body shifted four bytes into ieMask. */
            if (len <= sizeof(WMI_BSS_INFO_HDR))
                status = A_EINVAL;
            else
                status = wmi_bssInfo_event_rx(wmip, datap, len);
        } else {
            WMI_BSS_INFO_HDR2 bih2;
            WMI_BSS_INFO_HDR *bih;

            if (len <= sizeof(WMI_BSS_INFO_HDR2)) {
                status = A_EINVAL;
                break;
            }
            memcpy(&bih2, datap, sizeof(WMI_BSS_INFO_HDR2));
            if (A_NETBUF_PUSH(osbuf, 4) != 0) {
                status = A_EINVAL;
                break;
            }
            datap = A_NETBUF_DATA(osbuf);
            len = A_NETBUF_LEN(osbuf);
            bih = (WMI_BSS_INFO_HDR *)datap;
            bih->channel = bih2.channel;
            bih->frameType = bih2.frameType;
            bih->snr = bih2.snr;
            bih->rssi = bih2.snr - 95;
            bih->ieMask = bih2.ieMask;
            memcpy(bih->bssid, bih2.bssid, ATH_MAC_LEN);
            status = wmi_bssInfo_event_rx(wmip, datap, len);
        }
        break;
    case (WMI_REGDOMAIN_EVENTID):"""
    matches = list(case_re.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(f"BSSINFO dispatch: expected one case, found {len(matches)}")
    text = case_re.sub(lambda _match: case_new, text, count=1)

    for token in (
        "wmi_n3ds_harvest", "wmi_n3ds_direct_bss_seen",
        "wmi_n3ds_discard_direct_bss_count", "wmi_inject_bssinfo",
    ):
        if token in text:
            raise RuntimeError(f"WMI harvest token survived: {token}")
    return text


def main() -> None:
    for path in (DRV, WMI, HOST, API):
        if not path.exists():
            raise SystemExit(f"missing canonical source: {path}")
    DRV.write_text(patch_driver(DRV.read_text()))
    HOST.write_text(patch_host(HOST.read_text()))
    API.write_text(patch_api(API.read_text()))
    WMI.write_text(patch_wmi(WMI.read_text()))
    print("patch_ar6014_remove_ram_harvest: direct full-header WMI path only")


if __name__ == "__main__":
    main()
