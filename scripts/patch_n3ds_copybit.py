#!/usr/bin/env python3
"""Install and enable the Android3DS built-in CPU copybit HAL."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(A3DS_ROOT)
SOURCE = PROJECT_ROOT / "hal/copybit/copybit_n3ds.cpp"
GRALLOC_DIR = ROOT / "third_party/libhardware/modules/gralloc"
DESTINATION = GRALLOC_DIR / "copybit_n3ds.cpp"
HAL_LOOKUP = GRALLOC_DIR / "hw_get_module_static.cpp"
BUILD_GRALLOC = ROOT / "scripts/build_gralloc.sh"
BUILD_LIBAGL = ROOT / "scripts/build_libagl.sh"
MARKER = "N3DS_BUILTIN_COPYBIT"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_gralloc_build(text: str) -> str:
    if MARKER not in text:
        text = replace_once(
            text,
            "# HAL_MODULE_INFO_SYM is redefined so the module struct has a unique, linkable\n",
            "# N3DS_BUILTIN_COPYBIT: copybit_n3ds.cpp is a CPU-backed HAL linked\n"
            "# into the same static module registry as gralloc.\n"
            "# HAL_MODULE_INFO_SYM is redefined so the module struct has a unique, linkable\n",
            "gralloc build marker",
        )
        text = replace_once(
            text,
            'SRCS="gralloc.cpp mapper.cpp allocator.cpp framebuffer.cpp"',
            'SRCS="gralloc.cpp mapper.cpp allocator.cpp framebuffer.cpp copybit_n3ds.cpp"',
            "copybit gralloc source",
        )
    for required in (MARKER, "copybit_n3ds.cpp"):
        if required not in text:
            raise SystemExit("build_gralloc.sh missing " + required)
    return text


def patch_libagl_build(text: str) -> str:
    if MARKER not in text:
        old_comment = """#   copybit.cpp / -DLIBAGL_USE_GRALLOC_COPYBITS -- NOT built. copybit is a
#   2D blitter HAL; this device has no such hardware and no copybit module,
#   and with the define off libagl falls through to its own pixelflinger
#   path, which is the only real path here anyway.
"""
        new_comment = """#   N3DS_BUILTIN_COPYBIT: copybit.cpp and LIBAGL_USE_GRALLOC_COPYBITS are
#   enabled against Android3DS' built-in CPU copybit HAL. Unsupported formats
#   still return an error and retain libagl's pixelflinger fallback.
"""
        text = replace_once(text, old_comment, new_comment,
                            "libagl copybit description")
        text = replace_once(
            text,
            '-DLOG_TAG=\\"libagl\\" -DGL_GLEXT_PROTOTYPES -DEGL_EGLEXT_PROTOTYPES \\\n',
            '-DLOG_TAG=\\"libagl\\" -DGL_GLEXT_PROTOTYPES -DEGL_EGLEXT_PROTOTYPES \\\n'
            '-DLIBAGL_USE_GRALLOC_COPYBITS \\\n',
            "libagl copybit define",
        )
        text = replace_once(text, 'CXX_SRCS="\negl.cpp\n',
                            'CXX_SRCS="\negl.cpp\ncopybit.cpp\n',
                            "libagl copybit source")
    for required in (MARKER, "-DLIBAGL_USE_GRALLOC_COPYBITS", "copybit.cpp"):
        if required not in text:
            raise SystemExit("build_libagl.sh missing " + required)
    return text


def patch_hal_lookup(text: str) -> str:
    if MARKER not in text:
        text = replace_once(
            text,
            "#include <hardware/gralloc.h>\n#include <hardware/lights.h>\n",
            "#include <hardware/gralloc.h>\n#include <hardware/lights.h>\n"
            "#include <hardware/copybit.h>\n",
            "copybit header",
        )
        text = replace_once(
            text,
            'extern "C" struct hw_module_t n3ds_gralloc_module;\n',
            'extern "C" struct hw_module_t n3ds_gralloc_module;\n'
            '/* N3DS_BUILTIN_COPYBIT */\n'
            'extern "C" struct copybit_module_t n3ds_copybit_module;\n',
            "copybit extern",
        )
        text = replace_once(
            text,
            "    { GRALLOC_HARDWARE_MODULE_ID, &n3ds_gralloc_module },\n"
            "    { LIGHTS_HARDWARE_MODULE_ID, &n3ds_lights_module },\n",
            "    { GRALLOC_HARDWARE_MODULE_ID, &n3ds_gralloc_module },\n"
            "    { COPYBIT_HARDWARE_MODULE_ID,\n"
            "      &n3ds_copybit_module.common },\n"
            "    { LIGHTS_HARDWARE_MODULE_ID, &n3ds_lights_module },\n",
            "copybit registry row",
        )
    for required in (MARKER, "COPYBIT_HARDWARE_MODULE_ID",
                     "n3ds_copybit_module.common"):
        if required not in text:
            raise SystemExit("hw_get_module_static.cpp missing " + required)
    return text


def write_if_changed(path: Path, text: str) -> None:
    if path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
        print(f"patched {path}")
    else:
        print(f"verified {path}")


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    for marker in (b"N3DS_COPYBIT_CPU_HAL",
                   b"N3DS_COPYBIT_BOOT_QUARANTINE"):
        if marker not in source_bytes:
            raise SystemExit("copybit source lacks " + marker.decode())
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    if not DESTINATION.is_file() or DESTINATION.read_bytes() != source_bytes:
        DESTINATION.write_bytes(source_bytes)
        print(f"installed {DESTINATION}")
    else:
        print(f"verified {DESTINATION}")

    write_if_changed(BUILD_GRALLOC, patch_gralloc_build(
        BUILD_GRALLOC.read_text(encoding="utf-8")))
    write_if_changed(BUILD_LIBAGL, patch_libagl_build(
        BUILD_LIBAGL.read_text(encoding="utf-8")))
    write_if_changed(HAL_LOOKUP, patch_hal_lookup(
        HAL_LOOKUP.read_text(encoding="utf-8")))
    print("patch_n3ds_copybit: built-in copybit sources verified")


if __name__ == "__main__":
    main()
