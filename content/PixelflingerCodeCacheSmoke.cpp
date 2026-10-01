#include <stdint.h>
#include <stdio.h>

#include "codeflinger/CodeCache.h"
#include "codeflinger/GGLAssembler.h"

using android::Assembly;
using android::AssemblyKey;
using android::CodeCache;
using android::sp;

static int testRegisterPressureUnwind()
{
    android::RegisterAllocator::RegisterFile regs;
    const int allocatable[] = {
        0, 1, 2, 3, 12, 14, 4, 5, 6, 7, 8, 9, 10, 11
    };
    for (unsigned i = 0; i < sizeof(allocatable) / sizeof(allocatable[0]); i++)
        regs.reserve(allocatable[i]);

    {
        android::RegisterAllocator::Scratch scratch(regs);
        if (scratch.obtain() != android::ARMAssemblerInterface::SP ||
                !(regs.status() &
                  android::RegisterAllocator::RegisterFile::OUT_OF_REGISTERS)) {
            fprintf(stderr, "register exhaustion did not return the SP sentinel\n");
            return 1;
        }
    }

    /* Both cleanup paths must leave the permanent stack register reserved. */
    regs.recycle(android::ARMAssemblerInterface::SP);
    if (regs.countFreeRegs() != 0) {
        fprintf(stderr, "register-pressure unwind released SP\n");
        return 1;
    }
    regs.reset();
    if (regs.status() != 0 || regs.countFreeRegs() != 14) {
        fprintf(stderr, "register allocator reset did not restore invariants\n");
        return 1;
    }
    return 0;
}

int main()
{
    if (testRegisterPressureUnwind())
        return 1;

    sp<Assembly> assembly = new Assembly(4096);
    if (assembly->size() < 8) {
        fprintf(stderr, "Assembly allocation failed\n");
        return 1;
    }

    /* mov r0, #42; bx lr */
    assembly->base()[0] = 0xe3a0002a;
    assembly->base()[1] = 0xe12fff1e;
    assembly->resize(8);

    CodeCache cache(4096);
    const AssemblyKey<uint32_t> key(0x3d5c0deU);
    if (cache.cache(key, assembly) < 0) {
        fprintf(stderr, "CodeCache rejected generated code\n");
        return 1;
    }

    typedef int (*GeneratedFunction)();
    GeneratedFunction function =
            reinterpret_cast<GeneratedFunction>(assembly->base());
    const int result = function();
    if (result != 42) {
        fprintf(stderr, "generated function returned %d\n", result);
        return 1;
    }

    printf("PASS: PixelFlinger register-pressure unwind preserved SP\n");
    printf("PASS: Pixelflinger CodeCache executed generated ARM code\n");
    return 0;
}
