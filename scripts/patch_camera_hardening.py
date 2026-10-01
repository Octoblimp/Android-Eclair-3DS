#!/usr/bin/env python3
"""Harden the camera path against the launch-time crash + CPU peg.

Three independent hazards, all fixed here:

 1. AndroidManifest: screenOrientation="landscape" makes WindowManager ask
    SurfaceFlinger for ROTATION_90 the instant the activity starts.  This
    board has one fixed 320x240 software-composited panel and no rotation
    path, so the request cannot be satisfied and the relayout never settles.
    "nosensor" pins the activity to the display's natural orientation and
    never issues a rotation request.

 2. CameraHardwareStub::previewThread() only sleeps inside "if (buffer != 0)".
    A null buffer returns NO_ERROR immediately and Thread re-enters, so the
    loop free-runs at 100% CPU with nothing to throttle it.  A preview frame
    rate of 0 is just as bad: 1e6/0.0f is +inf and (int)+inf is undefined on
    ARM (lands on INT_MIN), so usleep() gets a negative argument, returns
    EINVAL immediately, and the loop free-runs again.

 3. CameraService::Client::Client() dereferences mHardware with no null check.
    openCameraHardware() returning 0 segfaults mediaserver, and mediaserver
    has no "oneshot" in init.rc, so init respawns it forever.

Idempotent: every edit is guarded by its own N3DS_ marker.
"""
from a3ds_paths import A3DS_ROOT

import io
import os
import re
import sys

ROOT = A3DS_ROOT
MANIFEST = ROOT + "/build/camera_app/source/AndroidManifest.xml"
STUB = ROOT + "/third_party/frameworks/base/camera/libcameraservice/CameraHardwareStub.cpp"
SVC = ROOT + "/third_party/frameworks/base/camera/libcameraservice/CameraService.cpp"

changed = []


def read(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


# ------------------------------------------------------------------ 1. manifest
src = read(MANIFEST)
if "N3DS_FIXED_ORIENTATION" not in src:
    n = src.count('android:screenOrientation="landscape"')
    src = src.replace('android:screenOrientation="landscape"',
                      'android:screenOrientation="nosensor"')
    # "behind" inherits from whatever launched it, which is now nosensor too,
    # but pin it anyway so a direct VIEW intent cannot reintroduce a rotation.
    n += src.count('android:screenOrientation="behind"')
    src = src.replace('android:screenOrientation="behind"',
                      'android:screenOrientation="nosensor"')
    src = src.replace(
        "<manifest ",
        "<!-- N3DS_FIXED_ORIENTATION: the 3DS bottom panel is a fixed 320x240\n"
        "     software-composited framebuffer with no rotation path.  Asking\n"
        "     WindowManager for landscape makes it request ROTATION_90, which\n"
        "     this display cannot satisfy; the relayout then never settles. -->\n"
        "<manifest ", 1)
    write(MANIFEST, src)
    changed.append("manifest: pinned %d activities to nosensor" % n)
else:
    changed.append("manifest: already pinned (skipped)")

# ------------------------------------------------------ 2. previewThread() spin
src = read(STUB)
if "N3DS_PREVIEW_THROTTLE" not in src:
    old = """    // TODO: here check all the conditions that could go wrong
    if (buffer != 0) {
        // Calculate how long to wait between frames.
        int delay = (int)(1000000.0f / float(previewFrameRate));
    """
    if old not in src:
        sys.exit("previewThread(): anchor not found -- source moved")

    new = """    // N3DS_PREVIEW_THROTTLE: upstream computes the inter-frame delay from an
    // unvalidated parameter and only sleeps on the buffer != 0 path.  Both
    // escapes free-run this thread at 100% CPU:
    //   - previewFrameRate == 0 makes 1e6/0.0f +inf, and (int)+inf is
    //     undefined on ARM (INT_MIN in practice), so usleep() gets a negative
    //     argument and returns EINVAL without sleeping;
    //   - a null buffer returns NO_ERROR immediately and Thread re-enters.
    // Clamp the rate, then sleep unconditionally at the bottom.
    if (previewFrameRate < 1)  previewFrameRate = 1;
    if (previewFrameRate > 30) previewFrameRate = 30;
    const int delay = 1000000 / previewFrameRate;

    if (buffer == 0 || heap == 0 || fakeCamera == 0) {
        // Not initialised yet (or torn down under us).  Idle at the frame
        // rate rather than spinning; startPreview() may still be racing
        // setParameters() and the next pass can succeed.
        LOGW("previewThread: buffer/heap/camera not ready, idling");
        usleep(delay);
        return NO_ERROR;
    }

    {
    """
    src = src.replace(old, new, 1)

    old2 = """        // Advance the buffer pointer.
        mCurrentPreviewFrame = (mCurrentPreviewFrame + 1) % kBufferCount;

        // Wait for it...
        usleep(delay);
    }

    return NO_ERROR;
}"""
    new2 = """        // Advance the buffer pointer.
        mCurrentPreviewFrame = (mCurrentPreviewFrame + 1) % kBufferCount;
    }

    // Wait for it...  Unconditional: see N3DS_PREVIEW_THROTTLE above.
    usleep(delay);

    return NO_ERROR;
}"""
    if old2 not in src:
        sys.exit("previewThread(): tail anchor not found -- source moved")
    src = src.replace(old2, new2, 1)
    write(STUB, src)
    changed.append("CameraHardwareStub::previewThread: throttled + null-guarded")
else:
    changed.append("previewThread: already throttled (skipped)")

# ------------------------------------------ 2b. initHeapLocked zero-size guard
src = read(STUB)
if "N3DS_HEAP_SANITY" not in src:
    old = """    // Note that we enforce yuv422 in setParameters().
    int how_big = preview_width * preview_height * 2;
"""
    if old not in src:
        sys.exit("initHeapLocked(): anchor not found -- source moved")
    new = """    // N3DS_HEAP_SANITY: CameraParameters::getPreviewSize() hands back -1/-1
    // when the key is absent or unparseable, and a client is free to set 0x0.
    // Either way the heap below would be bogus and every mBuffers[] entry
    // would stay null, which used to strand previewThread() in a tight loop.
    if (preview_width <= 0 || preview_height <= 0) {
        LOGW("initHeapLocked: bad preview size %dx%d, falling back to 176x144",
             preview_width, preview_height);
        preview_width = 176;
        preview_height = 144;
        mParameters.setPreviewSize(preview_width, preview_height);
    }

    // Note that we enforce yuv422 in setParameters().
    int how_big = preview_width * preview_height * 2;
"""
    src = src.replace(old, new, 1)
    write(STUB, src)
    changed.append("CameraHardwareStub::initHeapLocked: preview size sanity")
else:
    changed.append("initHeapLocked: already guarded (skipped)")

# ------------------------------------------------- 3. Client ctor null-checks
src = read(SVC)
if "N3DS_HAL_NULL_GUARD" not in src:
    old = """    mHardware = openCameraHardware();
    mUseOverlay = mHardware->useOverlay();
"""
    if old not in src:
        sys.exit("Client::Client(): anchor not found -- source moved")
    new = """    mHardware = openCameraHardware();
    // N3DS_HAL_NULL_GUARD: openCameraHardware() can legitimately fail (the
    // stub's singleton promote() races a tear-down).  Upstream dereferences
    // it unconditionally; a null here segfaults mediaserver, and mediaserver
    // has no "oneshot" in init.rc, so init respawns it forever -- which reads
    // on the device as "the whole system died and the CPU is pegged".
    if (mHardware == 0) {
        LOGE("openCameraHardware() failed; camera client will be inert");
        mUseOverlay = false;
        mOverlayW = 0;
        mOverlayH = 0;
        mPreviewCallbackFlag = FRAME_CALLBACK_FLAG_NOOP;
        cameraService->incUsers();
        return;
    }
    mUseOverlay = mHardware->useOverlay();
"""
    src = src.replace(old, new, 1)
    write(SVC, src)
    changed.append("CameraService::Client::Client: mHardware null guard")
else:
    changed.append("Client ctor: already guarded (skipped)")

print("\n".join("  - " + c for c in changed))
