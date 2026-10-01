#!/usr/bin/env python3
"""Static contract for the GPU-Z crash and Global Time black-frame repairs."""

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return (ROOT / relative).read_text()


global_time = read("third_party/globaltime/src/com/android/globaltime/GlobalTime.java")
global_style = read("third_party/globaltime/res/values/styles.xml")
gl_view = read("third_party/globaltime/src/com/android/globaltime/GLView.java")
gpuz = read("content/gpuz/src/com/android/gpuz/GPUZActivity.java")
global_build = read("scripts/build_globaltime_app.sh")
native_build = read("scripts/rebuild_native_stack.sh")
libjavacore_build = read("scripts/build_libjavacore.sh")
verifier = read("scripts/verify_release_artifacts.sh")

for marker in (
    "N3DS_SURFACE_TYPE_NORMAL",
    "N3DS_SURFACE_CHANGED_ASPECT",
    "N3DS_CLIP_PLANE_CLEANUP",
    "N3DS_VIEWPORT_SAFE_BOUNDS",
    "N3DS_GLOBALTIME_LOG_TAG",
    "N3DS_GLOBALTIME_FRAME_STATE",
    "N3DS_GLOBALTIME_EGL_SURFACE_READY",
    "N3DS_GLOBALTIME_FIRST_FRAME",
    "N3DS_GLOBALTIME_RGB565_WINDOW",
    "N3DS_GLOBALTIME_RGB565_CONFIG",
    "N3DS_GLOBALTIME_READBACK_IMPORTS",
    "N3DS_GLOBALTIME_PIXEL_FORMAT_IMPORT",
    "N3DS_GLOBALTIME_READBACK_STATE",
    "N3DS_GLOBALTIME_RGBA_READBACK",
    "N3DS_GLOBALTIME_GEOMETRY_FALLBACK",
    "N3DS_GLOBALTIME_FALLBACK_STATE",
    "N3DS_GLOBALTIME_FALLBACK_RESET",
    "N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT",
    "N3DS_GLOBALTIME_FIXED_POINT_GL",
    "N3DS_GLOBALTIME_FIXED_POINT_PROXY",
    "N3DS_GLOBALTIME_FLOAT_ABI_PROBE",
    "N3DS_GLOBALTIME_GL_ERROR",
    "N3DS_GLOBALTIME_FALLBACK_DRAW",
    "N3DS_GLOBALTIME_FALLBACK_DISPATCH",
    "N3DS_GLOBALTIME_FALLBACK_LIGHT_ISOLATION",
    "N3DS_GLOBALTIME_FALLBACK_ATMOSPHERE_ISOLATION",
):
    assert marker in global_time, "Global Time source missing " + marker
assert "N3DS_GLVIEW_SAFE_ASPECT" in gl_view
assert "getHolder().setType(SurfaceHolder.SURFACE_TYPE_GPU);" not in global_time
assert "getHolder().setType(SurfaceHolder.SURFACE_TYPE_NORMAL);" in global_time
assert "getHolder().setFormat(PixelFormat.RGB_565);" in global_time
assert "EGL10.EGL_RED_SIZE,     5" in global_time
assert "EGL10.EGL_GREEN_SIZE,   6" in global_time
assert "EGL10.EGL_BLUE_SIZE,    5" in global_time
assert "GL10.GL_RGBA" in global_time
assert "GL10.GL_UNSIGNED_BYTE" in global_time
assert "GL10.GL_UNSIGNED_SHORT_5_6_5, bytes" not in global_time
# N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT supersedes the forced colored-sphere
# default (N3DS_GLOBALTIME_FALLBACK_DEFAULT, #235): the black frame was the
# scalar-float JNI ABI mismatch, not the textured world path.  The readback
# fallback (mUseFallbackWorld = true on a black/erroring first frame) stays.
assert 'mUseFallbackWorld = true;' in global_time
assert 'mUseFallbackWorld = false;' in global_time
assert 'N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT fallback=false' in global_time
assert 'N3DS_GLOBALTIME_FALLBACK_DEFAULT enabled' not in global_time
assert 'N3DS_GLOBALTIME_FIXED_POINT_GL' in gl_view
FLOAT_GL_CALL = re.compile(
    r'[.]gl(Frustumf|Translatef|Rotatef|Scalef|Orthof|TexParameterf|TexEnvf|'
    r'Materialf|Lightf|LightModelf|Fogf|ClearColor|ClearDepthf|Color4f|'
    r'PointSize|LineWidth|AlphaFunc|PolygonOffset|DepthRangef|'
    r'SampleCoverage|MultiTexCoord4f|Normal3f|PointParameterf)\s*[(]')
float_calls = [line for source in (global_time, gl_view)
               for line in source.splitlines()
               if FLOAT_GL_CALL.search(line)]
assert len(float_calls) == 1, float_calls
assert 'N3DS_GLOBALTIME_FLOAT_ABI_PROBE_CALL' in float_calls[0], float_calls
assert 'mWorld.draw(worldGL(gl));' in global_time
assert 'mDisplayLights && !mDisplayWorldFlat && !mUseFallbackWorld' in global_time
assert 'mDisplayAtmosphere && !mDisplayWorldFlat && !mUseFallbackWorld' in global_time
assert "N3DS_GLOBALTIME_TRANSLUCENT_WINDOW" in global_style
assert 'android:windowIsTranslucent">true' in global_style
assert 'android:windowBackground">@null' in global_style
assert 'getWindow().setFormat(PixelFormat.TRANSLUCENT);' in global_time
assert all(marker in global_build for marker in (
    "N3DS_SURFACE_TYPE_NORMAL",
    "N3DS_SURFACE_CHANGED_ASPECT",
    "N3DS_CLIP_PLANE_CLEANUP",
    "N3DS_VIEWPORT_SAFE_BOUNDS",
    "N3DS_GLVIEW_SAFE_ASPECT",
    "N3DS_GLOBALTIME_LOG_TAG",
    "N3DS_GLOBALTIME_FRAME_STATE",
    "N3DS_GLOBALTIME_EGL_SURFACE_READY",
    "N3DS_GLOBALTIME_FIRST_FRAME",
    "N3DS_GLOBALTIME_RGB565_WINDOW",
    "N3DS_GLOBALTIME_RGB565_CONFIG",
    "N3DS_GLOBALTIME_READBACK_IMPORTS",
    "N3DS_GLOBALTIME_PIXEL_FORMAT_IMPORT",
    "N3DS_GLOBALTIME_READBACK_STATE",
    "N3DS_GLOBALTIME_RGBA_READBACK",
    "N3DS_GLOBALTIME_GEOMETRY_FALLBACK",
    "N3DS_GLOBALTIME_FALLBACK_STATE",
    "N3DS_GLOBALTIME_FALLBACK_RESET",
    "N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT",
    "N3DS_GLOBALTIME_FIXED_POINT_GL",
    "N3DS_GLOBALTIME_FIXED_POINT_PROXY",
    "N3DS_GLOBALTIME_FLOAT_ABI_PROBE",
    "N3DS_GLOBALTIME_GL_ERROR",
    "N3DS_GLOBALTIME_FALLBACK_DRAW",
    "N3DS_GLOBALTIME_FALLBACK_DISPATCH",
    "N3DS_GLOBALTIME_FALLBACK_LIGHT_ISOLATION",
    "N3DS_GLOBALTIME_FALLBACK_ATMOSPHERE_ISOLATION",
    "N3DS_GLOBALTIME_TRANSLUCENT_WINDOW",
))

assert "N3DS_GPUZ_DECIMALFORMAT_ABI_PROBE" in gpuz
assert "N3DS_GPUZ_BENCH_STATS_READY" in gpuz
assert "String.format(" in gpuz
assert "Kernel P3D qualified; Android GL is software" in gpuz
assert 'mIsHwAccelerated = false;' in gpuz

icu_root = "/third_party/dalvik/libcore/icu/src/main/native"
assert icu_root in native_build
assert icu_root in verifier
assert '"$LIBCORE/icu/src/main/native"' in libjavacore_build

# N3DS_FLOAT_JNI_CAST_WHITESPACE / N3DS_FLOAT_JNI_SPLIT_DEFINITION: the
# audit used to miss every "(void *) fn" registration and could not
# annotate split-line definitions, so GLImpl's float bindings shipped
# without pcs(aapcs) while the source-only gate reported 0 functions.
float_audit = read("scripts/audit_float_jni.py")
float_apply = read("scripts/apply_float_jni_abi.py")
assert "N3DS_FLOAT_JNI_CAST_WHITESPACE" in float_audit
assert "N3DS_FLOAT_JNI_SPLIT_DEFINITION" in float_apply
sys.path.insert(0, str(ROOT / "scripts"))
import audit_float_jni
import apply_float_jni_abi
sample = "".join(line + chr(10) for line in (
    'static void',
    'android_glTexParameterf__IIF',
    '  (JNIEnv *_env, jobject _this, jint target, jint pname, jfloat param) {',
    '}',
    'static JNINativeMethod methods[] = {',
    '{"glTexParameterf", "(IIF)V", (void *) android_glTexParameterf__IIF },',
    '};',
))
found = [m.group('function') for m in audit_float_jni.ENTRY.finditer(sample)
         if audit_float_jni.has_scalar_fp(m.group('signature'))]
assert found == ['android_glTexParameterf__IIF'], found
annotated, changed, error = apply_float_jni_abi.annotate(
    sample, 'android_glTexParameterf__IIF')
assert changed and error is None, (changed, error)
assert ('static __attribute__((pcs("aapcs"))) void' + chr(10)
        + 'android_glTexParameterf__IIF') in annotated
again, changed, error = apply_float_jni_abi.annotate(
    annotated, 'android_glTexParameterf__IIF')
assert not changed and error is None and again == annotated

print("PASS: PICA application/render repair contract")
