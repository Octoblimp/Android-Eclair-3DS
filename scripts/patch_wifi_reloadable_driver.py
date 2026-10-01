#!/usr/bin/env python3
"""Make the AR6002 driver reloadable so STA/AP firmware mode is real."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path
import re

ROOT = Path(A3DS_ROOT)
DEFCONFIG = ROOT / "third_party/linux/arch/arm/configs/nintendo3ds_defconfig"
DOTCONFIG = ROOT / "third_party/linux/.config"
WIFI_C = ROOT / "third_party/libhardware_legacy/wifi/wifi.c"
HIF_C = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"
HIF_H = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/include/hif_internal.h"
DRIVER_C = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
MARKER = "N3DS_WIFI_RELOADABLE_ATH6KL"
TEARDOWN_MARKER = "N3DS_ATH6KL_STARTUP_TEARDOWN"
NETDEV_LIFETIME_MARKER = "N3DS_ATH6KL_NETDEV_LIFETIME"
CFG_BEFORE_TRANSPORT_MARKER = "N3DS_ATH6KL_CFG80211_BEFORE_TRANSPORT"
INITRAMFS_MODULE_MARKER = "N3DS_WIFI_INITRAMFS_MODULE"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_config(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    changed = False
    if "CONFIG_ATH6K_LEGACY=m" not in text:
        text = replace_once(text, "CONFIG_ATH6K_LEGACY=y",
                            "CONFIG_ATH6K_LEGACY=m", str(path))
        changed = True
    if "# CONFIG_MODULES is not set" in text:
        text = replace_once(text, "# CONFIG_MODULES is not set",
                            "CONFIG_MODULES=y\nCONFIG_MODULE_UNLOAD=y",
                            str(path) + " module support")
        changed = True
    elif "CONFIG_MODULES=y" not in text:
        text = replace_once(text, "CONFIG_ATH6K_LEGACY=m",
                            "CONFIG_MODULES=y\nCONFIG_MODULE_UNLOAD=y\n"
                            "CONFIG_ATH6K_LEGACY=m",
                            str(path) + " module support")
        changed = True
    elif "CONFIG_MODULE_UNLOAD=y" not in text:
        text = replace_once(text, "CONFIG_MODULES=y",
                            "CONFIG_MODULES=y\nCONFIG_MODULE_UNLOAD=y",
                            str(path) + " module unload")
        changed = True
    if changed:
        path.write_text(text, encoding="utf-8")


def patch_station_module_cache(text: str) -> str:
    """Load STA/AP module from initramfs and wait for the real wlan0 gate."""
    wait_helper = '''static int wait_for_driver_interface() {
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
'''
    old_macro = '''/* N3DS_WIFI_INITRAMFS_MODULE: keep module reads off SD-backed /system. */
#define WIFI_DRIVER_MODULE_PATH         "/lib/modules/ath6kl.ko"
#define WIFI_DRIVER_INTERFACE_PATH      "/sys/class/net/wlan0"
#define WIFI_DRIVER_INTERFACE_RETRIES   300'''
    new_macro = '''/* N3DS_WIFI_INITRAMFS_MODULE: /usr is replaced by an SD bind
 * mount, so /lib -> /usr/lib cannot retain an initramfs module. Keep the
 * primary module below an unmasked root and preserve /system as fallback. */
#define WIFI_DRIVER_MODULE_PATH         "/n3ds/modules/ath6kl.ko"
#define WIFI_DRIVER_MODULE_FALLBACK_PATH "/system/lib/modules/ath6kl.ko"
#define WIFI_DRIVER_INTERFACE_PATH      "/sys/class/net/wlan0"
#define WIFI_DRIVER_INTERFACE_RETRIES   300'''
    if old_macro in text:
        text = replace_once(text, old_macro, new_macro,
                            "masked initramfs module path upgrade")
    elif INITRAMFS_MODULE_MARKER not in text:
        text = replace_once(
            text,
            '#define WIFI_DRIVER_MODULE_PATH         "/system/lib/modules/ath6kl.ko"',
            new_macro,
            "initramfs station module path",
        )

    fallback_declaration = (
        "static const char DRIVER_MODULE_FALLBACK_PATH[]  = "
        "WIFI_DRIVER_MODULE_FALLBACK_PATH;\n"
    )
    if fallback_declaration not in text:
        text = replace_once(
            text,
            "static const char DRIVER_MODULE_PATH[]  = WIFI_DRIVER_MODULE_PATH;\n",
            "static const char DRIVER_MODULE_PATH[]  = WIFI_DRIVER_MODULE_PATH;\n"
            + fallback_declaration,
            "module fallback declaration",
        )

    original_load = '''

int wifi_load_driver() {
    system("i2cset -y 1 0x25 0x2a 0x01");
    if (!check_driver_loaded() &&
            insmod(DRIVER_MODULE_PATH, DRIVER_MODULE_ARG) != 0) {
        LOGE("Unable to load %s: %s", DRIVER_MODULE_PATH, strerror(errno));
        system("i2cset -y 1 0x25 0x2a 0x00");
        property_set(DRIVER_PROP_NAME, "failed");
        return -1;
    }
    property_set(DRIVER_PROP_NAME, "ok");
    return 0;
}
'''
    current_load = '''

int wifi_load_driver() {
    LOGI("N3DS_WIFI_DRIVER_LOAD begin path=%s", DRIVER_MODULE_PATH);
    system("i2cset -y 1 0x25 0x2a 0x01");
    if (!check_driver_loaded() &&
            insmod(DRIVER_MODULE_PATH, DRIVER_MODULE_ARG) != 0) {
        LOGE("N3DS_WIFI_DRIVER_LOAD module_failed path=%s error=%s",
             DRIVER_MODULE_PATH, strerror(errno));
        system("i2cset -y 1 0x25 0x2a 0x00");
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
        system("i2cset -y 1 0x25 0x2a 0x00");
        property_set(DRIVER_PROP_NAME, "failed");
        return -1;
    }
    LOGI("N3DS_WIFI_DRIVER_LOAD ready interface=wlan0");
    property_set(DRIVER_PROP_NAME, "ok");
    return 0;
}
'''
    new_load = '''

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
    system("i2cset -y 1 0x25 0x2a 0x01");
    if (!check_driver_loaded() &&
            insmod(module_path, DRIVER_MODULE_ARG) != 0) {
        LOGE("N3DS_WIFI_DRIVER_LOAD module_failed path=%s error=%s",
             module_path, strerror(errno));
        system("i2cset -y 1 0x25 0x2a 0x00");
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
        system("i2cset -y 1 0x25 0x2a 0x00");
        property_set(DRIVER_PROP_NAME, "failed");
        return -1;
    }
    LOGI("N3DS_WIFI_DRIVER_LOAD ready interface=wlan0");
    property_set(DRIVER_PROP_NAME, "ok");
    return 0;
}
'''
    if "N3DS_WIFI_MODULE_FALLBACK" not in text:
        if current_load in text:
            text = replace_once(text, current_load, new_load,
                                "runtime module fallback upgrade")
        else:
            text = replace_once(text, original_load, new_load,
                                "station interface readiness")

    # The previous upgrade form embedded the readiness helper in both the
    # already-patched load block and its replacement. Normalize that exact
    # historical state so repeated patch runs remain source- and build-idempotent.
    while text.count(wait_helper) > 1:
        text = text.replace(wait_helper + "\n", "", 1)
    if text.count(wait_helper) != 1:
        raise RuntimeError(
            "station interface readiness helper count must be exactly one")
    if text.count("static const char *driver_module_path()") != 1:
        raise RuntimeError(
            "runtime module fallback helper count must be exactly one")

    for required in (
        '"/n3ds/modules/ath6kl.ko"',
        '"/system/lib/modules/ath6kl.ko"',
        '"/sys/class/net/wlan0"',
        "driver_module_path",
        "N3DS_WIFI_MODULE_FALLBACK",
        "wait_for_driver_interface",
        "N3DS_WIFI_INTERFACE_READY",
        "WIFI_DRIVER_INTERFACE_RETRIES",
    ):
        if required not in text:
            raise RuntimeError(
                "marked initramfs Wi-Fi source missing " + required)
    return text


def patch_wifi(text: str) -> str:
    legacy_insmod = '''static int insmod(const char *filename, const char *args)
{
    void *module;
    unsigned int size;
    int ret;

    module = load_file(filename, &size);
    if (!module)
        return -1;

    ret = init_module(module, size, args);

    free(module);

    return ret;
}
'''
    bounded_insmod = '''static int insmod(const char *filename, const char *args)
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
'''
    if legacy_insmod in text:
        text = replace_once(text, legacy_insmod, bounded_insmod,
                            "self-contained module loader")
    if MARKER in text:
        text = patch_station_module_cache(text)
        for required in ("/n3ds/modules/ath6kl.ko",
                         "/system/lib/modules/ath6kl.ko", '"ath6kl"',
                         '"fwmode=1 ifname=wlan0"', "rmmod(DRIVER_MODULE_NAME)"):
            if required not in text:
                raise RuntimeError("marked reloadable Wi-Fi source missing " + required)
        if "load_file(filename" in text:
            raise RuntimeError("reloadable Wi-Fi source still depends on load_file")
        return text
    text = replace_once(text, '#include <string.h>\n',
                        '#include <string.h>\n#include <stdio.h>\n', "stdio import")
    text = replace_once(text,
        '#define WIFI_DRIVER_MODULE_PATH         "/system/lib/modules/wlan.ko"',
        '#define WIFI_DRIVER_MODULE_PATH         "/system/lib/modules/ath6kl.ko"',
        "driver path")
    text = replace_once(text, '#define WIFI_DRIVER_MODULE_NAME         "wlan"',
                        '#define WIFI_DRIVER_MODULE_NAME         "ath6kl"',
                        "driver name")
    text = replace_once(text, '#define WIFI_DRIVER_MODULE_ARG          ""',
                        '#define WIFI_DRIVER_MODULE_ARG          "fwmode=1 ifname=wlan0"',
                        "station arguments")
    old = '''static int check_driver_loaded() {
    return 1;
}


int wifi_load_driver() {
    system("i2cset -y 1 0x25 0x2a 0x01");
    property_set(DRIVER_PROP_NAME, "ok");
    return 0;
}


int wifi_unload_driver() {
    system("i2cset -y 1 0x25 0x2a 0x00");
    property_set(DRIVER_PROP_NAME, "unloaded");
    return 0;
}
'''
    new = '''/* N3DS_WIFI_RELOADABLE_ATH6KL: fwmode is consumed during BMI boot.
 * Normal Wi-Fi loads STA firmware; Mobile Data can unload and reload the
 * same staged module with fwmode=2 instead of pretending a built-in STA
 * target changed mode. */
static int check_driver_loaded() {
    char buffer[4096];
    int fd = open(MODULE_FILE, O_RDONLY);
    int length;
    if (fd < 0) return 0;
    length = read(fd, buffer, sizeof(buffer) - 1);
    close(fd);
    if (length <= 0) return 0;
    buffer[length] = '\\0';
    return strstr(buffer, DRIVER_MODULE_TAG) != NULL;
}


int wifi_load_driver() {
    system("i2cset -y 1 0x25 0x2a 0x01");
    if (!check_driver_loaded() &&
            insmod(DRIVER_MODULE_PATH, DRIVER_MODULE_ARG) != 0) {
        LOGE("Unable to load %s: %s", DRIVER_MODULE_PATH, strerror(errno));
        system("i2cset -y 1 0x25 0x2a 0x00");
        property_set(DRIVER_PROP_NAME, "failed");
        return -1;
    }
    property_set(DRIVER_PROP_NAME, "ok");
    return 0;
}


int wifi_unload_driver() {
    if (check_driver_loaded() && rmmod(DRIVER_MODULE_NAME) != 0) {
        property_set(DRIVER_PROP_NAME, "failed");
        return -1;
    }
    system("i2cset -y 1 0x25 0x2a 0x00");
    property_set(DRIVER_PROP_NAME, "unloaded");
    return 0;
}
'''
    text = replace_once(text, old, new, "Wi-Fi driver lifecycle")
    return patch_station_module_cache(text)


def patch_hif_header(text: str) -> str:
    if TEARDOWN_MARKER in text:
        stale = (
            "    /* N3DS_ATH6KL_STARTUP_TEARDOWN: module removal must join the\n"
            "     * one-shot startup/resume task before its code or device is freed. */\n"
            "    struct task_struct* startup_task;\n"
        )
        safe = (
            "    /* N3DS_ATH6KL_STARTUP_TEARDOWN: completion remains valid after\n"
            "     * the one-shot startup task exits; a borrowed task pointer does not. */\n"
            "    struct completion startup_completion;\n"
        )
        if stale in text:
            return replace_once(text, stale, safe,
                                "HIF stale startup task ownership upgrade")
        if "struct completion startup_completion;" not in text:
            raise RuntimeError("marked HIF header lacks startup completion")
        return text
    old = "    struct completion async_completion;          /* thread completion */\n"
    new = old + (
        "    /* N3DS_ATH6KL_STARTUP_TEARDOWN: module removal must join the\n"
        "     * one-shot startup task before its code or device is freed. */\n"
        "    struct completion startup_completion;\n"
    )
    return replace_once(text, old, new, "HIF startup task field")


def patch_hif_source(text: str) -> str:
    init_pattern = re.compile(
        r"^[ \t]*init_completion\(&device->startup_completion\);[ \t]*$",
        re.MULTILINE,
    )
    if TEARDOWN_MARKER in text:
        stale_remove = """\tif (device->startup_task != NULL) {
\t\tkthread_stop(device->startup_task);
\t\tdevice->startup_task = NULL;
\t}
"""
        if stale_remove in text:
            text = replace_once(
                text, stale_remove,
                "\twait_for_completion(&device->startup_completion);\n",
                "HIF stale startup pointer removal upgrade")
            text = replace_once(
                text,
                "    if (kthread_should_stop())\n        return 0;\n",
                "", "HIF stale startup cancellation upgrade")
            text = replace_once(
                text,
                "        AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, (\"AR6000: Device rejected\\n\"));\n"
                "    }\n    return 0;\n}\n\n#if defined(CONFIG_PM)\n",
                "        AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, (\"AR6000: Device rejected\\n\"));\n"
                "    }\n    complete(&device->startup_completion);\n"
                "    return 0;\n}\n\n#if defined(CONFIG_PM)\n",
                "HIF startup completion signal upgrade")
            text = replace_once(
                text,
                "    device->startup_task = pTask;\n    wake_up_process(pTask);\n",
                "    reinit_completion(&device->startup_completion);\n"
                "    wake_up_process(pTask);\n",
                "HIF startup completion arm upgrade")
        # Do not use a substring check here: ``reinit_completion(...)``
        # contains the complete spelling ``init_completion(...)`` and caused
        # #231's HIF device to reach wait_for_completion() with a zeroed,
        # uninitialized wait-queue head.  The resulting rmmod task corrupted
        # its unwind frame and stalled cross-CPU TLB flushes on hardware.
        if init_pattern.search(text) is None:
            text = replace_once(
                text,
                "\tspin_lock_init(&device->asynclock);\n\n"
                "\tDL_LIST_INIT(&device->ScatterReqHead);\n",
                "\tspin_lock_init(&device->asynclock);\n"
                "\tinit_completion(&device->startup_completion);\n"
                "\tcomplete(&device->startup_completion);\n\n"
                "\tDL_LIST_INIT(&device->ScatterReqHead);\n",
                "HIF startup completion initialization upgrade")
        for required in ("wait_for_completion(&device->startup_completion)",
                         "reinit_completion(&device->startup_completion)",
                         "complete(&device->startup_completion)"):
            if required not in text:
                raise RuntimeError("marked HIF teardown lacks " + required)
        if len(init_pattern.findall(text)) != 1:
            raise RuntimeError("marked HIF teardown must initialize startup completion exactly once")
        return text

    remove_old = """\tdevice = ath6kl_get_hifdev(func);
\tif (device->claimedContext != NULL)
"""
    remove_new = """\tdevice = ath6kl_get_hifdev(func);
\t/* N3DS_ATH6KL_STARTUP_TEARDOWN: kthread_create() is asynchronous.
\t * sdio_unregister_driver() may otherwise return while AR6K startup still
\t * executes module text, making a subsequent insmod a use-after-unload.
\t * Wait on device-owned completion before callbacks or freeing HIF.  The
\t * completion stays valid after a fast startup task has already exited. */
\twait_for_completion(&device->startup_completion);
\tif (device->claimedContext != NULL)
"""
    text = replace_once(text, remove_old, remove_new,
                        "HIF remove startup join")
    text = replace_once(
        text,
        "\tspin_lock_init(&device->asynclock);\n\n"
        "\tDL_LIST_INIT(&device->ScatterReqHead);\n",
        "\tspin_lock_init(&device->asynclock);\n"
        "\tinit_completion(&device->startup_completion);\n"
        "\tcomplete(&device->startup_completion);\n\n"
        "\tDL_LIST_INIT(&device->ScatterReqHead);\n",
        "HIF startup completion initialization")

    startup_old = """    device = (struct hif_device *)param;
    AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, ("AR6000: call HTC from startup_task\\n"));
        /* start  up inform DRV layer */
    if ((osdrvCallbacks.deviceInsertedHandler(osdrvCallbacks.context,device)) != 0) {
"""
    startup_new = """    device = (struct hif_device *)param;
    AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, ("AR6000: call HTC from startup_task\\n"));
        /* start  up inform DRV layer */
    if ((osdrvCallbacks.deviceInsertedHandler(osdrvCallbacks.context,device)) != 0) {
"""
    text = replace_once(text, startup_old, startup_new,
                        "HIF startup completion entry")
    text = replace_once(
        text,
        "        AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, (\"AR6000: Device rejected\\n\"));\n"
        "    }\n    return 0;\n}\n\n#if defined(CONFIG_PM)\n",
        "        AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, (\"AR6000: Device rejected\\n\"));\n"
        "    }\n    complete(&device->startup_completion);\n"
        "    return 0;\n}\n\n#if defined(CONFIG_PM)\n",
        "HIF startup completion signal")

    create_old = """    wake_up_process(pTask);
    AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, ("AR6000: -hifEnableFunc\\n"));
"""
    create_new = """    reinit_completion(&device->startup_completion);
    wake_up_process(pTask);
    AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, ("AR6000: -hifEnableFunc\\n"));
"""
    return replace_once(text, create_old, create_new,
                        "HIF startup completion arm")


def patch_driver_source(text: str) -> str:
    """Keep ar6_softc alive until every teardown consumer has finished.

    ar6_softc is netdev-private storage.  The vendor order called
    free_netdev() before cfg80211 teardown and four firmware-buffer frees,
    turning every later access through ``ar`` into a use-after-free.  Physical
    #226 evidence stopped immediately after wlan0/phy0 removal in that window.
    """
    if CFG_BEFORE_TRANSPORT_MARKER in text and NETDEV_LIFETIME_MARKER not in text:
        text = replace_once(
            text,
            "    /* N3DS_ATH6KL_CFG80211_BEFORE_TRANSPORT: unregister userspace-visible\n",
            "    /* N3DS_ATH6KL_NETDEV_LIFETIME /\n"
            "     * N3DS_ATH6KL_CFG80211_BEFORE_TRANSPORT: unregister userspace-visible\n",
            "preserve netdev lifetime contract marker")
    if NETDEV_LIFETIME_MARKER in text:
        marker = text.index(NETDEV_LIFETIME_MARKER)
        destroy_end = text.index("-ar6000_destroy", marker)
        managed = text[marker:destroy_end]
        if managed.count("free_netdev(dev);") != 1:
            raise RuntimeError("marked driver teardown has invalid netdev free count")
        if managed.index("ar6k_cfg80211_deinit(ar);") > managed.index("free_netdev(dev);"):
            raise RuntimeError("marked driver teardown still frees before cfg80211")
        if managed.index("kfree(ar->fw_data);") > managed.index("free_netdev(dev);"):
            raise RuntimeError("marked driver teardown still frees before firmware buffers")
        if CFG_BEFORE_TRANSPORT_MARKER not in managed:
            old_cfg = """    /* N3DS_ATH6KL_NETDEV_LIFETIME: ar6_softc is netdev-private.
     * Keep it alive through cfg80211 and firmware teardown; freeing it here
     * made AP-failure rollback use freed memory and hard-lock the kernel. */
    ar6k_cfg80211_deinit(ar);

"""
            if old_cfg not in text:
                raise RuntimeError("marked teardown lacks migratable cfg80211 block")
            text = replace_once(text, old_cfg, "", "move cfg80211 before transport")
            anchor = """    ar->arWlanState = WLAN_DISABLED;
    if (ar->arHtcTarget != NULL) {
"""
            replacement = """    ar->arWlanState = WLAN_DISABLED;

    /* N3DS_ATH6KL_NETDEV_LIFETIME /
     * N3DS_ATH6KL_CFG80211_BEFORE_TRANSPORT: unregister userspace-visible
     * netdev/wiphy state and drain cfg80211 work while HTC/HIF are still
     * alive.  #228 AP rollback destroyed the transport first; cfg80211 then
     * blocked after device_del(/ieee80211/phy0) while flushing work that
     * could no longer complete. */
    if (unregister && is_netdev_registered) {
        A_PRINTF("N3DS ath6kl teardown: unregister_netdev begin\\n");
        unregister_netdev(dev);
        is_netdev_registered = 0;
        A_PRINTF("N3DS ath6kl teardown: unregister_netdev done\\n");
    }
    A_PRINTF("N3DS ath6kl teardown: cfg80211 begin\\n");
    ar6k_cfg80211_deinit(ar);
    A_PRINTF("N3DS ath6kl teardown: cfg80211 done\\n");

    if (ar->arHtcTarget != NULL) {
"""
            text = replace_once(text, anchor, replacement,
                                "cfg80211-before-transport insertion")
            old_unregister = """    /* Free up the device data structure */
    if (unregister && is_netdev_registered) {\t\t
        unregister_netdev(dev);
        is_netdev_registered = 0;
    }
"""
            text = replace_once(text, old_unregister,
                                "    /* netdev and cfg80211 were drained before transport teardown. */\n",
                                "remove late netdev unregister")
        return text

    old = """    free_netdev(dev);

    ar6k_cfg80211_deinit(ar);
"""
    new = """    /* N3DS_ATH6KL_NETDEV_LIFETIME: ar6_softc is netdev-private.
     * Keep it alive through cfg80211 and firmware teardown; freeing it here
     * made AP-failure rollback use freed memory and hard-lock the kernel. */
    ar6k_cfg80211_deinit(ar);
"""
    text = replace_once(text, old, new, "ath6kl premature netdev free")
    return replace_once(
        text,
        "    kfree(ar->fw_data);\n\n"
        "    AR_DEBUG_PRINTF(ATH_DEBUG_INFO,(\"-ar6000_destroy \\n\"));\n",
        "    kfree(ar->fw_data);\n\n"
        "    /* No ar/ar6_softc consumer may follow this point. */\n"
        "    free_netdev(dev);\n\n"
        "    AR_DEBUG_PRINTF(ATH_DEBUG_INFO,(\"-ar6000_destroy \\n\"));\n",
        "ath6kl final netdev free")


def main() -> None:
    for path in (DEFCONFIG, DOTCONFIG, WIFI_C, HIF_C, HIF_H, DRIVER_C):
        if not path.is_file():
            raise SystemExit("missing canonical reloadable Wi-Fi source: " + str(path))
    patch_config(DEFCONFIG)
    patch_config(DOTCONFIG)
    original = WIFI_C.read_text(encoding="utf-8")
    updated = patch_wifi(original)
    if updated != original:
        WIFI_C.write_text(updated, encoding="utf-8")
    original_hif = HIF_C.read_text(encoding="utf-8")
    updated_hif = patch_hif_source(original_hif)
    if updated_hif != original_hif:
        HIF_C.write_text(updated_hif, encoding="utf-8")
    original_header = HIF_H.read_text(encoding="utf-8")
    updated_header = patch_hif_header(original_header)
    if updated_header != original_header:
        HIF_H.write_text(updated_header, encoding="utf-8")
    original_driver = DRIVER_C.read_text(encoding="utf-8")
    updated_driver = patch_driver_source(original_driver)
    if updated_driver != original_driver:
        DRIVER_C.write_text(updated_driver, encoding="utf-8")
    print("patch_wifi_reloadable_driver: reloadable STA/AP boundary installed")


if __name__ == "__main__":
    main()
