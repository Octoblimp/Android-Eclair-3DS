#!/bin/bash
# N3DS_SETTINGS_PERSIST gate: drive the real android_prefs_init.sh through
# save passes, simulated reboots and the boot-loop breaker, as root inside a
# private mount namespace with tmpfs over /data, /tmp and /mnt.  The host's
# own directories are never touched.  installd's half (refilling
# /data/data/<package>) is covered by test_installd_qemu.sh.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

SCRIPT=${1:-"${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/android_prefs_init.sh}

if [ "${N3DS_SETTINGS_NS:-}" != 1 ]; then
    test -x "$SCRIPT"
    COPY=$(mktemp /tmp/android_prefs_init.XXXXXX)
    cp "$SCRIPT" "$COPY"
    SELF=$(mktemp /tmp/test_settings_persist.XXXXXX)
    cp "$0" "$SELF"
    trap 'rm -f "$COPY" "$SELF"' EXIT
    a3ds_sudo env N3DS_SETTINGS_NS=1 N3DS_SCRIPT_COPY="$COPY" \
        unshare --mount --propagation private -- bash "$SELF"
    exit $?
fi

fail() { echo "FAIL: $*" >&2; exit 1; }
owner_mode() { stat -c '%u:%g %a' "$1"; }

# Everything the script will see lives on private tmpfs mounts.
mount -t tmpfs tmpfs /mnt
WORK=/mnt/work
mkdir -p "$WORK" /mnt/sd
cp "$N3DS_SCRIPT_COPY" "$WORK/android_prefs_init.sh"
chmod 755 "$WORK/android_prefs_init.sh"
mount -t tmpfs tmpfs /mnt/sd
mkdir -p /data
mount -t tmpfs tmpfs /data
mount -t tmpfs tmpfs /tmp
mount --bind /dev/null /dev/kmsg

cat > "$WORK/getprop" <<'EOF'
#!/bin/sh
echo '[persist.sys.timezone]: [America/Chicago]'
echo '[persist.service.adb.enable]: [1]'
echo '[ro.build.id]: [N3DS]'
EOF
cat > "$WORK/setprop" <<'EOF'
#!/bin/sh
echo "$1=$2" >> /mnt/work/setprop.log
EOF
chmod 755 "$WORK/getprop" "$WORK/setprop"
export N3DS_GETPROP="$WORK/getprop" N3DS_SETPROP="$WORK/setprop"

P=/mnt/sd/linux/android/persistent
mkdir -p /mnt/sd/linux/android
run() { sh "$WORK/android_prefs_init.sh" "$@"; }
boot() {   # a fresh RAM /data and /tmp, then init's exec of the script
    umount /data /tmp
    mount -t tmpfs tmpfs /data
    mount -t tmpfs tmpfs /tmp
    mkdir -p /data/misc/wifi
    run || true
}
put() {    # put <path> <content>
    mkdir -p "$(dirname "$1")"
    printf '%s' "$2" > "$1"
}
putdb() {  # a file that starts like an SQLite database
    mkdir -p "$(dirname "$1")"
    { printf 'SQLite format 3\000'; printf '%s' "$2"; } > "$1"
}

# --- first boot: nothing saved yet -----------------------------------------
mkdir -p /data/misc/wifi
run || true
test -f /tmp/n3ds_prefs/stamp || fail "prepare did not leave the save stamp"
test ! -e "$P/restore_boots" || fail "boot counter written with nothing restored"
sleep 1.1

# --- Android runs and writes its settings ----------------------------------
D=/data/data
putdb $D/com.android.providers.settings/databases/settings.db "v1"
: > $D/com.android.providers.settings/databases/settings.db-journal
put $D/com.android.launcher/shared_prefs/launcher.xml "<map>one</map>"
putdb $D/com.android.browser/databases/browser.db "bookmarks"
putdb $D/com.android.browser/databases/webviewCache.db "cache index"
putdb $D/com.android.browser/app_icons/WebpageIcons.db "icons"
put $D/com.android.browser/cache/webviewCache/0a1b "page"
putdb $D/com.android.providers.telephony/databases/mmssms.db "sms"
put $D/com.android.settings/files/wallpaper "PNG"
putdb $D/com.android.inputmethod.latin/databases/busy.db "dict"
printf '\331\325\005\371rest' > $D/com.android.inputmethod.latin/databases/busy.db-journal
put $D/com.example/shared_prefs/mid.xml "<map>new</map>"
put $D/com.example/shared_prefs/mid.xml.bak "<map>old</map>"
mkdir -p $D/com.example/files
head -c 5242880 /dev/zero > $D/com.example/files/big
put /data/system/wallpaper_info.xml "<wp />"
put /data/system/packages.xml "<packages />"
putdb /data/shared/n3dsdialer/n3dsdialer_shared.db "contacts"

run --pass
A=$P/appdata
for f in \
    "$A/com.android.providers.settings/databases/settings.db" \
    "$A/com.android.launcher/shared_prefs/launcher.xml" \
    "$A/com.android.browser/databases/browser.db" \
    "$A/com.android.settings/files/wallpaper" \
    "$P/system/wallpaper_info.xml" \
    "$P/datashared/n3dsdialer/n3dsdialer_shared.db"; do
    test -f "$f" || fail "not saved: $f"
done
cmp -s "$A/com.android.providers.settings/databases/settings.db" \
    $D/com.android.providers.settings/databases/settings.db || fail "settings.db copy differs"
for f in \
    "$A/com.android.browser/databases/webviewCache.db" \
    "$A/com.android.browser/app_icons" \
    "$A/com.android.browser/cache" \
    "$A/com.android.providers.telephony" \
    "$A/com.android.inputmethod.latin/databases/busy.db" \
    "$A/com.android.providers.settings/databases/settings.db-journal" \
    "$A/com.example/shared_prefs/mid.xml" \
    "$A/com.example/shared_prefs/mid.xml.bak" \
    "$A/com.example/files/big" \
    "$P/system/packages.xml"; do
    test ! -e "$f" || fail "must not be saved: $f"
done
test -z "$(find "$P" -name '*.n3ds-save')" || fail "a save temporary was left behind"
grep -qx 'persist.sys.timezone=America/Chicago' "$P/system/persist.props" || fail "time zone not saved"
grep -q 'adb' "$P/system/persist.props" && fail "persist.service.adb.enable was saved"
grep -q 'busy.db' /tmp/n3ds_prefs/pending || fail "database mid-transaction not queued for retry"
grep -q 'mid.xml' /tmp/n3ds_prefs/pending || fail "preferences mid-write not queued for retry"
echo "PASS: save pass kept settings, skipped caches/telephony/big files, queued mid-writes"

# --- the writes finish, one setting changes, one file is deleted -----------
sleep 1.1
: > $D/com.android.inputmethod.latin/databases/busy.db-journal
rm $D/com.example/shared_prefs/mid.xml.bak
put $D/com.android.launcher/shared_prefs/launcher.xml "<map>two</map>"
rm $D/com.android.browser/databases/browser.db
run --pass
test -f "$A/com.android.inputmethod.latin/databases/busy.db" || fail "retried database not saved"
test -f "$A/com.example/shared_prefs/mid.xml" || fail "retried preferences not saved"
grep -q two "$A/com.android.launcher/shared_prefs/launcher.xml" || fail "changed setting not saved"
test ! -e "$A/com.android.browser/databases/browser.db" || fail "deleted file kept in the mirror"
echo "PASS: retries saved, change saved, deletion pruned"

# --- shutdown flush --------------------------------------------------------
sleep 1.1
put $D/com.android.launcher/shared_prefs/launcher.xml "<map>three</map>"
run --flush
grep -q three "$A/com.android.launcher/shared_prefs/launcher.xml" || fail "flush did not save"
echo "PASS: shutdown flush saved the last change"

# --- reboot: restore -------------------------------------------------------
putdb "$P/datashared/torn.db" "x"
printf 'garbage' > "$P/datashared/torn.db"
put "$P/datashared/n3dsdialer/.n3dsdialer_shared.db.n3ds-save" "half"
: > "$WORK/setprop.log"
boot
test "$(owner_mode /data/system/wallpaper_info.xml)" = "1000:1000 660" || fail "wallpaper_info.xml owner/mode"
grep -q '<wp />' /data/system/wallpaper_info.xml || fail "wallpaper_info.xml content"
test ! -e /data/system/packages.xml || fail "packages.xml restored"
test "$(owner_mode /data/shared/n3dsdialer/n3dsdialer_shared.db)" = "1000:1000 666" || fail "dialer db owner/mode"
test "$(owner_mode /data/shared/n3dsdialer)" = "1000:1000 777" || fail "dialer dir owner/mode"
test ! -e /data/shared/torn.db || fail "torn database restored"
test ! -e /data/shared/n3dsdialer/.n3dsdialer_shared.db.n3ds-save || fail "save temporary restored"
test ! -e /data/data || fail "app data must be left to installd"
grep -qx 'persist.sys.timezone=America/Chicago' "$WORK/setprop.log" || fail "time zone not set back"
grep -q adb "$WORK/setprop.log" && fail "adb property was set"
test "$(cat "$P/restore_boots")" = 1 || fail "boot counter not 1"
echo "PASS: reboot restored /data/system, /data/shared and the time zone"

# --- boot completes: the watcher clears the counter and old temporaries ----
put "$A/com.android.launcher/shared_prefs/.launcher.xml.n3ds-save" "half"
timeout 4 sh "$WORK/android_prefs_init.sh" --watch || true
test "$(cat "$P/restore_boots")" = 0 || fail "watcher did not clear the boot counter"
test ! -e "$A/com.android.launcher/shared_prefs/.launcher.xml.n3ds-save" || fail "stale temporary kept"
echo "PASS: boot_completed watcher cleared the counter and stale temporaries"

# --- boot loop: three boots that never complete, then the fourth -----------
boot; boot; boot
test "$(cat "$P/restore_boots")" = 3 || fail "boot counter not 3 after three failed boots"
boot
test -d "$P/quarantine/appdata" || fail "saved settings not set aside"
test ! -e "$P/appdata" || fail "saved settings still in place after the breaker"
test ! -e /data/system/wallpaper_info.xml || fail "breaker boot still restored"
test "$(cat "$P/restore_boots")" = 0 || fail "boot counter not reset by the breaker"
echo "PASS: boot-loop breaker set the saved settings aside on the 4th failed boot"

echo "settings_persist: ALL PASS"
