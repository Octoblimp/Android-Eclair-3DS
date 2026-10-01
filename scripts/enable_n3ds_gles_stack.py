#!/usr/bin/env python3
"""Restore Eclair's EGL/GLES Java-to-native registrations."""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

from pathlib import Path


ROOT = Path(A3DS_ROOT)
RUNTIME = ROOT / "third_party/frameworks/base/core/jni/AndroidRuntime.cpp"
LIBAGL_BUILD = ROOT / "scripts/build_libagl.sh"

text = RUNTIME.read_text()
marker = "N3DS_GLES11_JNI_REGISTRATION"
if marker not in text:
    needle = "    REG_JNI(register_android_view_Surface),\n"
    replacement = needle + (
        "\n"
        "    // N3DS_GLES11_JNI_REGISTRATION: restore the stock JSR-239 EGL\n"
        "    // and GLES 1.0/1.1 bridge. libagl is always linked as the safe\n"
        "    // software implementation; the qualified PICA backend may take\n"
        "    // ownership beneath the same API without changing applications.\n"
        "    REG_JNI(register_com_google_android_gles_jni_EGLImpl),\n"
        "    REG_JNI(register_com_google_android_gles_jni_GLImpl),\n"
        "    REG_JNI(register_android_opengl_jni_GLES10),\n"
        "    REG_JNI(register_android_opengl_jni_GLES10Ext),\n"
        "    REG_JNI(register_android_opengl_jni_GLES11),\n"
        "    REG_JNI(register_android_opengl_jni_GLES11Ext),\n")
    if text.count(needle) != 1:
        raise SystemExit("AndroidRuntime Surface registration anchor missing")
    text = text.replace(needle, replacement, 1)
RUNTIME.write_text(text)

# Eclair's software libagl implements the GLES 1.0/1.1 core plus its own
# advertised extensions, but not every symbol in the generated GLES*Ext JNI
# superset. Register the complete core bridge; unadvertised extension calls
# correctly remain unavailable instead of creating unresolved static links.
text = RUNTIME.read_text()
for registration in (
        "register_android_opengl_jni_GLES10",
        "register_android_opengl_jni_GLES10Ext",
        "register_android_opengl_jni_GLES11",
        "register_android_opengl_jni_GLES11Ext"):
    text = text.replace("    REG_JNI(" + registration + "),\n", "")
RUNTIME.write_text(text)

if RUNTIME.read_text().count(marker) != 1:
    raise SystemExit("GLES JNI registration marker missing or duplicated")
build = LIBAGL_BUILD.read_text()
if "N3DS_STATIC_GLES_COMPAT" not in build:
    build = build.replace(
        "SRC=$FWBASE/opengl/libagl\n",
        "SRC=$FWBASE/opengl/libagl\n"
        "# N3DS_STATIC_GLES_COMPAT: ABI normally supplied by GLES_CM.so.\n"
        f"COMPAT=\"{A3DS_WIN}/native/gles_compat.cpp\"\n",
        1)
    build = build.replace(
        "for f in $ASM_SRCS; do\n",
        "if \"$GXX\" $CXXFLAGS -c \"$COMPAT\" -o \"$OUT/obj/gles_compat.o\" 2>>\"$OUT/build.log\"; then\n"
        "    OK=$((OK+1))\n"
        "else\n"
        "    FAIL=$((FAIL+1)); FAILED=\"$FAILED gles_compat.cpp\"\n"
        "fi\n"
        "for f in $ASM_SRCS; do\n",
        1)
LIBAGL_BUILD.write_text(build)

print("enable_n3ds_gles_stack: EGL/GLES 1.1 JNI registrations restored")
