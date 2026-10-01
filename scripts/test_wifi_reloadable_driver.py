#!/usr/bin/env python3
"""Static regression contract for the reloadable AR6002 STA/AP boundary."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    patch = (ROOT / "scripts/patch_wifi_reloadable_driver.py").read_text(encoding="utf-8")
    hif_source = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c").read_text(encoding="utf-8")
    hif_header = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/include/hif_internal.h").read_text(encoding="utf-8")
    driver_source = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c").read_text(encoding="utf-8")
    wifi_source = Path(f"{A3DS_ROOT}/third_party/libhardware_legacy/wifi/wifi.c").read_text(encoding="utf-8")
    initramfs = (ROOT / "scripts/build_minimal_initramfs.sh").read_text(encoding="utf-8")
    kernel = (ROOT / "scripts/build_kernel.sh").read_text(encoding="utf-8")
    pipeline = (ROOT / "scripts/rebuild_everything.sh").read_text(encoding="utf-8")
    for token in ("CONFIG_ATH6K_LEGACY=m", "CONFIG_MODULES=y",
                  "CONFIG_MODULE_UNLOAD=y", "/n3ds/modules/ath6kl.ko",
                  "/system/lib/modules/ath6kl.ko",
                  'fwmode=1 ifname=wlan0', "wifi_load_driver",
                  "wifi_unload_driver", "rmmod(DRIVER_MODULE_NAME)",
                  "self-contained module loader", "init_module(module"):
        assert token in patch, token
    for token in ("N3DS_WIFI_INITRAMFS_MODULE", "/n3ds/modules/ath6kl.ko",
                  "/system/lib/modules/ath6kl.ko", "driver_module_path",
                  "N3DS_WIFI_MODULE_FALLBACK",
                  "/sys/class/net/wlan0", "wait_for_driver_interface",
                  "N3DS_WIFI_INTERFACE_READY", "WIFI_DRIVER_INTERFACE_RETRIES"):
        assert token in wifi_source, token
        assert token in patch, token
    assert 'WIFI_DRIVER_MODULE_PATH         "/lib/modules/ath6kl.ko"' not in wifi_source
    assert wifi_source.index("driver_module_path()") < wifi_source.index(
        "insmod(module_path, DRIVER_MODULE_ARG)")
    assert wifi_source.index("wait_for_driver_interface()") < wifi_source.index(
        'property_set(DRIVER_PROP_NAME, "ok")')
    for token in ("N3DS_WIFI_INITRAMFS_MODULE",
                  "n3ds/modules/ath6kl.ko", "cmp -s"):
        assert token in initramfs, token
    assert "usr/lib/modules/ath6kl.ko" not in initramfs
    for token in ("N3DS_ATH6KL_STARTUP_TEARDOWN",
                  "wait_for_completion(&device->startup_completion)",
                  "reinit_completion(&device->startup_completion)",
                  "complete(&device->startup_completion)",
                  "init_completion(&device->startup_completion)",
                  "struct completion startup_completion;"):
        assert token in patch, token
    startup_init = re.findall(
        r"^[ \t]*init_completion\(&device->startup_completion\);[ \t]*$",
        hif_source,
        re.MULTILINE,
    )
    assert len(startup_init) == 1, (
        "startup_completion must have one real init_completion line; "
        "reinit_completion is not initialization"
    )
    assert hif_source.index(startup_init[0]) < hif_source.index(
        "reinit_completion(&device->startup_completion)")
    assert hif_source.index(startup_init[0]) < hif_source.index(
        "wait_for_completion(&device->startup_completion)")
    assert "kthread_stop(device->startup_task)" not in hif_source
    assert "device->startup_task = pTask" not in hif_source
    assert "struct task_struct* startup_task;" not in hif_header
    destroy_start = driver_source.index("void\nar6000_destroy(struct net_device")
    destroy_end = driver_source.index("static void disconnect_timer_handler",
                                      destroy_start)
    destroy = driver_source[destroy_start:destroy_end]
    assert "N3DS_ATH6KL_NETDEV_LIFETIME" in destroy
    assert destroy.count("free_netdev(dev);") == 1
    assert destroy.index("ar6k_cfg80211_deinit(ar);") < destroy.index("free_netdev(dev);")
    assert destroy.index("kfree(ar->fw_data);") < destroy.index("free_netdev(dev);")
    assert destroy.index("unregister_netdev(dev);") < destroy.index("ar6k_cfg80211_deinit(ar);")
    assert destroy.index("ar6k_cfg80211_deinit(ar);") < destroy.index("HTCDestroy(ar->arHtcTarget);")
    assert destroy.index("ar6k_cfg80211_deinit(ar);") < destroy.index("HIFReleaseDevice(ar->arHifDevice);")
    assert "N3DS_ATH6KL_CFG80211_BEFORE_TRANSPORT" in destroy
    for token in ("zImage modules", "ath6kl.ko", "system/lib/modules"):
        assert token in kernel, token
    assert "run patch_wifi_reloadable_driver.py" in pipeline
    assert "run test_wifi_reloadable_driver.py" in pipeline
    assert pipeline.index("run patch_wifi_reloadable_driver.py") < pipeline.index(
        "run build_kernel.sh")
    print("wifi_reloadable_driver: PASS")


if __name__ == "__main__":
    main()
