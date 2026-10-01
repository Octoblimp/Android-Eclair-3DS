#!/bin/bash
# Build libservices_jni.a -- the native JNI glue com.android.server's Java
# classes (AlarmManagerService, BatteryService, HardwareService,
# KeyInputQueue, SensorService, SystemServer) need, statically linked
# directly into app_process (see build_app_process.sh /
# build_app_process_debug.sh) instead of a separate dlopen()'d
# libandroid_servers.so.
#
# REPLACES build_libandroid_servers.sh (2026-08-04 session). That approach
# built these sources into a real shared object loaded at runtime via
# System.loadLibrary("android_servers") -> dlopen(). That cannot work:
# app_process is a fully static executable (no PT_DYNAMIC, no PT_INTERP),
# and bionic/libdl/libdl.c's dlopen()/dlsym()/dlerror()/dlclose() are
# genuine stubs that unconditionally `return 0` -- the real ELF-loading
# implementation only exists in the dynamic linker (bionic/linker/dlfcn.c),
# which never runs for a statically linked binary (see
# scripts/build_libdl.sh's own header comment -- this was known and
# documented *before* libandroid_servers.so was built, just not
# cross-checked against it at the time). The previous session's boot that
# exercised this (softlocked_0426.jpg, see docs/HANDOFF.md) also uncovered
# two more real bugs the .so approach carried structurally, both now moot:
#   - AndroidRuntime::getRuntime() (core/jni/AndroidRuntime.cpp) returns a
#     file-scope-static `gCurRuntime`, set once by the real
#     AndroidRuntime::start(). A second copy of that translation unit
#     statically linked into a separate .so would have its own, always-NULL
#     copy -- system_init()'s `runtime->callStatic(...)` would have been a
#     null-pointer call.
#   - system_init()'s ProcessState::self()/defaultServiceManager() would
#     have opened a SECOND, independent /dev/binder fd in the same process,
#     not sharing app_process's own already-initialized ProcessState.
# Registering these natives directly into app_process's own gRegJNI[]
# (AndroidRuntime.cpp) -- the exact same mechanism every other framework
# native already uses -- avoids all three problems at once: no dlopen
# needed, one AndroidRuntime instance, one ProcessState/binder fd, and no
# second copy of Skia/SQLite/ICU/OpenSSL/libdvm's code+data resident in the
# same process (a real memory-pressure concern on a 256 MB/no-swap device).
# SystemServer.java's System.loadLibrary("android_servers") call is deleted
# to match (see that file) -- there is no longer a library to load.
#
# Upstream's services/jni/Android.mk also links libui and libsystem_server.
# Neither is built as its own module here (unchanged from the .so version):
#
#   - libui (frameworks/base/libs/ui) upstream is Camera/EGL/Surface/
#     GraphicBuffer/FramebufferNativeWindow -- all GPU-compositor plumbing
#     that doesn't exist yet (see docs/HANDOFF.md,
#     [[project_phase6_compositor_scope]]). The only thing services/jni
#     actually needs from it is EventHub.cpp (evdev input) + the KeyLayoutMap
#     it depends on, both self-contained (checked: no Surface/GraphicBuffer
#     includes). Compiled directly into this archive instead of pulling in
#     real libui.
#   - libsystem_server (cmds/system_server/library/system_init.cpp) provides
#     system_init(), which com_android_server_SystemServer.cpp's "init1"
#     native method calls directly. Upstream's version instantiates
#     SurfaceFlinger/AudioFlinger/CameraService/MediaPlayerService/
#     AudioPolicyService -- none of which exist here yet either. Patched in
#     place (see the file itself) to drop those calls, same precedent as the
#     GL removals in Canvas.cpp/ViewRoot.java, and compiled directly into
#     this archive instead of as its own libsystem_server.so.
#
# No onload.cpp here (unlike the .so version) -- JNI_OnLoad is a dlopen-only
# convention (the well-known symbol name System.loadLibrary()'s loader looks
# for); registration now happens through gRegJNI[] like everything else, so
# there's also no need for the sql__sqlite_jni.o JNI_OnLoad rename dance the
# .so version needed (that collision only existed because two JNI_OnLoad
# definitions competed to be *the* dlopen-visible one -- a static archive
# doesn't have that concept at all).
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
LSTL=$BIONIC/libstdc++
SYSCORE=$TP/system_core
FWBASE=$TP/frameworks/base
DALVIK=$TP/dalvik
JNI=$FWBASE/services/jni
UI=$FWBASE/libs/ui
BUILD="${ANDROID3DS_ROOT}"/build
OUT=$BUILD/libservices_jni

mkdir -p "$OUT/obj" "$OUT/log"
rm -f "$OUT"/obj/*.o "$OUT"/log/*.log

# Same C++ dialect/prologue as every other framework library here (see
# build_libandroid_runtime.sh for why -std=gnu++98 and -include
# AndroidConfig.h).
CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks -fno-strict-aliasing \
-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \
-Wno-multichar -Wno-unused-variable -Wno-narrowing \
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
-I $FWBASE/include/ui \
-I $FWBASE/include/utils \
-I $FWBASE/native/include \
-I $JNI \
-I $DALVIK/libnativehelper/include \
-I $DALVIK/libnativehelper/include/nativehelper \
-I $TP/libhardware/include \
-I $TP/libhardware_legacy/include \
-I $TP/libhardware_legacy/include/hardware_legacy"

echo "=== libui (EventHub-only: EventHub.cpp + KeyLayoutMap.cpp) ==="
"$GXX" $CXXFLAGS -I "$UI" -c "$UI/EventHub.cpp" -o "$OUT/obj/EventHub.o" \
    2>&1 | tee "$OUT/log/EventHub.log"
"$GXX" $CXXFLAGS -I "$UI" -c "$UI/KeyLayoutMap.cpp" -o "$OUT/obj/KeyLayoutMap.o" \
    2>&1 | tee "$OUT/log/KeyLayoutMap.log"

echo "=== system_init.cpp (trimmed -- see this script's header comment) ==="
"$GXX" $CXXFLAGS -I "$TP/frameworks/base/cmds/system_server/library" \
    -c "$TP/frameworks/base/cmds/system_server/library/system_init.cpp" \
    -o "$OUT/obj/system_init.o" 2>&1 | tee "$OUT/log/system_init.log"

echo "=== services/jni sources ==="
SRCS="com_android_server_AlarmManagerService.cpp \
com_android_server_BatteryService.cpp \
com_android_server_HardwareService.cpp \
com_android_server_KeyInputQueue.cpp \
com_android_server_SensorService.cpp \
com_android_server_SystemServer.cpp"

ok=0; fail=0; FAILED=""
for f in $SRCS; do
    base=$(basename "$f")
    if "$GXX" $CXXFLAGS -c "$JNI/$f" -o "$OUT/obj/${base%.*}.o" \
            > "$OUT/log/${base%.*}.log" 2>&1; then
        ok=$((ok + 1))
    else
        fail=$((fail + 1))
        FAILED="$FAILED $base"
    fi
done
echo "compiled: $ok  failed: $fail"
if [ -n "$FAILED" ]; then
    for b in $FAILED; do
        echo "--- $b"
        grep -m5 -E "error:|fatal error:" "$OUT/log/${b%.*}.log" | sed 's/^/    /'
    done
    echo "STOPPING: fix the above before archiving"
    exit 1
fi

echo "=== archiving libservices_jni.a ==="
rm -f "$OUT/libservices_jni.a"
"$AR" rcs "$OUT/libservices_jni.a" \
    "$OUT"/obj/EventHub.o "$OUT"/obj/KeyLayoutMap.o "$OUT"/obj/system_init.o \
    "$OUT"/obj/com_android_server_*.o

ls -la "$OUT/libservices_jni.a"
echo "Link this into app_process/app_process_debug next (build_app_process.sh / build_app_process_debug.sh)."
