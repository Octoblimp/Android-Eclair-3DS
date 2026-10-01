/*
 * Copyright 2008, The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <stdlib.h>
#include <fcntl.h>
#include <errno.h>
#include <poll.h>
#include <string.h>
#include <stdio.h>

#include "hardware_legacy/wifi.h"
#include "libwpa_client/wpa_ctrl.h"

#define LOG_TAG "WifiHW"
#include "cutils/log.h"
#include "cutils/memory.h"
#include "cutils/misc.h"
#include "cutils/properties.h"
#include "private/android_filesystem_config.h"
#ifdef HAVE_LIBC_SYSTEM_PROPERTIES
#define _REALLY_INCLUDE_SYS__SYSTEM_PROPERTIES_H_
#include <sys/_system_properties.h>
#endif

static struct wpa_ctrl *ctrl_conn;
static struct wpa_ctrl *monitor_conn;

extern int do_dhcp();
extern int ifc_init();
extern void ifc_close();
extern char *dhcp_lasterror();
extern void get_dhcp_info();
extern int init_module(void *, unsigned long, const char *);
extern int delete_module(const char *, unsigned int);

static char iface[PROPERTY_VALUE_MAX];
// TODO: use new ANDROID_SOCKET mechanism, once support for multiple
// sockets is in

#ifndef WIFI_DRIVER_MODULE_PATH
/* N3DS_WIFI_INITRAMFS_MODULE: /usr is replaced by an SD bind
 * mount, so /lib -> /usr/lib cannot retain an initramfs module. Keep the
 * primary module below an unmasked root and preserve /system as fallback. */
#define WIFI_DRIVER_MODULE_PATH         "/n3ds/modules/ath6kl.ko"
#define WIFI_DRIVER_MODULE_FALLBACK_PATH "/system/lib/modules/ath6kl.ko"
#define WIFI_DRIVER_INTERFACE_PATH      "/sys/class/net/wlan0"
#define WIFI_DRIVER_INTERFACE_RETRIES   300
#endif
#ifndef WIFI_DRIVER_MODULE_NAME
#define WIFI_DRIVER_MODULE_NAME         "ath6kl"
#endif
#ifndef WIFI_DRIVER_MODULE_ARG
#define WIFI_DRIVER_MODULE_ARG          "fwmode=1 ifname=wlan0"
#endif
#ifndef WIFI_FIRMWARE_LOADER
#define WIFI_FIRMWARE_LOADER		""
#endif
#define WIFI_TEST_INTERFACE		"sta"

static const char IFACE_DIR[]           = "/data/system/wpa_supplicant";
static const char DRIVER_MODULE_NAME[]  = WIFI_DRIVER_MODULE_NAME;
static const char DRIVER_MODULE_TAG[]   = WIFI_DRIVER_MODULE_NAME " ";
static const char DRIVER_MODULE_PATH[]  = WIFI_DRIVER_MODULE_PATH;
static const char DRIVER_MODULE_FALLBACK_PATH[]  = WIFI_DRIVER_MODULE_FALLBACK_PATH;
static const char DRIVER_MODULE_ARG[]   = WIFI_DRIVER_MODULE_ARG;
static const char FIRMWARE_LOADER[]     = WIFI_FIRMWARE_LOADER;
static const char DRIVER_PROP_NAME[]    = "wlan.driver.status";
static const char SUPPLICANT_NAME[]     = "wpa_supplicant";
static const char SUPP_PROP_NAME[]      = "init.svc.wpa_supplicant";
static const char SUPP_CONFIG_TEMPLATE[]= "/system/etc/wifi/wpa_supplicant.conf";
static const char SUPP_CONFIG_FILE[]    = "/data/misc/wifi/wpa_supplicant.conf";
static const char MODULE_FILE[]         = "/proc/modules";

static int insmod(const char *filename, const char *args)
{
    void *module;
    off_t length;
    ssize_t offset = 0;
    int fd;
    int ret;

    fd = open(filename, O_RDONLY);
    if (fd < 0) return -1;
    length = lseek(fd, 0, SEEK_END);
    if (length <= 0 || (off_t)(unsigned int)length != length ||
            lseek(fd, 0, SEEK_SET) != 0) {
        close(fd);
        errno = EINVAL;
        return -1;
    }
    module = malloc((size_t)length);
    if (!module) {
        close(fd);
        return -1;
    }
    while (offset < length) {
        ssize_t count = read(fd, (char *)module + offset,
                             (size_t)(length - offset));
        if (count <= 0) {
            free(module);
            close(fd);
            errno = EIO;
            return -1;
        }
        offset += count;
    }
    close(fd);
    ret = init_module(module, (unsigned int)length, args);
    free(module);
    return ret;
}

static int rmmod(const char *modname)
{
    int ret = -1;
    int maxtry = 10;

    while (maxtry-- > 0) {
        ret = delete_module(modname, O_NONBLOCK | O_EXCL);
        if (ret < 0 && errno == EAGAIN)
            usleep(500000);
        else
            break;
    }

    if (ret != 0)
        LOGD("Unable to unload driver module \"%s\": %s\n",
             modname, strerror(errno));
    return ret;
}

int do_dhcp_request(int *ipaddr, int *gateway, int *mask,
                    int *dns1, int *dns2, int *server, int *lease) {
    /* For test driver, always report success */
    if (strcmp(iface, WIFI_TEST_INTERFACE) == 0)
        return 0;

    if (ifc_init() < 0)
        return -1;

    if (do_dhcp(iface) < 0) {
        ifc_close();
        return -1;
    }
    ifc_close();
    get_dhcp_info(ipaddr, gateway, mask, dns1, dns2, server, lease);
    return 0;
}

const char *get_dhcp_error_string() {
    return dhcp_lasterror();
}

/* N3DS_WIFI_RELOADABLE_ATH6KL: fwmode is consumed during BMI boot.
 * Normal Wi-Fi loads STA firmware; Mobile Data can unload and reload the
 * same staged module with fwmode=2 instead of pretending a built-in STA
 * target changed mode. */
/* N3DS_WIFI_KEEP_RADIO_POWERED: the MCU I2C line at 0x25:0x2a is the AR6002's
 * power rail, not a soft "radio off" switch.  The target holds the firmware
 * downloaded over BMI in its own RAM, so dropping this line destroys the
 * running target and resets the SDIO function.  ath6kl stays bound and wlan0
 * stays registered across that, which is precisely the state
 * check_driver_loaded() cannot distinguish from a healthy load -- so the next
 * wifi_load_driver() skips insmod and hands the framework a dead radio that
 * accepts a scan request and never answers it.
 *
 * The line is therefore only ever moved together with the module itself.  The
 * property is a breadcrumb so a load can recognise a radio that some other
 * path (an older build, a forced unload) power-cycled underneath a resident
 * module and force the reload that is the only possible recovery.
 */
static void wifi_radio_power(int on) {
    system(on ? "i2cset -y 1 0x25 0x2a 0x01" : "i2cset -y 1 0x25 0x2a 0x00");
    property_set("n3ds.wifi.radio_power", on ? "1" : "0");
}

static int check_driver_loaded() {
    char buffer[4096];
    int fd = open(MODULE_FILE, O_RDONLY);
    int length;
    if (fd < 0) return 0;
    length = read(fd, buffer, sizeof(buffer) - 1);
    close(fd);
    if (length <= 0) return 0;
    buffer[length] = '\0';
    return strstr(buffer, DRIVER_MODULE_TAG) != NULL;
}



static int wait_for_driver_interface() {
    int attempt;
    for (attempt = 0; attempt < WIFI_DRIVER_INTERFACE_RETRIES; ++attempt) {
        if (access(WIFI_DRIVER_INTERFACE_PATH, F_OK) == 0) {
            LOGI("N3DS_WIFI_INTERFACE_READY attempts=%d", attempt + 1);
            return 0;
        }
        usleep(100000);
    }
    errno = ETIMEDOUT;
    return -1;
}


/* N3DS_WIFI_MODULE_FALLBACK: the initramfs module is independent of FAT,
 * while the byte-identical /system copy recovers a missing rootfs entry. */
static const char *driver_module_path() {
    if (access(DRIVER_MODULE_PATH, R_OK) == 0)
        return DRIVER_MODULE_PATH;
    if (access(DRIVER_MODULE_FALLBACK_PATH, R_OK) == 0) {
        LOGW("N3DS_WIFI_DRIVER_LOAD primary_missing fallback=%s",
             DRIVER_MODULE_FALLBACK_PATH);
        return DRIVER_MODULE_FALLBACK_PATH;
    }
    return DRIVER_MODULE_PATH;
}


int wifi_load_driver() {
    const char *module_path = driver_module_path();
    LOGI("N3DS_WIFI_DRIVER_LOAD begin path=%s", module_path);
    wifi_radio_power(1);

    /* N3DS_WIFI_STALE_MODULE_RELOAD: a previous enable can leave the module
     * resident with no wlan0 -- e.g. supplicant died right after bring-up
     * and the framework's disable path unloaded/reset the interface without
     * the module ever coming out, or a prior wait_for_driver_interface()
     * timeout's rmmod() below failed silently. check_driver_loaded() alone
     * can't tell a healthy loaded module from this stuck one, and skipping
     * insmod in that state means wait_for_driver_interface() below polls
     * for an interface that will never come back -- every later enable
     * attempt just burns WIFI_DRIVER_INTERFACE_RETRIES*100ms and times out,
     * which matches "third attempt just hung on starting" reports exactly. */
    if (check_driver_loaded() && access(WIFI_DRIVER_INTERFACE_PATH, F_OK) != 0) {
        LOGW("N3DS_WIFI_DRIVER_LOAD stale_module_no_interface, forcing reload");
        rmmod(DRIVER_MODULE_NAME);
    }

    /* N3DS_WIFI_DEAD_TARGET_RELOAD: wlan0 present proves nothing once the
     * rail has been cut -- the firmware lives in target RAM.  Only a module
     * round trip can re-run BMI, so take the unreliable reload over handing
     * the framework an interface that will never answer a scan. */
    if (check_driver_loaded()) {
        char powered[PROPERTY_VALUE_MAX];
        property_get("n3ds.wifi.radio_power", powered, "1");
        if (strcmp(powered, "1") != 0) {
            LOGW("N3DS_WIFI_DRIVER_LOAD radio was power-cycled while resident; "
                 "firmware is gone, forcing reload");
            rmmod(DRIVER_MODULE_NAME);
        }
    }

    if (!check_driver_loaded() &&
            insmod(module_path, DRIVER_MODULE_ARG) != 0) {
        LOGE("N3DS_WIFI_DRIVER_LOAD module_failed path=%s error=%s",
             module_path, strerror(errno));
        wifi_radio_power(0);
        property_set(DRIVER_PROP_NAME, "failed");
        return -1;
    }
    /* N3DS_WIFI_INTERFACE_READY: init_module returns before the legacy
     * startup thread registers wlan0. Starting wpa_supplicant in that window
     * makes the Android toggle fall straight back to disabled. */
    if (wait_for_driver_interface() != 0) {
        LOGE("N3DS_WIFI_DRIVER_LOAD interface_timeout path=%s",
             WIFI_DRIVER_INTERFACE_PATH);
        if (check_driver_loaded())
            rmmod(DRIVER_MODULE_NAME);
        wifi_radio_power(0);
        property_set(DRIVER_PROP_NAME, "failed");
        return -1;
    }
    LOGI("N3DS_WIFI_DRIVER_LOAD ready interface=wlan0");
    property_set(DRIVER_PROP_NAME, "ok");
    return 0;
}


/* N3DS_WIFI_NO_MODULE_UNLOAD: ath6kl on this AR6002 SDIO part does not
 * survive a module round trip. The 2026-09-11 capture is unambiguous:
 *
 *   04:45:22 supplicant failed -> framework disabled Wi-Fi -> rmmod ath6kl
 *   04:47:52 user re-enabled Wi-Fi -> insmod succeeded (no module_failed)
 *   04:48:22 N3DS_WIFI_DRIVER_LOAD interface_timeout  (wlan0 never returned)
 *
 * So the *first* load always works and every reload is dead -- the SDIO
 * function is left in a state the driver's probe cannot recover (BMI/target
 * reset ordering, see the AR6002 notes). Unloading therefore converts one
 * recoverable failure into a permanently broken radio until the next reboot,
 * which is exactly what "my WiFi refused to boot" looked like.
 *
 * Keep the module resident instead. wlan0 stays registered, so the next
 * enable is an immediate no-op load followed straight by another supplicant
 * attempt -- the part that actually can succeed on a retry. The MCU rail is
 * deliberately left up in that case: it is the target's power supply, not a
 * soft radio switch, and dropping it wipes the BMI-loaded firmware out from
 * under the still-bound driver (N3DS_WIFI_KEEP_RADIO_POWERED).
 *
 * The reload path is kept behind a property for the Mobile Data / fwmode=2
 * case described at N3DS_WIFI_RELOADABLE_ATH6KL, which genuinely needs a
 * different firmware mode and has no other way to ask for one:
 *   setprop n3ds.wifi.allow_module_unload 1
 */
int wifi_unload_driver() {
    char allow[PROPERTY_VALUE_MAX];

    property_get("n3ds.wifi.allow_module_unload", allow, "0");
    if (strcmp(allow, "1") == 0) {
        LOGW("N3DS_WIFI_DRIVER_UNLOAD forced by n3ds.wifi.allow_module_unload");
        if (check_driver_loaded() && rmmod(DRIVER_MODULE_NAME) != 0) {
            property_set(DRIVER_PROP_NAME, "failed");
            return -1;
        }
        /* The module is out, so nothing is bound to the target any more and
         * the rail can go down.  The next load re-runs BMI from scratch. */
        wifi_radio_power(0);
    } else {
        /* N3DS_WIFI_KEEP_RADIO_POWERED: see wifi_radio_power().  Cutting the
         * rail here is what broke the manual re-enable -- the module stayed
         * resident over a target that had lost its firmware, so the next load
         * skipped insmod (attempts=1 instead of the boot path's attempts=23)
         * and Settings sat on "scanning" forever. */
        LOGI("N3DS_WIFI_DRIVER_UNLOAD keeping ath6kl resident and powered "
             "(reload is fatal on AR6002 SDIO, and the rail holds its "
             "firmware); interface stays up for the next enable");
    }
    property_set(DRIVER_PROP_NAME, "unloaded");
    return 0;
}


int ensure_config_file_exists()
{
    char buf[2048];
    int srcfd, destfd;
    int nread;

    if (access(SUPP_CONFIG_FILE, R_OK|W_OK) == 0) {
        return 0;
    } else if (errno != ENOENT) {
        LOGE("Cannot access \"%s\": %s", SUPP_CONFIG_FILE, strerror(errno));
        return -1;
    }

    srcfd = open(SUPP_CONFIG_TEMPLATE, O_RDONLY);
    if (srcfd < 0) {
        LOGE("Cannot open \"%s\": %s", SUPP_CONFIG_TEMPLATE, strerror(errno));
        return -1;
    }

    destfd = open(SUPP_CONFIG_FILE, O_CREAT|O_WRONLY, 0660);
    if (destfd < 0) {
        close(srcfd);
        LOGE("Cannot create \"%s\": %s", SUPP_CONFIG_FILE, strerror(errno));
        return -1;
    }

    while ((nread = read(srcfd, buf, sizeof(buf))) != 0) {
        if (nread < 0) {
            LOGE("Error reading \"%s\": %s", SUPP_CONFIG_TEMPLATE, strerror(errno));
            close(srcfd);
            close(destfd);
            unlink(SUPP_CONFIG_FILE);
            return -1;
        }
        write(destfd, buf, nread);
    }

    close(destfd);
    close(srcfd);

    if (chown(SUPP_CONFIG_FILE, AID_SYSTEM, AID_WIFI) < 0) {
        LOGE("Error changing group ownership of %s to %d: %s",
             SUPP_CONFIG_FILE, AID_WIFI, strerror(errno));
        unlink(SUPP_CONFIG_FILE);
        return -1;
    }
    return 0;
}

/* N3DS_WIFI_SUPPLICANT_START_RETRY: the 2026-09-11 capture shows this
 * function returning failure 5.96 s after wlan0 was ready -- i.e. through the
 * "went running, then stopped again" branch below, not through its timeout.
 * The service wrapper lives exactly that long when the daemon dies during
 * bring-up, and the identical binary and config associate fine when the same
 * service is started by hand a couple of minutes later. One failed bring-up
 * attempt is therefore not evidence that Wi-Fi cannot work, and turning it
 * into a hard failure is what stranded the radio for the whole boot:
 * WifiService goes straight to unloadDriver(), and on this AR6002 the module
 * never comes back (see N3DS_WIFI_NO_MODULE_UNLOAD).
 *
 * Split the original body out and retry it, and log what the property
 * actually said on the way out so the next capture can name the cause
 * instead of leaving it to inference. */
#define WIFI_SUPPLICANT_START_ATTEMPTS  3
#define WIFI_SUPPLICANT_START_GAP_US    1000000

/* N3DS_WIFI_SUPPLICANT_SOCKET_WAIT: init.svc.wpa_supplicant tracks the
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
    char supp_status[PROPERTY_VALUE_MAX] = {'\0'};
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

static int wifi_start_supplicant_once()
{
    char supp_status[PROPERTY_VALUE_MAX] = {'\0'};
    int count = 100; /* wait at most 10 seconds per attempt */
#ifdef HAVE_LIBC_SYSTEM_PROPERTIES
    const prop_info *pi;
    unsigned serial = 0;
#endif

    /* Check whether already running -- and whether that is worth anything.
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

    /* Before starting the daemon, make sure its config file exists */
    if (ensure_config_file_exists() < 0) {
        LOGE("Wi-Fi will not be enabled");
        return -1;
    }

    /* Clear out any stale socket files that might be left over. */
    wpa_ctrl_cleanup();

#ifdef HAVE_LIBC_SYSTEM_PROPERTIES
    /*
     * Get a reference to the status property, so we can distinguish
     * the case where it goes stopped => running => stopped (i.e.,
     * it start up, but fails right away) from the case in which
     * it starts in the stopped state and never manages to start
     * running at all.
     */
    pi = __system_property_find(SUPP_PROP_NAME);
    if (pi != NULL) {
        serial = pi->serial;
    }
#endif
    property_set("ctl.start", SUPPLICANT_NAME);
    sched_yield();

    while (count-- > 0) {
 #ifdef HAVE_LIBC_SYSTEM_PROPERTIES
        if (pi == NULL) {
            pi = __system_property_find(SUPP_PROP_NAME);
        }
        if (pi != NULL) {
            __system_property_read(pi, NULL, supp_status);
            if (strcmp(supp_status, "running") == 0) {
                return wait_for_supplicant_socket();
            } else if (pi->serial != serial &&
                    strcmp(supp_status, "stopped") == 0) {
                LOGE("N3DS_WIFI_SUPPLICANT_WAIT died_during_startup "
                     "after=%dms status=%s", (100 - count) * 100, supp_status);
                return -1;
            }
        }
#else
        if (property_get(SUPP_PROP_NAME, supp_status, NULL)) {
            if (strcmp(supp_status, "running") == 0)
                return wait_for_supplicant_socket();
        }
#endif
        usleep(100000);
    }
    LOGE("N3DS_WIFI_SUPPLICANT_WAIT timeout status=%s",
         supp_status[0] ? supp_status : "<unset>");
    return -1;
}

int wifi_start_supplicant()
{
    int attempt;

    for (attempt = 1; attempt <= WIFI_SUPPLICANT_START_ATTEMPTS; attempt++) {
        if (wifi_start_supplicant_once() == 0) {
            if (attempt > 1)
                LOGI("N3DS_WIFI_SUPPLICANT_START recovered on attempt %d",
                     attempt);
            return 0;
        }
        LOGW("N3DS_WIFI_SUPPLICANT_START attempt %d/%d failed",
             attempt, WIFI_SUPPLICANT_START_ATTEMPTS);
        if (attempt == WIFI_SUPPLICANT_START_ATTEMPTS)
            break;
        /* Make sure init has actually reaped the previous instance, or the
         * next ctl.start is a no-op against a service still marked running. */
        wifi_stop_supplicant();
        usleep(WIFI_SUPPLICANT_START_GAP_US);
    }
    LOGE("N3DS_WIFI_SUPPLICANT_START giving up after %d attempts",
         WIFI_SUPPLICANT_START_ATTEMPTS);
    return -1;
}

int wifi_stop_supplicant()
{
    char supp_status[PROPERTY_VALUE_MAX] = {'\0'};
    int count = 50; /* wait at most 5 seconds for completion */

    /* Check whether supplicant already stopped */
    if (property_get(SUPP_PROP_NAME, supp_status, NULL)
        && strcmp(supp_status, "stopped") == 0) {
        return 0;
    }

    property_set("ctl.stop", SUPPLICANT_NAME);
    sched_yield();

    while (count-- > 0) {
        if (property_get(SUPP_PROP_NAME, supp_status, NULL)) {
            if (strcmp(supp_status, "stopped") == 0)
                return 0;
        }
        usleep(100000);
    }
    return -1;
}

/* N3DS_WIFI_CTRL_OPEN_RETRY: init publishes init.svc.wpa_supplicant=running
 * the instant it forks the service, so the property is true well before
 * wpa_supplicant has created its control socket -- and IFACE_DIR is created by
 * the supplicant itself, so even the directory test can lose the race.  The
 * old code opened once and gave up, leaving the framework's four-try/five-
 * second retry in WifiMonitor to recover it 5-20 s later. */
#define WIFI_CTRL_OPEN_TRIES        40
#define WIFI_CTRL_OPEN_DELAY_US     200000

static struct wpa_ctrl *wifi_ctrl_open_retry(char *ifname, size_t ifname_len)
{
    char supp_status[PROPERTY_VALUE_MAX] = {'\0'};
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
                LOGI("Connected to supplicant on \"%s\" after %d ms",
                     ifname, attempt * (WIFI_CTRL_OPEN_DELAY_US / 1000));
            }
            return conn;
        }
    }

    LOGE("Unable to open connection to supplicant on \"%s\" after %d ms: %s",
         ifname, WIFI_CTRL_OPEN_TRIES * (WIFI_CTRL_OPEN_DELAY_US / 1000),
         strerror(errno));
    return NULL;
}

int wifi_connect_to_supplicant()
{
    char ifname[256];
    char supp_status[PROPERTY_VALUE_MAX] = {'\0'};

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
    monitor_conn = wpa_ctrl_open(ifname);
    if (monitor_conn == NULL) {
        wpa_ctrl_close(ctrl_conn);
        ctrl_conn = NULL;
        return -1;
    }
    if (wpa_ctrl_attach(monitor_conn) != 0) {
        wpa_ctrl_close(monitor_conn);
        wpa_ctrl_close(ctrl_conn);
        ctrl_conn = monitor_conn = NULL;
        return -1;
    }
    return 0;
}

int wifi_send_command(struct wpa_ctrl *ctrl, const char *cmd, char *reply, size_t *reply_len)
{
    int ret;

    if (ctrl_conn == NULL) {
        LOGV("Not connected to wpa_supplicant - \"%s\" command dropped.\n", cmd);
        return -1;
    }
    ret = wpa_ctrl_request(ctrl, cmd, strlen(cmd), reply, reply_len, NULL);
    if (ret == -2) {
        LOGD("'%s' command timed out.\n", cmd);
        return -2;
    } else if (ret < 0 || strncmp(reply, "FAIL", 4) == 0) {
        return -1;
    }
    if (strncmp(cmd, "PING", 4) == 0) {
        reply[*reply_len] = '\0';
    }
    return 0;
}

/*
 * N3DS_WIFI_MONITOR_POLL (#325): wpa_supplicant 2.10's wpa_ctrl_open() makes
 * the control socket non-blocking ("so that we don't hang forever if target
 * dies"), but this is Eclair's wifi.c, written for the 0.6 wpa_ctrl whose
 * recv() blocked.  Every wpa_ctrl_recv() here failed at once with EAGAIN,
 * WifiMonitor treats a null event as "try again", and system_server spun at
 * ~4000 iterations a second, each logging "wpa_ctrl_recv failed: Try again"
 * -- the whole 64 KB main log buffer, every second, for the entire boot.
 *
 * It also hid a supplicant that died: a dead peer on a datagram socket looks
 * exactly like a quiet one, so WifiStateTracker never heard TERMINATING,
 * never tore down, and Wi-Fi stayed "connected" with no network under it.
 *
 * Wait in poll() instead, a second at a time, and between waits check the
 * supplicant is still running.  If it is not, or the socket reports an
 * error, report TERMINATING the way a clean supplicant exit would.
 */
#define WIFI_EVENT_POLL_MS 1000

static int wifi_supplicant_gone(char *buf, size_t buflen, const char *why)
{
    LOGE("N3DS_WIFI_MONITOR_POLL: %s; reporting the supplicant terminated", why);
    strncpy(buf, WPA_EVENT_TERMINATING " - supplicant not running", buflen-1);
    buf[buflen-1] = '\0';
    return strlen(buf);
}

int wifi_wait_for_event(char *buf, size_t buflen)
{
    size_t nread = buflen - 1;
    char supp_status[PROPERTY_VALUE_MAX];
    struct pollfd pfd;
    int result;

    if (monitor_conn == NULL)
        return 0;

    pfd.fd = wpa_ctrl_get_fd(monitor_conn);
    pfd.events = POLLIN;
    for (;;) {
        pfd.revents = 0;
        result = poll(&pfd, 1, WIFI_EVENT_POLL_MS);
        if (monitor_conn == NULL)
            return 0;
        if (result > 0) {
            if (pfd.revents & (POLLERR | POLLHUP | POLLNVAL))
                return wifi_supplicant_gone(buf, buflen, "monitor socket error");
            break;
        }
        if (result < 0 && errno != EINTR) {
            LOGE("poll on the supplicant monitor socket failed: %s", strerror(errno));
            usleep(100000);  /* never spin */
            continue;
        }
        if (result == 0) {
            supp_status[0] = '\0';
            if (!property_get(SUPP_PROP_NAME, supp_status, NULL)
                    || strcmp(supp_status, "running") != 0)
                return wifi_supplicant_gone(buf, buflen, "supplicant is no longer running");
        }
    }

    result = wpa_ctrl_recv(monitor_conn, buf, &nread);
    if (result < 0) {
        if (errno == EAGAIN || errno == EINTR)
            return 0;
        LOGD("wpa_ctrl_recv failed: %s\n", strerror(errno));
        usleep(100000);  /* never spin */
        return -1;
    }
    buf[nread] = '\0';
    /* LOGD("wait_for_event: result=%d nread=%d string=\"%s\"\n", result, nread, buf); */
    /* Check for EOF on the socket */
    if (result == 0 && nread == 0) {
        /* Fabricate an event to pass up */
        LOGD("Received EOF on supplicant socket\n");
        strncpy(buf, WPA_EVENT_TERMINATING " - signal 0 received", buflen-1);
        buf[buflen-1] = '\0';
        return strlen(buf);
    }
    /*
     * Events strings are in the format
     *
     *     <N>CTRL-EVENT-XXX 
     *
     * where N is the message level in numerical form (0=VERBOSE, 1=DEBUG,
     * etc.) and XXX is the event name. The level information is not useful
     * to us, so strip it off.
     */
    if (buf[0] == '<') {
        char *match = strchr(buf, '>');
        if (match != NULL) {
            nread -= (match+1-buf);
            memmove(buf, match+1, nread+1);
        }
    }
    return nread;
}

void wifi_close_supplicant_connection()
{
    if (ctrl_conn != NULL) {
        wpa_ctrl_close(ctrl_conn);
        ctrl_conn = NULL;
    }
    if (monitor_conn != NULL) {
        wpa_ctrl_close(monitor_conn);
        monitor_conn = NULL;
    }
}

int wifi_command(const char *command, char *reply, size_t *reply_len)
{
    return wifi_send_command(ctrl_conn, command, reply, reply_len);
}


// wpa_ctrl dependencies from os_unix.c
#include <sys/time.h>
struct os_reltime {
    time_t sec;
    time_t usec;
};
void *os_zalloc(size_t size) { return calloc(1, size); }
void os_sleep(int sec, int usec) { usleep(sec * 1000000 + usec); }
size_t os_strlcpy(char *dest, const char *src, size_t siz) { return strlcpy(dest, src, siz); }
int os_get_reltime(struct os_reltime *t) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    t->sec = tv.tv_sec;
    t->usec = tv.tv_usec;
    return 0;
}
