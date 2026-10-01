#!/usr/bin/env python3
"""Restore the matching legacy Atheros WEXT/XIOCTL AP control sources."""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

from pathlib import Path

WIN = Path(A3DS_WIN)
SOURCE = WIN / "scratch/niazlv-linux/drivers/staging/ath6kl/os/linux"
ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy")
DEST = ROOT / "os/linux"
MAKEFILE = ROOT / "Makefile"
MARKER = "N3DS_AR6014_WEXT_AP_CONTROL"


def main() -> None:
    for name in ("ioctl.c", "wireless_ext.c"):
        src = SOURCE / name
        if not src.is_file() or src.stat().st_size < 50000:
            raise SystemExit(f"missing/truncated matching legacy source: {src}")
        content = src.read_text(encoding="utf-8")
        
        import re
        # Translate legacy types to upstream kernel types
        content = content.replace("AR_SOFTC_T", "struct ar6_softc")
        content = content.replace("HIF_DEVICE", "struct hif_device")
        content = content.replace("A_UINT32", "u32")
        content = content.replace("A_UINT16", "u16")
        content = content.replace("A_UINT8", "u8")
        content = content.replace("A_INT32", "s32")
        content = content.replace("A_INT16", "s16")
        content = content.replace("A_INT8", "s8")
        content = content.replace("A_BOOL", "bool")
        content = content.replace("FALSE", "false")
        content = content.replace("TRUE", "true")
        content = content.replace("A_STATUS", "int")
        content = re.sub(r'\bA_OK\b', '0', content)
        
        # Replace booleans
        # Only replace exact word matches for TRUE/FALSE
        content = re.sub(r'\bTRUE\b', 'true', content)
        content = re.sub(r'\bFALSE\b', 'false', content)
        
        # Replace memory macros
        content = re.sub(r'A_MEMZERO\(([^,]+),\s*([^)]+)\)', r'memset(\1, 0, \2)', content)
        content = content.replace("A_MEMCPY", "memcpy")
        content = content.replace("A_MEMCMP", "memcmp")
        
        # Other leftover types
        content = content.replace("A_UCHAR", "u8")
        content = content.replace("A_CHAR", "char")
        
        # Header includes
        content = content.replace('#include "a_hci.h"', '/* #include "a_hci.h" */')
        content = content.replace('#include "ar6000_drv.h"', '#include "ar6000_drv.h"\n#define A_FAILED(x) ((x) != 0)\n#define A_FREE(x) kfree(x)')
        
        # Remove deleted event sender
        content = re.sub(r'ar6000_send_event_to_app\([^;]+;', '/* event removed */', content)

        # Fix timer syntax
        content = content.replace('ar->arHBChallengeResp.timer.t', 'ar->arHBChallengeResp.timer')
        
        # Disable HCI and tcmdPM blocks (deleted upstream)
        if name == "wireless_ext.c":
            content = content.replace("void ar6000_install_static_wep_keys(struct ar6_softc *ar)", "void legacy_ar6000_install_static_wep_keys(struct ar6_softc *ar)")
            content = content.replace("extern int ar6014_scanprep;", 
                "int ar6014_scanprep = 6;\nint ar6014_dwell_min = 0;\nint ar6014_dwell_act = 105;\nint ar6014_dwell_pas = 150;\nint ar6014_scanflags = 0x3f;\nint ar6014_home_dwell = 0;")
        
        if name == "ioctl.c":
            content = content.replace("extern int bmienable;", "int bmienable = 0;")
            content = re.sub(r'static int\s+ar6000_create_acl_data_osbuf.*?^\}', 'static int ar6000_create_acl_data_osbuf(void *dev, u8 *userdata, void **osbuf) { return -EOPNOTSUPP; }', content, flags=re.DOTALL | re.MULTILINE)
            content = re.sub(r'void\s+ar6000_tcmd_rx_report_event.*?^\}', 'void ar6000_tcmd_rx_report_event(void *devt, u8 *datap, int len) { }', content, flags=re.DOTALL | re.MULTILINE)
            
            # Use strict replacement for tcmd_get_rx_report
            import re
            content = re.sub(r'int\s+ar6000_ioctl_tcmd_get_rx_report.*?^ar6000_ioctl_set_error_report_bitmask', 
                             'int ar6000_ioctl_tcmd_get_rx_report(struct net_device *dev, struct ifreq *rq, u8 *data, u32 len) { return -EOPNOTSUPP; }\n#endif\n\nstatic int\nar6000_ioctl_set_error_report_bitmask', 
                             content, flags=re.DOTALL | re.MULTILINE)

            content = content.replace('if ((ar->tcmdPm == TCMD_PM_SLEEP) ||', 'if (0 && ')
            content = content.replace('(ar->tcmdPm == TCMD_PM_DEEPSLEEP)', '(0)')
            content = content.replace('ar->tcmdPm = pmCmd.mode;', '/* tcmdPm removed */')
            content = content.replace('WMI_SET_HT_OP_CMD htOp;', 'WMI_SET_HT_OP_CMD htOp __attribute__((unused));')
            content = content.replace('WMI_SET_HT_CAP_CMD htCap;', 'WMI_SET_HT_CAP_CMD htCap __attribute__((unused));')

        (DEST / name).write_text(content, encoding="utf-8")
    text = MAKEFILE.read_text(encoding="utf-8")
    if MARKER not in text:
        anchor = "ath6kl-y += os/linux/ar6000_drv.o\n"
        if text.count(anchor) != 1:
            raise SystemExit("legacy Makefile driver anchor is not unique")
        text = text.replace(
            anchor,
            anchor
            + f"# {MARKER}: matching legacy standard AP/WPA host control.\n"
            + "ath6kl-y += os/linux/wireless_ext.o\n"
            + "ath6kl-y += os/linux/ioctl.o\n",
            1,
        )
        MAKEFILE.write_text(text, encoding="utf-8")
    print("port_ar6014_wext_ap: matching legacy WEXT/XIOCTL sources installed")


if __name__ == "__main__":
    main()
