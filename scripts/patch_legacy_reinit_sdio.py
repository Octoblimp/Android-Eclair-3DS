from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"
with open(path) as f:
    content = f.read()

with open(path[:path.rindex("/")] + "/hif.c") as f:
    pass  # sanity: same path, no-op

start_marker = "int ReinitSDIO(struct hif_device *device)\n{"
end_marker = "    sdio_release_host(func);\n    AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, (\"AR6000: -ReinitSDIO \\n\"));\n\n    return (err) ? A_ERROR : 0;\n}"

start_idx = content.index(start_marker)
end_idx = content.index(end_marker, start_idx) + len(end_marker)
assert start_idx != -1 and end_idx != -1

old_block = content[start_idx:end_idx]

new_block = '''int ReinitSDIO(struct hif_device *device)
{
    /* Phase 2 (WiFi bring-up, legacy AR6002 driver port): this manual
     * bus reinit sequence hand-rolls SD/SDIO card bring-up (CMD0/CMD5/
     * CMD3/CMD7, high-speed CCCR negotiation) using mmc_host/mmc_card
     * fields (host->ocr, MMC_STATE_HIGHSPEED, mmc_card_set_highspeed(),
     * mmc_card_highspeed()) that were removed outright from the kernel's
     * MMC core between this driver's original era and now -- not
     * renamed, genuinely gone, since the core manages this state
     * internally today. It's only reached from the HIF_DEVICE_POWER_UP
     * path after a full HIF_DEVICE_POWER_CUT (a suspend/power-cycle
     * recovery case), which isn't part of the initial association
     * bring-up this porting pass is targeting -- normal enumeration
     * already works via the standard mmc core path (confirmed: real
     * hardware reports "mmc0: new SDIO card at address 0001"). Stubbed
     * out rather than hand-porting untested low-level bus sequencing
     * against removed internals; revisit if/when suspend/resume power
     * cycling is actually being exercised.
     */
    return 0;
}'''

content = content[:start_idx] + new_block + content[end_idx:]

with open(path, 'w') as f:
    f.write(content)
print("OK")
