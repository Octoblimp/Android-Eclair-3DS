#!/usr/bin/env python3
"""Let PixelFlinger retry after register pressure instead of aborting.

GGLAssembler intentionally returns SP as a non-executable sentinel when all
allocatable ARM registers are busy.  Scratch used to treat that sentinel as a
real allocation, clear the permanent SP reservation during unwinding, and then
LOG_FATAL while the caller was trying to retry at a lower optimization level.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
HEADER = ROOT / "third_party/system_core/libpixelflinger/codeflinger/GGLAssembler.h"
SOURCE = ROOT / "third_party/system_core/libpixelflinger/codeflinger/GGLAssembler.cpp"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


header = HEADER.read_text()
if "N3DS_PIXELFLINGER_OOR_SENTINEL" not in header:
    header = replace_once(
        header,
        """        int obtain() { 
            int reg = mRegFile.obtain();
            mScratch |= 1<<reg;
            return reg;
        }
""",
        """        int obtain() {
            int reg = mRegFile.obtain();
            /* N3DS_PIXELFLINGER_OOR_SENTINEL: SP is the allocator's
             * non-executable out-of-register sentinel, not scratch storage.
             * Keeping it out of mScratch preserves the permanent SP reserve
             * while scanline() unwinds and retries a lower optimization. */
            if (reg != ARMAssemblerInterface::SP ||
                    !(mRegFile.status() & RegisterFile::OUT_OF_REGISTERS)) {
                mScratch |= 1<<reg;
            }
            return reg;
        }
""",
        "Scratch::obtain",
    )
HEADER.write_text(header)


source = SOURCE.read_text()
if "N3DS_PIXELFLINGER_OOR_RECYCLE" not in source:
    source = replace_once(
        source,
        """RegisterAllocator::RegisterFile::RegisterFile(const RegisterFile& rhs)
    : mRegs(rhs.mRegs), mTouched(rhs.mTouched)
""",
        """RegisterAllocator::RegisterFile::RegisterFile(const RegisterFile& rhs)
    : mRegs(rhs.mRegs), mTouched(rhs.mTouched), mStatus(rhs.mStatus)
""",
        "RegisterFile copy status",
    )
    source = replace_once(
        source,
        """void RegisterAllocator::RegisterFile::recycle(int reg)
{
    LOG_FATAL_IF(!isUsed(reg),
            "recycling unallocated register %d",
            reg);
    mRegs &= ~(1<<reg);
}

void RegisterAllocator::RegisterFile::recycleSeveral(uint32_t regMask)
{
    LOG_FATAL_IF((mRegs & regMask)!=regMask,
            "recycling unallocated registers "
            "(recycle=%08x, allocated=%08x, unallocated=%08x)",
            regMask, mRegs, mRegs&regMask);
    mRegs &= ~regMask;
}
""",
        """void RegisterAllocator::RegisterFile::recycle(int reg)
{
    /* N3DS_PIXELFLINGER_OOR_RECYCLE: obtain() returns SP only as an error
     * sentinel.  Cleanup must not release or reject that permanent reserve;
     * scanline() owns the lower-optimization retry decision. */
    if (reg == ARMAssemblerInterface::SP && (mStatus & OUT_OF_REGISTERS))
        return;
    LOG_FATAL_IF(!isUsed(reg),
            "recycling unallocated register %d",
            reg);
    mRegs &= ~(1<<reg);
}

void RegisterAllocator::RegisterFile::recycleSeveral(uint32_t regMask)
{
    if (mStatus & OUT_OF_REGISTERS)
        regMask &= ~(1U << ARMAssemblerInterface::SP);
    LOG_FATAL_IF((mRegs & regMask)!=regMask,
            "recycling unallocated registers "
            "(recycle=%08x, allocated=%08x, unallocated=%08x)",
            regMask, mRegs, mRegs&regMask);
    mRegs &= ~regMask;
}
""",
        "RegisterFile recycle",
    )
SOURCE.write_text(source)

for path, marker in ((HEADER, "N3DS_PIXELFLINGER_OOR_SENTINEL"),
                     (SOURCE, "N3DS_PIXELFLINGER_OOR_RECYCLE")):
    if path.read_text().count(marker) != 1:
        raise SystemExit(f"{marker} missing or duplicated")

print("patch_pixelflinger_register_exhaustion: SP sentinel survives retry cleanup")
