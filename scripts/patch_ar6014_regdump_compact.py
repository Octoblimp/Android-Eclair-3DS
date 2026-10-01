"""Stop the target register dump from destroying the evidence around it.

When the NWM target asserts, ar6000_dump_target_assert_info() prints one line
per register.  regDumpCount is 60, so a single assert emits 60 consecutive
lines -- and the diagnostic window that captures the Mobile Data failure keeps
only the last 65 lines of dmesg.  Every ``AR6002 AP:`` line and the entire WMI
command-history ring were therefore evicted by the very dump that was meant to
explain the failure, in both AP runs captured so far.

The registers were never the missing evidence; the commands around them were.
Eight words per line puts the same 60 registers in eight lines and leaves room
for the history that names the command in flight.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/miscdrv/common_drv.c"

MARKER = "N3DS_AR6014_REGDUMP_COMPACT"

DUMP_OLD = r"""        for (i = 0; i < regDumpCount; i++) {
            //ATHR_DISPLAY_MSG (_T(" %d :  0x%8.8X \n"), i, regDumpValues[i]);
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 REGDUMP base=0x%08x addr=0x%08x index=%u value=0x%08x \n",
                 regDumpArea, regDumpArea + (i * sizeof(u32)), i,
                 regDumpValues[i]));

#ifdef UNDER_CE
        /*
         * For Every logPrintf() Open the File so that in case of Crashes
         * We will have until the Last Message Flushed on to the File
         * So use logPrintf Sparingly..!!
         */
        tgtassertPrintf(ATH_DEBUG_TRC,
                        "AR6002 REGDUMP base=0x%08x addr=0x%08x index=%u value=0x%08x \n",
                        regDumpArea, regDumpArea + (i * sizeof(u32)), i,
                        regDumpValues[i]);
#endif
        }
"""

DUMP_NEW = r"""        /* N3DS_AR6014_REGDUMP_COMPACT: one line per register is 60 lines per
         * assert, which evicted every AR6002 AP: line and the whole WMI
         * command-history ring from the 65-line diagnostic window that
         * captures this failure.  Same data, eight lines. */
        for (i = 0; i < regDumpCount; i += 8) {
            char line[8 * 9 + 1];
            u32 chunk = regDumpCount - i;
            u32 w;

            if (chunk > 8) {
                chunk = 8;
            }
            for (w = 0; w < chunk; w++) {
                snprintf(line + (9 * w), 10, "%08x ", regDumpValues[i + w]);
            }
            line[9 * chunk] = 0;
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 REGDUMP base=0x%08x +%02u: %s\n",
                 regDumpArea, i, line));
        }
"""

HUNKS = (("compact the target register dump", DUMP_OLD, DUMP_NEW),)


def patch_common_drv(text):
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, "%s: expected exactly one anchor, found %d" % (
            name,
            text.count(old),
        )
        text = text.replace(old, new)
    return text


def main():
    text = TARGET.read_text()
    patched = patch_common_drv(text)
    if patched == text:
        print("patch_ar6014_regdump_compact: already applied")
        return
    TARGET.write_text(patched)
    print("patch_ar6014_regdump_compact: applied to %s" % TARGET)


if __name__ == "__main__":
    main()
