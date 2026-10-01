#!/bin/bash
# Build and statically link app_process -- the zygote / app launcher.
#
# Single source file (app_main.cpp): creates an AndroidRuntime, and either
# starts ZygoteInit (--zygote) or runs a named Java class's main(). Static
# link, same reasoning as dalvikvm/init/servicemanager: no dynamic linker
# wired into this initramfs yet.
#
# Also links libservices_jni.a (build_services_jni.sh) -- the
# com.android.server.* natives SystemServer.java needs. These used to be a
# separate dlopen()'d libandroid_servers.so; that cannot work from a fully
# static binary (bionic's dlopen() stub always returns NULL -- see
# build_services_jni.sh's header comment and docs/HANDOFF.md's 2026-08-04
# softlock recap), so they're registered directly into gRegJNI[] instead,
# same as every other framework native.
#
# Prints the sorted unique list of undefined references on failure, same
# convention as link_dalvikvm.sh, so remaining porting gaps are visible at a
# glance instead of buried in linker noise.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
STRIP="$TC/arm-buildroot-linux-gnueabihf-strip"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
LSTL=$BIONIC/libstdc++
SYSCORE=$TP/system_core
FWBASE=$TP/frameworks/base
DALVIK=$TP/dalvik
BUILD="${ANDROID3DS_ROOT}"/build
OUT=$BUILD/app_process
LIBGCC="$("$GCC" -print-libgcc-file-name)"
# libutils' CallStack.cpp calls _Unwind_Backtrace/_Unwind_VRS_Get. On ARM
# those live in libgcc_eh.a, not the libgcc.a -print-libgcc-file-name
# reports, and a static link has to name it explicitly. Nothing referenced
# CallStack.o until libui entered the link with the compositor.
LIBGCC_EH="$("$GCC" -print-file-name=libgcc_eh.a)"

mkdir -p "$OUT/obj"

# Same C++ dialect/prologue as libandroid_runtime (see build_libandroid_runtime.sh).
CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks -fno-strict-aliasing \
-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DLINUX \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $BIONIC/libc/private \
-I $SYSCORE/include \
-I $FWBASE/include \
`# Both levels: AndroidRuntime.h says #include <nativehelper/jni.h>.` \
-I $DALVIK/libnativehelper/include \
-I $DALVIK/libnativehelper/include/nativehelper"

if [ ! -f "$BUILD/libservices_jni/libservices_jni.a" ]; then
    echo "libservices_jni.a missing -- run build_services_jni.sh first" >&2
    exit 1
fi

echo "=== app_main.cpp ==="
"$GXX" $CXXFLAGS -c "$FWBASE/cmds/app_process/app_main.cpp" -o "$OUT/obj/app_main.o"

# N3DS_STATIC_JNI_LIBS: LatinIME's BinaryDictionary natives.  Upstream these
# are libjni_latinime.so, System.loadLibrary()ed by an APK class -- the same
# static-binary dlopen() wall as libwebcore, except the caller is an app, so
# they cannot go in gRegJNI[]: RegisterNatives has to run against the class
# the APK's loader defines.  dalvik/vm/Native.c therefore resolves the name
# "libjni_latinime.so" to JNI_OnLoad_jni_latinime (weak) when dlopen() fails
# and calls it with the app's class loader in force, exactly as a real
# shared library's JNI_OnLoad would be.  /system/lib/libjni_latinime.so is a
# placeholder so PathClassLoader.findLibrary() still finds the name.
LATINIME=$TP/latinime/dictionary
LATINIME_FLAGS="-I $LATINIME/src -I $TP/icu4c/common"
echo "=== LatinIME dictionary natives (N3DS_STATIC_JNI_LIBS) ==="
"$GXX" $CXXFLAGS $LATINIME_FLAGS -DJNI_OnLoad=JNI_OnLoad_jni_latinime \
    -c "$LATINIME/jni/com_android_inputmethod_latin_BinaryDictionary.cpp" \
    -o "$OUT/obj/latinime_BinaryDictionary.o"
"$GXX" $CXXFLAGS $LATINIME_FLAGS \
    -c "$LATINIME/src/dictionary.cpp" -o "$OUT/obj/latinime_dictionary.o"

# Extract Static.o (LibUtilsFirstStatics) as a standalone object so it can
# be positioned first on the link line, ahead of app_main.o and the archive
# group -- "archive.a(member.o)" is not valid positional-file syntax for
# ld/gcc (it just tries to open that literal filename and fails), so this is
# an ar-extract, not a linker trick.
#
# Why this needs to be *first*, not just present: dalvikvm (link_dalvikvm.sh)
# only forces Static.o in with -u and that's enough, because it has no
# global C++ objects competing for init_array order. app_process does --
# every libbinder/libandroid_runtime TU with a static String8/String16 (e.g.
# IBinder's descriptor) -- and global constructors run in link order, not
# declaration order, across TUs. Observed under qemu: getEmptyString()'s
# SharedBuffer hadn't been initialized yet when IBinder's static String16
# constructor ran, segfaulting in android_atomic_inc() during
# SharedBuffer::acquire(). Linking this member first makes its constructor
# the first one call_array() runs.
"$AR" x --output "$OUT/obj" "$BUILD/libutils/libutils.a" Static.o

# 2026-08-05: same disease, different archive -- skia's image decoders.
#
# Symptom on hardware: "D/skia: --- SkImageDecoder::Factory returned null"
# followed by a NullPointerException out of ZygoteInit.preloadDrawables(),
# i.e. EVERY framework-res PNG failed to decode. The deployed binary
# contained the SkImageDecoder.cpp strings but not one libpng or libjpeg
# string, which is the whole story:
#
# Each decoder registers itself purely through a file-static constructor at
# the bottom of its own .cpp --
#
#     static SkTRegistry<SkImageDecoder*, SkStream*> gDReg(DFactory);
#
# -- and nothing anywhere else references any symbol those objects define
# (DFactory and gDReg are both `static`, so there is not even a symbol to
# -Wl,-u). In AOSP libskia is a shared library, so every member is linked in
# unconditionally and the constructors all run. Here it is a static archive
# linked into a static binary, so the linker pulls members out of the .a
# only on demand, finds no demand for these six, and drops them. The
# registry is therefore empty at runtime and Factory() has nothing to return
# -- which is also why libpng.a/libjpeg.a/libgif.a below contributed nothing
# despite being on the link line.
#
# Same failure mode as libutils' Static.o above, and the fix is the same
# shape: extract the members and link them as loose objects. Deliberately
# NOT --whole-archive on libskia.a -- that would drag in every port/ and
# effects/ member built into the archive, including ones whose dependencies
# were never built for this target.
"$AR" x --output "$OUT/obj" "$BUILD/skia/libskia.a" \
    SkImageDecoder_libpng.o \
    SkImageDecoder_libjpeg.o \
    SkImageDecoder_libgif.o \
    SkImageDecoder_libbmp.o \
    SkImageDecoder_libico.o \
    SkImageDecoder_wbmp.o

echo "=== link app_process ==="
"$GCC" -nostdlib -static \
    "$BUILD/bionic/crtbegin.o" \
    "$OUT/obj/Static.o" \
    "$OUT/obj/app_main.o" \
    "$OUT/obj/SkImageDecoder_libpng.o" \
    "$OUT/obj/SkImageDecoder_libjpeg.o" \
    "$OUT/obj/SkImageDecoder_libgif.o" \
    "$OUT/obj/SkImageDecoder_libbmp.o" \
    "$OUT/obj/SkImageDecoder_libico.o" \
    "$OUT/obj/SkImageDecoder_wbmp.o" \
    "$OUT/obj/latinime_BinaryDictionary.o" \
    "$OUT/obj/latinime_dictionary.o" \
    -Wl,--start-group \
        "$BUILD/libservices_jni/libservices_jni.a" \
        "$BUILD/libandroid_runtime/libandroid_runtime.a" \
        `# The WebKit engine. Upstream this was libwebcore.so, dlopen(3)ed
         # from WebViewCore's class initialiser; bionic dlopen() returns
         # NULL from a static executable, so it is linked in here and
         # registered from gRegJNI[] instead (see WebCoreJniRegistration.cpp).
         # It costs about 5.2 MB stripped. libxml2 is WebCore's own XML
         # parser and is built separately by build_libxml2_webkit.sh -- it is
         # not the system libexpat, which stays where it is below.` \
        "$BUILD/webkit_intermediates/libwebcore.a" \
        "$BUILD/libxml2_webkit/libxml2.a" \
        `# The audio client stack. The services (AudioFlinger,
         # AudioPolicyService, MediaPlayerService) are NOT here -- they
         # live in mediaserver and are reached over binder. What zygote
         # needs is the client halves that libandroid_runtime binds to:
         # AudioTrack, AudioRecord, AudioSystem, ToneGenerator, the
         # MediaPlayer proxy, plus SoundPool, which is genuinely
         # in-process -- it owns AudioTracks in the app itself.` \
        "$BUILD/audio/libsoundpool.a" \
        "$BUILD/audio/libmedia.a" \
        "$BUILD/libbinder/libbinder.a" \
        "$BUILD/libdvm/libdvm.a" \
        "$BUILD/libdex/libdex.a" \
        "$BUILD/libnativehelper/libnativehelper.a" \
        "$BUILD/libnativehelper/libnativehelper_register.a" \
        "$BUILD/libjavacore/libjavacore.a" \
        "$BUILD/skia/libskia.a" \
        "$BUILD/freetype/libft2.a" \
        "$BUILD/libpng/libpng.a" \
        "$BUILD/jpeg/libjpeg.a" \
        "$BUILD/libgif/libgif.a" \
        "$BUILD/icu4c/libicui18n.a" \
        "$BUILD/icu4c/libicuuc.a" \
        "$BUILD/icu4c/libicudata.a" \
        "$BUILD/openssl/libssl.a" \
        "$BUILD/openssl/libcrypto.a" \
        "$BUILD/sqlite/libsqlite.a" \
        "$BUILD/sqlite3_android/libsqlite3_android.a" \
        "$BUILD/expat/libexpat.a" \
        "$BUILD/fdlibm/libfdlibm.a" \
        "$BUILD/bionic_compat/libbionic_compat.a" \
        `# The compositor. android_view_Surface.cpp (now in
         # libandroid_runtime.a, now in gRegJNI[]) is what binds
         # android.view.Surface/SurfaceSession, which WindowManagerService
         # cannot construct without. libui pulls gralloc/libagl/
         # libpixelflinger in behind it.
         #
         # libgralloc_n3ds.a MUST precede libhardware.a -- it defines the
         # static hw_get_module() that replaces libhardware's dlopen-based
         # module lookup, and dlopen() unconditionally returns NULL in a
         # static binary.` \
        "$BUILD/libui/libui.a" \
        "$BUILD/libgralloc/libgralloc_n3ds.a" \
        "$BUILD/libagl/libagl.a" \
        "$BUILD/libpixelflinger/libpixelflinger.a" \
        "$BUILD/libhardware/libhardware.a" \
        "$BUILD/libhardware_legacy/libhardware_legacy.a" \
        "$BUILD/libutils/libutils.a" \
        "$BUILD/libnetutils/libnetutils.a" \
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/zlib/libz.a" \
        "$BUILD/libm/libm.a" \
        "$BUILD/libdl/libdl.a" \
        "$BUILD/bionic/libc.a" \
        "$LIBGCC" \
        "$LIBGCC_EH" \
    -Wl,--end-group \
    "$BUILD/bionic/crtend.o" \
    -o "$OUT/app_process" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    2>"$OUT/link.log"

grep -oE "undefined reference to \`[a-zA-Z0-9_:<>~,. ]+'" "$OUT/link.log" | sort -u
grep -v 'undefined reference to' "$OUT/link.log" | grep -vE '^\s*$' | head -30

if [ -f "$OUT/app_process" ]; then
    ls -la "$OUT/app_process"
    TC_NM="$TC/arm-buildroot-linux-gnueabihf-nm"
    if ! "$TC_NM" "$OUT/app_process" | grep -qE ' T JNI_OnLoad_jni_latinime$'; then
        echo "FATAL: JNI_OnLoad_jni_latinime is not defined in app_process (N3DS_STATIC_JNI_LIBS)" >&2
        exit 1
    fi
    echo "=== JNI_OnLoad_jni_latinime linked (N3DS_STATIC_JNI_LIBS) ==="

    if [ "${BUILD_ONLY:-0}" = 1 ]; then
        echo "=== BUILD_ONLY: link verified; rootfs overlay unchanged ==="
        exit 0
    fi

    # The overlay is the source of truth for sync_android_to_sdcard.sh.
    # A 2026-08-05 partial rebuild copied the fixed binary only to the card;
    # the next sync silently restored the stale overlay binary and brought
    # back the exact 0x104148 SkMallocPixelRef crash loop.  Deploy every
    # successful link atomically so a manual rebuild cannot create that
    # split-brain state again.
    DEST="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin/app_process
    mkdir -p "$(dirname "$DEST")"
    "$STRIP" -o "$DEST.new" "$OUT/app_process"
    chmod 755 "$DEST.new"
    mv -f "$DEST.new" "$DEST"
    echo "=== deployed app_process to rootfs overlay ==="
    ls -la "$DEST"
else
    echo "LINK FAILED -- no binary produced (full output: $OUT/link.log)"
    exit 1
fi
