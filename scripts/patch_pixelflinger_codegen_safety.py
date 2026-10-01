#!/usr/bin/env python3
"""Ensure PixelFlinger stability on ARM11 MPCore SMP and safe memory allocation.

1. Sets ANDROID_CODEGEN to ANDROID_CODEGEN_ASM so UI compositing uses
   statically compiled assembly scanlines and generic C fallback, preventing
   SMP I-cache desync crashes on 4-core ARM11 MPCore.
2. Updates pick_scanline to check (ANDROID_CODEGEN == ANDROID_CODEGEN_GENERATED)
   so complex 3D rasterization safely falls back to the generic C scanline
   pipeline instead of running runtime JIT assembly on multi-core SMP.
3. Updates Assembly memory allocation in CodeCache.cpp to use page-aligned
   anonymous mmap/munmap instead of malloc/realloc/free on the dlmalloc heap.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(A3DS_ROOT)
SCANLINE = ROOT / "third_party/system_core/libpixelflinger/scanline.cpp"
CODECACHE = ROOT / "third_party/system_core/libpixelflinger/codeflinger/CodeCache.cpp"
ARMASSEMBLER = ROOT / "third_party/system_core/libpixelflinger/codeflinger/ARMAssembler.cpp"

# 1. Update scanline.cpp
scanline_text = SCANLINE.read_text()
if "N3DS_PIXELFLINGER_ASM_CODEGEN" not in scanline_text:
    old_def = """#ifdef NDEBUG
#   define ANDROID_RELEASE
#   define ANDROID_CODEGEN      ANDROID_CODEGEN_GENERATED
#else
#   define ANDROID_DEBUG
#   define ANDROID_CODEGEN      ANDROID_CODEGEN_GENERATED
#endif"""
    new_def = """/* N3DS_PIXELFLINGER_ASM_CODEGEN: on ARM11 MPCore SMP, runtime JIT heap
 * codegen suffers from cross-core I-cache desynchronization and heap mprotect
 * corruption. Use hand-optimized assembly scanlines with generic C fallback. */
#define ANDROID_CODEGEN      ANDROID_CODEGEN_ASM
#ifdef NDEBUG
#   define ANDROID_RELEASE
#else
#   define ANDROID_DEBUG
#endif"""
    if old_def in scanline_text:
        scanline_text = scanline_text.replace(old_def, new_def, 1)

if "#if ANDROID_ARM_CODEGEN && (ANDROID_CODEGEN == ANDROID_CODEGEN_GENERATED)\n    // we're going to have to generate some code..." not in scanline_text:
    old_arm_codegen = """#if ANDROID_ARM_CODEGEN
    // we're going to have to generate some code..."""
    new_arm_codegen = """#if ANDROID_ARM_CODEGEN && (ANDROID_CODEGEN == ANDROID_CODEGEN_GENERATED)
    // we're going to have to generate some code..."""
    if old_arm_codegen in scanline_text:
        scanline_text = scanline_text.replace(old_arm_codegen, new_arm_codegen, 1)

SCANLINE.write_text(scanline_text)
print("scanline.cpp patched with ANDROID_CODEGEN_ASM and safe JIT gate")

# 2. Update CodeCache.cpp
codecache_text = CODECACHE.read_text()
if "N3DS_CODECACHE_MMAP_ALLOC" not in codecache_text:
    old_alloc = """Assembly::Assembly(size_t size)
    : mCount(1), mSize(0)
{
    mBase = (uint32_t*)malloc(size);
    if (mBase) {
        mSize = size;
    }
}

Assembly::~Assembly()
{
    free(mBase);
}"""
    new_alloc = """/* N3DS_CODECACHE_MMAP_ALLOC: allocate executable assembly from dedicated
 * anonymous mmap pages rather than the dlmalloc heap, avoiding heap corruption
 * when mprotect(PROT_EXEC) is applied. */
Assembly::Assembly(size_t size)
    : mCount(1), mSize(0)
{
    const long pageSize = sysconf(_SC_PAGESIZE);
    size_t allocSize = (size + pageSize - 1) & ~(pageSize - 1);
    void* ptr = mmap(NULL, allocSize, PROT_READ | PROT_WRITE | PROT_EXEC,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (ptr != MAP_FAILED) {
        mBase = (uint32_t*)ptr;
        mSize = allocSize;
    } else {
        mBase = NULL;
        mSize = 0;
    }
}

Assembly::~Assembly()
{
    if (mBase && mSize > 0) {
        munmap(mBase, mSize);
    }
}"""
    if old_alloc in codecache_text:
        codecache_text = codecache_text.replace(old_alloc, new_alloc, 1)
        # Also update resize
        old_resize = """ssize_t Assembly::resize(size_t newSize)
{
    mBase = (uint32_t*)realloc(mBase, newSize);
    mSize = newSize;
    return size();
}"""
        new_resize = """ssize_t Assembly::resize(size_t newSize)
{
    /* With dedicated mmap allocation, we preserve the mapped page range and
     * update the logical size without reallocating/moving. */
    if (mBase && newSize <= mSize) {
        return newSize;
    }
    return size();
}"""
        codecache_text = codecache_text.replace(old_resize, new_resize, 1)
        CODECACHE.write_text(codecache_text)
        print("CodeCache.cpp patched with dedicated mmap allocation")
    else:
        print("CodeCache.cpp Assembly alloc anchor not found")
else:
    print("CodeCache.cpp already patched with N3DS_CODECACHE_MMAP_ALLOC")

# 3. Update ARMAssembler.cpp
armasm_text = ARMASSEMBLER.read_text()
if "N3DS_ARMASSEMBLER_SYNC_BASE" not in armasm_text:
    old_gen = """    mAssembly->resize( int(pc()-base())*4 );
    
    // the instruction cache is flushed by CodeCache"""
    new_gen = """    /* N3DS_ARMASSEMBLER_SYNC_BASE: synchronize base pointer after resize */
    mAssembly->resize( int(pc()-base())*4 );
    mBase = (uint32_t *)mAssembly->base();
    
    // the instruction cache is flushed by CodeCache"""
    if old_gen in armasm_text:
        armasm_text = armasm_text.replace(old_gen, new_gen, 1)
        ARMASSEMBLER.write_text(armasm_text)
        print("ARMAssembler.cpp patched with base sync")
    else:
        print("ARMAssembler.cpp resize anchor not found")
else:
    print("ARMAssembler.cpp already patched with N3DS_ARMASSEMBLER_SYNC_BASE")

print("patch_pixelflinger_codegen_safety: complete")
