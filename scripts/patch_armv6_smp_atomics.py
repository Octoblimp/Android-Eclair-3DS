#!/usr/bin/env python3
"""Replace Eclair's explicitly UP-only ARMv6 atomics with SMP-safe helpers."""
from a3ds_paths import A3DS_ROOT

import re
from pathlib import Path


SOURCE = Path(
    f"{A3DS_ROOT}/third_party/system_core/"
    "libcutils/atomic-android-armv6.S"
)
MARKER = "N3DS_ARMV6_SMP_ATOMICS"
KUSER_CMPXCHG = "0xffff0fc0"

START = '''/* FIXME: On SMP systems memory barriers may be needed */
#warning  "this file is not safe with SMP systems"
'''

END = '''/*
 * ----------------------------------------------------------------------------
 * android_atomic_cmpxchg_64
'''

REPLACEMENT = r'''/* N3DS_ARMV6_SMP_ATOMICS:
 *
 * cutils/atomic.h promises that every operation synchronizes preceding memory,
 * but Eclair's original ARMv6 file explicitly warned that it was unsafe on
 * SMP and used bare LDREX/STREX with no data-memory barrier.  That can publish
 * Dalvik interface-cache versions out of order on the four ARM11 cores.
 *
 * Linux exposes __kuser_cmpxchg at 0xffff0fc0.  On ARMv6 SMP the helper wraps
 * its retrying LDREX/STREX sequence with the kernel's real SMP DMB operation.
 * Build the read/modify/write APIs from that helper so their historical return
 * contract is retained: all operations except write return the old value, and
 * cmpxchg returns zero on success and non-zero on mismatch.
 */

__n3ds_kuser_cmpxchg:
    ldr     r12, =0xffff0fc0
    bx      r12

/* input: r0=value, r1=address; output ignored */
android_atomic_write:
    b       android_atomic_swap

/* input: r0=address; output: old value */
android_atomic_inc:
    stmfd   sp!, {r4-r6, lr}
    mov     r6, r0
1:  ldr     r4, [r6]
    add     r1, r4, #1
    mov     r0, r4
    mov     r2, r6
    bl      __n3ds_kuser_cmpxchg
    cmp     r0, #0
    bne     1b
    mov     r0, r4
    ldmfd   sp!, {r4-r6, pc}

/* input: r0=address; output: old value */
android_atomic_dec:
    stmfd   sp!, {r4-r6, lr}
    mov     r6, r0
1:  ldr     r4, [r6]
    sub     r1, r4, #1
    mov     r0, r4
    mov     r2, r6
    bl      __n3ds_kuser_cmpxchg
    cmp     r0, #0
    bne     1b
    mov     r0, r4
    ldmfd   sp!, {r4-r6, pc}

/* input: r0=value, r1=address; output: old value */
android_atomic_add:
    stmfd   sp!, {r4-r6, lr}
    mov     r5, r0
    mov     r6, r1
1:  ldr     r4, [r6]
    add     r1, r4, r5
    mov     r0, r4
    mov     r2, r6
    bl      __n3ds_kuser_cmpxchg
    cmp     r0, #0
    bne     1b
    mov     r0, r4
    ldmfd   sp!, {r4-r6, pc}

/* input: r0=value, r1=address; output: old value */
android_atomic_and:
    stmfd   sp!, {r4-r6, lr}
    mov     r5, r0
    mov     r6, r1
1:  ldr     r4, [r6]
    and     r1, r4, r5
    mov     r0, r4
    mov     r2, r6
    bl      __n3ds_kuser_cmpxchg
    cmp     r0, #0
    bne     1b
    mov     r0, r4
    ldmfd   sp!, {r4-r6, pc}

/* input: r0=value, r1=address; output: old value */
android_atomic_or:
    stmfd   sp!, {r4-r6, lr}
    mov     r5, r0
    mov     r6, r1
1:  ldr     r4, [r6]
    orr     r1, r4, r5
    mov     r0, r4
    mov     r2, r6
    bl      __n3ds_kuser_cmpxchg
    cmp     r0, #0
    bne     1b
    mov     r0, r4
    ldmfd   sp!, {r4-r6, pc}

/* input: r0=value, r1=address; output: old value */
android_atomic_swap:
    stmfd   sp!, {r4-r6, lr}
    mov     r5, r0
    mov     r6, r1
1:  ldr     r4, [r6]
    mov     r0, r4
    mov     r1, r5
    mov     r2, r6
    bl      __n3ds_kuser_cmpxchg
    cmp     r0, #0
    bne     1b
    mov     r0, r4
    ldmfd   sp!, {r4-r6, pc}

/* input: r0=old, r1=new, r2=address; output: zero success, non-zero miss */
android_atomic_cmpxchg:
    b       __n3ds_kuser_cmpxchg


'''


def verify(text: str) -> None:
    if text.count(MARKER) != 1:
        raise RuntimeError("ARMv6 atomic source marker missing or duplicated")
    required = (
        MARKER,
        KUSER_CMPXCHG,
        "__n3ds_kuser_cmpxchg:",
        "android_atomic_write:",
        "android_atomic_inc:",
        "android_atomic_dec:",
        "android_atomic_add:",
        "android_atomic_and:",
        "android_atomic_or:",
        "android_atomic_swap:",
        "android_atomic_cmpxchg:",
    )
    for item in required:
        if item not in text:
            raise RuntimeError(f"patched atomic source missing {item}")
    if "this file is not safe with SMP systems" in text:
        raise RuntimeError("obsolete UP-only ARMv6 atomic implementation remains")
    if re.search(r"(?im)^\s*(ldrex|strex)\b", text):
        raise RuntimeError("raw UP-only exclusive instruction remains")


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"missing canonical source: {SOURCE}")
    text = SOURCE.read_text(encoding="utf-8")
    if MARKER not in text:
        if text.count(START) != 1 or text.count(END) != 1:
            raise RuntimeError("ARMv6 atomic source anchors missing or duplicated")
        before, rest = text.split(START, 1)
        _discarded, after = rest.split(END, 1)
        text = before + REPLACEMENT + END + after
        SOURCE.write_text(text, encoding="utf-8")
    verify(text)
    print("patch_armv6_smp_atomics: barrier-correct kuser atomics installed")


if __name__ == "__main__":
    main()
