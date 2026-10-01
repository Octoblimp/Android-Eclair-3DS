#!/usr/bin/env python3
"""Harden arm9linuxfw SD PIO using the current Luma3DS production sequence.

The inherited driver is the older fastboot-era variant.  Under sustained
four-core New3DS I/O it reports immediate TMIO write errors.  Keep the bounded
command/recovery work from patch_arm9_sd_recovery.py, but use Luma3DS's safer
clock programming, controller setup, standard OCR, and alignment-independent
FIFO copies.  ARM11 SMP, 804 MHz mode, and PL310 remain untouched.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
SDMMC = ROOT / "third_party/arm9linuxfw/source/hw/sdmmc.c"
SDMMC_H = ROOT / "third_party/arm9linuxfw/include/hw/sdmmc.h"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


header = SDMMC_H.read_text()
if "N3DS_LUMA_SD_CLOCK_SEQUENCE" not in header:
    header = replace_once(
        header,
        """static inline void setckl(u32 data)
{
	sdmmc_write16(REG_SDCLKCTL, data & 0xFF);
	sdmmc_write16(REG_SDCLKCTL, 1u<<8 | (data & 0x2FF));
}""",
        """/* N3DS_LUMA_SD_CLOCK_SEQUENCE: stop, change the complete divider,
 * then restart the SD clock.  This is the sequence used by current Luma3DS;
 * the inherited pair of raw writes transiently programmed only eight bits. */
static inline void setckl(u32 data)
{
	sdmmc_mask16(REG_SDCLKCTL, 0x100, 0);
	sdmmc_mask16(REG_SDCLKCTL, 0x2FF, data & 0x2FF);
	sdmmc_mask16(REG_SDCLKCTL, 0, 0x100);
}""",
        "SD clock programming",
    )
SDMMC_H.write_text(header)


sdmmc = SDMMC.read_text()
if "N3DS_LUMA_SD_STABILITY" not in sdmmc:
    sdmmc = replace_once(
        sdmmc,
        "#define DATA32_SUPPORT\n",
        """#define DATA32_SUPPORT

/* N3DS_LUMA_SD_STABILITY: the ARM11 performance configuration remains at
 * four cores, full retail LGR2 clock, and PL310.  Stabilize the independent
 * ARM9 TMIO path using current Luma3DS's production register sequence and
 * alignment-safe FIFO copies instead of disabling New3DS performance. */
""",
        "stability marker",
    )

    sdmmc = replace_once(
        sdmmc,
        """\tsdmmc_write16(REG_SDSTATUS0, 0);
\tsdmmc_write16(REG_SDSTATUS1, 0);
\tsdmmc_mask16(REG_DATACTL32, 0x1800, 0x400);
\tsdmmc_write16(REG_SDCMDARG0, args & 0xFFFF);""",
        """\tsdmmc_write16(REG_SDSTATUS0, 0);
\tsdmmc_write16(REG_SDSTATUS1, 0);
\t/* Match current Luma3DS: disable the FIFO request IRQ bits without
\t * asserting the older fastboot-only 0x400 state on every command. */
\tsdmmc_mask16(REG_DATACTL32, 0x1800, 0);
\tsdmmc_write16(REG_SDCMDARG0, args & 0xFFFF);""",
        "DATACTL command setup",
    )

    pointer_start = sdmmc.index("\tu32 size = ctx->size;", sdmmc.index("static void sdmmc_send_command"))
    pointer_end = sdmmc.index("\tu16 status0 = 0;", pointer_start)
    sdmmc = (
        sdmmc[:pointer_start]
        + """\tu32 size = ctx->size;
\tconst u16 blkSize = sdmmc_read16(REG_SDBLKLEN32);
\tu8 *rDataPtr = ctx->rData;
\tconst u8 *tDataPtr = ctx->tData;
\tbool rUseBuf = rDataPtr != NULL;
\tbool tUseBuf = tDataPtr != NULL;
"""
        + sdmmc[pointer_end:]
    )

    read_old = """\t\t\t\tif (rUseBuf && size >= blkSize) {
\t\t\t\t\tsdmmc_mask16(REG_SDSTATUS1, TMIO_STAT1_RXRDY, 0);
\t\t\t\t\tfor (u32 i = 0; i < blkSize; i += 16) {
\t\t\t\t\t\t*rDataPtr32++ = sdmmc_read32(REG_SDFIFO32);
\t\t\t\t\t\t*rDataPtr32++ = sdmmc_read32(REG_SDFIFO32);
\t\t\t\t\t\t*rDataPtr32++ = sdmmc_read32(REG_SDFIFO32);
\t\t\t\t\t\t*rDataPtr32++ = sdmmc_read32(REG_SDFIFO32);
\t\t\t\t\t}
\t\t\t\t\tsize -= blkSize;
\t\t\t\t}"""
    read_new = """\t\t\t\tif (rUseBuf && size >= blkSize) {
\t\t\t\t\tsdmmc_mask16(REG_SDSTATUS1, TMIO_STAT1_RXRDY, 0);
\t\t\t\t\tfor (u32 i = 0; i < blkSize; i += 4) {
\t\t\t\t\t\tu32 data = sdmmc_read32(REG_SDFIFO32);
\t\t\t\t\t\t*rDataPtr++ = data;
\t\t\t\t\t\t*rDataPtr++ = data >> 8;
\t\t\t\t\t\t*rDataPtr++ = data >> 16;
\t\t\t\t\t\t*rDataPtr++ = data >> 24;
\t\t\t\t\t}
\t\t\t\t\tsize -= blkSize;
\t\t\t\t}"""
    sdmmc = replace_once(sdmmc, read_old, read_new, "alignment-safe read FIFO")

    write_old = """\t\t\t\tif (tUseBuf && size >= blkSize) {
\t\t\t\t\tsdmmc_mask16(REG_SDSTATUS1, TMIO_STAT1_TXRQ, 0);
\t\t\t\t\tfor (u32 i = 0; i < blkSize; i += 16) {
\t\t\t\t\t\tsdmmc_write32(REG_SDFIFO32, *tDataPtr32++);
\t\t\t\t\t\tsdmmc_write32(REG_SDFIFO32, *tDataPtr32++);
\t\t\t\t\t\tsdmmc_write32(REG_SDFIFO32, *tDataPtr32++);
\t\t\t\t\t\tsdmmc_write32(REG_SDFIFO32, *tDataPtr32++);
\t\t\t\t\t}
\t\t\t\t\tsize -= blkSize;
\t\t\t\t}"""
    write_new = """\t\t\t\tif (tUseBuf && size >= blkSize) {
\t\t\t\t\tsdmmc_mask16(REG_SDSTATUS1, TMIO_STAT1_TXRQ, 0);
\t\t\t\t\tfor (u32 i = 0; i < blkSize; i += 4) {
\t\t\t\t\t\tu32 data = *tDataPtr++;
\t\t\t\t\t\tdata |= (u32)*tDataPtr++ << 8;
\t\t\t\t\t\tdata |= (u32)*tDataPtr++ << 16;
\t\t\t\t\t\tdata |= (u32)*tDataPtr++ << 24;
\t\t\t\t\t\tsdmmc_write32(REG_SDFIFO32, data);
\t\t\t\t\t}
\t\t\t\t\tsize -= blkSize;
\t\t\t\t}"""
    sdmmc = replace_once(sdmmc, write_old, write_new, "alignment-safe write FIFO")

    sdmmc = sdmmc.replace("\n\t(void)rDataPtr8;\n\t(void)tDataPtr8;", "", 1)

    sdmmc = replace_once(
        sdmmc,
        """\thandleSD.tData = in;
\thandleSD.size = numsectors << 9;""",
        """\thandleSD.rData = NULL;
\thandleSD.tData = in;
\thandleSD.size = numsectors << 9;""",
        "clear stale read pointer",
    )
    sdmmc = replace_once(
        sdmmc,
        """\thandleSD.rData = out;
\thandleSD.size = numsectors << 9;""",
        """\thandleSD.rData = out;
\thandleSD.tData = NULL;
\thandleSD.size = numsectors << 9;""",
        "clear stale write pointer",
    )

    sdmmc = replace_once(
        sdmmc,
        """void sdmmc_init()
{
\t//NAND""",
        """void sdmmc_init()
{
\t/* Current Luma3DS InitSD sequence: fully reset the FS interface before
\t * touching TMIO.  A halfword 0x340 write was an undocumented project
\t * workaround and left unrelated control bits asserted. */
\t*(vu32*)0x10000020 = 0;
\t*(vu32*)0x10000020 = 0x200;

\t//NAND""",
        "FS interface reset",
    )
    if sdmmc.count("*(vu16*)0x10006028 = 0x40E9;") != 2:
        raise SystemExit("SDOPT reset value: expected DATA32 and legacy matches")
    sdmmc = sdmmc.replace("*(vu16*)0x10006028 = 0x40E9;", "*(vu16*)0x10006028 = 0x40EE;")

    sdmmc = replace_once(
        sdmmc,
        """\thandleSD.clk = 0x20; // 523.655968 KHz
\thandleSD.devicenumber = 0;

\t// We need to send at least 74 clock pulses.
\tset_target(&handleSD);
\twait(2 * 128 * 74);""",
        """\thandleSD.clk = 0x80;
\thandleSD.devicenumber = 0;

\tset_target(&handleSD);
\t/* Production Luma3DS gives card-detect and power substantially more
\t * settling time than the inherited minimum-74-clock delay. */
\twait(1u << 22);
\tif (!(sdmmc_read16(REG_SDSTATUS0) & TMIO_STAT0_SIGSTATE))
\t\treturn -13;""",
        "SD power-up settling",
    )
    sdmmc = replace_once(sdmmc, "0x10100000 | temp", "0x00FF8000 | temp", "standard OCR voltage window")

    start = sdmmc.index("\t// Command Class 10 support", sdmmc.index("int SD_Init()"))
    end = sdmmc.index("\n\treturn 0;", start)
    stable_tail = """\thandleSD.total_size = sdmmc_calc_size((u8*)&handleSD.ret[0], -1);
\thandleSD.clk = 1;
\tsetckl(1);

\tsdmmc_send_command(&handleSD, 0x10507, handleSD.initarg << 0x10);
\tif (handleSD.error & 0x4) return -4;

\tsdmmc_send_command(&handleSD, 0x10437, handleSD.initarg << 0x10);
\tif (handleSD.error & 0x4) return -5;

\thandleSD.SDOPT = 1;
\tsdmmc_send_command(&handleSD, 0x10446, 0x2);
\tif (handleSD.error & 0x4) return -6;

\tsdmmc_send_command(&handleSD, 0x1040D, handleSD.initarg << 0x10);
\tif (handleSD.error & 0x4) return -7;

\tsdmmc_send_command(&handleSD, 0x10410, 0x200);
\tif (handleSD.error & 0x4) return -8;
\thandleSD.clk |= 0x200;
"""
    sdmmc = sdmmc[:start] + stable_tail + sdmmc[end:]

    sdmmc = replace_once(
        sdmmc,
        """\t// SD mount fix
\t*((vu16*)0x10000020) = 0x340;

\t// init SDMMC / NAND""",
        """\t// sdmmc_init() performs the complete current Luma3DS FS reset.

\t// init SDMMC / NAND""",
        "remove halfword FS workaround",
    )

if "N3DS_LUMA_SD_STABILITY" not in sdmmc or "0x00FF8000 | temp" not in sdmmc:
    raise SystemExit("Luma SD stability patch incomplete")
SDMMC.write_text(sdmmc)

print("patch_arm9_sd_luma_stability: production clock/init/OCR/alignment behavior applied")
