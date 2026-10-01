#!/usr/bin/env python3
"""Add a bounded AR6014 SDIO power-cycle boundary for firmware-mode rebinds."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")
SOURCE = ROOT / "drivers/platform/nintendo3ds/ctr_sdhc.c"
HEADER = ROOT / "drivers/platform/nintendo3ds/ctr_sdhc.h"
MARKER = "N3DS_WIFI_SDIO_RECOVERY"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_header(text: str) -> str:
    if "wifi_en; /* N3DS_WIFI_SDIO_RECOVERY */" in text:
        return text
    return replace_once(
        text,
        "\tstruct clk *sdclk;\n",
        "\tstruct clk *sdclk;\n"
        "\tstruct gpio_desc *wifi_en; /* N3DS_WIFI_SDIO_RECOVERY */\n"
        "\tstruct mutex recovery_lock;\n"
        "\tbool host_registered;\n",
        "SDIO recovery state",
    )


def patch_source(text: str) -> str:
    if MARKER in text:
        legacy = '''\tret = mmc_add_host(host->mmc);
\tif (!ret) {
\t\thost->host_registered = true;
\t\tdev_info(dev, "WiFi SDIO recovery complete\\n");
\t} else {
\t\tdev_err(dev, "WiFi SDIO recovery re-enumeration failed: %d\\n", ret);
\t}
'''
        repaired = '''\thost->mmc->rescan_entered = 0;
\thost->init_trace_done = false;
\tret = mmc_add_host(host->mmc);
\tif (!ret) {
\t\thost->host_registered = true;
\t\tflush_delayed_work(&host->mmc->detect);
\t\tif (!host->mmc->card)
\t\t\tret = -ENODEV;
\t}
\tif (!ret) {
\t\tdev_info(dev, "WiFi SDIO recovery complete; card present\\n");
\t} else {
\t\tdev_err(dev, "WiFi SDIO recovery re-enumeration failed: %d\\n", ret);
\t}
'''
        if "host->mmc->rescan_entered = 0" not in text:
            text = replace_once(text, legacy, repaired,
                                "#232 SDIO rescan migration")
        for required in ("wifi_recover_store", "DEVICE_ATTR(wifi_recover",
                         "host->wifi_en = wifi_en", "host_registered",
                         "host->mmc->rescan_entered = 0",
                         "flush_delayed_work(&host->mmc->detect)",
                         "if (!host->mmc->card)"):
            if required not in text:
                raise RuntimeError("marked SDIO recovery lacks " + required)
        return text

    text = replace_once(
        text,
        "#include <linux/gpio/consumer.h>\n",
        "#include <linux/gpio/consumer.h>\n#include <linux/mutex.h>\n",
        "mutex include",
    )
    text = replace_once(
        text,
        "\tstruct ctr_sdhc *host;\n\n\tdev = &pdev->dev;\n",
        "\tstruct ctr_sdhc *host;\n\tstruct gpio_desc *wifi_en;\n\n"
        "\tdev = &pdev->dev;\n",
        "WiFi GPIO lifetime",
    )
    old_power = '''\t{
\t\tstruct gpio_desc *wifi_en;

\t\twifi_en = devm_gpiod_get(dev, "wifi-enable", GPIOD_OUT_LOW);
\t\tif (IS_ERR(wifi_en)) {
\t\t\tret = PTR_ERR(wifi_en);
\t\t\treturn dev_err_probe(dev, ret,
\t\t\t\t\t     "WiFi power GPIO unavailable\\n");
\t\t}

\t\tdev_info(dev, "WiFi power GPIO low; holding reset for 100 ms\\n");
\t\tmsleep(100);
\t\tgpiod_set_value_cansleep(wifi_en, 1);
\t\tdev_info(dev, "WiFi power GPIO high; waiting 50 ms before SDIO\\n");
\t\tmsleep(50);
\t}
'''
    new_power = '''\twifi_en = devm_gpiod_get(dev, "wifi-enable", GPIOD_OUT_LOW);
\tif (IS_ERR(wifi_en)) {
\t\tret = PTR_ERR(wifi_en);
\t\treturn dev_err_probe(dev, ret,
\t\t\t\t     "WiFi power GPIO unavailable\\n");
\t}

\tdev_info(dev, "WiFi power GPIO low; holding reset for 100 ms\\n");
\tmsleep(100);
\tgpiod_set_value_cansleep(wifi_en, 1);
\tdev_info(dev, "WiFi power GPIO high; waiting 50 ms before SDIO\\n");
\tmsleep(50);
'''
    text = replace_once(text, old_power, new_power, "persistent WiFi GPIO")
    text = replace_once(
        text,
        "\thost->sdclk = sdclk;\n",
        "\thost->sdclk = sdclk;\n"
        "\thost->wifi_en = wifi_en;\n"
        "\tmutex_init(&host->recovery_lock);\n"
        "\thost->host_registered = false;\n",
        "SDIO recovery initialization",
    )

    ops_anchor = "static const struct mmc_host_ops ctr_sdhc_ops = {\n"
    recovery = r'''/* N3DS_WIFI_SDIO_RECOVERY: fwmode is loaded only at target boot.  A
 * failed AP/STA module transition can leave the soldered AR6014 alive while
 * the MMC core still believes the old SDIO card is enumerated.  Expose one
 * root-only, synchronous recovery edge: remove the card, power-cycle it, and
 * let the normal MMC core enumerate a fresh function. */
static ssize_t wifi_recover_store(struct device *dev,
                                  struct device_attribute *attr,
                                  const char *buf, size_t count)
{
	struct ctr_sdhc *host = dev_get_drvdata(dev);
	int ret;

	if (!host || !sysfs_streq(buf, "1"))
		return -EINVAL;

	mutex_lock(&host->recovery_lock);
	dev_info(dev, "WiFi SDIO recovery begin\n");
	if (host->host_registered) {
		mmc_remove_host(host->mmc);
		host->host_registered = false;
	}
	del_timer_sync(&host->timeout_timer);
	del_timer_sync(&host->sdio_timer);
	host->sdio_irq_on = false;
	gpiod_set_value_cansleep(host->wifi_en, 0);
	msleep(100);
	ctr_sdhc_reset(host);
	gpiod_set_value_cansleep(host->wifi_en, 1);
	msleep(50);
	host->mmc->rescan_entered = 0;
	host->init_trace_done = false;
	ret = mmc_add_host(host->mmc);
	if (!ret) {
		host->host_registered = true;
		flush_delayed_work(&host->mmc->detect);
		if (!host->mmc->card)
			ret = -ENODEV;
	}
	if (!ret) {
		dev_info(dev, "WiFi SDIO recovery complete; card present\n");
	} else {
		dev_err(dev, "WiFi SDIO recovery re-enumeration failed: %d\n", ret);
	}
	mutex_unlock(&host->recovery_lock);
	return ret ? ret : count;
}

static DEVICE_ATTR(wifi_recover, 0200, NULL, wifi_recover_store);

'''
    text = replace_once(text, ops_anchor, recovery + ops_anchor,
                        "SDIO recovery sysfs boundary")

    old_add = "\tmmc_add_host(mmc);\n\tpm_suspend_ignore_children(&pdev->dev, 1);\n"
    new_add = '''\tret = mmc_add_host(mmc);
\tif (ret)
\t\tgoto free_mmc;
\thost->host_registered = true;
\tret = device_create_file(dev, &dev_attr_wifi_recover);
\tif (ret) {
\t\tmmc_remove_host(mmc);
\t\thost->host_registered = false;
\t\tgoto free_mmc;
\t}
\tpm_suspend_ignore_children(&pdev->dev, 1);
'''
    return replace_once(text, old_add, new_add, "SDIO recovery attribute")


def main() -> None:
    if not SOURCE.is_file() or not HEADER.is_file():
        raise SystemExit("missing canonical Nintendo 3DS SDHC source")
    source = patch_source(SOURCE.read_text(encoding="utf-8"))
    header = patch_header(HEADER.read_text(encoding="utf-8"))
    SOURCE.write_text(source, encoding="utf-8")
    HEADER.write_text(header, encoding="utf-8")
    print("patch_n3ds_wifi_sdio_recovery: installed")


if __name__ == "__main__":
    main()
