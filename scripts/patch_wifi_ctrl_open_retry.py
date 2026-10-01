#!/usr/bin/env python3
"""Wait for wpa_supplicant's control socket instead of failing on the first try.

From the 2026-09-01 capture:

    E/WifiHW (458): Unable to open connection to supplicant on
                    "/data/system/wpa_supplicant/wlan0": No such file or directory

`wifi_connect_to_supplicant()` checks that the `init.svc.wpa_supplicant`
property says "running" and then opens the control socket exactly once.  init
publishes "running" the instant it forks the service, so the property is true
long before wpa_supplicant has created its socket -- and the socket lives in a
directory the supplicant creates itself, so even the directory test can lose
this race.

Nothing recovers this at the C level.  What saved the boot was
`WifiMonitor.connectToSupplicant()` in the framework, which retries four times
five seconds apart; the capture shows the profile connect succeeding ~35 s
later.  So the cost is 5-20 s of dead time on every Wi-Fi enable rather than an
outright failure -- but it is dead time spent before the first connect attempt,
and it puts an `E/WifiHW` line in every log that looks like a fatal error.

Poll instead: up to 8 s in 200 ms steps, giving up early if the supplicant
stops, and recomputing the socket path each attempt because IFACE_DIR may not
exist yet on the first one.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


WIFI_C = Path(f"{A3DS_ROOT}/third_party/libhardware_legacy/wifi/"
              "wifi.c")

MARKER = "N3DS_WIFI_CTRL_OPEN_RETRY"

OLD = '''int wifi_connect_to_supplicant()
{
    char ifname[256];
    char supp_status[PROPERTY_VALUE_MAX] = {'\\0'};

    /* Make sure supplicant is running */
    if (!property_get(SUPP_PROP_NAME, supp_status, NULL)
            || strcmp(supp_status, "running") != 0) {
        LOGE("Supplicant not running, cannot connect");
        return -1;
    }

    property_get("wifi.interface", iface, WIFI_TEST_INTERFACE);

    if (access(IFACE_DIR, F_OK) == 0) {
        snprintf(ifname, sizeof(ifname), "%s/%s", IFACE_DIR, iface);
    } else {
        strlcpy(ifname, iface, sizeof(ifname));
    }

    ctrl_conn = wpa_ctrl_open(ifname);
    if (ctrl_conn == NULL) {
        LOGE("Unable to open connection to supplicant on \\"%s\\": %s",
             ifname, strerror(errno));
        return -1;
    }
'''

NEW = '''/* N3DS_WIFI_CTRL_OPEN_RETRY: init publishes init.svc.wpa_supplicant=running
 * the instant it forks the service, so the property is true well before
 * wpa_supplicant has created its control socket -- and IFACE_DIR is created by
 * the supplicant itself, so even the directory test can lose the race.  The
 * old code opened once and gave up, leaving the framework's four-try/five-
 * second retry in WifiMonitor to recover it 5-20 s later. */
#define WIFI_CTRL_OPEN_TRIES        40
#define WIFI_CTRL_OPEN_DELAY_US     200000

static struct wpa_ctrl *wifi_ctrl_open_retry(char *ifname, size_t ifname_len)
{
    char supp_status[PROPERTY_VALUE_MAX] = {'\\0'};
    struct wpa_ctrl *conn;
    int attempt;

    for (attempt = 0; attempt < WIFI_CTRL_OPEN_TRIES; attempt++) {
        if (attempt > 0) {
            /* A supplicant that has died is not worth waiting out. */
            if (!property_get(SUPP_PROP_NAME, supp_status, NULL)
                    || strcmp(supp_status, "running") != 0) {
                LOGE("Supplicant stopped while waiting for its control socket");
                return NULL;
            }
            usleep(WIFI_CTRL_OPEN_DELAY_US);
        }

        /* Recomputed every attempt: IFACE_DIR may not exist yet. */
        if (access(IFACE_DIR, F_OK) == 0) {
            snprintf(ifname, ifname_len, "%s/%s", IFACE_DIR, iface);
        } else {
            strlcpy(ifname, iface, ifname_len);
        }

        conn = wpa_ctrl_open(ifname);
        if (conn != NULL) {
            if (attempt > 0) {
                LOGI("Connected to supplicant on \\"%s\\" after %d ms",
                     ifname, attempt * (WIFI_CTRL_OPEN_DELAY_US / 1000));
            }
            return conn;
        }
    }

    LOGE("Unable to open connection to supplicant on \\"%s\\" after %d ms: %s",
         ifname, WIFI_CTRL_OPEN_TRIES * (WIFI_CTRL_OPEN_DELAY_US / 1000),
         strerror(errno));
    return NULL;
}

int wifi_connect_to_supplicant()
{
    char ifname[256];
    char supp_status[PROPERTY_VALUE_MAX] = {'\\0'};

    /* Make sure supplicant is running */
    if (!property_get(SUPP_PROP_NAME, supp_status, NULL)
            || strcmp(supp_status, "running") != 0) {
        LOGE("Supplicant not running, cannot connect");
        return -1;
    }

    property_get("wifi.interface", iface, WIFI_TEST_INTERFACE);

    ctrl_conn = wifi_ctrl_open_retry(ifname, sizeof(ifname));
    if (ctrl_conn == NULL) {
        return -1;
    }
'''

HUNKS = (
    ("bounded ctrl socket wait", OLD, NEW),
)


def patch_text(text: str) -> str:
    """Give wifi_connect_to_supplicant() a bounded wait for the ctrl socket.

    Idempotent: an already-patched tree is returned untouched.
    """
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, f"{name}: expected exactly one match"
        text = text.replace(old, new)
    return text


def main() -> None:
    original = WIFI_C.read_text(encoding="utf-8")
    patched = patch_text(original)
    if patched == original:
        print("wifi_ctrl_open_retry: already applied")
        return
    WIFI_C.write_text(patched, encoding="utf-8")
    print(f"wifi_ctrl_open_retry: patched {WIFI_C}")


if __name__ == "__main__":
    main()
