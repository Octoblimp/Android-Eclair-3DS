#!/bin/bash
# RETIRED 2026-08-04 (softlock session). Do not run this script.
#
# This used to build libandroid_servers.so and deploy it for
# System.loadLibrary("android_servers") to dlopen() at runtime. That
# approach cannot work: app_process is a fully static executable, and
# bionic's dlopen() (bionic/libdl/libdl.c) is a stub that unconditionally
# returns NULL for a static binary -- the real ELF-loading implementation
# only exists in the dynamic linker, which never runs for one. This was
# actually documented already, in build_libdl.sh's own header comment, just
# not cross-checked against this file when it was written.
#
# What actually happened on hardware: SystemServer.main() forks (raw
# fork(), not fork+exec -- see Zygote.forkSystemServer()) before ever
# reaching System.loadLibrary(), so the dlopen failure alone doesn't explain
# what was observed (softlocked_0426.jpg -- a total watchdog/RCU-stall
# lockup across all 4 CPUs). The real, independently-confirmed bug: the
# smoketest scripts that are supposed to guarantee "only one Dalvik-VM-class
# process alive at a time" (see [[project_phase6_vm_smoketest_lockup]])
# only ever killed the PID they explicitly tracked. A raw fork()'d child
# (system_server) gets its own PID that the shell script never learns and
# never kills -- so once app_process_debug_smoketest.sh's 150s timeout
# fires and it SIGKILLs only the zygote parent, the forked system_server
# survives as an orphan and keeps running (whatever it was doing: crashing
# from the dlopen failure and being relaunched by a retry, spinning, or
# just sitting in system_init()'s joinThreadPool() with a second, broken
# ProcessState -- doesn't matter which) right as app_process_smoketest.sh
# starts a *second* full Dalvik VM. That's the exact "multiple VM-heavy
# processes alive on a 256 MB/no-swap device" failure mode already on
# record, just reached via an orphaned child instead of unserialized
# services. See docs/HANDOFF.md's 2026-08-04 softlock session recap for the
# full writeup, including the app_process_smoketest.sh /
# app_process_debug_smoketest.sh setsid + process-group-kill fix.
#
# The real fix for the dlopen problem: services/jni's six sources +
# system_init.cpp + EventHub.cpp/KeyLayoutMap.cpp are now built as a static
# archive (scripts/build_services_jni.sh -> libservices_jni.a) and linked
# directly into app_process/app_process_debug (build_app_process.sh /
# build_app_process_debug.sh), registered into AndroidRuntime.cpp's
# gRegJNI[] table exactly like every other framework native.
# SystemServer.java's System.loadLibrary("android_servers") call is deleted
# to match. This also structurally removes two bugs the .so approach
# carried (both now moot, kept here for the record):
#   - AndroidRuntime::getRuntime() would have returned NULL in the .so's own
#     copy of that translation unit's static gCurRuntime -- system_init()'s
#     runtime->callStatic(...) would have been a null-pointer call.
#   - system_init()'s ProcessState::self() would have opened a second,
#     independent /dev/binder fd rather than sharing app_process's own.
#
# libandroid_servers.so itself (board/nintendo3ds/rootfs_overlay/system/lib/)
# was deleted -- dead weight, nothing loads it anymore.
echo "build_libandroid_servers.sh is retired -- run build_services_jni.sh instead (see this file's header comment)." >&2
exit 1
