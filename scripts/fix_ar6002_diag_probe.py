"""Phase 2 / AR6002: probe host interest through the diagnostic window.

The AR6002 exposes two address spaces and two access mechanisms:

  BMI  (BMIReadMemory/BMIWriteMemory)  virtual  0x005xxxxx
  diag (ar6000_{Read,Write}RegDiag)    physical 0x001xxxxx, via AR6002_VTOP
                                       (vaddr & 0x001FFFFF)

The driver already reaches host interest through the diag path -- see
ar6000_set_host_app_area() and dbglog_get_debug_hdr_ptr(), both of which do
TARG_VTOP(HOST_INTEREST_ITEM_ADDRESS(...)) and then ar6000_ReadRegDiag.

Every writability measurement so far used BMI only, so "NOT WRITABLE" at
0x500400 may just mean the target's BMI handler range-checks that region,
while the diag window reaches it normally. That would resolve the standing
contradiction: Nintendo's NWM records 0x00500400 as the host-interest base
(config struct at 0x00154720, field +0x34), BMI refuses it, and the pristine
dump found no populated host_interest_s at either candidate.

Pure measurement -- reads the original word, writes a pattern, reads back,
restores. Deliberately avoids bmifn() so one failure doesn't abort the rest.
"""
from a3ds_paths import A3DS_ROOT

drv = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"

with open(drv) as f:
    c = f.read()


def replace_once(old, new, label):
    global c
    n = c.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    c = c.replace(old, new)


old_anchor = """static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

new_anchor = """/* Same probe as ar6002_probe_writable(), but through the SDIO diagnostic
 * window at physical addresses instead of BMI at virtual ones. If a region
 * shows NOT WRITABLE over BMI but WRITABLE here, the target's BMI handler is
 * range-checking it and host-interest writes need to go through diag. */
static void
ar6002_probe_diag_writable(struct ar6_softc *ar)
{
    static const u32 diag_addrs[] = {
        0x00500400,   /* NWM's recorded host-interest base */
        0x00500418,   /* base + 0x18  hi_dset_list_head    */
        0x00500454,   /* base + 0x54  hi_board_data        */
        0x0050046C,   /* base + 0x6c  hi_mbox_io_block_sz  */
        0x00520400,   /* the RAM candidate we switched to  */
        0x00524C00,   /* known BMI-writable: main_type1    */
        0x0053FE18,   /* known BMI-writable: database      */
    };
    u32 i;

    for (i = 0; i < sizeof(diag_addrs) / sizeof(diag_addrs[0]); i++) {
        u32 vaddr = diag_addrs[i];
        u32 paddr = TARG_VTOP(ar->arTargetType, vaddr);
        u32 addr, orig, pattern, back;

        addr = paddr;
        if (ar6000_ReadRegDiag(ar->arHifDevice, &addr, &orig) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 DIAG 0x%08x (phys 0x%08x): initial read FAILED\\n",
                 vaddr, paddr));
            continue;
        }

        pattern = 0x5A5A0000 | i;
        addr = paddr;
        if (ar6000_WriteRegDiag(ar->arHifDevice, &addr, &pattern) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 DIAG 0x%08x (phys 0x%08x): write FAILED (orig 0x%08x)\\n",
                 vaddr, paddr, orig));
            continue;
        }

        addr = paddr;
        if (ar6000_ReadRegDiag(ar->arHifDevice, &addr, &back) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 DIAG 0x%08x (phys 0x%08x): readback FAILED\\n",
                 vaddr, paddr));
            continue;
        }

        addr = paddr;
        ar6000_WriteRegDiag(ar->arHifDevice, &addr, &orig);

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 DIAG 0x%08x (phys 0x%08x): orig=0x%08x wrote=0x%08x read=0x%08x %s\\n",
             vaddr, paddr, orig, pattern, back,
             (back == pattern) ? "WRITABLE" : "*** NOT WRITABLE ***"));
    }
}

static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

replace_once(old_anchor, new_anchor, "add diag-window probe")

replace_once(
    """    ar6002_probe_writable(ar);
""",
    """    ar6002_probe_writable(ar);
    ar6002_probe_diag_writable(ar);
""",
    "call diag probe",
)

with open(drv, "w") as f:
    f.write(c)
print("OK")
