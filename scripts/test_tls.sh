#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
OUT="${ANDROID3DS_ROOT}"/build/bionic
GCC_INCLUDE="$("$GCC" -print-file-name=include)"
LIBGCC="$("$GCC" -print-libgcc-file-name)"

cat > /tmp/tls_test.c <<'EOF'
extern int __set_tls(void *ptr);

static unsigned int read_tpidruro(void) {
    unsigned int val;
    __asm__ volatile ("mrc p15, 0, %0, c13, c0, 3" : "=r"(val));
    return val;
}

void _start_c(void) {
    static void *tls_area[16];
    tls_area[0] = (void*)0xDEADBEEF;

    int ret = __set_tls((void*)tls_area);

    unsigned int got1 = read_tpidruro();

    /* do an intervening syscall (getpid) to see if it clobbers TLS reg */
    register int p0 __asm__("r0");
    register int p7 __asm__("r7") = 20; /* __NR_getpid */
    __asm__ volatile ("swi #0" : "=r"(p0) : "r"(p7));

    unsigned int got = read_tpidruro();
    (void)got1;

    /* write results directly via raw syscall so we don't depend on anything else */
    char buf[64];
    int i = 0;
    buf[i++] = 'r'; buf[i++] = 'e'; buf[i++] = 't'; buf[i++] = '=';
    if (ret < 0) { buf[i++] = '-'; ret = -ret; }
    if (ret == 0) buf[i++] = '0';
    else {
        char tmp[16]; int t=0;
        while (ret > 0) { tmp[t++] = '0' + (ret % 10); ret /= 10; }
        while (t > 0) buf[i++] = tmp[--t];
    }
    buf[i++] = ' '; buf[i++] = 'g'; buf[i++] = '1'; buf[i++] = '=';
    buf[i++] = '0'; buf[i++] = 'x';
    {
        int shift;
        for (shift = 28; shift >= 0; shift -= 4) {
            unsigned int nib = (got1 >> shift) & 0xf;
            buf[i++] = nib < 10 ? ('0' + nib) : ('a' + nib - 10);
        }
    }
    buf[i++] = ' '; buf[i++] = 'g'; buf[i++] = '2'; buf[i++] = '=';
    buf[i++] = '0'; buf[i++] = 'x';
    {
        int shift;
        for (shift = 28; shift >= 0; shift -= 4) {
            unsigned int nib = (got >> shift) & 0xf;
            buf[i++] = nib < 10 ? ('0' + nib) : ('a' + nib - 10);
        }
    }
    buf[i++] = '\n';

    register int r0 __asm__("r0") = 1; /* fd */
    register const char *r1 __asm__("r1") = buf;
    register int r2 __asm__("r2") = i;
    register int r7 __asm__("r7") = 4; /* __NR_write */
    __asm__ volatile ("swi #0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7));

    register int e0 __asm__("r0") = 0;
    register int e7 __asm__("r7") = 1; /* __NR_exit */
    __asm__ volatile ("swi #0" : "+r"(e0) : "r"(e7));
    __builtin_unreachable();
}
EOF

"$GCC" -nostdinc -nostdlib -std=gnu89 -fno-stack-protector -fno-pic -fno-builtin \
    -D__ARM_EABI__ -DHAVE_ARM_TLS_REGISTER \
    -isystem "$GCC_INCLUDE" \
    -I "$BIONIC/libc/include" \
    -I "$BIONIC/libc/kernel/common" \
    -I "$BIONIC/libc/kernel/arch-arm" \
    -I "$BIONIC/libc/arch-arm/include" \
    -c /tmp/tls_test.c -o /tmp/tls_test.o

cat > /tmp/tls_start.S <<'EOF'
.text
.globl _start
_start:
    bl _start_c
1:  b 1b
EOF
"$GCC" -nostdinc -c /tmp/tls_start.S -o /tmp/tls_start.o

"$GCC" -nostdlib -static /tmp/tls_start.o /tmp/tls_test.o \
    -Wl,--start-group "$OUT/libc.a" "$LIBGCC" -Wl,--end-group \
    -o /tmp/tls_test -Wl,-e,_start \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0
echo "=== built /tmp/tls_test ==="
"${ANDROID3DS_ROOT}"/toolchain/qemu/qemu-arm-static /tmp/tls_test
