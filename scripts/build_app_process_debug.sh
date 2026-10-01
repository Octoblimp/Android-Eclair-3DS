#!/bin/bash
# Debug variant of app_process, linked against liblog_fake instead of the
# real liblog -- see build_liblog_fake.sh for why.
#
# On 2026-08-03, real hardware ran `app_process /system/bin --zygote` via
# app_process_smoketest.sh and it returned exit status 0 after ~100ms with
# zero captured output. app_process links the REAL liblog, whose ALOG*/
# LOG_ALWAYS_FATAL calls go to /dev/log/main (the kernel logger char device)
# -- not stdout/stderr -- and there is no logcat in this image to read that
# device back. So "no output" does not mean "nothing happened"; it means
# whatever AndroidRuntime::start()/JNI_CreateJavaVM/ZygoteInit logged is
# sitting in a log buffer nobody reads. This variant routes all of that to
# stderr instead, which app_process_debug_smoketest.sh captures the same way
# dalvik_smoketest.sh already does for dalvikvm_debug.
#
# Do NOT ship this as the primary app_process -- diagnostic only, same rule
# as dalvikvm_debug.
#
# Also links libservices_jni.a (build_services_jni.sh) -- see
# build_app_process.sh's header comment for why these are linked directly
# instead of built as a separate dlopen()'d libandroid_servers.so.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
LSTL=$BIONIC/libstdc++
SYSCORE=$TP/system_core
FWBASE=$TP/frameworks/base
DALVIK=$TP/dalvik
BUILD="${ANDROID3DS_ROOT}"/build

# The host zygote test uses the same binary but swaps libcutils' device
# /dev/ashmem backend for AOSP's ashmem-host implementation.  Keep that
# opt-in so app_process_debug remains usable on physical hardware.
if [ "${QEMU_HOST_ASHMEM:-0}" = 1 ]; then
    OUT=$BUILD/app_process_qemu
    OUT_NAME=app_process_qemu
    CUTILS_ARCHIVE=$BUILD/libcutils_qemu/libcutils.a
    HOST_TEST_DEFINE=-DN3DS_QEMU_HOST_TEST
else
    OUT=$BUILD/app_process_debug
    OUT_NAME=app_process_debug
    CUTILS_ARCHIVE=$BUILD/libcutils/libcutils.a
    HOST_TEST_DEFINE=""
fi
LIBGCC="$("$GCC" -print-libgcc-file-name)"
# libutils' CallStack.cpp calls _Unwind_Backtrace/_Unwind_VRS_Get. On ARM
# those live in libgcc_eh.a, not the libgcc.a -print-libgcc-file-name
# reports, and a static link has to name it explicitly. Nothing referenced
# CallStack.o until libui entered the link with the compositor.
LIBGCC_EH="$("$GCC" -print-file-name=libgcc_eh.a)"

mkdir -p "$OUT/obj"

if [ ! -f "$BUILD/liblog_fake/liblog.a" ]; then
    echo "liblog_fake missing -- run build_liblog_fake.sh first" >&2
    exit 1
fi

CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks -fno-strict-aliasing \
-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \
$HOST_TEST_DEFINE \
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
-I $DALVIK/libnativehelper/include \
-I $DALVIK/libnativehelper/include/nativehelper"

if [ ! -f "$BUILD/libservices_jni/libservices_jni.a" ]; then
    echo "libservices_jni.a missing -- run build_services_jni.sh first" >&2
    exit 1
fi

if [ ! -f "$CUTILS_ARCHIVE" ]; then
    echo "$CUTILS_ARCHIVE missing" >&2
    exit 1
fi

echo "=== app_main.cpp (debug) ==="
"$GXX" $CXXFLAGS -c "$FWBASE/cmds/app_process/app_main.cpp" -o "$OUT/obj/app_main.o"

# N3DS_STATIC_JNI_LIBS: LatinIME's dictionary natives, exactly as
# build_app_process.sh links them, so test_latinime_qemu.sh can drive
# System.loadLibrary("jni_latinime") -> Native.c's built-in table ->
# JNI_OnLoad_jni_latinime -> openNative/getSuggestions on the real dictionary.
LATINIME=$TP/latinime/dictionary
LATINIME_FLAGS="-I $LATINIME/src -I $TP/icu4c/common"
echo "=== LatinIME dictionary natives (debug, N3DS_STATIC_JNI_LIBS) ==="
"$GXX" $CXXFLAGS $LATINIME_FLAGS -DJNI_OnLoad=JNI_OnLoad_jni_latinime \
    -c "$LATINIME/jni/com_android_inputmethod_latin_BinaryDictionary.cpp" \
    -o "$OUT/obj/latinime_BinaryDictionary.o"
"$GXX" $CXXFLAGS $LATINIME_FLAGS \
    -c "$LATINIME/src/dictionary.cpp" -o "$OUT/obj/latinime_dictionary.o"

# Same Static.o-first fix as build_app_process.sh -- see that script for why.
"$AR" x --output "$OUT/obj" "$BUILD/libutils/libutils.a" Static.o

# Image decoders register themselves only through file-static constructors.
# Link them as loose objects just like the shipping app_process; otherwise a
# diagnostic build reaches preloadResources() with an empty decoder registry
# and reports a host-test-only failure for every framework PNG.
"$AR" x --output "$OUT/obj" "$BUILD/skia/libskia.a" \
    SkImageDecoder_libpng.o \
    SkImageDecoder_libjpeg.o \
    SkImageDecoder_libgif.o \
    SkImageDecoder_libbmp.o \
    SkImageDecoder_libico.o \
    SkImageDecoder_wbmp.o

echo "=== link app_process_debug ==="
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
        `# The WebKit engine, same as build_app_process.sh. gRegJNI[]
         # names android::register_android_webkit_WebCore, which lives in
         # WebCoreJniRegistration.o inside this archive, so leaving it out
         # here is an undefined reference and not merely a smaller binary.` \
        "$BUILD/webkit_intermediates/libwebcore.a" \
        "$BUILD/libxml2_webkit/libxml2.a" \
        `# Same two archives as build_app_process.sh, and for the same
         # reason: libandroid_runtime.a now compiles six audio JNI
         # sources, so zygote references AudioTrack, AudioRecord,
         # AudioSystem, ToneGenerator, the MediaPlayer client proxy and
         # SoundPool. Only client halves belong here -- AudioFlinger,
         # AudioPolicyService and MediaPlayerService live in mediaserver
         # and are reached over binder. SoundPool is the exception: it
         # is genuinely in-process, owning AudioTracks in the app.
         #
         # This file is what test_zygote_preload_qemu.sh links, so it has
         # to track build_app_process.sh or the gate cannot run.` \
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
        "$CUTILS_ARCHIVE" \
        "$BUILD/liblog_fake/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/zlib/libz.a" \
        "$BUILD/libm/libm.a" \
        "$BUILD/libdl/libdl.a" \
        "$BUILD/bionic/libc.a" \
        "$LIBGCC" \
        "$LIBGCC_EH" \
    -Wl,--end-group \
    "$BUILD/bionic/crtend.o" \
    -o "$OUT/$OUT_NAME" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    2>"$OUT/link.log"

grep -oE "undefined reference to \`[a-zA-Z0-9_:<>~,. ]+'" "$OUT/link.log" | sort -u
grep -v 'undefined reference to' "$OUT/link.log" | grep -vE '^\s*$' | head -30

if [ -f "$OUT/$OUT_NAME" ]; then
    ls -la "$OUT/$OUT_NAME"
else
    echo "LINK FAILED -- no binary produced (full output: $OUT/link.log)"
    # build_app_process.sh has always exited 1 here. This copy did not, so a
    # failed link left the previous binary in place and reported success --
    # and test_zygote_preload_qemu.sh, which runs this script, then tested
    # whatever was there before. Same behaviour in both files now.
    exit 1
fi
