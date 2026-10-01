#!/usr/bin/env python3
"""Remove the unsafe AR6014 diag shortcut and make transient DSR errors safe."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")
DIAG = ROOT / "drivers/staging/ath6k_legacy/miscdrv/common_drv.c"
HIF = ROOT / "drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"


diag = DIAG.read_text()
fast = """int
ar6000_ReadDataDiag(struct hif_device *hifDevice, u32 address,
                    u8 *data, u32 length)
{
    u32 count;
    int status = 0;

    /* N3DS_AR6014_DIAG_PAGE_FASTPATH: the diagnostic window's upper address
     * bytes are unchanged for 64 consecutive words.  With the whole transfer
     * serialized, program them once per 256-byte page and advance using the
     * low byte only.  On any short-write failure, retry that word through the
     * conservative full-address helper before giving up. */
    mutex_lock(&ar6000_diag_lock);
    for (count = 0; count < length; count += 4, address += 4) {
        if (count == 0 || (address & 0xff) == 0) {
            status = ar6000_SetAddressWindowRegister(hifDevice,
                    WINDOW_READ_ADDR_ADDRESS, address);
        } else {
            status = HIFReadWrite(hifDevice, WINDOW_READ_ADDR_ADDRESS,
                    (u8 *)&address, sizeof(u8), HIF_WR_SYNC_BYTE_INC, NULL);
        }
        if (!status)
            status = HIFReadWrite(hifDevice, WINDOW_DATA_ADDRESS,
                    &data[count], sizeof(u32), HIF_RD_SYNC_BYTE_INC, NULL);
        if (status) {
            status = __ar6000_ReadRegDiag(hifDevice, address,
                                          (u32 *)&data[count]);
            if (status)
                break;
        }
    }
    mutex_unlock(&ar6000_diag_lock);
    return status;
}
"""
safe = """int
ar6000_ReadDataDiag(struct hif_device *hifDevice, u32 address,
                    u8 *data, u32 length)
{
    u32 count;
    int status = 0;

    /* N3DS_AR6014_DIAG_CONSERVATIVE_PANIC_FIX: LSB-only address-window
     * advancement produced a physical SDIO/HTC DSR failure and kernel panic.
     * Program the complete target address for every word.  The scan harvester
     * is now only 16 KiB, so correctness no longer costs multiple minutes. */
    mutex_lock(&ar6000_diag_lock);
    for (count = 0; count < length; count += 4, address += 4) {
        status = __ar6000_ReadRegDiag(hifDevice, address,
                                      (u32 *)&data[count]);
        if (status)
            break;
    }
    mutex_unlock(&ar6000_diag_lock);
    return status;
}
"""
if "N3DS_AR6014_DIAG_PAGE_FASTPATH" in diag:
    if diag.count(fast) != 1:
        raise SystemExit("unsafe diagnostic page-fastpath hunk not found exactly once")
    diag = diag.replace(fast, safe)
elif "N3DS_AR6014_DIAG_CONSERVATIVE_PANIC_FIX" not in diag:
    raise SystemExit("neither unsafe nor corrected diagnostic reader found")
DIAG.write_text(diag)


hif = HIF.read_text()
old = """    atomic_set(&device->irqHandling, 0);
    AR_DEBUG_ASSERT(status == 0 || status == A_ECANCELED);
    AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, ("AR6000: -hifIRQHandler\\n"));
"""
new = """    atomic_set(&device->irqHandling, 0);
    /* N3DS_HIF_DSR_NONFATAL_RECOVERY: the physical AR6014 can return a
     * transient SDIO error while diagnostic traffic is in flight.  This old
     * vendor debug assertion halted the entire kernel.  Leave the interrupt
     * boundary clean and let the installed 10 ms card-IRQ poller retry. */
    if (status != 0 && status != A_ECANCELED)
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 HIF DSR transient status=%d; poller will retry\\n",
             status));
    AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, ("AR6000: -hifIRQHandler\\n"));
"""
if "N3DS_HIF_DSR_NONFATAL_RECOVERY" not in hif:
    if hif.count(old) != 1:
        raise SystemExit("HIF DSR assertion hunk not found exactly once")
    hif = hif.replace(old, new)
HIF.write_text(hif)

print("patch_wifi_irq_panic_recovery: conservative diag reads + nonfatal DSR retry")
