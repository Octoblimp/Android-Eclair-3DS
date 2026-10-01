#!/bin/bash
# Build and deploy AOSP Eclair's bundled OpenGL ES Global Time sample.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
SRC="${ANDROID3DS_WIN}/third_party/globaltime"
TP="$ROOT/third_party"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JARSIGNER="$JDK/bin/jarsigner"
AAPT="$ROOT/build/aapt/aapt"
DX="$ROOT/build/dx/dx"
FWRES="$ROOT/build/framework_res/framework-res.apk"
FW_CLASSES="$ROOT/build/framework_jar/classes.jar"
CORE_CLASSES="$ROOT/build/core/classes.jar"
SEC="$TP/build_system/target/product/security"
OUT="$ROOT/build/globaltime_app"
BUILD_SRC="$OUT/source"
TARGET="$TP/buildroot/board/nintendo3ds/rootfs_overlay/system/app"
LOG="$ROOT/build_globaltime_app.log"

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$SRC/AndroidManifest.xml" "$SRC/assets/world.gles" \
         "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_globaltime_app: missing $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
cp -a "$SRC" "$BUILD_SRC"
: > "$LOG"

# The patch must live in the authoritative Windows tree. Fail if only an old
# generated build copy was patched and the copy above discarded that work.
GT_JAVA="$BUILD_SRC/src/com/android/globaltime/GlobalTime.java"
GLVIEW_JAVA="$BUILD_SRC/src/com/android/globaltime/GLView.java"
STYLE_XML="$BUILD_SRC/res/values/styles.xml"
for marker in N3DS_SURFACE_TYPE_NORMAL N3DS_SURFACE_CHANGED_ASPECT \
              N3DS_CLIP_PLANE_CLEANUP N3DS_VIEWPORT_SAFE_BOUNDS \
              N3DS_GLOBALTIME_LOG_TAG N3DS_GLOBALTIME_FRAME_STATE \
              N3DS_GLOBALTIME_EGL_SURFACE_READY \
              N3DS_GLOBALTIME_FIRST_FRAME \
              N3DS_GLOBALTIME_RGB565_WINDOW \
              N3DS_GLOBALTIME_RGB565_CONFIG \
              N3DS_GLOBALTIME_READBACK_IMPORTS \
              N3DS_GLOBALTIME_PIXEL_FORMAT_IMPORT \
              N3DS_GLOBALTIME_READBACK_STATE \
              N3DS_GLOBALTIME_RGBA_READBACK \
              N3DS_GLOBALTIME_GEOMETRY_FALLBACK \
              N3DS_GLOBALTIME_FALLBACK_STATE \
              N3DS_GLOBALTIME_FALLBACK_RESET \
              N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT \
              N3DS_GLOBALTIME_FALLBACK_DRAW \
              N3DS_GLOBALTIME_FALLBACK_DISPATCH \
              N3DS_GLOBALTIME_FALLBACK_LIGHT_ISOLATION \
              N3DS_GLOBALTIME_FALLBACK_ATMOSPHERE_ISOLATION \
              N3DS_GLOBALTIME_FIXED_POINT_GL \
              N3DS_GLOBALTIME_FIXED_POINT_PROXY \
              N3DS_GLOBALTIME_FLOAT_ABI_PROBE \
              N3DS_GLOBALTIME_GL_ERROR; do
    grep -F "$marker" "$GT_JAVA" >/dev/null || {
        echo "build_globaltime_app: authoritative source missing $marker" >&2
        exit 1
    }
done
# N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT supersedes the forced colored-sphere
# default (N3DS_GLOBALTIME_FALLBACK_DEFAULT, #235).  That default only hid the
# black frame; the cause was scalar-float GL calls crossing the hard-float /
# base-AAPCS JNI mismatch.  The textured globe is the default again and the
# readback-triggered fallback remains.
grep -F 'N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT fallback=false' "$GT_JAVA" >/dev/null || {
    echo 'build_globaltime_app: real-globe default runtime marker missing' >&2
    exit 1
}
grep -F 'mUseFallbackWorld = false;' "$GT_JAVA" >/dev/null || {
    echo 'build_globaltime_app: surface creation no longer defaults to the real globe' >&2
    exit 1
}
if grep -F 'N3DS_GLOBALTIME_FALLBACK_DEFAULT enabled' "$GT_JAVA" >/dev/null; then
    echo 'build_globaltime_app: superseded forced-fallback default is back' >&2
    exit 1
fi
# N3DS_GLOBALTIME_FIXED_POINT_GL: no scalar-float GL call may reach JNI from
# the app's own drawing code.  The single deliberate exception is the float
# ABI probe, tagged N3DS_GLOBALTIME_FLOAT_ABI_PROBE_CALL on its own line.
grep -F 'N3DS_GLOBALTIME_FIXED_POINT_GL' "$GLVIEW_JAVA" >/dev/null || {
    echo 'build_globaltime_app: GLView lost its GLfixed projection/view' >&2
    exit 1
}
FLOAT_GL_CALL='\.gl(Frustumf|Translatef|Rotatef|Scalef|Orthof|TexParameterf|TexEnvf|Materialf|Lightf|LightModelf|Fogf|ClearColor|ClearDepthf|Color4f|PointSize|LineWidth|AlphaFunc|PolygonOffset|DepthRangef|SampleCoverage|MultiTexCoord4f|Normal3f|PointParameterf)[[:space:]]*[(]'
if grep -nE "$FLOAT_GL_CALL" "$BUILD_SRC"/src/com/android/globaltime/*.java \
        | grep -vF 'N3DS_GLOBALTIME_FLOAT_ABI_PROBE_CALL'; then
    echo 'build_globaltime_app: scalar-float GL call would cross the broken JNI float ABI' >&2
    exit 1
fi
PROBE_CALLS="$(grep -cF 'N3DS_GLOBALTIME_FLOAT_ABI_PROBE_CALL' "$GT_JAVA" || true)"
test "$PROBE_CALLS" = 1 || {
    echo "build_globaltime_app: expected exactly one float ABI probe call, found $PROBE_CALLS" >&2
    exit 1
}
grep -F 'N3DS_GLOBALTIME_TRANSLUCENT_WINDOW' "$STYLE_XML" >/dev/null || {
    echo 'build_globaltime_app: authoritative translucent-window repair missing' >&2
    exit 1
}
grep -F 'N3DS_GLVIEW_SAFE_ASPECT' "$GLVIEW_JAVA" >/dev/null || {
    echo 'build_globaltime_app: authoritative GLView safe-aspect repair missing' >&2
    exit 1
}
if grep -F 'getHolder().setType(SurfaceHolder.SURFACE_TYPE_GPU);' \
        "$GT_JAVA" >/dev/null; then
    echo 'build_globaltime_app: forbidden SURFACE_TYPE_GPU remains' >&2
    exit 1
fi
if grep -F 'GL10.GL_UNSIGNED_SHORT_5_6_5, bytes' "$GT_JAVA" >/dev/null; then
    echo 'build_globaltime_app: invalid RGB565 readback remains' >&2
    exit 1
fi

echo '=== 1/5 aapt: Global Time resources/assets ==='
"$AAPT" package -f -m -M "$BUILD_SRC/AndroidManifest.xml" -S "$BUILD_SRC/res" \
    -A "$BUILD_SRC/assets" -I "$FWRES" -J "$OUT/gen" \
    -F "$OUT/GlobalTime.apk" >> "$LOG" 2>&1

echo '=== 2/5 javac ==='
# GlobalTime uses javax.microedition.khronos.egl.* which was excluded from
# framework.jar (no native GLES backing). Compile the full opengl/java tree
# into a stub jar so GlobalTime can reference EGL10/EGL11/EGLContext/GL10 etc.
# The stub jar is compile-time only and not packaged into the APK.
EGL_TREE="$ROOT/third_party/frameworks/base/opengl/java"
EGL_STUBS="$OUT/egl_stubs"
mkdir -p "$EGL_STUBS/classes"
find "$EGL_TREE" -name '*.java' > "$OUT/egl_sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -d "$EGL_STUBS/classes" @"$OUT/egl_sources.txt" >> "$LOG" 2>&1
"$JDK/bin/jar" cf "$EGL_STUBS/egl_stubs.jar" -C "$EGL_STUBS/classes" .
EGL_STUBS_JAR="$EGL_STUBS/egl_stubs.jar"

find "$BUILD_SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES:$EGL_STUBS_JAR" \
    -classpath "$FW_CLASSES:$CORE_CLASSES:$EGL_STUBS_JAR" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 3/5 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1
for runtime_marker in 'N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT fallback=false' \
                      'N3DS_GLOBALTIME_FLOAT_ABI_PROBE glTexParameterf error=0x' \
                      'N3DS_GLOBALTIME_FIXED_POINT_PROXY ready interfaces=' \
                      'N3DS_GLOBALTIME_GL_ERROR stage=' \
                      'N3DS_GLOBALTIME_READBACK drawError=0x'; do
    grep -aF "$runtime_marker" "$OUT/dex/classes.dex" >/dev/null || {
        echo "build_globaltime_app: classes.dex missing '$runtime_marker'" >&2
        exit 1
    }
done
if grep -aF 'N3DS_GLOBALTIME_FALLBACK_DEFAULT enabled' "$OUT/dex/classes.dex" >/dev/null; then
    echo 'build_globaltime_app: classes.dex still forces the fallback default' >&2
    exit 1
fi

echo '=== 4/5 package classes.dex ==='
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/GlobalTime.apk" classes.dex ) \
    >> "$LOG" 2>&1

echo '=== 5/5 platform signature/deploy ==='
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/GlobalTime.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -verify "$OUT/GlobalTime.apk" >> "$LOG" 2>&1

mkdir -p "$TARGET"
cp "$OUT/GlobalTime.apk" "$TARGET/GlobalTime.apk"
chmod 644 "$TARGET/GlobalTime.apk"
rm -f "$TARGET/GlobalTime.odex"

"$AAPT" list "$TARGET/GlobalTime.apk" | grep -qx classes.dex
"$AAPT" list "$TARGET/GlobalTime.apk" | grep -qx assets/world.gles
unzip -p "$TARGET/GlobalTime.apk" classes.dex \
    | grep -aF 'N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT fallback=false' >/dev/null
"$AAPT" dump badging "$TARGET/GlobalTime.apk" \
    | grep -F "package: name='com.android.globaltime'"
"$AAPT" dump badging "$TARGET/GlobalTime.apk" \
    | grep -F "launchable activity name='com.android.globaltime.GlobalTime'"
echo '=== build_globaltime_app: ALL OK ==='
ls -la "$TARGET/GlobalTime.apk"
