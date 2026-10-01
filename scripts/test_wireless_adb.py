#!/usr/bin/env python3
"""Static release checks for Settings-controlled TCP ADB."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "content/settings/src/com/android/settings/WirelessAdbSettings.java"
MANIFEST = ROOT / "content/settings/AndroidManifest.xml"
SCREEN = ROOT / "content/settings/res/xml/settings.xml"
INIT = ROOT / "sdcard/linux/android/etc/init.rc"
PROP = ROOT / "sdcard/linux/android/system/build.prop"
BUILD = ROOT / "scripts/build_adbd.sh"
PIPELINE = ROOT / "scripts/rebuild_everything.sh"
SHELL_PATCH = ROOT / "scripts/patch_adbd_shell_path.py"


def main():
    java = JAVA.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    screen = SCREEN.read_text(encoding="utf-8")
    init = INIT.read_text(encoding="utf-8")
    prop = PROP.read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")
    pipeline = PIPELINE.read_text(encoding="utf-8")
    shell_patch = SHELL_PATCH.read_text(encoding="utf-8")
    assert "N3DS_WIRELESS_ADB_PROPERTY_CONTROL" in java
    assert 'SystemProperties.set("service.adb.tcp.port"' in java
    assert "Anyone on the same network can obtain a root shell" in java
    assert "adb.exe connect " in java and "adb.exe disconnect " in java
    assert "N3DS_WIRELESS_ADB_VERIFIED_READY" in java
    assert 'SystemProperties.get("init.svc.adbd"' in java
    assert 'SystemProperties.getInt("sys.adb.tcp.ready"' in java
    assert 'mEnabled.setPersistent(false)' in java
    assert 'mHandler.removeCallbacks(mRefresh)' in java
    assert "getIpAddress()" in java and "5555" in java
    assert "WirelessAdbSettings" in manifest and "WirelessAdbSettings" in screen
    # N3DS_ADB_ALWAYS_ROOT: the daemon still starts unconditionally at boot --
    # the device ships pre-rooted by explicit request and has no USB gadget
    # path, so build.prop publishes 5555 and adbd is listening before anything
    # can toggle it. port=0 in build.prop would mean "adb off at boot" and is
    # still wrong here.
    #
    # N3DS_WIRELESS_ADB_TCP_ONLY: what IS required again is the pair of
    # property triggers. Settings only writes service.adb.tcp.port and adbd
    # reads it once at startup, so without these the checkbox controls nothing
    # and the UI lies about having disabled a root shell.
    assert "N3DS_ADB_ALWAYS_ROOT" in init
    assert "on property:service.adb.tcp.port=5555" in init
    assert "on property:service.adb.tcp.port=0" in init
    assert "    start adbd" in init and "    stop adbd" in init
    # The service must NOT be disabled: that would hand the pre-rooted boot
    # default to a checkbox and lock the user out if adb is the only shell.
    adbd_block = init.split("service adbd /system/bin/adbd", 1)[1].split("\nservice ", 1)[0]
    assert "disabled" not in adbd_block, "adbd must still start at boot"
    assert "service adbd /system/bin/adbd" in init
    assert "group shell log input inet graphics sdcard_rw" in init
    assert "group root shell log input inet graphics misc sdcard_rw" not in init
    assert init.count("\nservice adbd ") == 1, "adbd declared more than once"
    assert "service.adb.tcp.port=5555" in prop
    assert "persist.service.adb.enable=1" not in prop
    assert 'N3DS_ADBD_ROOTFS_SHELL' in build
    assert '#define SHELL_COMMAND "/bin/sh"' in shell_patch
    assert pipeline.index("run patch_adbd_shell_path.py") < pipeline.index("run build_adbd.sh")
    print("wireless_adb: PASS")


if __name__ == "__main__":
    main()
