#!/bin/bash
# libdvm -- the Dalvik VM itself. Source list is taken verbatim from
# dalvik/vm/Dvm.mk (LOCAL_SRC_FILES + the WITH_HPROF and dvm_arch==arm
# blocks); the ".arm" suffixes there only meant "build this TU in ARM mode
# rather than Thumb", which is already the default for us, so they're
# stripped.
#
# Arch variant: armv5te. Eclair has no armv6 mterp variant (the choices are
# armv4t / armv5te / armv5te-vfp / armv7-a), and the 3DS's ARM11 is ARMv6,
# which runs ARMv5TE code natively. armv7-a would use instructions the
# ARM11 does not have.
#
# JIT stays off (WITH_JIT unset): Eclair's JIT was new and ARMv7-oriented;
# the portable/mterp interpreter is the thing to get working first.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
DALVIK="${ANDROID3DS_ROOT}"/third_party/dalvik
ZLIB="${ANDROID3DS_ROOT}"/third_party/zlib
SAFEIOP="${ANDROID3DS_ROOT}"/third_party/safe-iop/include
KHDR="${ANDROID3DS_ROOT}"/third_party/linux/include/uapi
OUT="${ANDROID3DS_ROOT}"/build/libdvm
VARIANT=armv5te

mkdir -p "$OUT/obj"
LOG="$OUT/build.log"
: > "$LOG"

# Dvm.mk's own LOCAL_CFLAGS, plus the standard bionic-target discipline used
# by every other lib here. Kernel uapi goes LAST in the include order (see
# docs/HANDOFF.md) so it can't shadow bionic's sanitized copies.
CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -O2 -fno-stack-protector -fno-pic \
-fstrict-aliasing -Wstrict-aliasing=2 -fno-align-jumps \
-Wno-attributes -Wno-implicit-function-declaration -Wno-pointer-sign \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-DWITH_PROFILER -DWITH_DEBUGGER -DDVM_RESOLVER_CACHE=0 -DDVM_SHOW_EXCEPTION=1 \
-DWITH_HPROF=1 \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $BIONIC/libm/include \
-I $BIONIC/libm/include/arm \
-I $FWBASE/include \
-I $SYSCORE/include \
-I $DALVIK \
-I $DALVIK/vm \
-I $DALVIK/libnativehelper/include/nativehelper \
-I $ZLIB \
-I $SAFEIOP \
-I $KHDR"

SRCS="AllocTracker.c AtomicCache.c CheckJni.c Ddm.c Debugger.c DvmDex.c \
Exception.c Hash.c IndirectRefTable.c Init.c InlineNative.c Inlines.c \
Intern.c Jni.c JarFile.c LinearAlloc.c Misc.c Native.c PointerSet.c \
Profile.c Properties.c RawDexFile.c ReferenceTable.c SignalCatcher.c \
StdioConverter.c Sync.c Thread.c UtfString.c \
alloc/clz.c alloc/Alloc.c alloc/HeapBitmap.c alloc/HeapDebug.c \
alloc/HeapSource.c alloc/HeapTable.c alloc/HeapWorker.c alloc/Heap.c \
alloc/MarkSweep.c alloc/DdmHeap.c \
analysis/CodeVerify.c analysis/DexOptimize.c analysis/DexVerify.c \
analysis/ReduceConstants.c analysis/RegisterMap.c analysis/VerifySubs.c \
interp/Interp.c interp/Stack.c \
jdwp/ExpandBuf.c jdwp/JdwpAdb.c jdwp/JdwpConstants.c jdwp/JdwpEvent.c \
jdwp/JdwpHandler.c jdwp/JdwpMain.c jdwp/JdwpSocket.c \
mterp/Mterp.c mterp/out/InterpC-portstd.c mterp/out/InterpC-portdbg.c \
native/InternalNative.c native/dalvik_system_DexFile.c \
native/dalvik_system_SamplingProfiler.c native/dalvik_system_VMDebug.c \
native/dalvik_system_VMRuntime.c native/dalvik_system_VMStack.c \
native/dalvik_system_Zygote.c native/java_lang_Class.c \
native/java_lang_Object.c native/java_lang_Runtime.c \
native/java_lang_String.c native/java_lang_System.c \
native/java_lang_SystemProperties.c native/java_lang_Throwable.c \
native/java_lang_VMClassLoader.c native/java_lang_VMThread.c \
native/java_lang_reflect_AccessibleObject.c native/java_lang_reflect_Array.c \
native/java_lang_reflect_Constructor.c native/java_lang_reflect_Field.c \
native/java_lang_reflect_Method.c native/java_lang_reflect_Proxy.c \
native/java_security_AccessController.c \
native/java_util_concurrent_atomic_AtomicLong.c \
native/org_apache_harmony_dalvik_NativeTestTarget.c \
native/org_apache_harmony_dalvik_ddmc_DdmServer.c \
native/org_apache_harmony_dalvik_ddmc_DdmVmInternal.c \
native/sun_misc_Unsafe.c native/SystemThread.c \
oo/AccessCheck.c oo/Array.c oo/Class.c oo/Object.c oo/Resolve.c \
oo/TypeCheck.c \
reflect/Annotation.c reflect/Proxy.c reflect/Reflect.c \
test/AtomicSpeed.c test/TestHash.c test/TestIndirectRefTable.c \
hprof/Hprof.c hprof/HprofClass.c hprof/HprofHeap.c hprof/HprofOutput.c \
hprof/HprofString.c \
arch/arm/HintsEABI.c mterp/out/InterpC-$VARIANT.c"

ASM_SRCS="arch/arm/CallOldABI.S arch/arm/CallEABI.S \
mterp/out/InterpAsm-$VARIANT.S"

OK=0; FAIL=0; FAILED=""
for f in $SRCS; do
    obj="$OUT/obj/$(echo "${f%.c}" | tr / _).o"
    if "$GCC" $CFLAGS -c "$DALVIK/vm/$f" -o "$obj" >>"$LOG" 2>&1; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done
for f in $ASM_SRCS; do
    obj="$OUT/obj/$(echo "${f%.S}" | tr / _).o"
    if "$GCC" $CFLAGS -c "$DALVIK/vm/$f" -o "$obj" >>"$LOG" 2>&1; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

echo "libdvm: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    echo "see $LOG"
    exit 1
fi
"$AR" rcs "$OUT/libdvm.a" "$OUT"/obj/*.o
echo "libdvm.a built: $("$AR" t "$OUT/libdvm.a" | wc -l) objects"
