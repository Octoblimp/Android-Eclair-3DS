"""Static checks for update-safe state inside sdcard/linux/android."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE_SOURCE = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/android_prefs_init.sh"
SERVICE_STAGED = ROOT / "sdcard/linux/android/etc/android_prefs_init.sh"
INIT = ROOT / "sdcard/linux/android/etc/init.rc"
SYNC = ROOT / "scripts/sync_android_to_sdcard.sh"
PAYLOAD_DIR = ROOT / "sdcard/linux/android"
TEMPLATE_DIR = PAYLOAD_DIR / "templates"


def require(text: str, needle: str, label: str) -> None:
    assert needle in text, f"{label}: missing {needle!r}"


def main() -> None:
    source = SERVICE_SOURCE.read_text()
    staged = SERVICE_STAGED.read_text()
    init = INIT.read_text()
    sync = SYNC.read_text()

    assert source == staged, "source/staged persistence service drifted"
    for marker in (
        "N3DS_UPDATE_SAFE_PREFS",
        "PERSIST_WIFI=",
        "PERSIST_MOBILE=",
        "N3DS_WIFI_FILE_BOOT_POLICY",
        "write_runtime_wifi",
        "sync_runtime_wifi",
        'PAYLOAD=/mnt/sd/linux/android',
        'ROOT="$PAYLOAD/persistent"',
        'SECURE="$ROOT/secure"',
        'USERS="$ROOT/users"',
        "user_ids()",
        "printf '0\\n'",
        "network=",
        "atomic_copy",
        "mv -f",
        "sync",
        "cmp -s",
        "--watch",
        "0600",
        "0700",
    ):
        require(source, marker, "initializer")

    # The migration is guarded by the new destination and a network block;
    # an older template can never overwrite an existing persistent file.
    require(source, 'if [ ! -f "$PERSIST_WIFI" ]', "migration guard")
    require(source, "grep -q '^network='", "migration credential guard")
    assert "cat \"$PERSIST_WIFI\"" not in source
    assert "echo \"$PERSIST_WIFI\"" not in source
    assert 'atomic_copy "$PERSIST_WIFI" "$RUNTIME_WIFI"' not in source
    assert "sqlite3" not in source
    require(source, "/mnt/sd/linux/mobile_registration.conf", "mobile migration")
    require(source, "$SHARED/mobile_registration.conf", "mobile destination")

    for marker in (
        "N3DS_UPDATE_SAFE_PREFS:",
        "mkdir /sdcard 0755 root root",
        "mount none /mnt/sd/linux/android /sdcard bind",
        "exec /etc/android_prefs_init.sh",
        "service prefs_sync /etc/android_prefs_init.sh --watch",
        "N3DS_UPDATE_SAFE_PREFS_BOOT_COMPLETED",
        "start prefs_sync",
    ):
        require(init, marker, "init integration")

    fallback = init.index(
        "copy /system/etc/wifi/wpa_supplicant.conf "
        "/data/misc/wifi/wpa_supplicant.conf"
    )
    imported = init.index("exec /etc/android_prefs_init.sh")
    owned = init.index("chown wifi wifi /data/misc/wifi/wpa_supplicant.conf")
    assert fallback < imported < owned, "persistent import must replace the fallback before chown"
    assert "android_prefs_sync" not in init
    service_name = "prefs_sync"
    assert len(service_name) <= 16, "legacy init service names are limited to 16 bytes"
    watch_branch = source.split('if [ "$MODE" = "--watch" ]; then', 1)[1]
    assert "prepare ||" not in watch_branch.split("else", 1)[0]

    require(sync, "N3DS_UPDATE_SAFE_PREFS", "sync exclusion marker")
    require(sync, 'PERSISTENT_STATE="$DEST/persistent"', "sync persistent path")
    require(sync, 'RS="rsync -rtLc --delete --stats"', "byte-exact payload sync")
    # All destructive rsync calls remain scoped to the three update-managed
    # trees.  No rsync invocation may target the persistent sibling.
    rsync_lines = [line for line in sync.splitlines() if "rsync" in line]
    assert not any("PERSISTENT" in line for line in rsync_lines)
    assert not any("$DEST/persistent" in line for line in rsync_lines)

    wifi_template = (TEMPLATE_DIR / "wifi.conf.example").read_text()
    prefs_template = (TEMPLATE_DIR / "user-preferences.conf.example").read_text()
    mobile_template = (TEMPLATE_DIR / "mobile_registration.conf.example").read_text()
    assert "YOUR_" in wifi_template
    assert "schema=1" in prefs_template
    assert "mobile_data_on_boot=1" in mobile_template
    for template in (wifi_template, prefs_template):
        assert "ssid=\"TMOBILE" not in template
        assert "psk=\"" not in template.replace("# psk=\"", "")
    # Persistent state is user-owned and starts empty; no retired transport
    # configuration may ship in the deployable tree.
    persistent = PAYLOAD_DIR / "persistent"
    persistent_files = sorted(
        path.relative_to(persistent).as_posix()
        for path in persistent.rglob("*") if path.is_file()
    ) if persistent.exists() else []
    assert persistent_files == []
    for path in PAYLOAD_DIR.rglob("*"):
        if path.is_file():
            contents = path.read_text(errors="replace")
            assert "HomeWifi" not in contents
            assert "Dovef0327" not in contents

    print("update_safe_prefs: PASS")


if __name__ == "__main__":
    main()
