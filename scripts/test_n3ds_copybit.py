#!/usr/bin/env python3
"""Static regression contract for Android3DS' built-in copybit HAL."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(A3DS_ROOT)


def main() -> None:
    source = (PROJECT_ROOT / "hal/copybit/copybit_n3ds.cpp").read_text(
        encoding="utf-8")
    installed = (ROOT / "third_party/libhardware/modules/gralloc/"
                 "copybit_n3ds.cpp").read_text(encoding="utf-8")
    lookup = (ROOT / "third_party/libhardware/modules/gralloc/"
              "hw_get_module_static.cpp").read_text(encoding="utf-8")
    gralloc_build = (ROOT / "scripts/build_gralloc.sh").read_text(
        encoding="utf-8")
    libagl_build = (ROOT / "scripts/build_libagl.sh").read_text(
        encoding="utf-8")
    staged_init = (PROJECT_ROOT / "sdcard/linux/android/etc/init.rc").read_text(
        encoding="utf-8")
    staged_prop = (PROJECT_ROOT /
                   "sdcard/linux/android/system/build.prop").read_text(
        encoding="utf-8")

    assert installed == source, "canonical copybit source drift"
    for token in (
        "N3DS_COPYBIT_CPU_HAL",
        "N3DS_COPYBIT_READY backend=cpu",
        "N3DS_COPYBIT_BOOT_QUARANTINE",
        "N3DS_COPYBIT_QUARANTINED default=software",
        "N3DS_COPYBIT_EXPERIMENTAL enabled",
        'property_get("debug.n3ds.copybit", value, "0")',
        "private_handle_t::dynamicCast",
        "GRALLOC_USAGE_SW_READ_OFTEN",
        "GRALLOC_USAGE_SW_WRITE_OFTEN",
        "n3ds_copybit_blit",
        "n3ds_copybit_stretch",
        "COPYBIT_FORMAT_RGB_565",
        "COPYBIT_FORMAT_RGBA_8888",
        "return -ENOSYS",
    ):
        assert token in source, token
    assert "N3DS_BUILTIN_COPYBIT" in lookup
    assert "COPYBIT_HARDWARE_MODULE_ID" in lookup
    assert "&n3ds_copybit_module.common" in lookup
    assert "copybit_n3ds.cpp" in gralloc_build
    assert "N3DS_BUILTIN_COPYBIT" in gralloc_build
    assert "-DLIBAGL_USE_GRALLOC_COPYBITS" in libagl_build
    assert "copybit.cpp" in libagl_build
    assert "N3DS_BUILTIN_COPYBIT" in libagl_build
    gate = source.index("if (!n3ds_copybit_explicitly_enabled())")
    allocation = source.index("calloc(1, sizeof(*ctx))")
    ready = source.index("N3DS_COPYBIT_READY backend=cpu")
    assert gate < allocation < ready, "copybit must fail closed before allocation"
    assert "return -ENODEV;" in source[gate:allocation]
    for runtime in (staged_init, staged_prop):
        assert "debug.n3ds.copybit" not in runtime, (
            "copybit opt-in must not be enabled by the deployable")
    print("n3ds_copybit: PASS (built-in; default boot quarantine)")


if __name__ == "__main__":
    main()
