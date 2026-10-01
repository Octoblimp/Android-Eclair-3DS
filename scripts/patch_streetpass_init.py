#!/usr/bin/env python3
"""Install the property/lifecycle shell for the Android StreetPass bridge.

The raw-radio daemon is supplied by a separate package.  This patch only
owns its disabled-by-default init service, status defaults, and the durable
state save trigger used by android_prefs_init.sh.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
WSL_ROOT = Path(A3DS_ROOT)
ROOT = WSL_ROOT if (WSL_ROOT / "third_party").exists() else HERE
OVERLAY = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay"
STAGED = HERE / "sdcard/linux/android"

INIT_MARKER = "N3DS_STREETPASS_LIFECYCLE"
PROP_MARKER = "N3DS_STREETPASS_DEFAULTS"
LEGACY_SERVICE_MARKER = "# ANDROID3DS_STREETPASSD_SERVICE"

INIT_BLOCK = r'''

# N3DS_STREETPASS_LIFECYCLE: StreetPass owns an intermittent raw-radio
# session.  The daemon is disabled by default; Settings publishes only the
# requested service.streetpass.* properties and the daemon publishes the
# authenticated sys.streetpass.* status properties.
service streetpassd /system/bin/streetpassd --backend raw80211 --key-file /tmp/streetpass/key --transport-config /mnt/sd/linux/android/persistent/shared/streetpass-radio.conf
    class default
    disabled
    user root
    group root wifi inet

service streetpass_save /etc/android_prefs_init.sh --save-streetpass
    class default
    disabled
    oneshot
    user root
    group root

on property:service.streetpass.enable=1
    setprop persist.sys.streetpass.enabled 1
    exec /etc/android_prefs_init.sh --prepare-streetpass-key
    start streetpassd
    start streetpass_save

on property:service.streetpass.enable=0
    setprop persist.sys.streetpass.enabled 0
    setprop persist.sys.streetpass.adb 0
    stop streetpassd
    start streetpass_save

on property:service.streetpass.adb=1
    setprop persist.sys.streetpass.adb 1
    setprop service.adb.tcp.port 5555
    start streetpass_save

on property:service.streetpass.adb=0
    setprop persist.sys.streetpass.adb 0
    setprop service.adb.tcp.port 0
    start streetpass_save

on property:sys.powerctl=*
    stop streetpassd
'''

PROP_BLOCK = r'''

# N3DS_STREETPASS_DEFAULTS: explicit disabled-by-default requests.  The
# durable preference importer may replace these before class_start. The
# persist.sys.streetpass.* values are the daemon's durable read boundary.
service.streetpass.enable=0
service.streetpass.adb=0
persist.sys.streetpass.enabled=0
persist.sys.streetpass.adb=0
'''


def append_once(path: Path, marker: str, block: str):
    if not path.is_file():
        return False, False
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return True, False
    path.write_text(text.rstrip() + block + "\n", encoding="utf-8")
    return True, True


def patch_init(path: Path):
    if not path.is_file():
        return False, False
    text = path.read_text(encoding="utf-8")
    if INIT_MARKER in text:
        # An older integrate_streetpassd_overlay.py could have appended a
        # second daemon definition after this lifecycle block. Remove only
        # that known bounded legacy block before accepting an already-marked
        # file; never silently return with duplicate services.
        legacy = ("\n" + LEGACY_SERVICE_MARKER + "\n"
                  "service streetpassd /system/bin/streetpassd --backend unavailable\n"
                  "    class default\n"
                  "    user root\n"
                  "    group root\n")
        cleaned = text.replace(legacy, "")
        # Repair the first-generation lifecycle block in place when it did
        # not carry the provisioned key path.  This remains an exact bounded
        # replacement and cannot alter unrelated init services.
        cleaned = cleaned.replace(
            "service streetpassd /system/bin/streetpassd\n",
            "service streetpassd /system/bin/streetpassd --backend unavailable --key-file /tmp/streetpass/key\n",
            1,
        )
        cleaned = cleaned.replace(
            "service streetpassd /system/bin/streetpassd --key-file /data/misc/streetpass/key\n",
            "service streetpassd /system/bin/streetpassd --backend unavailable --key-file /tmp/streetpass/key\n",
            1,
        )
        cleaned = cleaned.replace(
            "service streetpassd /system/bin/streetpassd --backend managed --key-file /data/misc/streetpass/key --transport-config /mnt/sd/linux/android/persistent/shared/streetpass-transport.conf\n",
            "service streetpassd /system/bin/streetpassd --backend unavailable --key-file /tmp/streetpass/key\n",
            1,
        )
        cleaned = cleaned.replace(
            "service streetpassd /system/bin/streetpassd --backend managed --key-file /tmp/streetpass/key --transport-config /mnt/sd/linux/android/persistent/shared/streetpass-transport.conf\n",
            "service streetpassd /system/bin/streetpassd --backend unavailable --key-file /tmp/streetpass/key\n",
            1,
        )
        cleaned = cleaned.replace(
            "service streetpassd /system/bin/streetpassd --backend unavailable --key-file /tmp/streetpass/key\n",
            "service streetpassd /system/bin/streetpassd --backend raw80211 --key-file /tmp/streetpass/key --transport-config /mnt/sd/linux/android/persistent/shared/streetpass-radio.conf\n",
            1,
        )
        # Repair an already-marked lifecycle block from before the
        # SD-to-RAM key import was added.  The bounded replacement keeps the
        # import synchronously before start and is idempotent.
        cleaned = cleaned.replace(
            "on property:service.streetpass.enable=1\n"
            "    setprop persist.sys.streetpass.enabled 1\n"
            "    start streetpassd\n",
            "on property:service.streetpass.enable=1\n"
            "    setprop persist.sys.streetpass.enabled 1\n"
            "    exec /etc/android_prefs_init.sh --prepare-streetpass-key\n"
            "    start streetpassd\n",
            1,
        )
        if cleaned.count("service streetpassd ") != 1:
            raise RuntimeError("StreetPass init has duplicate or missing streetpassd service")
        if cleaned != text:
            path.write_text(cleaned, encoding="utf-8")
            return True, True
        return True, False
    # An earlier daemon-only integration appended a service without the
    # disabled/default-off lifecycle. Replace that exact bounded block so the
    # final init file has one authoritative streetpassd definition.
    legacy = (LEGACY_SERVICE_MARKER + "\n"
              "service streetpassd /system/bin/streetpassd --backend unavailable\n"
              "    class default\n"
              "    user root\n"
              "    group root\n")
    if legacy in text:
        text = text.replace(legacy, INIT_BLOCK.lstrip(), 1)
        path.write_text(text, encoding="utf-8")
        return True, True
    anchor = "# N3DS_WIRELESS_ADB_TCP_ONLY:"
    if text.count(anchor) != 1:
        raise RuntimeError("StreetPass init anchor is not unique")
    text = text.replace(anchor, INIT_BLOCK.rstrip() + "\n\n" + anchor, 1)
    path.write_text(text, encoding="utf-8")
    return True, True


def patch_prop(path: Path):
    return append_once(path, PROP_MARKER, PROP_BLOCK)


def main() -> None:
    candidates = [
        OVERLAY / "etc/init.rc",
        STAGED / "etc/init.rc",
    ]
    props = [
        OVERLAY / "system/build.prop",
        STAGED / "system/build.prop",
    ]
    changed = False
    found = False
    for path in candidates:
        if path.exists():
            found = True
            _present, installed = patch_init(path)
            changed = installed or changed
    for path in props:
        if path.exists():
            found = True
            _present, installed = patch_prop(path)
            changed = installed or changed
    if not found:
        raise SystemExit("patch_streetpass_init: no init.rc/build.prop candidate found")
    print("patch_streetpass_init: lifecycle/defaults installed" if changed
          else "patch_streetpass_init: already installed")


if __name__ == "__main__":
    main()
