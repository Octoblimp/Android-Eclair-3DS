#!/usr/bin/env python3
"""N3DS_WIFI_SUPPLICANT_SOCKET_WAIT.

The 2026-09-12 capture has the whole story in two lines and one silence:

  04:48:43.551 N3DS_WIFI_DRIVER_LOAD ready interface=wlan0
  04:48:45.878 Supplicant stopped while waiting for its control socket

and not a single N3DS_WIFI_SUPPLICANT_* line between them -- so
wifi_start_supplicant_once() returned SUCCESS, and the three-attempt retry
added for exactly this failure never ran once.

It returned success because it believed init.svc.wpa_supplicant.  init sets
that property to "running" the instant it forks the service and clears it
when the wrapper exits, and /etc/wpa_supplicant_diag.sh's settle loop breaks
out the moment the daemon dies rather than sleeping its full SETTLE_SECONDS.
A daemon that dies immediately therefore burns all three of the wrapper's
attempts in about two seconds, and "running" is true for every bit of that.
The HAL saw it, declared the supplicant started, and handed the caller a
service that was already on its way out.

Success now means the control socket exists.  That is the only thing the
caller is about to need, it cannot be faked by a service that is merely
in the middle of dying, and it turns the three retries above into three real
ctl.start cycles instead of three no-ops.
"""
from a3ds_paths import A3DS_ROOT
import io
import sys

PATH = f"{A3DS_ROOT}/third_party/libhardware_legacy/wifi/wifi.c"

src = io.open(PATH, encoding="utf-8").read()
orig = src

helper = '''/* N3DS_WIFI_SUPPLICANT_SOCKET_WAIT: init.svc.wpa_supplicant tracks the
 * lifetime of /etc/wpa_supplicant_diag.sh, not of wpa_supplicant itself, so
 * "running" is also true throughout a wrapper that is busy failing.  The
 * control socket is the honest signal: wpa_supplicant binds it once it is
 * actually up, and nothing else in the system creates it. */
#define WIFI_SUPPLICANT_SOCKET_TRIES    50
#define WIFI_SUPPLICANT_SOCKET_DELAY_US 200000

static void supplicant_socket_path(char *path, size_t len)
{
    char if_name[PROPERTY_VALUE_MAX];

    property_get("wifi.interface", if_name, WIFI_TEST_INTERFACE);
    snprintf(path, len, "%s/%s", IFACE_DIR, if_name);
}

static int supplicant_socket_present()
{
    char path[256];

    supplicant_socket_path(path, sizeof(path));
    return access(path, F_OK) == 0;
}

/* Returns 0 once the socket is there, -1 if the service goes away first or
 * never produces one.  Either failure is a real failure the caller can retry,
 * which is the whole point -- the old code could not tell them apart from a
 * healthy start. */
static int wait_for_supplicant_socket()
{
    char supp_status[PROPERTY_VALUE_MAX] = {'\\0'};
    char path[256];
    int attempt;

    supplicant_socket_path(path, sizeof(path));

    for (attempt = 0; attempt < WIFI_SUPPLICANT_SOCKET_TRIES; attempt++) {
        if (supplicant_socket_present()) {
            LOGI("N3DS_WIFI_SUPPLICANT_READY socket=%s after=%dms", path,
                 attempt * (WIFI_SUPPLICANT_SOCKET_DELAY_US / 1000));
            return 0;
        }
        if (!property_get(SUPP_PROP_NAME, supp_status, NULL)
                || strcmp(supp_status, "running") != 0) {
            LOGE("N3DS_WIFI_SUPPLICANT_SOCKET service left after=%dms "
                 "status=%s socket=%s never appeared",
                 attempt * (WIFI_SUPPLICANT_SOCKET_DELAY_US / 1000),
                 supp_status[0] ? supp_status : "<unset>", path);
            return -1;
        }
        usleep(WIFI_SUPPLICANT_SOCKET_DELAY_US);
    }

    LOGE("N3DS_WIFI_SUPPLICANT_SOCKET timeout after=%dms socket=%s "
         "(service still reports running)",
         WIFI_SUPPLICANT_SOCKET_TRIES * (WIFI_SUPPLICANT_SOCKET_DELAY_US / 1000),
         path);
    return -1;
}

'''

anchor = "static int wifi_start_supplicant_once()\n"
if "wait_for_supplicant_socket" not in src:
    assert anchor in src, "wifi_start_supplicant_once anchor missing"
    src = src.replace(anchor, helper + anchor, 1)

# ---- entry early-return: "already running" now has to prove it ------------
old = '''    /* Check whether already running */
    if (property_get(SUPP_PROP_NAME, supp_status, NULL)
            && strcmp(supp_status, "running") == 0) {
        return 0;
    }
'''
new = '''    /* Check whether already running -- and whether that is worth anything.
     * A wrapper that is still winding down reports "running" too, and
     * returning success there is what let a dead supplicant look started. */
    if (property_get(SUPP_PROP_NAME, supp_status, NULL)
            && strcmp(supp_status, "running") == 0) {
        if (supplicant_socket_present())
            return 0;
        LOGW("N3DS_WIFI_SUPPLICANT_ZOMBIE service reports running with no "
             "control socket; stopping it before a fresh start");
        wifi_stop_supplicant();
    }
'''
assert old in src, "entry early-return anchor missing"
src = src.replace(old, new, 1)

# ---- the wait loop: "running" is the start of the wait, not the end -------
old = '''            __system_property_read(pi, NULL, supp_status);
            if (strcmp(supp_status, "running") == 0) {
                return 0;
            } else if (pi->serial != serial &&
'''
new = '''            __system_property_read(pi, NULL, supp_status);
            if (strcmp(supp_status, "running") == 0) {
                return wait_for_supplicant_socket();
            } else if (pi->serial != serial &&
'''
assert old in src, "property wait-loop anchor missing"
src = src.replace(old, new, 1)

old = '''        if (property_get(SUPP_PROP_NAME, supp_status, NULL)) {
            if (strcmp(supp_status, "running") == 0)
                return 0;
        }
#endif
        usleep(100000);
'''
new = '''        if (property_get(SUPP_PROP_NAME, supp_status, NULL)) {
            if (strcmp(supp_status, "running") == 0)
                return wait_for_supplicant_socket();
        }
#endif
        usleep(100000);
'''
assert old in src, "fallback wait-loop anchor missing"
src = src.replace(old, new, 1)

if src == orig:
    sys.stderr.write("no changes made\\n")
    sys.exit(1)

io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
print("patched " + PATH)
