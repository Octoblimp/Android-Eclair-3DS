#!/usr/bin/env python3
"""Static regression for the bounded AR6014 host power-cycle boundary."""
from a3ds_paths import A3DS_ROOT

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "scripts/patch_n3ds_wifi_sdio_recovery.py"
LINUX = Path(f"{A3DS_ROOT}/third_party/linux")


def load_patcher():
    spec = importlib.util.spec_from_file_location("sdio_recovery", PATCH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    patcher = load_patcher()
    source = (LINUX / "drivers/platform/nintendo3ds/ctr_sdhc.c").read_text()
    header = (LINUX / "drivers/platform/nintendo3ds/ctr_sdhc.h").read_text()
    source = patcher.patch_source(source)
    header = patcher.patch_header(header)
    for marker in (
        "N3DS_WIFI_SDIO_RECOVERY",
        "wifi_recover_store",
        "mmc_remove_host(host->mmc)",
        "gpiod_set_value_cansleep(host->wifi_en, 0)",
        "gpiod_set_value_cansleep(host->wifi_en, 1)",
        "host->mmc->rescan_entered = 0",
        "host->init_trace_done = false",
        "ret = mmc_add_host(host->mmc)",
        "flush_delayed_work(&host->mmc->detect)",
        "if (!host->mmc->card)",
        "WiFi SDIO recovery complete; card present",
        "DEVICE_ATTR(wifi_recover, 0200",
        "host->host_registered = true",
    ):
        assert marker in source, marker
    assert "wifi_en; /* N3DS_WIFI_SDIO_RECOVERY */" in header
    assert "struct mutex recovery_lock" in header
    remove = source.index("mmc_remove_host(host->mmc)")
    rescan = source.index("host->mmc->rescan_entered = 0")
    add = source.index("ret = mmc_add_host(host->mmc)", rescan)
    flush = source.index("flush_delayed_work(&host->mmc->detect)", add)
    card = source.index("if (!host->mmc->card)", flush)
    success = source.index("WiFi SDIO recovery complete; card present", card)
    assert remove < rescan < add < flush < card < success
    assert patcher.patch_source(source) == source
    assert patcher.patch_header(header) == header
    print("n3ds_wifi_sdio_recovery: PASS (root-only bounded power cycle)")


if __name__ == "__main__":
    main()
