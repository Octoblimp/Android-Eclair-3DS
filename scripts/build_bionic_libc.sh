#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

# MODE=static (default) builds libc.a for statically linked executables --
# this is what boots on hardware today, and defaulting to it keeps that
# build byte-for-byte unchanged.
#
# MODE=shared builds libc.so for the dynamic linker world. The two differ by
# exactly three things, per bionic's own libc/Android.mk:
#   - -fPIC
#   - exidx_dynamic.c   replaces exidx_static.c
#   - libc_init_dynamic.c replaces libc_init_static.c
# Everything else -- including the fiddly explicit netbsd list that took a
# few tries to get right -- is shared, which is why this is one script with
# a switch rather than two scripts that will drift apart.
MODE="${MODE:-static}"

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-gcc-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic

if [ "$MODE" = "shared" ]; then
    OUT="${ANDROID3DS_ROOT}"/build/bionic_shared
    PIC_FLAGS="-fPIC"
else
    OUT="${ANDROID3DS_ROOT}"/build/bionic
    PIC_FLAGS="-fno-pic"
fi
LOG="$OUT/build.log"
mkdir -p "$OUT"

rm -rf "$OUT/obj"
mkdir -p "$OUT/obj"
: > "$LOG"

GCC_INCLUDE="$("$GCC" -print-file-name=include)"

# -DUSE_DL_PREFIX is part of libc_common_cflags in bionic's own
# libc/Android.mk, so this matches the genuine Android build. It does NOT
# rename malloc/free/calloc/realloc/memalign -- dlmalloc.h aliases those five
# back to the plain names whenever MALLOC_LEAK_CHECK is off, which it is
# here. What it does keep dl-prefixed is dlmalloc_trim /
# dlmalloc_walk_free_pages / dlmalloc_walk_heap, which is what Dalvik's heap
# code actually links against; without it those three only existed under
# their malloc_* names and libdvm failed to link.

# -fcommon restores the pre-GCC-10 handling of tentative definitions this
# 2009 codebase assumes. bionic has genuine duplicates -- unistd/brk.c and
# unistd/sbrk.c both write `char *__bionic_brk;' with no extern, and
# upstream builds both -- which -fno-common turns into two real .bss
# definitions and a "multiple definition" link error. Same root cause as
# the __evOptMonoTime collision in the netbsd files below, so it is applied
# to the whole library rather than patched in one more place at a time.
# The -D block below is bionic's own libc_common_cflags from
# libc/Android.mk, adopted wholesale. We previously carried only a handful
# of these and the omissions were not cosmetic:
#
#   -DUSE_LOCKS        dlmalloc's thread safety. Without it malloc/free do
#                      no locking at all -- fine for single-threaded init,
#                      a heap-corruption race the moment Dalvik (heavily
#                      multithreaded) starts allocating.
#   -DFLOATING_POINT   vfprintf/vfscanf's %e/%f/%g support. Without it
#                      printf("%f") silently does nothing useful.
#   -DANDROID_CHANGES  gates a lot of the NetBSD-derived code onto its
#                      Android variant. stdlib/strtod.c only #includes the
#                      absent "extern.h" when this is NOT defined, which is
#                      the sole reason strtod had to be skipped -- and a
#                      libc without strtod cannot do Double.parseDouble.
#   -DWITH_ERRLIST     sys_errlist/sys_nerr, used by strerror().
#   -DINET6            IPv6 in the resolver (was applied to netbsd only).
#   -DREALLOC_ZERO_BYTES_FREES, -D_LIBC, -DNEED_PSELECT, -DSOFTFLOAT
#                      round out upstream's set.
#
# -fstrict-aliasing is upstream's ARM setting too.
CFLAGS_COMMON="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector $PIC_FLAGS -fno-builtin -fcommon \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-return-type -Wno-attributes \
-DWITH_ERRLIST -DANDROID_CHANGES -DUSE_LOCKS -DREALLOC_ZERO_BYTES_FREES \
-D_LIBC=1 -DSOFTFLOAT -DFLOATING_POINT -DNEED_PSELECT=1 -DINET6 \
-fstrict-aliasing \
-D__ARM_EABI__ -DANDROID -DSK_RELEASE -DHAVE_ARM_TLS_REGISTER -DUSE_DL_PREFIX \
-isystem $GCC_INCLUDE \
-I $BIONIC/libc/string \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $BIONIC/libc/arch-arm/syscalls \
-I $BIONIC/libc/private \
-I $BIONIC/libc/stdio \
-I $BIONIC/libc/stdlib \
-I $BIONIC/libc/netbsd \
-I $BIONIC/libc/netbsd/resolv \
-I $BIONIC/libc/bionic \
-I $BIONIC/libm/include \
-I ${ANDROID3DS_ROOT}/third_party/system_core/include"

SRC_DIRS="
libc/arch-arm/syscalls
libc/arch-arm/bionic
libc/bionic
libc/stdio
libc/stdlib
libc/string
libc/unistd
libc/inet
libc/tzcode
"

# The netbsd/ tree is NOT globbed like the dirs above: it contains files that
# bionic's own libc/Android.mk deliberately leaves out of the build (the
# *_r.c reentrant variants, res_compat.c, res_random.c ...), which reference
# types and prototypes that don't exist in this configuration and fail to
# compile. This is the exact list from libc/Android.mk.
NETBSD_SRCS="
netbsd/gethnamaddr.c
netbsd/isc/ev_timers.c
netbsd/isc/ev_streams.c
netbsd/isc/android3ds_isc_stubs.c
netbsd/inet/nsap_addr.c
netbsd/resolv/__dn_comp.c
netbsd/resolv/__res_close.c
netbsd/resolv/__res_send.c
netbsd/resolv/herror.c
netbsd/resolv/res_comp.c
netbsd/resolv/res_data.c
netbsd/resolv/res_debug.c
netbsd/resolv/res_init.c
netbsd/resolv/res_mkquery.c
netbsd/resolv/res_query.c
netbsd/resolv/res_send.c
netbsd/resolv/res_state.c
netbsd/resolv/res_cache.c
netbsd/net/nsdispatch.c
netbsd/net/getaddrinfo.c
netbsd/net/getnameinfo.c
netbsd/net/getservbyname.c
netbsd/net/getservent.c
netbsd/net/base64.c
netbsd/net/getservbyport.c
netbsd/nameser/ns_name.c
netbsd/nameser/ns_parse.c
netbsd/nameser/ns_ttl.c
netbsd/nameser/ns_netint.c
netbsd/nameser/ns_print.c
netbsd/nameser/ns_samedomain.c
"

OK=0
FAIL=0
FAILED_FILES=""

for d in $SRC_DIRS; do
    for f in "$BIONIC/$d"/*.c "$BIONIC/$d"/*.S; do
        [ -e "$f" ] || continue
        base="$(basename "$f")"
        name="${base%.*}"
        ext="${base##*.}"
        # skip x86-only files, and the crt*.S files (built separately by
        # test_compile_bionic_crt.sh, which also renames them -- the
        # crtbegin.o/crtend.o naming mismatch was a real bring-up bug).
        case "$base" in
            atomics_x86.S|atomics_x86.c) continue ;;
            crtbegin_dynamic.S|crtbegin_static.S|crtend.S) continue ;;
        esac
        # Generic C string functions that the ARM build replaces with hand
        # written assembly. bionic's libc_common_src_files deliberately
        # omits these five from the string/ list and the TARGET_ARCH==arm
        # block supplies arch-arm/bionic/{memcmp,memcpy,memset}.S,
        # strlen.c.arm and ffs.S instead -- globbing the directory picks up
        # both copies.
        #
        # In the static build this was invisible: the linker only pulls the
        # first archive member that resolves a symbol, so which memset you
        # got depended on link order. --whole-archive (needed to make a .so
        # actually export anything) pulls both and it becomes a hard
        # "multiple definition" error. Skipping them here fixes the shared
        # build and makes the static one deterministic on the same
        # assembly Android actually ships.
        if [ "$d" = "libc/string" ]; then
            case "$base" in
                memcmp.c|memcpy.c|memset.c|strlen.c) continue ;;
            esac
        fi
        # Same story: stdlib/sha1hash.c and bionic/sha1.c both define
        # SHA1Init/Update/Final/Transform. Upstream's source list has only
        # bionic/sha1.c.
        if [ "$d" = "libc/stdlib" ] && [ "$base" = "sha1hash.c" ]; then
            continue
        fi
        # The static/dynamic pair: exactly one of each belongs in the build.
        if [ "$MODE" = "shared" ]; then
            case "$base" in
                exidx_static.c|libc_init_static.c) continue ;;
            esac
        else
            case "$base" in
                exidx_dynamic.c|libc_init_dynamic.c) continue ;;
            esac
        fi
        extra=""
        case "$base" in
            setjmp.S|_setjmp.S) extra="-DSOFTFLOAT" ;;
        esac
        objname="$(echo "$d/$name" | tr '/' '__').o"
        out="$OUT/obj/$objname"
        if "$GCC" $CFLAGS_COMMON $extra -c "$f" -o "$out" >>"$LOG" 2>&1; then
            OK=$((OK+1))
        else
            FAIL=$((FAIL+1))
            FAILED_FILES="$FAILED_FILES $d/$base"
        fi
    done
done

for f in $NETBSD_SRCS; do
    src="$BIONIC/libc/$f"
    [ -e "$src" ] || { echo "missing source: $f"; continue; }
    objname="$(echo "libc/${f%.c}" | tr '/' '__').o"
    # -DANDROID_CHANGES and -DINET6 are part of bionic's own
    # libc_common_cflags. The resolver files genuinely need them: res_init.c
    # only includes "resolv_private.h" (which is where res_state, MAXNS and
    # MAXRESOLVSORT live) under #ifdef ANDROID_CHANGES, falling back to the
    # public <resolv.h> otherwise, which declares none of them. Applied to
    # the netbsd files only rather than to all of libc, so the rest of a
    # libc that already boots on hardware is left bit-identical.
    #
    # -fcommon: eventlib_p.h declares `int __evOptMonoTime;' with no extern,
    # a tentative definition. Pre-GCC-10 that produced a common symbol the
    # linker merged across TUs; GCC 14 defaults to -fno-common, so
    # ev_timers.o and ev_streams.o each emit a real .bss definition and the
    # final link dies with "multiple definition of `__evOptMonoTime'".
    if "$GCC" $CFLAGS_COMMON -DANDROID_CHANGES -DINET6 -fcommon -c "$src" \
            -o "$OUT/obj/$objname" >>"$LOG" 2>&1; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1))
        FAILED_FILES="$FAILED_FILES $f"
    fi
done

echo "compiled OK: $OK"
echo "compiled FAIL: $FAIL"
if [ -n "$FAILED_FILES" ]; then
    echo "failed files:$FAILED_FILES"
fi

echo "=== archiving libc.a ==="
rm -f "$OUT/libc.a"
"$AR" rcs "$OUT/libc.a" "$OUT"/obj/*.o
echo "libc.a size:"
ls -la "$OUT/libc.a"

if [ "$MODE" = "shared" ]; then
    echo "=== linking libc.so ==="
    # --whole-archive: a shared library must EXPORT its symbols, but the
    # linker only pulls archive members that resolve an existing undefined
    # reference. Without this, libc.so comes out nearly empty.
    #
    # libdl.so is the one and only library libc.so may depend on (bionic's
    # Android.mk is emphatic about this). It must already be built.
    #
    # NOTE: libgcc.a is linked WITHOUT --exclude-libs here, deliberately.
    # arch-arm/bionic/libgcc_compat.c exists precisely so libc.so re-exports
    # the ARM EABI helpers (__aeabi_dadd, __adddf3, ...) for everything else
    # in the system to import. bionic's warning about --exclude-libs=libgcc.a
    # applies to the OTHER libraries, which must keep their private copies
    # private -- not to libc.so, which is the intended provider.
    LIBGCC="$("$GCC" -print-libgcc-file-name)"
    "$GCC" -nostdlib -shared -Wl,-soname,libc.so \
        -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
        -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
        -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
        -o "$OUT/libc.so" \
        -Wl,--whole-archive "$OUT/libc.a" -Wl,--no-whole-archive \
        "$OUT/../bionic_shared/libdl.so" \
        "$LIBGCC" \
        > "$OUT/link_libc.log" 2>&1 || {
            echo "libc.so LINK FAILED"
            grep -oE "undefined reference to \`[a-zA-Z0-9_.]+'" "$OUT/link_libc.log" | sort -u | head -30
            grep -v 'undefined reference to' "$OUT/link_libc.log" | grep -vE '^\s*$' | head -20
            exit 1
        }
    ls -la "$OUT/libc.so"
fi
