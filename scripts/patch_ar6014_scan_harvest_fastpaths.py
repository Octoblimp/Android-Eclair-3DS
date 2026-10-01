#!/usr/bin/env python3
"""Make the Nintendo AR6014 target-RAM scan harvest fast and serialized."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one source anchor, found {count}")
    return text.replace(old, new)


# 1. Avoid two context switches for every synchronous four-byte diagnostic
# window transaction when there is no asynchronous request to preserve ahead
# of it. This is the hardware-measured path from the public AR6014 bring-up.
hif_path = ROOT / "drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"
hif = hif_path.read_text()
if "N3DS_HIF_SYNC_CALLER_FASTPATH" not in hif:
    hif = replace_once(
        hif,
        """/* queue a read/write request */
static unsigned int n3ds_hif_sync_trace_budget = 16;
""",
        """/* N3DS_HIF_SYNC_CALLER_FASTPATH: the AR6014 scan-result fallback
 * reads target RAM through tens of thousands of four-byte diagnostic-window
 * transactions. Sending each synchronous transfer through async_task costs
 * two context switches. When its queue is empty, sdio_claim_host() supplies
 * the same serialization and the caller can execute the transfer directly. */
static bool hif_sync_fastpath = true;
module_param(hif_sync_fastpath, bool, 0644);
MODULE_PARM_DESC(hif_sync_fastpath,
                 "run synchronous HIF requests directly while the async queue is idle");

/* queue a read/write request */
static unsigned int n3ds_hif_sync_trace_budget = 16;
""",
        "HIF fast-path declaration",
    )
    hif = replace_once(
        hif,
        """            AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, ("AR6000: Execution mode: %s\\n", 
                        (request & HIF_ASYNCHRONOUS)?"Async":"Synch"));
            busrequest = hifAllocateBusRequest(device);
""",
        """            AR_DEBUG_PRINTF(ATH_DEBUG_TRACE, ("AR6000: Execution mode: %s\\n", 
                        (request & HIF_ASYNCHRONOUS)?"Async":"Synch"));

            if ((request & HIF_SYNCHRONOUS) && hif_sync_fastpath &&
                !in_interrupt() && !irqs_disabled()) {
                bool idle;

                spin_lock_irqsave(&device->asynclock, flags);
                idle = device->asyncreq == NULL;
                spin_unlock_irqrestore(&device->asynclock, flags);

                if (idle) {
                    sdio_claim_host(device->func);
                    status = __HIFReadWrite(device, address, buffer, length,
                                            request & ~HIF_SYNCHRONOUS,
                                            NULL);
                    sdio_release_host(device->func);
                    return status;
                }
            }

            busrequest = hifAllocateBusRequest(device);
""",
        "HIF fast-path body",
    )
    hif_path.write_text(hif)
    print("Applied AR6014 synchronous HIF caller fast path")
else:
    print("AR6014 synchronous HIF caller fast path already present")


# 2. Move the 4/8/16/24/128-byte WiFi FIFO copies into the hard IRQ instead
# of waking the threaded handler for each one. SD-sized blocks stay threaded.
sdhc_path = ROOT / "drivers/platform/nintendo3ds/ctr_sdhc.c"
sdhc = sdhc_path.read_text()
if "N3DS_SDIO_INLINE_SHORT_PIO" not in sdhc:
    sdhc = replace_once(
        sdhc,
        """#define SDHC_SDIO_POLL_MS\t10

static void ctr_sdhc_sdio_arm(struct ctr_sdhc *host, bool enable)
""",
        """#define SDHC_SDIO_POLL_MS\t10

/* N3DS_SDIO_INLINE_SHORT_PIO: all AR6014 register and HTC mailbox
 * transactions are at most 128 bytes. Copy those in the hard IRQ and keep
 * 512-byte storage-style transfers on the threaded path. */
static unsigned int pio_inline_max = 128;
module_param(pio_inline_max, uint, 0644);
MODULE_PARM_DESC(pio_inline_max,
                 "largest FIFO block copied in hard IRQ context");

static void ctr_sdhc_sdio_arm(struct ctr_sdhc *host, bool enable)
""",
        "short PIO declaration",
    )
    sdhc = replace_once(
        sdhc,
        """\t\tif (int_reg & (SDHC_STAT_RX_READY | SDHC_STAT_TX_REQUEST)) {
\t\t\tret = IRQ_WAKE_THREAD;
\t\t\tbreak;
\t\t}
""",
        """\t\tif (int_reg & (SDHC_STAT_RX_READY | SDHC_STAT_TX_REQUEST)) {
\t\t\tif (host->data && host->data->blksz <= pio_inline_max)
\t\t\t\tctr_sdhc_pio(host);
\t\t\telse
\t\t\t\tret = IRQ_WAKE_THREAD;
\t\t\tbreak;
\t\t}
""",
        "short PIO IRQ branch",
    )
    sdhc_path.write_text(sdhc)
    print("Applied AR6014 short-transfer inline PIO path")
else:
    print("AR6014 short-transfer inline PIO path already present")


# 3. The diagnostic window is one shared target register set. A scan sweep,
# debug-log read, or other diagnostic access must not interleave its address
# and data phases with another caller.
diag_path = ROOT / "drivers/staging/ath6k_legacy/miscdrv/common_drv.c"
diag = diag_path.read_text()
if "N3DS_AR6014_DIAG_WINDOW_SERIALIZATION" not in diag:
    diag = replace_once(
        diag,
        '#include "a_config.h"\n',
        '#include <linux/mutex.h>\n\n#include "a_config.h"\n',
        "diagnostic mutex include",
    )
    diag = replace_once(
        diag,
        """static bool                    g_ModuleDebugInit = false;

#ifdef ATH_DEBUG_MODULE
""",
        """static bool                    g_ModuleDebugInit = false;

/* N3DS_AR6014_DIAG_WINDOW_SERIALIZATION: the target exposes one shared
 * address/data window, so a complete multiword operation owns it. */
static DEFINE_MUTEX(ar6000_diag_lock);

#ifdef ATH_DEBUG_MODULE
""",
        "diagnostic mutex declaration",
    )
    start = diag.index("int\nar6000_ReadRegDiag(")
    end = diag.index("\nint\nar6k_ReadTargetRegister", start)
    replacement = r'''static int
__ar6000_ReadRegDiag(struct hif_device *hifDevice, u32 address, u32 *data)
{
    int status;

    status = ar6000_SetAddressWindowRegister(hifDevice,
                                             WINDOW_READ_ADDR_ADDRESS,
                                             address);
    if (status)
        return status;

    status = HIFReadWrite(hifDevice, WINDOW_DATA_ADDRESS, (u8 *)data,
                          sizeof(u32), HIF_RD_SYNC_BYTE_INC, NULL);
    if (status)
        AR_DEBUG_PRINTF(ATH_LOG_ERR,
                        ("Cannot read from WINDOW_DATA_ADDRESS\n"));
    return status;
}

static int
__ar6000_WriteRegDiag(struct hif_device *hifDevice, u32 address, u32 *data)
{
    int status;

    status = HIFReadWrite(hifDevice, WINDOW_DATA_ADDRESS, (u8 *)data,
                          sizeof(u32), HIF_WR_SYNC_BYTE_INC, NULL);
    if (status) {
        AR_DEBUG_PRINTF(ATH_LOG_ERR,
                        ("Cannot write 0x%x to WINDOW_DATA_ADDRESS\n", *data));
        return status;
    }
    return ar6000_SetAddressWindowRegister(hifDevice,
                                           WINDOW_WRITE_ADDR_ADDRESS,
                                           address);
}

int
ar6000_ReadRegDiag(struct hif_device *hifDevice, u32 *address, u32 *data)
{
    int status;

    mutex_lock(&ar6000_diag_lock);
    status = __ar6000_ReadRegDiag(hifDevice, *address, data);
    mutex_unlock(&ar6000_diag_lock);
    return status;
}

int
ar6000_WriteRegDiag(struct hif_device *hifDevice, u32 *address, u32 *data)
{
    int status;

    mutex_lock(&ar6000_diag_lock);
    status = __ar6000_WriteRegDiag(hifDevice, *address, data);
    mutex_unlock(&ar6000_diag_lock);
    return status;
}

int
ar6000_ReadDataDiag(struct hif_device *hifDevice, u32 address,
                    u8 *data, u32 length)
{
    u32 count;
    int status = 0;

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

int
ar6000_WriteDataDiag(struct hif_device *hifDevice, u32 address,
                     u8 *data, u32 length)
{
    u32 count;
    int status = 0;

    mutex_lock(&ar6000_diag_lock);
    for (count = 0; count < length; count += 4, address += 4) {
        status = __ar6000_WriteRegDiag(hifDevice, address,
                                       (u32 *)&data[count]);
        if (status)
            break;
    }
    mutex_unlock(&ar6000_diag_lock);
    return status;
}
'''
    diag = diag[:start] + replacement + diag[end:]
    diag_path.write_text(diag)
    print("Applied AR6014 diagnostic-window serialization")
else:
    print("AR6014 diagnostic-window serialization already present")
