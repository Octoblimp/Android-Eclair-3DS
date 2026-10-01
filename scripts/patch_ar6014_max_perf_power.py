#!/usr/bin/env python3
"""Take the station link out of power save (W17).

Build #255 confirmed the assoc-IE underflow fix works: wpa_supplicant keeps
its own RSN IE, cfg80211 is handed sane lengths, and `connect_result SUCCESS
reqIe=40 respIe=0` replaced the old `reqIe=252 respIe=250`.  The link still
carries nothing.  Every association reports `AR6002 census disconnect
frames=0 bcast=0 eapol_rx=0 eapol_tx=0`, and one of the two BSSIDs tears the
link down with `reason=4 status=34` -- 802.11 reason 34 is DISASSOC_LOW_ACK,
which means literally "I transmitted frames to you and you did not
acknowledge them".

The driver never leaves power save.  `wmi_powermode_cmd()` has exactly three
call sites in this tree and all three are dead code: two sit inside
`ADAPTIVE_POWER_THROUGHPUT_CONTROL`, which ar6000_drv.c line 96 `#undef`s,
and the third inside `ATH6K_CONFIG_OTA_MODE`, which is not defined either.
`wmi.c` sets only the host-side shadow `wmip->wmi_powerMode = REC_POWER`; no
power-mode command is ever put on the wire.  So the station joins in the
firmware's default power-save state with a listen interval, the AP buffers
EAPOL message 1/4 for a client it believes is asleep, the station never
collects it, and the AP eventually gives up on the un-acked frames.  That is
every symptom at once: zero EAPOL, zero frames of any kind, and reason 34.

MAX_PERF_POWER is sent once the WMI is ready and re-asserted on every
association, because a target that resets its power state on join would
otherwise undo the init-time setting.  `n3ds_max_perf=0` restores the old
behaviour without a rebuild, so the next capture can A/B it.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"

MARKER = "N3DS_AR6014_MAX_PERF_POWER"

PARAM_OLD = """unsigned int firmware_bridge;

module_param_string(ifname, ifname, sizeof(ifname), 0644);
"""

PARAM_NEW = """unsigned int firmware_bridge;

/* N3DS_AR6014_MAX_PERF_POWER: the stock driver never sends a power-mode
 * command at all -- every wmi_powermode_cmd() call site is behind an #undef'd
 * or undefined build flag -- so the station associates in the firmware's
 * default power-save state and never collects the EAPOL frames the AP buffers
 * for it.  Set to 0 to restore that behaviour for an A/B run. */
static int n3ds_max_perf = 1;
module_param(n3ds_max_perf, int, 0644);
MODULE_PARM_DESC(n3ds_max_perf,
    "keep the radio in MAX_PERF_POWER instead of the firmware default (0 = off)");

/* N3DS_AR6014_MAX_PERF_POWER: one place to send it, so init and every
 * association report the same way. */
static void n3ds_set_max_perf(struct ar6_softc *ar, const char *when)
{
    int rc;

    if (!n3ds_max_perf) {
        return;
    }
    if (ar == NULL || ar->arWmi == NULL || ar->arWmiReady == false) {
        return;
    }

    rc = wmi_powermode_cmd(ar->arWmi, MAX_PERF_POWER);
    A_PRINTF("AR6002 power: MAX_PERF at %s status=%d\\n", when, rc);
}

module_param_string(ifname, ifname, sizeof(ifname), 0644);
"""

INIT_OLD = """#ifdef ATH6K_CONFIG_OTA_MODE
    if ((wmi_powermode_cmd(ar->arWmi, MAX_PERF_POWER)) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,("Unable to set power mode \\n"));
        status = A_ERROR;
    }
#endif
"""

INIT_NEW = """/* N3DS_AR6014_MAX_PERF_POWER: this was the only unconditional power-mode
 * call in the file and ATH6K_CONFIG_OTA_MODE is not defined, so it never ran.
 * Send it for real; a station that stays in power save never collects
 * message 1/4 of the four-way handshake. */
    n3ds_set_max_perf(ar, "init");
"""

CONNECT_OLD = """    if ((ar->arNetworkType == INFRA_NETWORK)) {
        wmi_listeninterval_cmd(ar->arWmi, ar->arListenIntervalT, ar->arListenIntervalB);
    }
"""

CONNECT_NEW = """    if ((ar->arNetworkType == INFRA_NETWORK)) {
        wmi_listeninterval_cmd(ar->arWmi, ar->arListenIntervalT, ar->arListenIntervalB);
        /* N3DS_AR6014_MAX_PERF_POWER: re-assert per association -- the target
         * may reset its power state on join, and the handshake happens in the
         * first seconds of the link, which is exactly when a sleeping station
         * misses the AP's buffered unicast. */
        n3ds_set_max_perf(ar, "connect");
    }
"""

HUNKS = (
    ("power-mode module parameter and helper", PARAM_OLD, PARAM_NEW),
    ("send MAX_PERF_POWER at init", INIT_OLD, INIT_NEW),
    ("re-assert MAX_PERF_POWER on association", CONNECT_OLD, CONNECT_NEW),
)


def patch_driver(text):
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, (
            "%s: anchor matched %d times, expected 1" % (name, text.count(old)))
        text = text.replace(old, new)
    return text


def main():
    text = TARGET.read_text(encoding="utf-8")
    patched = patch_driver(text)
    if patched == text:
        print("patch_ar6014_max_perf_power: already applied")
        return 0
    TARGET.write_text(patched, encoding="utf-8")
    print("patch_ar6014_max_perf_power: applied %d hunks" % len(HUNKS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
