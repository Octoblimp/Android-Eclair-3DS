#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CARD_ROOT="$PROJECT_ROOT/sdcard/linux"
ANDROID_ROOT="$CARD_ROOT/android"
NATIVE_ROOT="${ANDROID3DS_ROOT}"
WSL_ANDROID_ROOT="$NATIVE_ROOT/sdcard/linux/android"
AAPT="$NATIVE_ROOT/build/aapt/aapt"
WINDOWS_PROJECT_ROOT="${ANDROID3DS_WIN}"
# The verifier can be launched from either the Windows release workspace or
# the separate canonical WSL tree. Most source checks live under NATIVE_ROOT,
# but a few workspace-owned sources (the PICA smoke test) are not guaranteed
# to be mirrored into WSL. Resolve each source authority explicitly and fail
# closed if neither copy exists; never silently skip the source check.
LATINIME_SRC="$NATIVE_ROOT/third_party/latinime"
PICA_SMOKETEST_SOURCE="$PROJECT_ROOT/native/pica200_smoketest.c"
if [ ! -f "$PICA_SMOKETEST_SOURCE" ]; then
    WINDOWS_PICA_SMOKETEST_SOURCE="$WINDOWS_PROJECT_ROOT/native/pica200_smoketest.c"
    if [ -f "$WINDOWS_PICA_SMOKETEST_SOURCE" ]; then
        PICA_SMOKETEST_SOURCE="$WINDOWS_PICA_SMOKETEST_SOURCE"
        echo "=== source authority: using Windows workspace PICA smoke-test source ==="
    else
        echo "FATAL: PICA smoke-test source missing from verifier root and Windows workspace" >&2
        exit 1
    fi
fi
PRELOAD_TMP="$(mktemp)"
MANIFEST_TMP="$(mktemp)"
SETTINGS_MANIFEST_TMP="$(mktemp)"
SETTINGS_APP_MANIFEST_TMP="$(mktemp)"
SETTINGS_RESOURCES_TMP="$(mktemp)"
SETTINGS_DEX_TMP="$(mktemp)"
SETTINGS_SECURITY_METHOD_TMP="$(mktemp)"
INITRC_TMP="$(mktemp)"
WORKSPACE_TMP="$(mktemp)"
SERVICES_DEX_TMP="$(mktemp)"
PHONE_DEX_TMP="$(mktemp)"
MMS_DEX_TMP="$(mktemp)"
KTR_DTB_TMP="$(mktemp)"
CTR_DTB_TMP="$(mktemp)"
TOUCHDIAG_MANIFEST_TMP="$(mktemp)"
MICTEST_MANIFEST_TMP="$(mktemp)"
BROWSER_MANIFEST_TMP="$(mktemp)"
IME_MANIFEST_TMP="$(mktemp)"
KERNEL_STRINGS_TMP="$(mktemp)"
WPA_INITRAMFS_TMP="$(mktemp)"
WIFI_INITRAMFS_TMP="$(mktemp)"
CAMERA_DEX_TMP="$(mktemp)"
CAMERA_STRINGS_TMP="$(mktemp)"
WPA_RUNTIME_MARKERS='N3DS-PRIVACY N3DS-WPA-RAW N3DS-RSN-RAW N3DS-SECURITY-UNKNOWN'
trap 'rm -f "$PRELOAD_TMP" "$MANIFEST_TMP" "$SETTINGS_MANIFEST_TMP" "$SETTINGS_APP_MANIFEST_TMP" "$SETTINGS_RESOURCES_TMP" "$SETTINGS_DEX_TMP" "$SETTINGS_SECURITY_METHOD_TMP" "$INITRC_TMP" "$WORKSPACE_TMP" "$SERVICES_DEX_TMP" "$PHONE_DEX_TMP" "$MMS_DEX_TMP" "$KTR_DTB_TMP" "$CTR_DTB_TMP" "$TOUCHDIAG_MANIFEST_TMP" "$BROWSER_MANIFEST_TMP" "$IME_MANIFEST_TMP" "$KERNEL_STRINGS_TMP" "$WPA_INITRAMFS_TMP" "$WIFI_INITRAMFS_TMP" "$CAMERA_DEX_TMP" "$CAMERA_STRINGS_TMP"' EXIT

echo '=== Dalvik cache dependency records ==='
python3 "$PROJECT_ROOT/scripts/jar_dexdep.py" verify "$ANDROID_ROOT"

echo '=== Windows/canonical-WSL managed staging parity ==='
test -d "$WSL_ANDROID_ROOT"
for sub in system etc usr; do
    MIRROR_DIFF="$(rsync -rtLc --delete --dry-run --itemize-changes \
        "$ANDROID_ROOT/$sub/" "$WSL_ANDROID_ROOT/$sub/")"
    if [ -n "$MIRROR_DIFF" ]; then
        echo "FATAL: Windows and canonical WSL staging differ ($sub)" >&2
        printf '%s\n' "$MIRROR_DIFF" >&2
        exit 1
    fi
done
for required in \
    system/framework/core.jar \
    system/framework/framework.jar \
    system/framework/services.jar; do
    test -s "$ANDROID_ROOT/$required"
    test -s "$WSL_ANDROID_ROOT/$required"
    cmp -s "$ANDROID_ROOT/$required" "$WSL_ANDROID_ROOT/$required" || {
        echo "FATAL: canonical WSL copy differs for $required" >&2
        exit 1
    }
    sha256sum "$ANDROID_ROOT/$required" "$WSL_ANDROID_ROOT/$required"
done
python3 "$PROJECT_ROOT/scripts/jar_dexdep.py" verify "$WSL_ANDROID_ROOT"

echo '=== ARM zygote preload payload ==='
unzip -p "$ANDROID_ROOT/system/framework/framework.jar" preloaded-classes > "$PRELOAD_TMP"
PRELOAD_COUNT="$(wc -l < "$PRELOAD_TMP")"
FORBIDDEN_COUNT="$(grep -Ec '^(android[.]bluetooth[.]|android[.]server[.]Bluetooth|android[.]media[.]|android[.]speech[.]srec[.]|android[.]opengl[.]|com[.]android[.]internal[.]location[.]GpsLocationProvider$)' "$PRELOAD_TMP" || true)"
echo "preloaded-count=$PRELOAD_COUNT"
echo "forbidden-preload-lines=$FORBIDDEN_COUNT"
test "$PRELOAD_COUNT" -gt 1000
test "$FORBIDDEN_COUNT" -eq 0

echo '=== Fonts ==='
FONT_COUNT="$(find "$ANDROID_ROOT/system/fonts" -maxdepth 1 -type f -name 'Droid*.ttf' | wc -l)"
echo "fonts=$FONT_COUNT"
find "$ANDROID_ROOT/system/fonts" -maxdepth 1 -type f -printf '%f %s\n' | sort
test "$FONT_COUNT" -eq 9

echo '=== Launcher HOME package ==='
"$AAPT" dump badging "$ANDROID_ROOT/system/app/Launcher2.apk" | grep '^package:'
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/Launcher2.apk" AndroidManifest.xml \
    > "$MANIFEST_TMP"
grep -F 'android.intent.action.MAIN' "$MANIFEST_TMP"
grep -F 'android.intent.category.HOME' "$MANIFEST_TMP"
grep -F 'android.intent.category.DEFAULT' "$MANIFEST_TMP"
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/Launcher2.apk" \
    res/xml/default_workspace.xml > "$WORKSPACE_TMP"
# N3DS_WORKSPACE_PACKAGES_PRESENT: this gate used to be a hardcoded list of
# packages that happened to be absent when it was written (contacts, mms,
# maps, vending). Mms and Contacts ship now, so the list both failed on
# entries that resolve perfectly well and stayed silent about anything else
# going missing. Resolve it against the image instead: collect the package
# name every APK in system/app declares, then require each packageName the
# default workspace references to be in that set.
SHIPPED_PACKAGES_TMP="$(mktemp)"
for APK in "$ANDROID_ROOT"/system/app/*.apk; do
    # aapt is read to completion on purpose: an early-exiting reader
    # (grep -m1, head) SIGPIPEs it, and pipefail turns that into 141.
    BADGING="$("$AAPT" dump badging "$APK" 2>/dev/null || true)"
    printf '%s\n' "$BADGING" | awk -F"'" '/^package: name=/ && !seen {print $2; seen=1}'
done | sort -u > "$SHIPPED_PACKAGES_TMP"
WORKSPACE_MISSING=0
for PKG in $(grep -o "packageName[^=]*=[^ ]*" "$WORKSPACE_TMP" | cut -d'"' -f2 | sort -u); do
    if ! grep -Fxq "$PKG" "$SHIPPED_PACKAGES_TMP"; then
        echo "workspace references absent package: $PKG" >&2
        WORKSPACE_MISSING=1
    fi
done
rm -f "$SHIPPED_PACKAGES_TMP"
if [ "$WORKSPACE_MISSING" -ne 0 ]; then
    echo "FATAL: Launcher workspace still references packages absent from the n3ds image" >&2
    exit 1
fi
grep -F 'com.android.settings.Settings' "$WORKSPACE_TMP"
grep -F 'com.android.touchdiag.TouchDiagnosticActivity' "$WORKSPACE_TMP"
grep -F 'com.android.globaltime.GlobalTime' "$WORKSPACE_TMP"
grep -F 'com.android.browser.BrowserActivity' "$WORKSPACE_TMP"
grep -E 'launcher:x.*="2"' "$WORKSPACE_TMP"
grep -F 'private static final int DATABASE_VERSION = 11;' \
    "$NATIVE_ROOT/third_party/launcher2/src/com/android/launcher2/LauncherProvider.java"
grep -F 'N3DS_SPACED_THREE_APP_WORKSPACE' \
    "$NATIVE_ROOT/third_party/launcher2/src/com/android/launcher2/LauncherProvider.java"
grep -F 'N3DS_BROWSER_EXISTING_WORKSPACE' \
    "$NATIVE_ROOT/third_party/launcher2/src/com/android/launcher2/LauncherProvider.java"
grep -F 'N3DS_REPEATABLE_WORKSPACE_LONG_PRESS' \
    "$NATIVE_ROOT/third_party/launcher2/src/com/android/launcher2/Launcher.java"
sed -n '/public void onDismiss(DialogInterface dialog)/,/^        }/p' \
    "$NATIVE_ROOT/third_party/launcher2/src/com/android/launcher2/Launcher.java" \
    | grep -F 'mWorkspace.setAllowLongPress(true);'
unzip -p "$ANDROID_ROOT/system/app/Launcher2.apk" classes.dex \
    | strings | grep -F 'Landroid/widget/GridView;'
if unzip -p "$ANDROID_ROOT/system/app/Launcher2.apk" classes.dex \
    | strings | grep -qx 'Finish'; then
    echo 'FATAL: Launcher still injects the temporary Finish control' >&2
    exit 1
fi

echo '=== Settings, Touch Diagnostic, provider, and system APK odex files ==='
"$AAPT" dump badging "$ANDROID_ROOT/system/app/Settings.apk" \
    | grep -F "launchable activity name='com.android.settings.Settings'"
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/Settings.apk" AndroidManifest.xml \
    > "$SETTINGS_APP_MANIFEST_TMP"
if grep -qi bluetooth "$SETTINGS_APP_MANIFEST_TMP"; then
    echo 'FATAL: Settings manifest exposes Bluetooth on n3ds' >&2
    exit 1
fi
if grep -qi streetpass "$SETTINGS_APP_MANIFEST_TMP"; then
    echo 'FATAL: compiled Settings manifest still exposes retired StreetPass' >&2
    exit 1
fi
grep -F 'MobileDataSettings' "$SETTINGS_APP_MANIFEST_TMP"
grep -F 'Mobile Data' "$SETTINGS_APP_MANIFEST_TMP"
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/Settings.apk" \
    res/xml/settings.xml > "$SETTINGS_RESOURCES_TMP"
if grep -qi streetpass "$SETTINGS_RESOURCES_TMP"; then
    echo 'FATAL: compiled Settings resources still contain retired StreetPass' >&2
    exit 1
fi
grep -F 'Mobile Data' "$SETTINGS_RESOURCES_TMP" "$SETTINGS_APP_MANIFEST_TMP"
grep -F '3DSTelco' "$SETTINGS_RESOURCES_TMP" "$SETTINGS_APP_MANIFEST_TMP" \
    || unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
        | strings | grep -F '3DSTelco'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex > "$SETTINGS_DEX_TMP"
if strings "$SETTINGS_DEX_TMP" | grep -qi streetpass; then
    echo 'FATAL: compiled Settings DEX still contains retired StreetPass' >&2
    exit 1
fi
strings "$SETTINGS_DEX_TMP" | grep -F 'Mobile Data'
strings "$SETTINGS_DEX_TMP" | grep -F '3DSTelco'
grep -F 'N3DS_SETTINGS_WIFI_CALLBACK_GUARD' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_REMEMBERED_UNSEEN_VISIBILITY' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_SCAN_SECURITY_FAIL_CLOSED' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointState.java"
grep -F 'N3DS_SETTINGS_SCAN_SECURITY_V3' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointState.java"
grep -F 'N3DS_SETTINGS_PROTECTED_SCAN_EVIDENCE' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointState.java"
grep -F 'N3DS_SETTINGS_UNKNOWN_SECURITY_FAIL_CLOSED' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointState.java"
grep -F 'N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointState.java"
grep -F 'N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_UNKNOWN_SAVE_REJECTED' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_MANUAL_REASSOCIATE_V2' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_PRIORITY_FAILURE_GUARD' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'mWifiManager.reassociate()' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_WPA_GROUP_CIPHERS_V2' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointState.java"
sed -n '/private void setupSecurity/,/private static boolean isHexWepKey/p' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointState.java" \
    > "$SETTINGS_SECURITY_METHOD_TMP"
if grep -Eq 'allowedGroupCiphers.set\(GroupCipher.WEP(40|104)\)' \
        "$SETTINGS_SECURITY_METHOD_TMP"; then
    echo 'FATAL: WPA/EAP setup still exports WEP group ciphers' >&2
    exit 1
fi
grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_REUSE' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_PROMPT' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiSettings.java"
grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointDialog.java"
grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_V2' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_V2' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiSettings.java"
grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_V2' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointDialog.java"
grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_V3' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointDialog.java"
grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_V4' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiSettings.java"
grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_V4' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_UNKNOWN_SCAN_REMEMBERED_MERGE' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_SCAN_ROWS_V5' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'N3DS_SETTINGS_WIFI_PROTECTED_LABEL_V2' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointPreference.java"
grep -F 'setTitle(mState.getHumanReadableSsid());' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointPreference.java"
if grep -Fq 'title += " [' \
        "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/AccessPointPreference.java"; then
    echo 'FATAL: Settings still appends security text to the SSID title' >&2
    exit 1
fi
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_ROW_CONNECT'
grep -F 'N3DS_WIFI_30S_DISCONNECTED_AUTO_SCAN' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'CONTINUOUS_SCAN_DELAY_MS = 30000' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
grep -F 'if (!mIsObtainingAddress && !mIsConnected)' \
    "$NATIVE_ROOT/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_WIFI_CALLBACK_FAILED'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_SCAN_SECURITY_UNKNOWN'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_UNKNOWN_SECURITY_FAIL_CLOSED'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_MANUAL_REASSOCIATE_FAILED'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_REUSE'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_PROMPT'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_SAVED_SCAN_SECURITY_RESOLVED='
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_SETTINGS_UNCLASSIFIED_SCAN_SUPPRESSED'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'N3DS_WIFI_AUTO_SCAN start interval='
grep -F '=".WirelessAdbSettings"' "$SETTINGS_APP_MANIFEST_TMP"
# N3DS_DEV_DEFAULTS (#317): developer options on by default.  The stock
# Applications screen links DevelopmentSettings and RunningServices; both
# must be declared or a tap is an ActivityNotFoundException.
grep -F '="DevelopmentSettings"' "$SETTINGS_APP_MANIFEST_TMP"
grep -F '="RunningServices"' "$SETTINGS_APP_MANIFEST_TMP"
grep -F '<bool name="def_install_non_market_apps">true</bool>' \
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/res/values/defaults.xml"
# N3DS_ADB_DEFAULT_ON: the setting is 1 and nothing writes
# persist.service.adb.enable, which only ever armed ZygoteInit's
# missing-preload-class crash.
grep -F 'Settings.Secure.putInt(mContentResolver, Settings.Secure.ADB_ENABLED, 1);' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/SystemServer.java"
if grep -F 'SystemProperties.set("persist.service.adb.enable"' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/SystemServer.java"; then
    echo 'FATAL: SystemServer writes persist.service.adb.enable again' >&2
    exit 1
fi
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'service.adb.tcp.port'
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'adb.exe connect '
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex \
    | strings | grep -F 'Anyone on the same network'
"$AAPT" dump badging "$ANDROID_ROOT/system/app/SettingsProvider.apk" | grep '^package:'
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/SettingsProvider.apk" AndroidManifest.xml \
    > "$SETTINGS_MANIFEST_TMP"
grep -F 'android:authorities' "$SETTINGS_MANIFEST_TMP" | grep -F '="settings"'
grep -q '<bookmarks>' "$ANDROID_ROOT/system/etc/bookmarks.xml"
if grep -Eq 'package=|class=' "$ANDROID_ROOT/system/etc/bookmarks.xml"; then
    echo 'FATAL: n3ds bookmarks file still names applications not in the image' >&2
    exit 1
fi
"$AAPT" dump badging "$ANDROID_ROOT/system/app/TouchDiagnostic.apk" \
    | grep -F "launchable activity name='com.android.touchdiag.TouchDiagnosticActivity'"
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/TouchDiagnostic.apk" AndroidManifest.xml \
    > "$TOUCHDIAG_MANIFEST_TMP"
grep -F 'android.intent.category.LAUNCHER' "$TOUCHDIAG_MANIFEST_TMP"
unzip -p "$ANDROID_ROOT/system/app/TouchDiagnostic.apk" classes.dex \
    | strings | grep -F 'N3DS_TOUCH_DIAG_READY single-touch 320x240 target test'
"$AAPT" dump badging "$ANDROID_ROOT/system/app/MicTest.apk" \
    | grep -F "launchable activity name='com.android.mictest.MicTestActivity'"
"$AAPT" dump badging "$ANDROID_ROOT/system/app/MicTest.apk" \
    | grep -F "uses-permission:'android.permission.RECORD_AUDIO'"
# The launcher cannot inflate an XML shape/layer-list drawable as an activity
# icon; it renders a blank fallback circle instead, with no error anywhere.
# Assert the resolved icon is a real PNG.
"$AAPT" dump badging "$ANDROID_ROOT/system/app/MicTest.apk" \
    | grep -E "^application: .*icon='res/drawable/icon.png'"
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/MicTest.apk" AndroidManifest.xml \
    > "$MICTEST_MANIFEST_TMP"
grep -F 'android.intent.category.LAUNCHER' "$MICTEST_MANIFEST_TMP"
unzip -p "$ANDROID_ROOT/system/app/MicTest.apk" classes.dex \
    | strings | grep -F 'N3DS_MIC_TEST_READY AudioRecord 8000 Hz mono 16-bit WAV recorder'
# register_android_media_MediaRecorder is not in gRegJNI in this build, so a
# MediaRecorder call is an UnsatisfiedLinkError -- an Error, not an exception,
# which is how the dialer died the first time.  MicTest must use AudioRecord.
if unzip -p "$ANDROID_ROOT/system/app/MicTest.apk" classes.dex | strings \
        | grep -qE 'Landroid/media/MediaRecorder;->'; then
    echo 'FATAL: MicTest calls MediaRecorder, whose JNI is absent' >&2
    exit 1
fi
# N3DS_MIC_FRONTEND (kernel #313): before it, ctr_csnd.c programmed the mic
# front end with TLV320AIC32x4 register numbers (p1.51 MICBIAS, p1.52/54 PGA
# routing, p1.59 gain).  On the CTR codec those are reserved, so the mic was
# never biased and the ADC read silence.  Hold the libn3ds microphoneInit()
# register set in place, and keep the old numbers out.
CSND_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_csnd.c"
grep -F 'N3DS_MIC_FRONTEND' "$CSND_SRC" >/dev/null
for d in CDC_MIC_PGA:'CDC(1, 0x2F)' CDC_ADC_IN_P:'CDC(1, 0x30)' \
         CDC_ADC_IN_M:'CDC(1, 0x31)' CDC_101_51:'CDC(101, 51)' \
         CDC_ADC_POWER:'CDC(0, 0x51)' CDC_ADC_MUTE:'CDC(0, 0x52)'; do
    grep -E "^#define ${d%%:*}[[:space:]]" "$CSND_SRC" | grep -F "${d#*:}" >/dev/null || {
        echo "FATAL: ctr_csnd.c lost the mic front-end define ${d%%:*} = ${d#*:}" >&2
        exit 1
    }
done
if grep -E 'CDC[(]1, *(0x33|51|0x34|52|0x36|54|0x3B|59)[)]' "$CSND_SRC"; then
    echo 'FATAL: ctr_csnd.c writes TLV320AIC32x4 mic registers again (reserved on the CTR codec)' >&2
    exit 1
fi
"$AAPT" dump badging "$ANDROID_ROOT/system/app/GlobalTime.apk" \
    | grep -F "launchable activity name='com.android.globaltime.GlobalTime'"
"$AAPT" list "$ANDROID_ROOT/system/app/GlobalTime.apk" | grep -qx assets/world.gles
GLOBALTIME_SOURCE="$WINDOWS_PROJECT_ROOT/third_party/globaltime/src/com/android/globaltime/GlobalTime.java"
GLOBALTIME_GLVIEW="$WINDOWS_PROJECT_ROOT/third_party/globaltime/src/com/android/globaltime/GLView.java"
for marker in N3DS_SURFACE_TYPE_NORMAL N3DS_SURFACE_CHANGED_ASPECT \
              N3DS_CLIP_PLANE_CLEANUP N3DS_VIEWPORT_SAFE_BOUNDS \
              N3DS_GLOBALTIME_RGBA_READBACK \
              N3DS_GLOBALTIME_GEOMETRY_FALLBACK \
              N3DS_GLOBALTIME_FALLBACK_DRAW \
              N3DS_GLOBALTIME_FALLBACK_DISPATCH \
              N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT \
              N3DS_GLOBALTIME_FIXED_POINT_GL \
              N3DS_GLOBALTIME_FIXED_POINT_PROXY \
              N3DS_GLOBALTIME_FLOAT_ABI_PROBE \
              N3DS_GLOBALTIME_GL_ERROR \
              N3DS_GLOBALTIME_FALLBACK_LIGHT_ISOLATION \
              N3DS_GLOBALTIME_FALLBACK_ATMOSPHERE_ISOLATION; do
    grep -F "$marker" "$GLOBALTIME_SOURCE"
done
# N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT supersedes the forced colored-sphere
# default (N3DS_GLOBALTIME_FALLBACK_DEFAULT): the #314 black frame was scalar
# float GL calls crossing the hard-float/base-AAPCS JNI mismatch.  The staged
# APK must carry the GLfixed build, not the forced-fallback one.
GLOBALTIME_DEX_STRINGS="$(unzip -p "$ANDROID_ROOT/system/app/GlobalTime.apk" classes.dex | strings)"
printf '%s\n' "$GLOBALTIME_DEX_STRINGS" \
    | grep -F 'N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT fallback=false'
printf '%s\n' "$GLOBALTIME_DEX_STRINGS" \
    | grep -F 'N3DS_GLOBALTIME_FLOAT_ABI_PROBE glTexParameterf error=0x'
printf '%s\n' "$GLOBALTIME_DEX_STRINGS" \
    | grep -F 'N3DS_GLOBALTIME_FIXED_POINT_PROXY ready interfaces='
if printf '%s\n' "$GLOBALTIME_DEX_STRINGS" \
        | grep -F 'N3DS_GLOBALTIME_FALLBACK_DEFAULT enabled'; then
    echo 'FATAL: staged GlobalTime.apk still forces the colored-sphere fallback' >&2
    exit 1
fi
grep -F 'N3DS_GLVIEW_SAFE_ASPECT' "$GLOBALTIME_GLVIEW"
grep -F 'N3DS_GLOBALTIME_FIXED_POINT_GL' "$GLOBALTIME_GLVIEW"
if grep -F 'getHolder().setType(SurfaceHolder.SURFACE_TYPE_GPU);' \
        "$GLOBALTIME_SOURCE"; then
    echo 'FATAL: authoritative Global Time source still requests GPU SurfaceHolder' >&2
    exit 1
fi
unzip -p "$ANDROID_ROOT/system/app/GPU-Z.apk" classes.dex \
    | strings | grep -F 'N3DS_GPUZ_BENCH_STATS_READY'
unzip -p "$ANDROID_ROOT/system/app/GPU-Z.apk" classes.dex \
    | strings | grep -F 'Kernel P3D qualified; Android GL is software'
echo '=== Browser system package ==='
"$AAPT" dump badging "$ANDROID_ROOT/system/app/Browser.apk" \
    | grep -F "launchable activity name='com.android.browser.BrowserActivity'"
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/Browser.apk" AndroidManifest.xml \
    > "$BROWSER_MANIFEST_TMP"
grep -F 'android.permission.INTERNET' "$BROWSER_MANIFEST_TMP"
grep -F 'android.intent.category.LAUNCHER' "$BROWSER_MANIFEST_TMP"
unzip -p "$ANDROID_ROOT/system/app/Browser.apk" classes.dex \
    | strings | grep -F 'Landroid/webkit/WebView;'
unzip -p "$ANDROID_ROOT/system/app/Browser.apk" classes.dex \
    | strings | grep -F 'Lcom/android/browser/TabControl;'
# N3DS_BROWSER_JS_FREE_SEARCH: Google's search page needs JavaScript this
# 2009 engine cannot parse; typed searches go to plain-HTTP Wiby instead.
unzip -p "$ANDROID_ROOT/system/app/Browser.apk" classes.dex     | strings | grep -F 'http://wiby.me/?q=%s'
if unzip -p "$ANDROID_ROOT/system/app/Browser.apk" classes.dex         | strings | grep -qF 'http://www.google.com/m?q=%s'; then
    echo "Browser.apk still sends typed searches to Google (N3DS_BROWSER_JS_FREE_SEARCH)" >&2
    exit 1
fi
# The engine behind that WebView, in the binary that has to answer for it.
# These two fail independently: an apk that constructs a WebView with no
# register_android_webkit_WebCore in app_process installs, launches, and
# then dies in WebViewCore's class initialiser.  Read by strings and not by
# nm because the deployed app_process is stripped: webcoreglue is
# WebCoreJniRegistration.cpp's LOG_TAG, and (IIIFIIZ)V is nativeSetSize's
# descriptor after the WebKit-vs-frameworks version skew was resolved in
# favour of this tree's WebViewCore.java.  Revert that and the descriptor
# returns to (IIIFIIIIZ)V, RegisterNatives rejects the entire class, and
# there is no zygote at all.
# No grep -q on these pipelines, for the reason given at the Camera gate.
strings "$ANDROID_ROOT/system/bin/app_process" | grep -x webcoreglue >/dev/null
strings "$ANDROID_ROOT/system/bin/app_process" \
    | grep -x android/webkit/WebViewCore >/dev/null
strings "$ANDROID_ROOT/system/bin/app_process" \
    | grep -xF '(IIIFIIZ)V' >/dev/null
# N3DS_WEBKIT_JNI: the strings checks above prove one descriptor.  This
# proves all of them: every GetMethodID/GetFieldID/FindClass/GetJMethod and
# every JNINativeMethod table in the WebKit sources build_webkit.py compiles
# (preprocessed with the captured flags), checked with Dalvik's own lookup
# rules against the framework.jar and core.jar that ship, plus every Java
# native in android.webkit.* against the registered tables.  The Browser died
# on "NoSuchMethodError: showRect" because only the RegisterNatives half of
# this had ever been checked; a by-name lookup failure does not stop zygote,
# it kills the WebViewCore thread the first time a page is opened.
python3 "$NATIVE_ROOT/scripts/check_webkit_jni.py" \
    --framework "$ANDROID_ROOT/system/framework/framework.jar" \
    --core "$ANDROID_ROOT/system/framework/core.jar"
# N3DS_WEBKIT_HARD_FLOAT (#323): the blank pages.  Every captured WebKit and
# libxml2 compile carried Eclair's -msoft-float -- -mfloat-abi=soft on this
# gnueabihf toolchain -- while Skia and everything else is hard-float, and
# app_process links with --no-warn-mismatch, so every float crossing the
# boundary was garbage.  A compiler-made object carries Tag_ABI_enum_size;
# a hard-float one also carries "Tag_ABI_VFP_args: VFP registers".
grep -F 'N3DS_WEBKIT_HARD_FLOAT' "$NATIVE_ROOT/scripts/build_webkit.py"
grep -F 'N3DS_WEBKIT_HARD_FLOAT' "$NATIVE_ROOT/scripts/build_libxml2_webkit.sh"
# (Lines are matched only before any '#': the script's own comment explains
# why the flag is gone and names it.)
if grep -Eq -- '^[^#]*-msoft-float' "$NATIVE_ROOT/scripts/build_libxml2_webkit.sh"; then
    echo 'FATAL: build_libxml2_webkit.sh compiles soft-float again (N3DS_WEBKIT_HARD_FLOAT)' >&2
    exit 1
fi
WEBKIT_READELF="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-readelf
webkit_soft_members="$(for a in "$NATIVE_ROOT/build/webkit_intermediates/libwebcore.a" \
                                "$NATIVE_ROOT/build/libxml2_webkit/libxml2.a"; do
        test -s "$a" || { echo "MISSING_ARCHIVE $a"; continue; }
        "$WEBKIT_READELF" -A "$a" 2>/dev/null || echo "MISSING_ARCHIVE $a"
    done | awk '
        /^MISSING_ARCHIVE / { bad++; next }
        /^File: / { if (m != "" && c && v == 0) bad++; m = $2; c = 0; v = 0; next }
        /Tag_ABI_enum_size/ { c = 1 }
        /Tag_ABI_VFP_args: VFP registers/ { v = 1 }
        END { if (m != "" && c && v == 0) bad++; print bad + 0 }')"
if [ "$webkit_soft_members" != "0" ]; then
    echo "FATAL: $webkit_soft_members soft-float (or missing) WebKit/libxml2 archive members (N3DS_WEBKIT_HARD_FLOAT)" >&2
    exit 1
fi
# N3DS_SKIA_SOFT_ASSERT (#323): theoldnet.com killed the Browser on a Skia
# SkASSERT (SK_DEBUG is required for WebKit's ABI) -- SK_CRASH writes
# 0xbbadbeef.  Failed asserts now log (first 3 per site) and continue;
# sk_throw stays fatal.
grep -F 'N3DS_SKIA_SOFT_ASSERT' "$NATIVE_ROOT/third_party/skia/include/core/SkUserConfig.h"
strings "$ANDROID_ROOT/system/bin/app_process" | grep -F 'N3DS_SKIA_SOFT_ASSERT' > /dev/null
echo '=== LatinIME system keyboard (replaced N3DSKeyboard) ==='
# AOSP LatinIME, Google's stock Eclair keyboard.  Every piece that makes it
# work here lives in a different tree and fails silently on the device:
# test_latinime.py checks the sources, this checks what ships.
python3 "$NATIVE_ROOT/scripts/test_latinime.py"
LATINIME_APK="$ANDROID_ROOT/system/app/LatinIME.apk"
"$AAPT" dump badging "$LATINIME_APK" \
    | grep -F "package: name='com.android.inputmethod.latin'"
"$AAPT" dump xmltree "$LATINIME_APK" AndroidManifest.xml > "$IME_MANIFEST_TMP"
grep -F 'android.permission.BIND_INPUT_METHOD' "$IME_MANIFEST_TMP"
grep -F 'android.view.InputMethod' "$IME_MANIFEST_TMP"
# N3DS_LATINIME_OWN_UID: a shared uid would tie the install to
# ContactsProvider's signature.
if grep -Fq 'sharedUserId' "$IME_MANIFEST_TMP"; then
    echo 'FATAL: LatinIME.apk declares a sharedUserId (N3DS_LATINIME_OWN_UID)' >&2
    exit 1
fi
# N3DS_LATINIME_REAL_DICT: upstream Eclair shipped a one-word stub; the real
# dictionary is about 1.2 MB and must be stored so AssetManager maps it.
unzip -v "$LATINIME_APK" res/raw/main.dict | grep -E ' Stored ' > /dev/null || {
    echo 'FATAL: LatinIME res/raw/main.dict is missing or compressed' >&2
    exit 1
}
latinime_dict_size="$(unzip -l "$LATINIME_APK" res/raw/main.dict | awk '$4 == "res/raw/main.dict" {print $1}')"
test "${latinime_dict_size:-0}" -gt 500000 || {
    echo "FATAL: LatinIME main.dict is only ${latinime_dict_size:-0} bytes (the stub?)" >&2
    exit 1
}
unzip -p "$LATINIME_APK" classes.dex | strings | grep -F 'jni_latinime' > /dev/null
# N3DS_STATIC_JNI_LIBS: the dictionary natives are inside app_process and
# Dalvik's built-in table names them; the .so is only a placeholder.
test -f "$ANDROID_ROOT/system/lib/libjni_latinime.so"
strings "$ANDROID_ROOT/system/bin/app_process" | grep -F 'libjni_latinime.so' > /dev/null
strings "$ANDROID_ROOT/system/bin/app_process" | grep -F '(N3DS_STATIC_JNI_LIBS)' > /dev/null
strings "$ANDROID_ROOT/system/bin/app_process" \
    | grep -F 'com/android/inputmethod/latin/BinaryDictionary' > /dev/null
for retired in N3DSKeyboard.apk N3DSKeyboard.odex; do
    if [ -e "$ANDROID_ROOT/system/app/$retired" ]; then
        echo "FATAL: retired $retired is still staged in $ANDROID_ROOT/system/app" >&2
        exit 1
    fi
done
grep -F 'N3DS_DEFAULT_TOUCH_IME' \
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java"
# N3DS_SETTINGS_DB_V44: pinned on purpose. Adding a default row without
# bumping DATABASE_VERSION leaves every already-provisioned device on the
# old database with the new row missing forever, and the symptom -- a
# setting that works on a wiped device and not on an upgraded one -- is
# invisible unless you know which database the tester started from. Bump
# this line together with the version and add the matching upgrade block.
grep -F 'private static final int DATABASE_VERSION = 44;' \
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java"
# ...and the 43 -> 44 upgrade must exist, or devices carrying a v43
# database get no ringtone, no notification sound and no DTMF row.
grep -F 'if (upgradeVersion == 43) {' \
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java"
grep -F 'N3DS_DEFAULT_SOUNDS' \
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java"
# Both paths, fresh-create and upgrade: 2 calls plus the declaration = 3.
test "$(grep -c 'loadN3dsSoundSettings' \
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java")" = 3
# The default URIs must name files that are actually on the card, or the
# first notification silently falls back to nothing.
test -s "$ANDROID_ROOT/system/media/audio/notifications/F1_New_SMS.wav"
test -s "$ANDROID_ROOT/system/media/audio/ringtones/Ring_Synth_04.wav"
test -s "$ANDROID_ROOT/system/media/audio/alarms/Alarm_Classic.wav"
unzip -p "$ANDROID_ROOT/system/app/SettingsProvider.apk" classes.dex \
    | strings | grep -F 'com.android.inputmethod.latin/.LatinIME'
grep -F 'N3DS_DEFAULT_LATINIME' \
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java"
echo '=== Camera capture (ctr_cam + CameraHardwareN3ds + stock app) ==='
# Kernel #313 made the camera real end to end: ctr_cam.c (N3DS_CAM_CAPTURE)
# streams YUYV frames from the CAM FIFOs to /dev/ctr_cam, and mediaserver's
# HAL, CameraHardwareN3ds (N3DS_CAMERA_HAL), turns them into RGB565 preview
# frames and libjpeg pictures.  This gate used to hold the bring-up scaffold
# (N3DS_CAM_BRINGUP, the dump_regs probe, AOSP CameraHardwareStub); every one
# of those is now a regression, so they are asserted ABSENT.  Any link below
# going missing is a silent Camera.open() failure or a grey preview.
CAM_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_cam.c"
CAM_DTSI="$NATIVE_ROOT/third_party/linux/arch/arm/boot/dts/nintendo3ds.dtsi"
grep -F 'N3DS_CAM_CAPTURE' "$CAM_SRC" >/dev/null
grep -F 'nintendo,3ds-cam' "$CAM_SRC" >/dev/null
grep -F 'PDN_CAM_CLOCK_ENABLE' "$CAM_SRC" >/dev/null
if grep -E 'N3DS_CAM_BRINGUP|module_param[(]dump_regs' "$CAM_SRC"; then
    echo 'FATAL: ctr_cam.c is the bring-up scaffold again, not the capture driver' >&2
    exit 1
fi
grep -F 'config CTR_CAM' "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/Kconfig" >/dev/null
grep -E 'obj-.[(]CONFIG_CTR_CAM[)][ 	]*[+]= ctr_cam[.]o' "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/Makefile" >/dev/null
grep -qx 'CONFIG_CTR_CAM=y' "$NATIVE_ROOT/third_party/linux/.config"
grep -F 'cam: cam@10120000' "$CAM_DTSI" >/dev/null
# The two data FIFOs are their own register windows; probe needs both.
grep -F '"fifo0", "fifo1"' "$CAM_DTSI" >/dev/null
grep -F 'nintendo,i2c-bus = <&i2c1>, <&i2c2>;' "$CAM_DTSI" >/dev/null
# ctr_i2c's waiter sleeps uninterruptibly; wake_up_interruptible() never woke
# it, so every sensor register access ran into the full timeout.
grep -F 'wake_up(&i2c->wq);' "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_i2c.c" >/dev/null
# ctr_spi had the same wake bug and also never acked SPI_FIFO_INT_STAT, so
# every codec/touch transfer slept 100 ms and the mic front end took ~10 s
# inside the first read() (N3DS_SPI_WAKE).
SPI_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_spi.c"
grep -F 'wake_up(&spi->wq);' "$SPI_SRC" >/dev/null
grep -F 'iowrite32(stat, spi->base + SPI_FIFO_INT_STAT);' "$SPI_SRC" >/dev/null
# The call, not the word: the driver's own comment explains the bug by name.
if grep -F 'wake_up_interruptible(&spi->wq)' "$SPI_SRC" >/dev/null; then
    echo 'FATAL: ctr_spi still wakes its uninterruptible waiter with wake_up_interruptible()' >&2
    exit 1
fi
# The capture driver takes no bring-up parameters from the command line.
for dts in nintendo3ds_ctr.dts nintendo3ds_ktr.dts; do
    if grep -E 'bootargs.*ctr_cam[.]' "$NATIVE_ROOT/third_party/linux/arch/arm/boot/dts/$dts"; then
        echo "FATAL: $dts bootargs still pass ctr_cam bring-up parameters" >&2
        exit 1
    fi
done
# The HAL.  RGB565 heaps are what make the preview visible at all: this
# SurfaceFlinger has no copybit, so a YCbCr_420_SP preview renders grey.
CAMSVC_DIR="$NATIVE_ROOT/third_party/frameworks/base/camera/libcameraservice"
grep -F 'N3DS_CAMERA_HAL' "$CAMSVC_DIR/CameraHardwareN3ds.cpp" >/dev/null
grep -F 'n3dsHeapFormat(params)' "$CAMSVC_DIR/CameraService.cpp" >/dev/null
test ! -e "$ANDROID_ROOT/system/app/N3dsCamera.apk"
test ! -e "$ANDROID_ROOT/system/app/N3dsCamera.odex"
"$AAPT" dump badging "$ANDROID_ROOT/system/app/Camera.apk" \
    | grep -F "package: name='com.android.camera'" >/dev/null
"$AAPT" dump badging "$ANDROID_ROOT/system/app/Camera.apk" \
    | grep -F "launchable activity name='com.android.camera.Camera'" >/dev/null
# Real upstream classes, not a stand-in. Extract once: grep -q closes the pipe
# on the first match, and under pipefail that fails the pipeline on success.
unzip -p "$ANDROID_ROOT/system/app/Camera.apk" classes.dex > "$CAMERA_DEX_TMP"
strings "$CAMERA_DEX_TMP" > "$CAMERA_STRINGS_TMP"
for c in Lcom/android/camera/Camera Lcom/android/camera/VideoCamera \
         Lcom/android/camera/ImageGallery; do
    grep -qF "$c" "$CAMERA_STRINGS_TMP"
done
# The N3DS app changes (build_camera_app.sh): the back/front switch, and the
# VGA/QVGA picture sizes without which opening Settings crashes.
grep -qF 'N3DS_CAMERA_SWITCH: camera ' "$CAMERA_STRINGS_TMP"
"$AAPT" dump --values resources "$ANDROID_ROOT/system/app/Camera.apk" \
    | grep -F '"640x480"' >/dev/null
# The userspace chain under the app. mediaserver publishes media.camera;
# app_process carries the JNI that reaches it. Without either, the app starts
# and then dies at Camera.open().
test -s "$ANDROID_ROOT/system/bin/mediaserver"
# No grep -q in these pipelines: it closes the pipe on the first match, which
# SIGPIPEs strings and fails the pipeline under pipefail on a SUCCESSFUL match.
strings "$ANDROID_ROOT/system/bin/mediaserver" | grep -x media.camera >/dev/null
strings "$ANDROID_ROOT/system/bin/mediaserver" > "$CAMERA_STRINGS_TMP.ms"
grep -F '/dev/ctr_cam' "$CAMERA_STRINGS_TMP.ms" >/dev/null
grep -F 'N3DS_CAMERA_HAL: camera HAL up' "$CAMERA_STRINGS_TMP.ms" >/dev/null
grep -F 'Wrong JPEG library version' "$CAMERA_STRINGS_TMP.ms" >/dev/null
if grep -F 'NO LIVE CAMERA FEED' "$CAMERA_STRINGS_TMP.ms"; then
    echo 'FATAL: mediaserver still links CameraHardwareStub (test pattern, not the sensor)' >&2
    exit 1
fi
rm -f "$CAMERA_STRINGS_TMP.ms"
strings "$ANDROID_ROOT/system/bin/app_process" | grep -x android/hardware/Camera >/dev/null
grep -F 'N3DS_MEDIASERVER' "$ANDROID_ROOT/etc/init.rc" >/dev/null
grep -F 'service mediaserver /system/bin/mediaserver' "$ANDROID_ROOT/etc/init.rc" >/dev/null
grep -F 'N3DS_CAMERA_JNI' "$NATIVE_ROOT/third_party/frameworks/base/core/jni/AndroidRuntime.cpp" >/dev/null
# ...and in the right PLACE. gRegJNI[] is ordered and the order is load-bearing.
# register_android_hardware_Camera resolves android/view/Surface.mSurface, and
# Dalvik's JNI FindClass runs the class initializer, so registering the camera
# before Surface's own natives are in place throws UnsatisfiedLinkError out of
# Surface.<clinit>; the field lookup fails, startReg() reports "Unable to
# register all android natives", and zygote exits 0 on every start. That is an
# endless init respawn with no crash and no stack trace, and it cost a physical
# boot on 2026-09-12. Presence of the REG_JNI line is not enough -- assert the
# order. (scripts/test_zygote_preload_qemu.sh catches the general case by
# actually running startReg under qemu; it needs sudo, so it is a ship-pipeline
# step rather than part of this gate.)
ART_CPP="$NATIVE_ROOT/third_party/frameworks/base/core/jni/AndroidRuntime.cpp"
surface_ln="$(grep -n 'REG_JNI(register_android_view_Surface)' "$ART_CPP" | cut -d: -f1)"
camera_ln="$(grep -n 'REG_JNI(register_android_hardware_Camera)' "$ART_CPP" | cut -d: -f1)"
test "$surface_ln" -gt 0
test "$camera_ln" -gt "$surface_ln" || {
    echo "FATAL: REG_JNI(register_android_hardware_Camera) is at line $camera_ln," >&2
    echo "       before REG_JNI(register_android_view_Surface) at line $surface_ln." >&2
    echo "       startReg() will fail and zygote will respawn forever. Move the" >&2
    echo "       camera registration back next to register_android_hardware_SensorManager." >&2
    exit 1
}
echo 'PASS: camera capture driver, HAL, stock app and CameraService path'

for odex in Launcher2.odex Browser.odex SettingsProvider.odex Settings.odex TouchDiagnostic.odex GlobalTime.odex GPU-Z.odex LatinIME.odex N3dsDialer.odex Camera.odex MicTest.odex MediaProvider.odex; do
    test -s "$ANDROID_ROOT/system/app/$odex"
    magic="$(head -c 8 "$ANDROID_ROOT/system/app/$odex" | od -An -tx1 | tr -d ' \n')"
    test "$magic" = '6465790a30333500' || {
        echo "FATAL: bad odex header for $odex: $magic" >&2
        exit 1
    }
done
python3 "$PROJECT_ROOT/scripts/jar_dexdep.py" verify-apps "$ANDROID_ROOT"

echo '=== Kernel poweroff integration ==='
SMP_SRC="$NATIVE_ROOT/third_party/linux/kernel/smp.c"
ARM_SMP_SRC="$NATIVE_ROOT/third_party/linux/arch/arm/kernel/smp.c"
PANIC_SRC="$NATIVE_ROOT/third_party/linux/kernel/panic.c"
GIC_SRC="$NATIVE_ROOT/third_party/linux/drivers/irqchip/irq-gic.c"
I2C_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_i2c.c"
MCU_POWER_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/mcu/poweroff.c"
PWRKEY_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pwrkey.c"
N3DS_KCONFIG="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/Kconfig"
grep -F 'N3DS_CSD_IPI_PROGRESS_RECOVERY' "$SMP_SRC"
grep -F 'arch_send_call_function_single_ipi(cpu);' "$SMP_SRC"
grep -F 'flush_smp_call_function_queue(false);' "$SMP_SRC"
grep -F 'N3DS_QUIET_CPU_STOP' "$ARM_SMP_SRC"
grep -F 'N3DS_SMP_STOP_RETRY' "$ARM_SMP_SRC"
grep -F 'N3DS_PANIC_CAUSE_LAST' "$PANIC_SRC"
grep -F 'N3DS_GIC_SGI_COMMIT_DSB' "$GIC_SRC"
grep -F 'N3DS_GIC_CPU_INIT_DSB' "$GIC_SRC"
grep -F 'N3DS_I2C_EMERGENCY_XFER' "$I2C_SRC"
# #324: the MCU NACKs while busy; without the retry its interrupt
# controller failed to probe and the HOME button never existed.
grep -F 'N3DS_I2C_NACK_RETRY' "$I2C_SRC"
grep -F 'N3DS_MCU_INTC_PROBE_RETRY' "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/mcu/intc.c"
grep -F 'N3DS_MCU_DIRECT_EMERGENCY_CUT' "$MCU_POWER_SRC"
grep -F 'N3DS_PWRKEY_DIRECT_MCU_DEADLINE' "$PWRKEY_SRC"
grep -F 'N3DS_POWER_OFF_LOG_GATE' "$PWRKEY_SRC"
grep -F 'proc_create("n3ds_poweroff_ready"' "$PWRKEY_SRC"
grep -F 'log finalizer not acknowledged' "$PWRKEY_SRC"
grep -F 'ctr_mcu_emergency_poweroff());' "$PWRKEY_SRC"
grep -F 'N3DS_PWRKEY_REQUIRES_MCU' "$N3DS_KCONFIG"
if sed -n '/static void ctr_pwrkey_force_poweroff/,/^}/p' "$PWRKEY_SRC" \
    | grep -Eq '^[[:space:]]*emergency_sync[(]'; then
    echo 'FATAL: forced START deadline still waits in emergency_sync()' >&2
    exit 1
fi
grep -E 'ctr_mcu_poweroff|ctr_pwrkey' "$CARD_ROOT/System.map" | tail -n 20
grep -q 'ctr_mcu_poweroff' "$CARD_ROOT/System.map"
grep -q 'ctr_mcu_emergency_poweroff' "$CARD_ROOT/System.map"
grep -q 'ctr_pwrkey_force_poweroff' "$CARD_ROOT/System.map"
grep -q 'ctr_pwrkey_timeout' "$CARD_ROOT/System.map"
strings "$NATIVE_ROOT/third_party/linux/vmlinux" \
    | grep -E 'userspace did not cut power|registered MCU poweroff|START held' \
    | head -n 20
strings "$NATIVE_ROOT/third_party/linux/vmlinux" \
    | grep -F 'forcing direct MCU cutoff'

echo '=== Public kernel build identity ==='
VMLINUX="$NATIVE_ROOT/third_party/linux/vmlinux"
strings "$VMLINUX" > "$KERNEL_STRINGS_TMP"
# The AR6002 driver is intentionally reloadable so BMI boot can select STA
# or AP firmware mode. Audit its runtime strings together with built-in
# kernel diagnostics; do not silently lose the existing AR6014 gates merely
# because they moved from vmlinux into the staged module.
strings "$ANDROID_ROOT/system/lib/modules/ath6kl.ko" >> "$KERNEL_STRINGS_TMP"
grep -F 'N3DS primary panic:' "$KERNEL_STRINGS_TMP"
KERNEL_VERSION_LINE="$(grep -m1 '^Linux version ' "$KERNEL_STRINGS_TMP")"
echo "$KERNEL_VERSION_LINE"
echo "$KERNEL_VERSION_LINE" | grep -F '(Octoblimp@Android3DS)'
if grep -Fq "$(id -un)@$(hostname)" "$KERNEL_STRINGS_TMP"; then
    echo 'FATAL: private local account/hostname survived in the kernel' >&2
    exit 1
fi
grep -F 'export KBUILD_BUILD_USER=Octoblimp' "$PROJECT_ROOT/scripts/build_kernel.sh"
grep -F 'export KBUILD_BUILD_HOST=Android3DS' "$PROJECT_ROOT/scripts/build_kernel.sh"

echo '=== Initramfs shutdown path ==='
poweroff_target="$(readlink "${ANDROID3DS_ROOT}"/build/minimal_initramfs/root/sbin/poweroff)"
echo "/sbin/poweroff -> $poweroff_target"
test "$poweroff_target" = /usr/bin/busybox
test -x "${ANDROID3DS_ROOT}"/third_party/buildroot/output/target/usr/bin/busybox
zcat "$CARD_ROOT/initramfs.cpio.gz" | cpio -it 2>/dev/null | grep -x 'init'
# The four NWM blobs are Nintendo's and are not in the repository: each
# builder carves them from their own console (README "Firmware").
for blob in stub_data.bin database.bin stub_code.bin main_type4.bin; do
    zcat "$CARD_ROOT/initramfs.cpio.gz" | cpio -it 2>/dev/null \
        | grep -x "usr/lib/firmware/ath6k/AR6002/nwm/$blob" || {
        echo "FATAL: initramfs has no Wi-Fi firmware nwm/$blob. It is user-supplied:" >&2
        echo "  run scripts/extract_n3ds_firmware.py (README, Firmware), then rebuild the initramfs" >&2
        exit 1
    }
done
zcat "$CARD_ROOT/initramfs.cpio.gz" \
    | cpio -i --to-stdout init.rc 2>/dev/null > "$INITRC_TMP"
grep -F 'mkdir /data 0771 system system' "$INITRC_TMP"
grep -F 'mkdir /cache 0770 system cache' "$INITRC_TMP"
grep -F 'mount none /mnt/sd/linux/android/data/dalvik-cache /data/dalvik-cache bind' "$INITRC_TMP"
if grep -q 'symlink /mnt/sd/linux/android/data /data' "$INITRC_TMP"; then
    echo 'FATAL: /data is still a VFAT symlink and cannot preserve app UIDs' >&2
    exit 1
fi
echo '=== Deployed Android shutdown path ==='
test -s "$ANDROID_ROOT/etc/ctr_poweroff.sh"
echo '--- ctr_poweroff.sh ---'
grep -E 'POWER_OFF="\$\{N3DS_POWER_OFF:-/sbin/poweroff\}"|"\$POWER_OFF" -f|kernel deadline remains armed' \
    "$ANDROID_ROOT/etc/ctr_poweroff.sh"
grep -F 'N3DS_LOG_FINALIZATION_V2' "$ANDROID_ROOT/etc/ctr_poweroff.sh"
grep -F 'wait_for_log_writers' "$ANDROID_ROOT/etc/ctr_poweroff.sh"
grep -F 'check_storage_errors' "$ANDROID_ROOT/etc/ctr_poweroff.sh"
grep -F 'echo 1 > "$POWER_READY"' "$ANDROID_ROOT/etc/ctr_poweroff.sh"
if grep -Fq 'umount -l' "$ANDROID_ROOT/etc/ctr_poweroff.sh"; then
    echo 'FATAL: shutdown path still permits lazy SD detach' >&2
    exit 1
fi
grep -F 'N3DS_ROOT_POWER_FINALIZER' "$ANDROID_ROOT/etc/init.rc"
grep -F 'service ctr_poweroff /etc/ctr_poweroff.sh' "$ANDROID_ROOT/etc/init.rc"
grep -F 'on property:sys.n3ds.poweroff=1' "$ANDROID_ROOT/etc/init.rc"

echo '=== No Bluetooth runtime/configuration ==='
test -z "$(find "$ANDROID_ROOT" -iname '*bluetooth*' -o -iname '*bluez*')"
if grep -Rqi -E 'bluetooth|bluez' \
    "$ANDROID_ROOT/etc" "$ANDROID_ROOT/system/etc"; then
    echo 'FATAL: Bluetooth configuration survived in the SD Android tree' >&2
    exit 1
fi

echo '=== Single source of truth: hand-written sources and docs ==='
# Both of these were read out of the Windows workspace, where nothing
# version-controlled them. dsp_chime.c had no repository at all even though the
# binary it produces IS tracked at system/bin/dsp_chime; adbd_tcp_usb_stub.c had
# a STALE tracked copy in WSL that was missing n3ds_adbd_tcp_status(), so adbd
# -- the only shell into this device -- could not have been rebuilt from a clean
# checkout. telco_https.c joined them on 2026-09-13, when the resolver
# diagnostic that explains a failed DNS lookup was written into the untracked
# Windows copy; a clean checkout would have built a binary that could not say
# why it could not reach 3dstelco.divergen.io. All three now live in the WSL
# repo only. See docs/SOURCE_OF_TRUTH.md.
for n3ds_src in native/dsp_chime.c native/adbd_tcp_usb_stub.c \
                native/telco_https.c; do
    test -s "$NATIVE_ROOT/$n3ds_src"
    if [ -e "$WINDOWS_PROJECT_ROOT/$n3ds_src" ]; then
        echo "FATAL: $n3ds_src is back in the Windows workspace; it is owned by" >&2
        echo "       the WSL repo and a second copy will drift (docs/SOURCE_OF_TRUTH.md)" >&2
        exit 1
    fi
done
# transport_local.c calls this symbol; only the promoted copy defines it.
grep -Fq 'n3ds_adbd_tcp_status' "$NATIVE_ROOT/native/adbd_tcp_usb_stub.c"
grep -Fq 'n3ds_adbd_tcp_status' \
    "$NATIVE_ROOT/third_party/system_core/adb/transport_local.c"
# build_telco_https.sh cannot join the blanket sweep below: it writes its
# output to the SD card staging tree, which really is under /mnt/c. So check
# the one thing that matters -- where it reads the source from.
if grep -Fq 'PROJECT/native/telco_https.c' \
        "$NATIVE_ROOT/scripts/build_telco_https.sh"; then
    echo 'FATAL: build_telco_https.sh compiles the Windows copy of its source' >&2
    echo '       again; the WSL repo owns it (docs/SOURCE_OF_TRUTH.md)' >&2
    exit 1
fi
grep -Fq 'ROOT/native/telco_https.c' "$NATIVE_ROOT/scripts/build_telco_https.sh"
for n3ds_scr in build_dsp_chime.sh build_adbd.sh test_dsp_boot_chime.py; do
    if grep -Fq '/mnt/c/' "$NATIVE_ROOT/scripts/$n3ds_scr"; then
        echo "FATAL: scripts/$n3ds_scr reads a source out of the Windows workspace" >&2
        echo "       again; the WSL tree owns it (docs/SOURCE_OF_TRUTH.md)" >&2
        exit 1
    fi
done
# The session notes (HANDOFF.md, docs/SOURCE_OF_TRUTH.md, ...) are local-only
# since #328 and are not in the repository; only the research doc is.
test -s "$NATIVE_ROOT/docs/CAMERA_RESEARCH.md"

echo '=== DSP firmware ==='
# dspfirm.cdc is user-supplied (README "Firmware") and optional: sound goes
# through CSND, and ctr_dsp only logs "audio unavailable" without it. This
# used to cmp against a copy at the repository root, which is no longer
# shipped; the overlay is the one input, and the card must carry that file.
DSP_FW_OVERLAY="$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/usr/lib/firmware/3ds/dspfirm.cdc"
if [ -s "$DSP_FW_OVERLAY" ]; then
    cmp -s "$DSP_FW_OVERLAY" "$ANDROID_ROOT/usr/lib/firmware/3ds/dspfirm.cdc"
    echo "dspfirm.cdc: card copy matches the overlay"
else
    echo "dspfirm.cdc: not supplied (optional)"
fi
test ! -e "$ANDROID_ROOT/usr/share/sounds/boot.wav"
python3 "$PROJECT_ROOT/scripts/test_dsp_boot_chime.py"

echo '=== Boot sound ==='
# There used to be a FATAL here forbidding any boot script that touched
# /dev/eac, on the 2026-09-07 belief that the node was dead and the Teak DSP
# was the audio path. That is exactly backwards -- CSND drives the speakers
# through /dev/eac, and the user has heard it -- so the guard is gone and the
# real design is asserted instead.
test -x "$ANDROID_ROOT/etc/bootsound.sh"
test -s "$ANDROID_ROOT/system/media/bootsound.pcm"
grep -Fq '/dev/eac' "$ANDROID_ROOT/etc/bootsound.sh"
grep -Fq '/system/media/bootsound.pcm' "$ANDROID_ROOT/etc/bootsound.sh"
# It raises lead_ms so the whole clip is buffered ahead of the play cursor, and
# it must put the old value back or every later sound inherits a 2 s latency.
grep -Fq '/sys/module/ctr_csnd/parameters/lead_ms' "$ANDROID_ROOT/etc/bootsound.sh"
grep -Fq 'OLD_LEAD' "$ANDROID_ROOT/etc/bootsound.sh"
# #318: the clip is read into the page cache before the channel is claimed,
# and a second of silence is queued after it so the drain can only ever stop
# silence.  Without them the #317 device heard "DRO-" and nothing else.
grep -Fq 'N3DS_BOOT_SOUND_PREWARM' "$ANDROID_ROOT/etc/bootsound.sh"
# #320 (N3DS_BOOT_SOUND_WHOLE_FRAMES): the tail is dd in whole 4-byte stereo
# frames.  `head -c` flushed 1025-byte writev()s, hung on the odd byte, and the
# script never finished -- so it is refused outright, not just unused.
grep -Fq 'N3DS_BOOT_SOUND_WHOLE_FRAMES' "$ANDROID_ROOT/etc/bootsound.sh"
grep -Eq '^TAIL_COUNT=[1-9][0-9]*$' "$ANDROID_ROOT/etc/bootsound.sh"
tail_bs="$(sed -n 's/^TAIL_BS=\([1-9][0-9]*\)$/\1/p' "$ANDROID_ROOT/etc/bootsound.sh")"
if [ -z "$tail_bs" ] || [ $((tail_bs % 4)) -ne 0 ]; then
    echo "FATAL: bootsound.sh TAIL_BS='$tail_bs' is not a whole number of 4-byte stereo frames" >&2
    exit 1
fi
grep -Fq 'dd if=/dev/zero bs="$TAIL_BS" count="$TAIL_COUNT"' "$ANDROID_ROOT/etc/bootsound.sh"
if awk '!/^[[:space:]]*#/ && /head[[:space:]]+-c/ { f = 1 } END { exit !f }' "$ANDROID_ROOT/etc/bootsound.sh"; then
    echo 'FATAL: bootsound.sh writes with head -c; its 1025-byte writev()s hang /dev/eac' >&2
    exit 1
fi
# N3DS_BOOT_SOUND_NO_KILL (#319): the boot clip must play out and end by
# itself.  #318's `sleep 15; kill -KILL` watchdog cut the writer off; nothing
# in the script may kill or time out the writer again.
grep -Fq 'N3DS_BOOT_SOUND_NO_KILL' "$ANDROID_ROOT/etc/bootsound.sh"
if awk '!/^[[:space:]]*#/ && /(^|[^a-z_])(kill|timeout)[[:space:]]/ { f = 1 } END { exit !f }' "$ANDROID_ROOT/etc/bootsound.sh"; then
    echo 'FATAL: bootsound.sh kills or times out the writer; the clip must self-terminate' >&2
    exit 1
fi
if [ "$(grep -c '^service bootsound ' "$ANDROID_ROOT/etc/init.rc")" != "1" ]; then
    echo 'FATAL: init.rc does not declare bootsound exactly once' >&2
    exit 1
fi
# Ordering is load-bearing: class_start walks services in definition order, and
# mediaserver opens /dev/eac from AudioHardwareGeneric's constructor. The
# driver refuses to reset a channel another writer has claimed, so this is
# belt and braces -- but it is cheap, and it is how the clip got cut in half.
awk '
    /^service bootsound /   { if (!media) sound = NR }
    /^service mediaserver / { media = NR }
    END { exit (sound && media && sound < media) ? 0 : 1 }
' "$ANDROID_ROOT/etc/init.rc" || {
    echo 'FATAL: bootsound is not declared ahead of mediaserver in init.rc' >&2
    exit 1
}
# And it may not go back to being a child of the boot animation: SurfaceFlinger
# stops bootanim mid-clip the moment the first real frame is ready. A mention
# is fine -- bootanim.sh explains where the sound went -- so look for a write.
if grep -Fq '> /dev/eac' "$ANDROID_ROOT/etc/bootanim.sh"; then
    echo 'FATAL: the boot sound is back inside bootanim.sh, which is killed mid-clip' >&2
    exit 1
fi

echo '=== System-server runtime prerequisites ==='
grep -qx 'ro.sf.lcd_density=160' "$ANDROID_ROOT/system/build.prop"
test -x "$ANDROID_ROOT/system/bin/installd"
grep -F 'service installd /system/bin/installd' "$ANDROID_ROOT/etc/init.rc"
grep -F 'socket installd stream 600 system system' "$ANDROID_ROOT/etc/init.rc"
test -x "$ANDROID_ROOT/system/bin/adbd"
file "$ANDROID_ROOT/system/bin/adbd" | grep -F 'ARM'
file "$ANDROID_ROOT/system/bin/adbd" | grep -F 'statically linked'
# N3DS_ADB_ALWAYS_ROOT: this device ships pre-rooted by explicit request and
# has no USB gadget path, so adbd is started unconditionally over TCP rather
# than gated behind a Settings toggle. These checks used to require the toggle
# (port=0 in build.prop, start/stop property triggers), which the image has not
# done for some time -- and port=0 would have meant no adb at all.
grep -F 'N3DS_ADB_ALWAYS_ROOT' "$ANDROID_ROOT/etc/init.rc"
grep -F 'service adbd /system/bin/adbd' "$ANDROID_ROOT/etc/init.rc"
grep -Fx 'service.adb.tcp.port=5555' "$ANDROID_ROOT/system/build.prop"
if [ "$(grep -c '^service adbd ' "$ANDROID_ROOT/etc/init.rc")" != "1" ]; then
    echo 'FATAL: init.rc declares adbd more than once' >&2
    exit 1
fi
if grep -Fq '    disabled' "$ANDROID_ROOT/etc/init.rc" &&
   grep -A3 '^service adbd ' "$ANDROID_ROOT/etc/init.rc" | grep -Fq 'disabled'; then
    echo 'FATAL: adbd is declared disabled; the pre-rooted image expects it always on' >&2
    exit 1
fi
echo '=== Mobile Data / 3DS Telco deployable runtime ==='
test -s "$ANDROID_ROOT/system/lib/modules/ath6kl.ko"
file "$ANDROID_ROOT/system/lib/modules/ath6kl.ko" | grep -F 'ARM'
grep -F 'N3DS_WIFI_INITRAMFS_MODULE' \
    "$PROJECT_ROOT/scripts/build_minimal_initramfs.sh"
test -s "$NATIVE_ROOT/build/minimal_initramfs/root/n3ds/modules/ath6kl.ko"
cmp -s "$ANDROID_ROOT/system/lib/modules/ath6kl.ko" \
    "$NATIVE_ROOT/build/minimal_initramfs/root/n3ds/modules/ath6kl.ko"
zcat "$CARD_ROOT/initramfs.cpio.gz" \
    | cpio -i --to-stdout n3ds/modules/ath6kl.ko 2>/dev/null \
    > "$WIFI_INITRAMFS_TMP"
test -s "$WIFI_INITRAMFS_TMP"
cmp -s "$ANDROID_ROOT/system/lib/modules/ath6kl.ko" "$WIFI_INITRAMFS_TMP"
if zcat "$CARD_ROOT/initramfs.cpio.gz" \
        | cpio -it 2>/dev/null | grep -qx 'usr/lib/modules/ath6kl.ko'; then
    echo 'FATAL: Wi-Fi module is still packaged below the masked /usr mount' >&2
    exit 1
fi
grep -F "N3DS_ATH6KL_CFG80211_BEFORE_TRANSPORT" "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
strings "$ANDROID_ROOT/system/bin/app_process" \
    | grep -F '/n3ds/modules/ath6kl.ko'
strings "$ANDROID_ROOT/system/bin/app_process" \
    | grep -F '/system/lib/modules/ath6kl.ko'
grep -qx 'CONFIG_ATH6K_LEGACY=m' "$NATIVE_ROOT/third_party/linux/.config"
grep -qx 'CONFIG_MODULES=y' "$NATIVE_ROOT/third_party/linux/.config"
grep -qx 'CONFIG_MODULE_UNLOAD=y' "$NATIVE_ROOT/third_party/linux/.config"
grep -F 'N3DS_WIFI_RELOADABLE_ATH6KL' \
    "$NATIVE_ROOT/third_party/libhardware_legacy/wifi/wifi.c"
grep -F 'N3DS_ATH6KL_STARTUP_TEARDOWN' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"
echo '=== Retired local-AP Mobile Data runtime is absent ==='
test ! -e "$ANDROID_ROOT/etc/mobiledata.sh"
test ! -e "$ANDROID_ROOT/system/bin/mobiledata_ipc"
test ! -e "$ANDROID_ROOT/system/bin/mobiledata_apctl"
test ! -e "$ANDROID_ROOT/system/bin/mobiledata_dhcp"
test ! -e "$ANDROID_ROOT/system/bin/mobiledata_status"
if grep -RqiE 'service[.]mobiledata|sys[.]mobiledata|N3DS_MOBILE_DATA_LIFECYCLE|fwmode=2' \
        "$ANDROID_ROOT/etc" "$ANDROID_ROOT/system/build.prop"; then
    echo 'FATAL: retired AP-style Mobile Data configuration survived staging' >&2
    exit 1
fi
grep -F 'N3DS_ATH6KL_STARTUP_TEARDOWN' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"
grep -F 'wait_for_completion(&device->startup_completion)' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"
grep -F 'N3DS_WIFI_SDIO_RECOVERY' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_sdhc.c"
grep -F 'N3DS_ATH6KL_CFG80211_BEFORE_TRANSPORT' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
python3 "$PROJECT_ROOT/scripts/test_n3ds_wifi_sdio_recovery.py"
python3 "$PROJECT_ROOT/scripts/test_wifi_reloadable_driver.py"
readelf -Ws "$ANDROID_ROOT/system/lib/modules/ath6kl.ko" \
    | grep -F 'wait_for_completion'
readelf -Ws "$ANDROID_ROOT/system/lib/modules/ath6kl.ko" \
    | grep -E '[[:space:]]ar6000_ioctl$'
python3 "$PROJECT_ROOT/scripts/test_3ds_telco_client.py"
python3 "$PROJECT_ROOT/scripts/test_boot_connectivity_config.py"
python3 "$PROJECT_ROOT/scripts/test_telco_live_regressions.py"
python3 "$PROJECT_ROOT/scripts/test_telco_stock_apps_boot.py"
python3 "$PROJECT_ROOT/scripts/test_telco_config_java.py"
python3 "$PROJECT_ROOT/scripts/test_telco_identity_java.py"
python3 "$PROJECT_ROOT/scripts/test_telco_persistence.py"
test -s "$ANDROID_ROOT/system/app/TelephonyProvider.apk"
test -s "$ANDROID_ROOT/system/app/TelephonyProvider.odex"
test -s "$ANDROID_ROOT/system/app/ContactsProvider.apk"
test -s "$ANDROID_ROOT/system/app/ContactsProvider.odex"
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/ContactsProvider.apk" AndroidManifest.xml > "$MANIFEST_TMP"
for authority in 'contacts;com.android.contacts' call_log; do
    grep -F 'android:authorities' "$MANIFEST_TMP" | grep -F "=\"$authority\"" >/dev/null
done
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/TelephonyProvider.apk" AndroidManifest.xml > "$MANIFEST_TMP"
for authority in sms mms mms-sms; do
    grep -F 'android:authorities' "$MANIFEST_TMP" | grep -F "=\"$authority\"" >/dev/null
done
# N3DS_MEDIA_PROVIDER: the "media" authority the stock Camera app saves photos
# into and its gallery reads. scripts/build_media_provider.sh explains the two
# properties held here: no media scanner (there is no libmedia_jni, so a scan
# kills android.process.media and the Camera with it), and one certificate for
# the android.media shared user it has with Camera.apk -- on a mismatch
# PackageManagerService silently drops whichever of the two it scans second.
test -s "$ANDROID_ROOT/system/app/MediaProvider.apk"
test -s "$ANDROID_ROOT/system/app/MediaProvider.odex"
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/MediaProvider.apk" AndroidManifest.xml > "$MANIFEST_TMP"
grep -F 'android:authorities' "$MANIFEST_TMP" | grep -F '="media"' >/dev/null
if grep -E 'MediaScanner(Receiver|Service)' "$MANIFEST_TMP" >/dev/null; then
    echo 'FATAL: MediaProvider.apk declares the media scanner; rebuild with build_media_provider.sh' >&2
    exit 1
fi
media_uid_cert() {
    local listing block
    listing="$(unzip -Z1 "$1")"
    block="$(printf '%s\n' "$listing" | grep -E '^META-INF/[^/]+[.](RSA|DSA|EC)$' | awk 'NR == 1')"
    test -n "$block" || return 0
    unzip -p "$1" "$block" | openssl pkcs7 -inform DER -print_certs \
        | openssl x509 -noout -fingerprint -sha256
}
MEDIA_PROVIDER_CERT="$(media_uid_cert "$ANDROID_ROOT/system/app/MediaProvider.apk")"
MEDIA_CAMERA_CERT="$(media_uid_cert "$ANDROID_ROOT/system/app/Camera.apk")"
if [ -z "$MEDIA_PROVIDER_CERT" ] || [ "$MEDIA_PROVIDER_CERT" != "$MEDIA_CAMERA_CERT" ]; then
    echo 'FATAL: MediaProvider.apk and Camera.apk share android.media but not a certificate' >&2
    echo "       MediaProvider: ${MEDIA_PROVIDER_CERT:-unsigned}" >&2
    echo "       Camera:        ${MEDIA_CAMERA_CERT:-unsigned}" >&2
    exit 1
fi
sh "$PROJECT_ROOT/scripts/test_supplicant_boot_toggle.sh"
test -f "$PROJECT_ROOT/tools/3ds_telco_client.py"
test -f "$PROJECT_ROOT/tools/3ds_telco_service.py"
grep -F '3DS Telco' "$PROJECT_ROOT/tools/README.md"
echo '=== canonical AR6014 ioctl callback contract ==='
python3 "$PROJECT_ROOT/scripts/test_ar6014_ioctl_contract.py"
grep -F 'N3DS_ADBD_ROOTFS_SHELL' \
    "$NATIVE_ROOT/third_party/system_core/adb/services.c"
grep -F '#define SHELL_COMMAND "/bin/sh"' \
    "$NATIVE_ROOT/third_party/system_core/adb/services.c"
unzip -p "$ANDROID_ROOT/system/framework/services.jar" classes.dex > "$SERVICES_DEX_TMP"
WIFI_SERVICE_SRC="$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/WifiService.java"
grep -F 'N3DS_WIFI_FILE_BOOT_ENABLE' "$WIFI_SERVICE_SRC"
grep -aF '/sdcard/persistent/shared/wpa_supplicant.conf' "$SERVICES_DEX_TMP"
grep -aF 'wifi_on_boot=1' "$SERVICES_DEX_TMP"
if grep -aFq 'Deferring persisted Wi-Fi enable until an explicit user toggle' "$SERVICES_DEX_TMP"; then
    echo 'FATAL: services.jar retains the obsolete manual-only Wi-Fi policy' >&2
    exit 1
fi
unzip -p "$ANDROID_ROOT/system/app/Phone.apk" classes.dex > "$PHONE_DEX_TMP"
grep -aF '/sdcard/persistent/shared/mobile_registration.conf' "$PHONE_DEX_TMP"
grep -aF 'Waiting for Wi-Fi hardware before registration.' "$PHONE_DEX_TMP"
unzip -p "$ANDROID_ROOT/system/app/Mms.apk" classes.dex > "$MMS_DEX_TMP"
grep -aF 'N3DS_MMS_MISSING_PROVIDER_GUARD' "$MMS_DEX_TMP"
grep -aF 'N3DS_MMS_MISSING_DRM_PROVIDER_GUARD' "$MMS_DEX_TMP"
grep -aF 'N3DS_MMS_MISSING_SMS_PROVIDER_GUARD' "$MMS_DEX_TMP"
# N3DS_NO_STOCK_CONTACTS (#317): the stock Contacts app is retired -- the
# dialer is N3dsDialer, ContactsProvider stays.  output/target is additive,
# so refuse the APK outright rather than trusting that nothing restaged it.
for retired in Contacts.apk Contacts.odex DevTools.apk DevTools.odex \
               N3dsCamera.apk N3dsCamera.odex \
               N3DSKeyboard.apk N3DSKeyboard.odex; do
    if [ -e "$ANDROID_ROOT/system/app/$retired" ]; then
        echo "FATAL: retired stock app $retired is staged in $ANDROID_ROOT/system/app" >&2
        exit 1
    fi
done
# N3DS_PRUNE_RETIRED_APPS (#318): not staging it was not enough.  sdcard.zip
# is extracted over the card and cannot delete, so the #317 device still had
# an old Contacts.apk and installed it.  prune_retired_apps.sh removes the
# retired names at boot; it must exist, name every one of them, and run from
# init.rc before class_start starts the package scan.
test -x "$ANDROID_ROOT/etc/prune_retired_apps.sh"
for app in Contacts DevTools N3dsCamera N3DSKeyboard; do
    grep -Eq "^RETIRED=\"([^\"]* )?$app( [^\"]*)?\"" "$ANDROID_ROOT/etc/prune_retired_apps.sh" || {
        echo "FATAL: prune_retired_apps.sh does not retire $app" >&2
        exit 1
    }
done
awk '
    /^[[:space:]]*exec \/etc\/prune_retired_apps\.sh/ { if (!cs) prune = NR }
    /^[[:space:]]*class_start default/                { if (!cs) cs = NR }
    END { exit (prune && cs && prune < cs) ? 0 : 1 }
' "$ANDROID_ROOT/etc/init.rc" || {
    echo 'FATAL: init.rc does not exec prune_retired_apps.sh ahead of class_start default' >&2
    exit 1
}
# N3DS_CONTACTS_INSERT_OR_EDIT: Mms "Add to contacts" starts INSERT_OR_EDIT
# unguarded; with the stock app gone, N3dsDialer's editor must answer it or
# the tap force-closes Mms.
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/N3dsDialer.apk" AndroidManifest.xml \
    | grep -F '"android.intent.action.INSERT_OR_EDIT"' >/dev/null || {
    echo "FATAL: N3dsDialer.apk does not handle INSERT_OR_EDIT (Mms Add to contacts)" >&2
    exit 1
}
grep -F 'N3DS_TELCO_STATUSBAR_ONLINE_STATE' "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/status/StatusBarPolicy.java"
grep -aF 'n3ds_telco_status' "$SERVICES_DEX_TMP"
grep -aF 'n3ds_telco_latency_ms' "$SERVICES_DEX_TMP"
grep -aF 'n3ds_telco_latency_sample_elapsed_ms' "$SERVICES_DEX_TMP"
grep -aF 'registration_storage_failed' "$PHONE_DEX_TMP"
grep -aF 'pending_config' "$PHONE_DEX_TMP"
grep -aF 'N3DS_TELCO_MESSAGE_JOURNAL_V1' "$PHONE_DEX_TMP"
grep -aF '/sdcard/persistent/shared/messages' "$PHONE_DEX_TMP"
python3 "$PROJECT_ROOT/scripts/test_telco_message_persistence.py"
grep -aF 'Registered and online' "$SERVICES_DEX_TMP"
grep -F 'mDataData.iconId = com.android.internal.R.drawable.stat_sys_data_connected_3g;' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/status/StatusBarPolicy.java"
grep -aF 'Skipping optional load-average overlay on n3ds' "$SERVICES_DEX_TMP"
grep -aF 'Audio service absent; volume status disabled' "$SERVICES_DEX_TMP"
# The Settings activity belongs to Settings.apk. The retired AP status
# notification embedded its class name in services.jar; current 3G policy
# does not launch that notification. Verify the real installed component.
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/Settings.apk" AndroidManifest.xml \
    | grep -F 'MobileDataSettings' >/dev/null
# #324: B and X now toggle the switcher from the policy looper; the old
# direct-call log line is gone (see N3DS_RECENTS_TOGGLE below).
grep -aF 'n3ds B/X: toggling recent applications' "$SERVICES_DEX_TMP"
grep -aF 'n3ds low-cost notification shade enabled' "$SERVICES_DEX_TMP"
grep -aF 'N3DS touch ' "$SERVICES_DEX_TMP"
grep -aF 'Failure synchronizing ADB setting; continuing boot' "$SERVICES_DEX_TMP"
grep -aF 'N3DS HOME resolver empty; using bundled Launcher' "$SERVICES_DEX_TMP"
grep -aF 'N3DS finalized poweroff requested' "$SERVICES_DEX_TMP"
if strings "$SERVICES_DEX_TMP" | grep -q 'Window .* destroying surface'; then
    echo 'FATAL: services.jar still contains WindowManager surface-destruction stack logging' >&2
    exit 1
fi
if strings "$SERVICES_DEX_TMP" \
    | grep -q 'com/android/internal/location/GpsLocationProvider'; then
    echo 'FATAL: services.jar can still initialize the unavailable GPS JNI provider' >&2
    exit 1
fi

echo '=== Physical input mappings and KeyCharacterMap runtime ==='
TOUCH_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/tsc/touch.c"
grep -F 'Android3DS Direct Touchscreen' "$TOUCH_SRC"
grep -F 'input_set_abs_params(input, ABS_X, 0, SCREEN_WIDTH - 1' "$TOUCH_SRC"
grep -F 'input_set_abs_params(input, ABS_Y, 0, SCREEN_HEIGHT - 1' "$TOUCH_SRC"
grep -F 'input_set_abs_params(input, ABS_PRESSURE, 0, 1' "$TOUCH_SRC"
# 4 ms, not 1: with the ctr_spi wake fixed a poll really runs at its
# interval, and 1 ms was a hundredfold load jump (N3DS_SPI_WAKE).
grep -F '#define POLL_INTERVAL_MS 4' "$TOUCH_SRC"
grep -F '#define DIAGNOSTIC_INTERVAL_POLLS (5000 / POLL_INTERVAL_MS)' "$TOUCH_SRC"
grep -F 'CONFIG_HZ_1000=y' "$NATIVE_ROOT/third_party/linux/.config"
grep -F 'input_set_capability(input, EV_KEY, BTN_TOUCH)' "$TOUCH_SRC"
grep -F 'set_bit(INPUT_PROP_DIRECT, input->propbit)' "$TOUCH_SRC"
grep -F 'N3DS_HARDWARE_SINGLE_TOUCH' "$TOUCH_SRC"
if grep -Eq 'ABS_MT_|input_mt_sync' "$TOUCH_SRC"; then
    echo 'FATAL: single-contact 3DS panel still advertises synthetic multitouch' >&2
    exit 1
fi
grep -F 'N3DS_TOUCH_ABS_PRESSURE_FALLBACK' \
    "$NATIVE_ROOT/third_party/frameworks/base/libs/ui/EventHub.cpp"
grep -F 'N3DS_TOUCH_PRESSURE_SETS_DOWN' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/KeyInputQueue.java"
grep -F 'N3DS_SINGLE_TOUCH_DISPATCH_TRACE' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/KeyInputQueue.java"
grep -F 'N3DS_TOUCH_ABS_WAKE_PRESERVE' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/WindowManagerService.java"
# N3DS_CIRCLEPAD_TRACKBALL (#322): the circle pad is a second input_dev in
# touch.c, so this checks the touchscreen's own device ("input"), not the
# file: every REL capability and report must belong to "cpad".
if grep -Eq 'input_set_capability\(input,[[:space:]]*EV_(REL|KEY,[[:space:]]*BTN_MOUSE)|input_report_rel\(input,|set_bit\(REL_' \
    "$TOUCH_SRC"; then
    echo 'FATAL: replacement Android touchscreen is still a hybrid relative device' >&2
    exit 1
fi
# No "grep -q" at the end of a pipe: under pipefail its early exit SIGPIPEs
# the producer and the whole test reads as false.
CPAD_STRAY_REL="$(grep -E 'input_report_rel\(|EV_REL' "$TOUCH_SRC" \
    | grep -Ev 'input_report_rel\(ts->cpad, REL_[XY],|input_set_capability\(cpad, EV_REL, REL_[XY]\)|^[[:space:]]*(/?\*|//)' \
    || true)"
if [ -n "$CPAD_STRAY_REL" ]; then
    printf '%s\n' "$CPAD_STRAY_REL" >&2
    echo 'FATAL: a relative axis in touch.c is not on the circle pad device' >&2
    exit 1
fi
unset CPAD_STRAY_REL
grep -F 'cpad->name = "Android3DS Circle Pad";' "$TOUCH_SRC"
grep -F 'input_set_capability(cpad, EV_REL, REL_X);' "$TOUCH_SRC"
grep -F 'input_set_capability(cpad, EV_REL, REL_Y);' "$TOUCH_SRC"
# EventHub calls a REL device a trackball only if it also has BTN_MOUSE.
grep -F 'input_set_capability(cpad, EV_KEY, BTN_MOUSE);' "$TOUCH_SRC"
grep -F 'android3ds_cpad_update(ts, fifo);' "$TOUCH_SRC"
grep -F 'test_bit(BTN_MOUSE, key_bitmask)' \
    "$NATIVE_ROOT/third_party/frameworks/base/libs/ui/EventHub.cpp"
CPAD_FW="$NATIVE_ROOT/third_party/frameworks/base/core/java/android"
grep -F 'N3DS_CIRCLEPAD_DPAD' "$CPAD_FW/view/ViewRoot.java"
grep -F 'private static final boolean DEBUG_TRACKBALL = false || LOCAL_LOGV;' \
    "$CPAD_FW/view/ViewRoot.java"
grep -F 'N3DS_CIRCLEPAD_PAN' "$CPAD_FW/webkit/WebView.java"
# The shipped framework.jar, not just the source: dex keeps member names.
CPAD_DEX_STRINGS="$(unzip -p "$ANDROID_ROOT/system/framework/framework.jar" classes.dex | strings)"
for member in deliverCirclePadDpad mPadRepeating mPadPanRemainX; do
    grep -x "$member" <<<"$CPAD_DEX_STRINGS" >/dev/null || {
        echo "FATAL: framework.jar lacks $member (N3DS_CIRCLEPAD_DPAD/PAN)" >&2
        exit 1
    }
done
unset CPAD_DEX_STRINGS
grep -F 'N3DS_NO_LEGACY_APP_SWITCH_GATE' \
    "$NATIVE_ROOT/third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/PhoneWindowManager.java"
grep -F 'N3DS_SLOW_CPU_KEY_DISPATCH_TIMEOUT' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/am/ActivityManagerService.java"
grep -F 'static final int KEY_DISPATCHING_TIMEOUT = 30*1000;' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/am/ActivityManagerService.java"
grep -F 'N3DS_SHADE_REQUIRES_DRAG' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/status/StatusBarService.java"
grep -F 'N3DS_SHADE_COLLAPSE_ON_MOVE' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/status/StatusBarService.java"
grep -F 'N3DS_NATIVE_ALL_APPS_DRAWER' \
    "$NATIVE_ROOT/third_party/launcher2/src/com/android/launcher2/AllAppsView.java"
if grep -Eq 'extends[[:space:]]+RSSurfaceView|import[[:space:]]+android[.]renderscript|lockCanvas[(]|SurfaceHolder[[:space:]]' \
    "$NATIVE_ROOT/third_party/launcher2/src/com/android/launcher2/AllAppsView.java"; then
    echo 'FATAL: custom Surface/RenderScript All Apps overlay survived' >&2
    exit 1
fi
grep -F 'N3DS_HOME_CLOSES_SOFTWARE_DRAWER' \
    "$NATIVE_ROOT/third_party/launcher2/src/com/android/launcher2/Launcher.java"
grep -F 'N3DS_SELECT_GLOBAL_ACTIONS' \
    "$NATIVE_ROOT/third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/PhoneWindowManager.java"
# #324: B and X toggle the running-apps switcher from the policy looper (the
# InputDispatcher thread has none, so the dialog never opened); it closes apps.
POLICY_IMPL="$NATIVE_ROOT/third_party/frameworks/policies/base/phone/com/android/internal/policy/impl"
grep -F 'N3DS_RECENTS_TOGGLE' "$POLICY_IMPL/PhoneWindowManager.java"
grep -F 'mHandler.post(mN3dsRecentsToggle);' "$POLICY_IMPL/PhoneWindowManager.java"
grep -F 'N3DS_RECENTS_CLOSE' "$POLICY_IMPL/RecentApplicationsDialog.java"
grep -F 'n3dsCanClose' "$POLICY_IMPL/RecentApplicationsDialog.java"
grep -aF 'N3DS_RECENTS_CLOSE: closing ' "$SERVICES_DEX_TMP"
grep -aF 'n3ds B/X: toggling recent applications' "$SERVICES_DEX_TMP"
if grep -Eq '^key[[:space:]]+304[[:space:]]+' \
    "$ANDROID_ROOT/system/usr/keylayout/hid_buttons.kl"; then
    echo 'FATAL: BTN_A must not be mapped to Android navigation' >&2
    exit 1
fi
NAV_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_navkey.c"
grep -F 'source=\"%s\" code=%u value=%d -> code=%d' "$NAV_SRC"
# #324: X opens recent apps like B; the per-press line is pr_debug.
grep -F 'N3DS_NAVKEY_X_RECENTS' "$NAV_SRC"
grep -F 'pr_debug("source=' "$NAV_SRC"
grep -F 'ctr_navkey_init' "$CARD_ROOT/System.map"
grep -F 'ctr_navkey_event' "$CARD_ROOT/System.map"
grep -F 'obj-$(CONFIG_CTR_NAVKEY)' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/Makefile"
grep -Eq '^key[[:space:]]+102[[:space:]]+HOME([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -Eq '^key[[:space:]]+148[[:space:]]+B([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -Eq '^key[[:space:]]+158[[:space:]]+BACK([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -Eq '^key[[:space:]]+28[[:space:]]+DPAD_CENTER([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -Eq '^key[[:space:]]+116[[:space:]]+POWER([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -F 'N3DS_SELECT_SYNTHETIC_POWER_HOLD' "$NAV_SRC"
grep -F 'SELECT_HOLD_MS 500' "$NAV_SRC"
grep -Eq '^key[[:space:]]+103[[:space:]]+DPAD_UP([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -Eq '^key[[:space:]]+108[[:space:]]+DPAD_DOWN([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -Eq '^key[[:space:]]+105[[:space:]]+DPAD_LEFT([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -Eq '^key[[:space:]]+106[[:space:]]+DPAD_RIGHT([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -F 'BTN_A' "$NAV_SRC"
if grep -Eq '^key[[:space:]]+(102|305|308)[[:space:]]+' \
    "$ANDROID_ROOT/system/usr/keylayout/hid_buttons.kl" \
    "$ANDROID_ROOT/system/usr/keylayout/mcu_buttons.kl"; then
    echo 'FATAL: source input devices must not duplicate translated navigation' >&2
    exit 1
fi

echo '=== Old 3DS dual-core and New 3DS four-core/full-clock/PL310 gates ==='
ATH6_AR6K_SRC="$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/htc2/AR6000/ar6k.c"
CTR_SDHC_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_sdhc.c"
ATH6_WMI_SRC="$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/wmi/wmi.c"
ATH6_HIF_SRC="$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"
ATH6_CFG80211_SRC="$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/os/linux/cfg80211.c"
ATH6_DRIVER_SRC="$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
grep -F 'N3DS_SDIO_POLL_UNMASK_ORDER' "$ATH6_AR6K_SRC"
grep -F 'AR6002 HTC IRQ arm complete: target enabled, SDIO poller started' \
    "$KERNEL_STRINGS_TMP"
grep -F 'N3DS_SDIO_IRQ_TIMER_FALLBACK' "$CTR_SDHC_SRC"
grep -F 'MMC_CAP_SDIO_IRQ' "$CTR_SDHC_SRC"
grep -F 'N3DS_SDHC_CMD53_TRACE_CONTROL' "$CTR_SDHC_SRC"
grep -F 'static bool cmd53_success_trace;' "$CTR_SDHC_SRC"
grep -F 'if (cmd53_success_trace && mrq->cmd' "$CTR_SDHC_SRC"
grep -F 'AR6002 SDHC CMD53 error status=' "$CTR_SDHC_SRC"
test -f "$PROJECT_ROOT/scripts/patch_ctr_sdhc_trace_control.py"
python3 "$PROJECT_ROOT/scripts/test_ctr_sdhc_trace_control.py"
# N3DS_SDIO_POLL_REALTIME (#321): "10 ms" really ran every 3.3 ms while
# the kernel clock was 3x fast (N3DS_TWD_PERIPHCLK); Wi-Fi was proven on
# that cadence, so the period is now 3 real ms.
grep -F 'N3DS_SDIO_POLL_REALTIME' "$CTR_SDHC_SRC"
grep -P '^#define SDHC_SDIO_POLL_MS\t3$' "$CTR_SDHC_SRC"
grep -F 'AR6002 SDHC IRQ timer fallback=v4 period=%ums cap=hardware (N3DS_SDIO_POLL_REALTIME)' \
    "$KERNEL_STRINGS_TMP"
grep -F 'N3DS_AR6014_LEGACY_WMI_READY' "$ATH6_WMI_SRC"
grep -F 'N3DS_BOUNDED_HIF_SYNC_TRACE' "$ATH6_HIF_SRC"
grep -F 'N3DS_CFG80211_SCAN_REQUEST_ORDER' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_CFG80211_SCAN_COMPLETION_OWNERSHIP' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_BOUNDED_CFG80211_SCAN_TRACE' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_CFG80211_BSS_CHANNEL_GUARD' "$ATH6_CFG80211_SRC"
grep -F 'if (!channel)' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_CFG80211_SCAN_IE_CAPABILITY' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_NWM_PROBED_SSID_SLOTS' "$ATH6_CFG80211_SRC"
grep -F '#define N3DS_MAX_SCAN_PROBED_SSIDS 5' "$ATH6_CFG80211_SRC"
grep -F 'wdev->wiphy->max_scan_ssids = N3DS_MAX_SCAN_PROBED_SSIDS;' \
    "$ATH6_CFG80211_SRC"
grep -F 'N3DS_AR6014_ASSOCIATION_COMPAT' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_AR6014_RECONNECT_REMOVED' "$ATH6_DRIVER_SRC"
grep -F 'N3DS_AR6014_NO_NETWORK_HANDOFF' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_AR6014_NWM_DISCONNECT_BOUNDS' "$ATH6_WMI_SRC"
grep -F 'N3DS_AR6014_CFG80211_DBM_SIGNAL' "$ATH6_CFG80211_SRC"
grep -F 'signal = (s32)ni->ni_rssi * 100;' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_AR6014_SHORT_DISCONNECT' "$ATH6_WMI_SRC"
grep -F 'N3DS_AR6014_NWM_PRECONNECT_KEEPALIVE' "$ATH6_WMI_SRC"
grep -F 'wmi_set_keepalive_cmd(wmip, 0)' "$ATH6_WMI_SRC"
# Build #253 replaced the station path's hardcoded `arConnectCtrlFlags = 0`
# (N3DS_AR6014_NWM_CONNECT_FLAGS) with the swept value; ctrl_flags was the one
# WMI_CONNECT field never varied, and CONNECT_PROFILE_MATCH_DONE produced this
# port's first association.  The invariant that survives is that the field is
# always assigned and never inherited: from the variant table on the station
# path, and back to 0 on the AP path so a commit cannot inherit a swept value.
grep -F 'N3DS_AR6014_CONNECT_CTRL_FLAGS_SWEEP' "$ATH6_CFG80211_SRC"
grep -F 'ar->arConnectCtrlFlags = cv->ctrl_flags;' "$ATH6_CFG80211_SRC"
grep -F 'ar->arConnectCtrlFlags = 0;' "$ATH6_DRIVER_SRC"
grep -F 'N3DS_AR6014_NWM_HOST_WPA' "$ATH6_CFG80211_SRC"
grep -F 'wmi_set_appie_cmd(ar->arWmi, WMI_FRAME_ASSOC_REQ' "$ATH6_CFG80211_SRC"
# #253's sweep made the WMI auth-mode argument conditional, so the old literal
# `ar->arDot11AuthMode, NONE_AUTH` pair no longer appears.  What NWM_HOST_WPA
# requires is unchanged: the station path still drives wmi_connect_cmd itself,
# and the auth mode comes from the variant table with NONE_AUTH as the arm that
# leaves the 4-way handshake to the host instead of offloading it to the target.
grep -F 'status = wmi_connect_cmd(ar->arWmi, ar->arNetworkType,' \
    "$ATH6_CFG80211_SRC"
grep -F 'cv->real_auth ? (AUTH_MODE)ar->arAuthMode' "$ATH6_CFG80211_SRC"
grep -F ': NONE_AUTH,' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_AR6014_NWM_APPIE_LAYOUT' "$ATH6_WMI_SRC"
grep -F 'N3DS_AR6014_NWM_AES_KEY_TYPE' "$ATH6_WMI_SRC"
grep -F 'AR6002 connect: NWM APP-IE len=' "$KERNEL_STRINGS_TMP"
grep -F 'AR6002 key: NWM type host=' "$KERNEL_STRINGS_TMP"
grep -F 'N3DS_AR6014_NWM_WMI_U16_HEADER' "$ATH6_WMI_SRC"
grep -F 'A_NETBUF_PUSH(osbuf, sizeof(u16))' "$ATH6_WMI_SRC"
grep -F 'A_NETBUF_PULL(osbuf, sizeof(u16))' "$ATH6_WMI_SRC"
grep -F 'AR6002 WMI: NWM u16 command/event header active' "$KERNEL_STRINGS_TMP"
test -f "$PROJECT_ROOT/scripts/patch_ar6014_nwm_data_header.py"
python3 "$PROJECT_ROOT/scripts/test_ar6014_nwm_data_header.py"
grep -F 'N3DS_AR6014_NWM_DATA_HEADER' "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/include/common/wmi.h"
grep -F 'N3DS_AR6014_NWM_DATA_INFO_LAYOUT' "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/include/common/wmi.h"
grep -F 'BUILD_BUG_ON(sizeof(WMI_DATA_HDR) != 2)' "$ATH6_WMI_SRC"
grep -F 'A_NETBUF_PUSH(osbuf, sizeof(WMI_DATA_HDR))' "$ATH6_WMI_SRC"
grep -F 'A_NETBUF_PULL(osbuf, sizeof(WMI_DATA_HDR))' "$ATH6_WMI_SRC"
grep -F 'N3DS_AR6014_NWM_DATA_METADATA_DISABLED' "$ATH6_WMI_SRC"
grep -F 'N3DS_AR6014_NWM_SYNC_HEADER_ZERO' "$ATH6_WMI_SRC"
grep -F 'N3DS_AR6014_NWM_RX_8023_BOUNDS' "$ATH6_DRIVER_SRC"
grep -F 'N3DS_AR6014_NWM_RX_REORDER_BYPASS' "$ATH6_DRIVER_SRC"
grep -F 'N3DS_AR6014_NWM_RX_PREFIX_BOUNDS' "$ATH6_DRIVER_SRC"
grep -F 'N3DS_AR6014_NWM_RX_METADATA_DISABLED' "$ATH6_DRIVER_SRC"
grep -F 'N3DS_AR6014_NWM_CHECKSUM_FALLBACK' "$ATH6_DRIVER_SRC"
grep -F 'A_NETBUF_LEN(skb)' "$ATH6_DRIVER_SRC"
grep -F 'ar->rxMetaVersion = 0;' "$ATH6_DRIVER_SRC"
grep -F 'skb_checksum_help(skb)' "$ATH6_DRIVER_SRC"
grep -F 'AR6002 data: NWM two-byte header active; checksum metadata disabled' "$KERNEL_STRINGS_TMP"
grep -F 'N3DS_AR6014_NWM_SHORT_DISCONNECT_LAYOUT' "$ATH6_WMI_SRC"
grep -F 'reason = datap[ATH_MAC_LEN];' "$ATH6_WMI_SRC"
grep -F 'N3DS_AR6014_NWM_READY_LAYOUT' "$ATH6_WMI_SRC"
grep -F 'len == sizeof(NWM_READY_EVENT)' "$ATH6_WMI_SRC"
grep -F 'AR6002 WMI NWM READY len=' "$KERNEL_STRINGS_TMP"
grep -F 'N3DS_AR6014_NWM_CHANNEL_TABLE' "$ATH6_CFG80211_SRC"
grep -F 'wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE' \
    "$ATH6_CFG80211_SRC"
grep -F 'AR6002 connect: search channel %u; NWM channel table mode=11G count=1' \
    "$ATH6_CFG80211_SRC"
grep -F 'AR6002 connect: search channel %u; NWM channel table mode=11G count=1' \
    "$KERNEL_STRINGS_TMP"
test -f "$PROJECT_ROOT/scripts/patch_ar6014_nwm_channel_table.py"
python3 "$PROJECT_ROOT/scripts/test_ar6014_nwm_channel_table.py"
grep -F 'N3DS_AR6014_NWM_CONNECTION_SCAN' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_AR6014_DISCOVERY_CONNECT_SPLIT' "$ATH6_CFG80211_SRC"
grep -F 'n3ds_ar6014_program_discovery_ssids(ar, request' "$ATH6_CFG80211_SRC"
grep -F 'SPECIFIC_SSID_FLAG : ANY_SSID_FLAG' "$ATH6_CFG80211_SRC"
grep -F 'wmi_scanparams_cmd(ar->arWmi, 0xffff, 0xffff, 0xffff' \
    "$ATH6_CFG80211_SRC"
grep -F '0, 0, num_channels, channel_list' "$ATH6_CFG80211_SRC"
grep -F 'AR6002 scan: discovery explicit channels=%d wildcard=%u' \
    "$KERNEL_STRINGS_TMP"
# The standalone scan-policy print is now the `stockscan=%u` field of the
# VARIANT line, which logs every field of the 52-byte WMI_CONNECT_CMD in one
# record.  Pin that line instead: it is strictly more coverage, not less.
grep -F 'AR6002 connect: VARIANT %d %s auth=%u pair=%u/%u group=%u/%u' \
    "$KERNEL_STRINGS_TMP"
test -f "$PROJECT_ROOT/scripts/patch_ar6014_nwm_connection_scan.py"
python3 "$PROJECT_ROOT/scripts/test_ar6014_nwm_connection_scan.py"
test -f "$PROJECT_ROOT/scripts/patch_ar6014_discovery_connect_split.py"
python3 "$PROJECT_ROOT/scripts/test_ar6014_discovery_connect_split.py"
grep -F 'wdev->wiphy->max_scan_ie_len = 1000;' "$ATH6_CFG80211_SRC"
grep -F '.scan = ar6k_cfg80211_scan' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_HIF_SYNC_CALLER_FASTPATH' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"
grep -F 'static bool hif_sync_fastpath = true;' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/hif/sdio/linux_sdio/src/hif.c"
grep -F 'N3DS_SDIO_INLINE_SHORT_PIO' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_sdhc.c"
grep -F 'static unsigned int pio_inline_max = 128;' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_sdhc.c"
grep -F 'N3DS_AR6014_DIAG_WINDOW_SERIALIZATION' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/miscdrv/common_drv.c"
grep -F 'N3DS_AR6014_DIAG_CONSERVATIVE_PANIC_FIX' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/miscdrv/common_drv.c"
if grep -Fq 'N3DS_AR6014_DIAG_PAGE_FASTPATH' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/miscdrv/common_drv.c"; then
    echo 'FATAL: unsafe AR6014 LSB-only diagnostic address shortcut returned' >&2
    exit 1
fi
grep -F 'N3DS_HIF_DSR_NONFATAL_RECOVERY' "$ATH6_HIF_SRC"
grep -F 'N3DS_WMI_BSS_CHANNEL_GUARD' "$ATH6_WMI_SRC"
grep -F 'bih->channel > 2472' "$ATH6_WMI_SRC"
if grep -Fq 'AR_DEBUG_ASSERT(status == 0 || status == A_ECANCELED);' \
    "$ATH6_HIF_SRC"; then
    echo 'FATAL: transient AR6014 DSR status still panics the kernel' >&2
    exit 1
fi
grep -F 'N3DS_AR6014_DIRECT_WMI_ONLY' "$ATH6_DRIVER_SRC"
grep -F 'N3DS_NWM_FULL_BSS_HEADER' "$ATH6_WMI_SRC"
grep -F 'wmi_n3ds_full_bss_header = true;' "$ATH6_WMI_SRC"
grep -F 'direct BSS accepted=%u; no RAM harvest' "$KERNEL_STRINGS_TMP"
if grep -Eq 'ar6014_harvest|AR6014_HARVEST|wmi_inject_bssinfo|RAM harvest merge|harvest complete injected=' \
    "$ATH6_DRIVER_SRC" "$ATH6_WMI_SRC" "$KERNEL_STRINGS_TMP"; then
    echo 'FATAL: RAM harvest source survived' >&2
    exit 1
fi
test ! -e "$NATIVE_ROOT/third_party/buildroot/package/wpa_supplicant/0002-n3ds-ar6014-scan-harvest-timeout.patch"
grep -F 'N3DS_WPA_SCAN_SECURITY_INTEGRITY' \
    "$NATIVE_ROOT/third_party/buildroot/package/wpa_supplicant/0005-n3ds-scan-security-integrity.patch"
grep -F 'N3DS_WPA_SCAN_SECURITY_INTEGRITY_V2' \
    "$NATIVE_ROOT/third_party/buildroot/package/wpa_supplicant/0005-n3ds-scan-security-integrity.patch"
grep -F 'N3DS-SECURITY-UNKNOWN' \
    "$NATIVE_ROOT/third_party/buildroot/package/wpa_supplicant/0005-n3ds-scan-security-integrity.patch"
grep -F 'wpa_parse_wpa_ie(ie, ie_len, &data)' \
    "$NATIVE_ROOT/third_party/buildroot/package/wpa_supplicant/0005-n3ds-scan-security-integrity.patch"
echo '=== Deployed initramfs supplicant security markers ==='
zcat "$CARD_ROOT/initramfs.cpio.gz" \
    | cpio -i --to-stdout usr/sbin/wpa_supplicant 2>/dev/null \
    > "$WPA_INITRAMFS_TMP"
test -s "$WPA_INITRAMFS_TMP"
for marker in $WPA_RUNTIME_MARKERS; do
    strings "$WPA_INITRAMFS_TMP" | grep -F "$marker"
done
grep -F 'public static final int RSN = 1;' \
    "$NATIVE_ROOT/third_party/frameworks/base/wifi/java/android/net/wifi/WifiConfiguration.java"
grep -F 'WPA/WPA2 PSK' \
    "$NATIVE_ROOT/third_party/settings/res/values/arrays.xml"
grep -F 'WPA2_PSK_AUTH' \
    "$NATIVE_ROOT/third_party/linux/drivers/staging/ath6k_legacy/include/common/wmi.h"
grep -F 'wmi_n3ds_take_direct_bss_count(ar->arWmi)' "$ATH6_DRIVER_SRC"
grep -F 'wmip->wmi_n3ds_direct_bss_count++;' "$ATH6_WMI_SRC"
grep -F 'AR6002 scan: direct BSS accepted=' "$KERNEL_STRINGS_TMP"
grep -F 'len >= (int)sizeof(*ev)' "$ATH6_WMI_SRC"
grep -F 'AR6002 scan: START_SCAN submitted' "$KERNEL_STRINGS_TMP"
grep -F 'AR6002 WMI READY legacy len=' "$KERNEL_STRINGS_TMP"
grep -F 'Nintendo AR6014 legacy READY; non-fatal' "$KERNEL_STRINGS_TMP"
grep -F 'AR6002 connect: search channel' "$KERNEL_STRINGS_TMP"
grep -F 'AR6002 connect: short disconnect' "$KERNEL_STRINGS_TMP"
grep -F 'AR6002 connect: NWM disconnect len=' "$KERNEL_STRINGS_TMP"
# W8 generalised the NO_NETWORK_AVAIL-only handoff to every disconnect reason,
# so the old print is gone; its replacement reports the reason, the protocol
# status and the SME state, which is what actually distinguishes a host-asked
# teardown (reason=3, a supplicant timer) from a target-side one.
grep -F 'AR6002 connect: disconnect reason=%u proto=%u sme=%u bssid=%pM' \
    "$KERNEL_STRINGS_TMP"
grep -F 'AR6002 connect: connect_result SUCCESS bssid=%pM' "$KERNEL_STRINGS_TMP"
grep -F 'AR6002 connect: NWM pre-connect keepalive=0 submitted' \
    "$KERNEL_STRINGS_TMP"
# ctrl_flags is swept now, so there is no flags=0 submission to pin; the VARIANT
# line carries the flags actually sent.
grep -F 'flags=0x%04x nettype=%u dot11auth=%u ssidlen=%u' "$KERNEL_STRINGS_TMP"
grep -F 'N3DS_AR6014_NWM_LIVE_PROTECTED_TUPLE' \
    "$ATH6_CFG80211_SRC"
# Host-managed auth alongside the AES tuple; see the NWM_HOST_WPA block above
# for why the literal argument pair is gone and this is what replaced it.
grep -F 'cv->real_auth ? (AUTH_MODE)ar->arAuthMode' "$ATH6_CFG80211_SRC"
grep -F 'nwm_pairwise_crypto = (CRYPTO_TYPE)4;' "$ATH6_CFG80211_SRC"
grep -F 'nwm_group_crypto = (CRYPTO_TYPE)4;' "$ATH6_CFG80211_SRC"
grep -F 'wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0)' \
    "$ATH6_CFG80211_SRC"
if grep -Fq 'AR6002 connect: bounded reconnect' "$KERNEL_STRINGS_TMP" ||
   grep -Fq 'AR6002 connect: direct reconnect' "$KERNEL_STRINGS_TMP"; then
    echo 'FATAL: target-wedging association reconnect fallback returned' >&2
    exit 1
fi
LOADER_START="$NATIVE_ROOT/third_party/firm_linux_loader/arm11/source/start.S"
LOADER_SMP="$NATIVE_ROOT/third_party/firm_linux_loader/arm11/source/smp.c"
MACHINE_SRC="$NATIVE_ROOT/third_party/linux/arch/arm/mach-ctr/main_ctr.c"
KTR_DTS="$NATIVE_ROOT/third_party/linux/arch/arm/boot/dts/nintendo3ds_ktr.dts"
CTR_DTS="$NATIVE_ROOT/third_party/linux/arch/arm/boot/dts/nintendo3ds_ctr.dts"
KERNEL_CONFIG="$NATIVE_ROOT/third_party/linux/.config"
grep -F 'N3DS_CPU1_SGI_EOI' "$LOADER_START"
grep -F 'N3DS_FULL_CLOCK_RESTORED' "$LOADER_SMP"
grep -F 'N3DS_KTR_PERFORMANCE_PROOF' "$MACHINE_SRC"
grep -F '.l2c_aux_mask' "$MACHINE_SRC"
SDMMC_SRC="$NATIVE_ROOT/third_party/arm9linuxfw/source/hw/sdmmc.c"
SDMMC_HEADER="$NATIVE_ROOT/third_party/arm9linuxfw/include/hw/sdmmc.h"
SDCARD_FW_SRC="$NATIVE_ROOT/third_party/arm9linuxfw/source/vdev/sdcard.c"
VQUEUE_FW_SRC="$NATIVE_ROOT/third_party/arm9linuxfw/source/virt/queue.c"
VMANAGER_FW_SRC="$NATIVE_ROOT/third_party/arm9linuxfw/source/virt/manager.c"
VMANAGER_FW_HEADER="$NATIVE_ROOT/third_party/arm9linuxfw/include/virt/manager.h"
ANDROID_INIT_RC="$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/init.rc"
DEPLOYED_ANDROID_INIT_RC="$ANDROID_ROOT/etc/init.rc"
WIFI_LED_SCRIPT="$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/wifi_led_state.sh"
DEPLOYED_WIFI_LED_SCRIPT="$ANDROID_ROOT/etc/wifi_led_state.sh"
WPA_SUPPLICANT_CONFIG="$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/etc/wifi/wpa_supplicant.conf"
DEPLOYED_WPA_SUPPLICANT_CONFIG="$ANDROID_ROOT/system/etc/wifi/wpa_supplicant.conf"
WPA_SUPPLICANT_DIAG="$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/wpa_supplicant_diag.sh"
DEPLOYED_WPA_SUPPLICANT_DIAG="$ANDROID_ROOT/etc/wpa_supplicant_diag.sh"
WPA_SUPPLICANT_BIN="$ANDROID_ROOT/usr/sbin/wpa_supplicant"
ZYGOTE_INIT="$NATIVE_ROOT/third_party/frameworks/base/core/java/com/android/internal/os/ZygoteInit.java"
ANDROID_UDHCPC="$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/android_udhcpc.sh"
FIRST_INIT_RC="$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/init.rc"
PREFS_SERVICE_SRC="$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/android_prefs_init.sh"
PREFS_SERVICE_DEPLOYED="$ANDROID_ROOT/etc/android_prefs_init.sh"
PREFS_TEMPLATES="$ANDROID_ROOT/templates"
if [ ! -f "$PREFS_TEMPLATES/wifi.conf.example" ] || \
   [ ! -f "$PREFS_TEMPLATES/user-preferences.conf.example" ]; then
    WINDOWS_ANDROID_ROOT="${ANDROID3DS_WIN}/sdcard/linux/android"
    WINDOWS_PREFS_TEMPLATES="$WINDOWS_ANDROID_ROOT/templates"
    if [ -f "$WINDOWS_PREFS_TEMPLATES/wifi.conf.example" ] && \
       [ -f "$WINDOWS_PREFS_TEMPLATES/user-preferences.conf.example" ]; then
        PREFS_TEMPLATES="$WINDOWS_PREFS_TEMPLATES"
        echo "=== source authority: using Windows release templates ==="
    else
        echo "FATAL: preference templates missing from canonical and Windows staging" >&2
        exit 1
    fi
fi
PXI_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pxi.c"
PXI_HEADER="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pxi.h"
grep -F 'N3DS_SDMMC_BOUNDED_COMMAND' "$SDMMC_SRC"
grep -F 'N3DS_LUMA_SD_STABILITY' "$SDMMC_SRC"
grep -F 'N3DS_SD_ADAPTIVE_SLOW_CLOCK' "$SDMMC_SRC"
grep -F 'handleSD.clk = 0x202;' "$SDMMC_SRC"
grep -F 'N3DS_LUMA_SD_CLOCK_SEQUENCE' "$SDMMC_HEADER"
grep -F '0x00FF8000 | temp' "$SDMMC_SRC"
grep -F 'N3DS_SDMMC_RECOVERY_RETRY' "$SDMMC_SRC"
grep -F 'timer_ms_to_ticks(SDMMC_COMMAND_TIMEOUT_MS)' "$SDMMC_SRC"
grep -F 'if(!timeout || SD_Init() != 0) ret |= 2;' "$SDMMC_SRC"
grep -F 'N3DS_VIRTIO_BLK_TRUTHFUL_STATUS' "$SDCARD_FW_SRC"
grep -F 'VIRTIO_BLK_S_IOERR' "$SDCARD_FW_SRC"
grep -F 'N3DS_VIRTIO_BLK_WIRE_ABI' "$SDCARD_FW_SRC"
grep -A4 -F 'N3DS_VIRTIO_BLK_WIRE_ABI' "$SDCARD_FW_SRC" \
    | grep -F 'u32 type;'
grep -F 'N3DS_VIRTQUEUE_16BIT_WRAP' "$VQUEUE_FW_SRC"
grep -F 'N3DS_PXI_INTERRUPTIBLE_DEVICE_WORK' "$VMANAGER_FW_SRC"
grep -F 'N3DS_VIRQ_SHORT_CRITICAL_NOTIFY' "$VMANAGER_FW_HEADER"
grep -F 'N3DS_VQUEUE_SHORT_CRITICAL_SECTIONS' "$VQUEUE_FW_SRC"
grep -F 'N3DS_SD_ONE_REQUEST_PER_PASS' "$SDCARD_FW_SRC"
grep -F 'N3DS_SD_ADAPTIVE_RECOVERY' "$SDCARD_FW_SRC"
grep -F 'N3DS_SD_DIAG_CONFIG' "$SDCARD_FW_SRC"
grep -F 'vman_notify_host(vdev, VIRQ_CONFIG);' "$SDCARD_FW_SRC"
grep -F 'N3DS_SD_RECOVERY_TELEMETRY' "$PXI_SRC"
grep -F 'N3DS_SD_RECOVERY seq=%u sector=%u' "$PXI_SRC"
grep -F 'n3ds_sd_diag_seq' "$PXI_HEADER"
python3 "$PROJECT_ROOT/scripts/test_arm9_sd_adaptive_recovery.py"
grep -F 'N3DS_BOOT_IO_QUIET' "$ANDROID_INIT_RC"
cmp -s "$ANDROID_INIT_RC" "$DEPLOYED_ANDROID_INIT_RC" || {
    echo 'FATAL: deployed Android init.rc differs from the verified overlay' >&2
    exit 1
}
echo '=== Update-safe per-user Android preferences ==='
test -x "$PREFS_SERVICE_SRC"
test -x "$PREFS_SERVICE_DEPLOYED"
cmp -s "$PREFS_SERVICE_SRC" "$PREFS_SERVICE_DEPLOYED" || {
    echo 'FATAL: deployed preference initializer differs from verified source' >&2
    exit 1
}
for marker in \
    'N3DS_UPDATE_SAFE_PREFS' \
    'PAYLOAD=/mnt/sd/linux/android' \
    'ROOT="$PAYLOAD/persistent"' \
    'USERS="$ROOT/users"' \
    'PERSIST_WIFI=' \
    'PERSIST_MOBILE=' \
    'N3DS_WIFI_FILE_BOOT_POLICY' \
    'write_runtime_wifi' \
    'sync_runtime_wifi' \
    'SECURE="$ROOT/secure"' \
    'atomic_copy' \
    'mv -f' \
    'sync' \
    'network='; do
    grep -F -- "$marker" "$PREFS_SERVICE_SRC"
done
grep -F 'N3DS_UPDATE_SAFE_PREFS' "$DEPLOYED_ANDROID_INIT_RC"
grep -F 'mount none /mnt/sd/linux/android /sdcard bind' "$DEPLOYED_ANDROID_INIT_RC"
grep -F 'exec /etc/android_prefs_init.sh' "$DEPLOYED_ANDROID_INIT_RC"
grep -F 'service prefs_sync /etc/android_prefs_init.sh --watch' "$DEPLOYED_ANDROID_INIT_RC"
grep -F 'start prefs_sync' "$DEPLOYED_ANDROID_INIT_RC"
if grep -Fq 'android_prefs_sync' "$DEPLOYED_ANDROID_INIT_RC"; then
    echo 'FATAL: legacy init-invalid preference service name returned' >&2
    exit 1
fi
PREFS_FALLBACK_LINE="$(grep -n -F 'copy /system/etc/wifi/wpa_supplicant.conf /data/misc/wifi/wpa_supplicant.conf' "$DEPLOYED_ANDROID_INIT_RC" | cut -d: -f1)"
# The Wi-Fi ordering check must use the first boot-time import only.
PREFS_IMPORT_LINE="$(grep -n -F '    exec /etc/android_prefs_init.sh' "$DEPLOYED_ANDROID_INIT_RC" | head -n 1 | cut -d: -f1)"
PREFS_CHOWN_LINE="$(grep -n -F 'chown wifi wifi /data/misc/wifi/wpa_supplicant.conf' "$DEPLOYED_ANDROID_INIT_RC" | cut -d: -f1)"
test "$PREFS_FALLBACK_LINE" -lt "$PREFS_IMPORT_LINE"
test "$PREFS_IMPORT_LINE" -lt "$PREFS_CHOWN_LINE"
grep -F 'N3DS_UPDATE_SAFE_PREFS_BOOT_COMPLETED' "$DEPLOYED_ANDROID_INIT_RC"
test -f "$PREFS_TEMPLATES/wifi.conf.example"
test -f "$PREFS_TEMPLATES/user-preferences.conf.example"
echo '=== Android settings survive a reboot (N3DS_SETTINGS_PERSIST) ==='
for marker in \
    'N3DS_SETTINGS_PERSIST' \
    'restore_settings' \
    'settings_pass' \
    'restore_guard' \
    'com.android.providers.telephony' \
    'persist.service.adb.enable) continue'; do
    grep -F -- "$marker" "$PREFS_SERVICE_SRC"
done
grep -F 'android_prefs_init.sh --flush' "$ANDROID_ROOT/etc/ctr_poweroff.sh"
strings "$ANDROID_ROOT/system/bin/installd" | grep -F 'N3DS_APPDATA_RESTORE'
strings "$ANDROID_ROOT/system/bin/installd" | grep -F '/mnt/sd/linux/android/persistent/appdata'
bash "$PROJECT_ROOT/scripts/test_settings_persist.sh" "$PREFS_SERVICE_DEPLOYED"
echo '=== Remembered-network automatic ranking ==='
WPA_RANK_PATCH="$NATIVE_ROOT/third_party/buildroot/package/wpa_supplicant/0003-n3ds-remembered-network-ranking.patch"
grep -F 'N3DS_REMEMBERED_NETWORK_RANKING' "$WPA_RANK_PATCH"
grep -F '#ifdef CONFIG_WEP' "$WPA_RANK_PATCH"
grep -F 'n3ds_select_remembered_bss' "$WPA_RANK_PATCH"
strings "$ANDROID_ROOT/usr/sbin/wpa_supplicant" \
    | grep -F 'N3DS: selected %s remembered BSS'
echo '=== Remembered-network active discovery ==='
WPA_DISCOVERY_PATCH="$NATIVE_ROOT/third_party/buildroot/package/wpa_supplicant/0004-n3ds-remembered-first-discovery.patch"
grep -F 'N3DS_REMEMBERED_FIRST_DISCOVERY' "$WPA_DISCOVERY_PATCH"
grep -F 'n3ds_add_remembered_scan_ssids' "$WPA_DISCOVERY_PATCH"
strings "$ANDROID_ROOT/usr/sbin/wpa_supplicant" \
    | grep -F 'N3DS: remembered-first directed scan:'
echo '=== State-driven Wi-Fi yellow LED ==='
grep -F 'N3DS_WIFI_LED_STATE' "$WIFI_SERVICE_SRC"
grep -F 'N3DS_WIFI_LED_SCAN_REASSERT' "$WIFI_SERVICE_SRC"
grep -aF 'N3DS_WIFI_LED_STATE' "$SERVICES_DEX_TMP"
grep -aF 'N3DS_WIFI_LED_SCAN_REASSERT enabled' "$SERVICES_DEX_TMP"
grep -F 'SystemProperties.set("sys.wifi.led", state);' "$WIFI_SERVICE_SRC"
grep -F 'setprop sys.wifi.led off' "$ANDROID_INIT_RC"
grep -F 'on property:sys.wifi.led=on' "$ANDROID_INIT_RC"
grep -F 'on property:sys.wifi.led=off' "$ANDROID_INIT_RC"
grep -F 'on property:sys.powerctl=*' "$ANDROID_INIT_RC"
grep -F 'on property:sys.shutdown.requested=*' "$ANDROID_INIT_RC"
if grep -Fq 'start blink_wifi' "$ANDROID_INIT_RC" || grep -Fq 'service blink_wifi ' "$ANDROID_INIT_RC"; then
    echo 'FATAL: scan/activity-driven blink_wifi service survived in source init.rc' >&2
    exit 1
fi
test -s "$WIFI_LED_SCRIPT"
test -x "$WIFI_LED_SCRIPT"
grep -F 'N3DS_WIFI_LED_REGMAP_STATE' "$WIFI_LED_SCRIPT"
grep -F 'LED=/sys/class/leds/n3ds-wifi/brightness' "$WIFI_LED_SCRIPT"
grep -F 'on) VALUE=1' "$WIFI_LED_SCRIPT"
grep -F 'off) VALUE=0' "$WIFI_LED_SCRIPT"
if grep -Eq '(^|/)(i2cset)([[:space:]]|$)' "$WIFI_LED_SCRIPT"; then
    echo 'FATAL: raw i2cset still bypasses the kernel MCU regmap' >&2
    exit 1
fi
WIFI_LED_KERNEL_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/mcu/wifi_led.c"
grep -F 'N3DS_WIFI_LED_REGMAP_STATE' "$WIFI_LED_KERNEL_SRC"
grep -F 'regmap_write(led->map, led->reg, brightness ? 1 : 0)' "$WIFI_LED_KERNEL_SRC"
grep -F 'mcu/wifi_led.o' "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/Makefile"
grep -F 'compatible = "nintendo,3dsmcu-wifi-led";' \
    "$NATIVE_ROOT/third_party/linux/arch/arm/boot/dts/nintendo3ds.dtsi"
grep -F 'n3ds_wifi_led_probe' "$CARD_ROOT/System.map"
grep -F 'n3ds-wifi' "$KERNEL_STRINGS_TMP"
cmp -s "$WIFI_LED_SCRIPT" "$DEPLOYED_WIFI_LED_SCRIPT" || {
    echo 'FATAL: deployed Wi-Fi LED state setter differs from verified overlay' >&2
    exit 1
}
if grep -Fq 'start blink_wifi' "$DEPLOYED_ANDROID_INIT_RC" || grep -Fq 'service blink_wifi ' "$DEPLOYED_ANDROID_INIT_RC"; then
    echo 'FATAL: scan/activity-driven blink_wifi service survived in deployed init.rc' >&2
    exit 1
fi
grep -Fx 'ctrl_interface=DIR=/data/system/wpa_supplicant GROUP=1010' \
    "$WPA_SUPPLICANT_CONFIG"
cmp -s "$WPA_SUPPLICANT_CONFIG" "$DEPLOYED_WPA_SUPPLICANT_CONFIG" || {
    echo 'FATAL: deployed wpa_supplicant.conf differs from the verified overlay' >&2
    exit 1
}
grep -F 'LIVE_MAX_BYTES=196608' "$WPA_SUPPLICANT_DIAG"
grep -F 'identity=$(id 2>&1)' "$WPA_SUPPLICANT_DIAG"
grep -F 'LIVE=/tmp/wpa_supplicant.live.$$' "$WPA_SUPPLICANT_DIAG"
grep -F 'SNAPSHOT_SECONDS=30' "$WPA_SUPPLICANT_DIAG"
grep -F 'awk -v out_path="$LIVE"' "$WPA_SUPPLICANT_DIAG"
grep -F 'tail -c "$LIVE_KEEP_BYTES" "$LIVE"' "$WPA_SUPPLICANT_DIAG"
if grep -Fq 'awk -v out_path="$LOG"' "$WPA_SUPPLICANT_DIAG"; then
    echo 'FATAL: supplicant debug output still writes every line directly to FAT' >&2
    exit 1
fi
if grep -Fq 'awk -v log=' "$WPA_SUPPLICANT_DIAG"; then
    echo 'FATAL: supplicant logger reuses awk builtin name log' >&2
    exit 1
fi
grep -F '/usr/sbin/wpa_supplicant -Dnl80211' "$WPA_SUPPLICANT_DIAG"
cmp -s "$WPA_SUPPLICANT_DIAG" "$DEPLOYED_WPA_SUPPLICANT_DIAG" || {
    echo 'FATAL: deployed supplicant diagnostic differs from the verified overlay' >&2
    exit 1
}
grep -F 'mkdir /data/system/wpa_supplicant 0770 wifi wifi' "$ANDROID_INIT_RC"
grep -F 'chown wifi wifi /data/misc/wifi/wpa_supplicant.conf' "$ANDROID_INIT_RC"
grep -F 'copy /system/etc/wifi/wpa_supplicant.conf /data/misc/wifi/wpa_supplicant.conf' "$ANDROID_INIT_RC"
grep -F 'service wpa_supplicant /etc/wpa_supplicant_diag.sh' "$ANDROID_INIT_RC"
grep -F 'service dhcpcd /sbin/udhcpc -f -i wlan0 -s /etc/android_udhcpc.sh' "$ANDROID_INIT_RC"
grep -F 'group root wifi inet' "$ANDROID_INIT_RC"
grep -F 'mkdir /tmp 1777 root root' "$FIRST_INIT_RC"
grep -F -- '--setgroups=1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,3001,3002,3003' "$ZYGOTE_INIT"
grep -F 'dhcp.$interface.result' "$ANDROID_UDHCPC"
# N3DS_TWO_RESOLVERS: this device has two independent resolvers and the DHCP
# lease has to reach both. bionic (everything Java, and the Android native
# libraries) reads net.dns1..4 and nothing else; telco_https is statically
# linked against musl, which reads /etc/resolv.conf and nothing else. Neither
# one is written by the SD image -- sync_android_to_sdcard.sh deliberately
# excludes resolv.conf -- so android_resolvconf.sh writing both at lease time
# is the only thing standing between the Phone app and "Could not resolve
# host: 3dstelco.divergen.io".
ANDROID_RESOLVCONF="$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/android_resolvconf.sh"
test -x "$ANDROID_RESOLVCONF"
test -x "$ANDROID_ROOT/etc/android_resolvconf.sh"
cmp -s "$ANDROID_RESOLVCONF" "$ANDROID_ROOT/etc/android_resolvconf.sh" || {
    echo 'FATAL: deployed android_resolvconf.sh differs from the verified overlay' >&2
    exit 1
}
grep -F 'nameserver' "$ANDROID_RESOLVCONF" >/dev/null
grep -F '/etc/resolv.conf' "$ANDROID_RESOLVCONF" >/dev/null
grep -F 'net.dns' "$ANDROID_RESOLVCONF" >/dev/null
grep -F '/etc/android_resolvconf.sh' "$ANDROID_UDHCPC" >/dev/null
sh -n "$ANDROID_RESOLVCONF"
# telco_https must be able to say which of the two failed; the message it
# prints is what the Phone app shows the user verbatim.
strings "$ANDROID_ROOT/system/bin/telco_https" | grep -F 'resolver: ' >/dev/null
test -x "$WPA_SUPPLICANT_BIN"
strings "$WPA_SUPPLICANT_BIN" | grep -x 'nl80211'
strings "$WPA_SUPPLICANT_BIN" | grep -F 'CTRL-EVENT-SCAN-RESULTS'
grep -F 'on property:sys.boot_completed=1' "$ANDROID_INIT_RC"
for service in bootlog lockupwatch; do
    awk -v wanted="$service" '
        { sub(/\r$/, "", $1) }
        $1 == "service" { in_service = ($2 == wanted) }
        in_service && $1 == "disabled" { found = 1 }
        END { exit found ? 0 : 1 }
    ' "$ANDROID_INIT_RC" || {
        echo "FATAL: boot-time FAT writer $service is not disabled" >&2
        exit 1
    }
done
for service in logcat bootprogress; do
    awk -v wanted="$service" '
        { sub(/\r$/, "", $1) }
        $1 == "service" { in_service = ($2 == wanted) }
        in_service && $1 == "disabled" { found = 1 }
        END { exit found ? 1 : 0 }
    ' "$ANDROID_INIT_RC" || {
        echo "FATAL: requested early logger $service is disabled" >&2
        exit 1
    }
done
grep -F 'N3DS_REQUESTED_EARLY_LOGS' "$ANDROID_INIT_RC"
grep -F 'N3DS_SD_NO_ATIME' "$FIRST_INIT_RC"
grep -F 'N3DS_PXI_REQUIRES_DMA_API' "$PXI_SRC"
grep -F 'VIRTIO_F_ACCESS_PLATFORM' "$PXI_SRC"
strings "$NATIVE_ROOT/third_party/linux/vmlinux" \
    | grep -F 'ARM9 transport using DMA API for PL310 coherency'
strings "$NATIVE_ROOT/third_party/linux/vmlinux" \
    | grep -F 'N3DS_SD_RECOVERY seq=%u sector=%u'
grep -qx 'CONFIG_SMP=y' "$KERNEL_CONFIG"
grep -qx 'CONFIG_NR_CPUS=4' "$KERNEL_CONFIG"
grep -qx 'CONFIG_CACHE_L2X0=y' "$KERNEL_CONFIG"
if grep -Eq 'bootargs[[:space:]]*=.*maxcpus=' "$KTR_DTS"; then
    echo 'FATAL: KTR device tree limits the four ARM11 application CPUs' >&2
    exit 1
fi
if grep -Eq 'bootargs[[:space:]]*=.*maxcpus=' "$CTR_DTS"; then
    echo 'FATAL: CTR device tree still limits its two ARM11 application CPUs' >&2
    exit 1
fi
grep -F 'N3DS_CTR_DUAL_CORE' "$CTR_DTS"
test "$(grep -Ec '^[[:space:]]*cpu@[0-9]+[[:space:]]*[{]' "$CTR_DTS")" -eq 2
if grep -Eq '^[[:space:]]*cpu@(2|3)[[:space:]]*[{]' "$CTR_DTS"; then
    echo 'FATAL: CTR falsely exposes the separate ARM946 as a Linux SMP CPU' >&2
    exit 1
fi
grep -F 'status = "okay";' "$KTR_DTS"
grep -q 'ctr_secondary_startup' "$CARD_ROOT/System.map"
grep -q 'l2x0_of_init' "$CARD_ROOT/System.map"
"$NATIVE_ROOT/third_party/linux/scripts/dtc/dtc" -I dtb -O dts \
    "$CARD_ROOT/nintendo3ds_ktr.dtb" > "$KTR_DTB_TMP"
grep -F 'l2-cache-controller@17e10000' "$KTR_DTB_TMP"
grep -F 'status = "okay";' "$KTR_DTB_TMP"
if grep -Eq 'bootargs[[:space:]]*=.*maxcpus=' "$KTR_DTB_TMP"; then
    echo 'FATAL: deployed KTR DTB limits the four ARM11 application CPUs' >&2
    exit 1
fi
"$NATIVE_ROOT/third_party/linux/scripts/dtc/dtc" -I dtb -O dts \
    "$CARD_ROOT/nintendo3ds_ctr.dtb" > "$CTR_DTB_TMP"
test "$(grep -Ec '^[[:space:]]*cpu@[0-9]+[[:space:]]*[{]' "$CTR_DTB_TMP")" -eq 2
if grep -Eq 'bootargs[[:space:]]*=.*maxcpus=' "$CTR_DTB_TMP"; then
    echo 'FATAL: deployed CTR DTB still limits dual-core SMP' >&2
    exit 1
fi

echo '=== Hardware-proven single bottom-screen scanout ==='
GRALLOC_FB="$NATIVE_ROOT/third_party/libhardware/modules/gralloc/framebuffer.cpp"
grep -F 'N3DS_SINGLE_SCANOUT_RECOVERY' "$GRALLOC_FB"
if grep -Eq 'CTR_LCD_IO_FLIP|double-buffered bottom screen|n3ds_panel2' "$GRALLOC_FB"; then
    echo 'FATAL: failed PDC1 A/B flip path survived in gralloc' >&2
    exit 1
fi

echo '=== PICA200 protected kernel boundary ==='
PICA_SRC="$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
python3 "$PROJECT_ROOT/scripts/test_pica200_completion_contract.py"
grep -F 'N3DS_PICA_IRQ_DMA_OWNERSHIP' "$PICA_SRC"
grep -F 'N3DS_PICA_COMMAND_VALIDATION' "$PICA_SRC"
grep -F 'N3DS_PICA_RELOCATION_REQUIRED' "$PICA_SRC"
grep -F 'N3DS_PICA_IMMUTABLE_COMMAND_SNAPSHOT' "$PICA_SRC"
grep -F 'N3DS_PICA_PPF_VALIDATED_TRANSFER' "$PICA_SRC"
grep -F 'N3DS_PICA_TIMEOUT_RESET_RECOVERY' "$PICA_SRC"
grep -F 'N3DS_PICA_PROBE_SELFTEST' "$PICA_SRC"
grep -q 'ctr_pica_probe' "$CARD_ROOT/System.map"
grep -F 'nintendo,3ds-pica200' "$KTR_DTB_TMP"
grep -F 'nintendo,3ds-pica200' "$CTR_DTB_TMP"
test -x "$ANDROID_ROOT/system/bin/pica200_smoketest"
strings "$ANDROID_ROOT/system/bin/pica200_smoketest" | grep -F 'PICA200_PROBE PASS'
strings "$ANDROID_ROOT/system/bin/pica200_smoketest" | grep -F 'PICA200_PPF PASS'
grep -F 'N3DS_PICA_BOOT_PROBE' \
    "$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/dump_bootlog.sh"

echo '=== Finite bootanimation termination ==='
BOOTANIM_SRC="$NATIVE_ROOT/third_party/frameworks/base/cmds/bootanimation/BootAnimation.cpp"
grep -F 'N3DS_BOOTANIM_EXIT_ALL_LOOPS' "$BOOTANIM_SRC"
grep -F 'N3DS_BOOTANIM_EXIT_CONFIRMED' "$BOOTANIM_SRC"
strings "$ANDROID_ROOT/system/bin/bootanimation" \
    | grep -F 'movie: exit request unwound every playback loop'
if grep -Eq 'display_bottom2:|nintendo,3ds-lcd' \
    "$NATIVE_ROOT/third_party/linux/arch/arm/boot/dts/nintendo3ds.dtsi"; then
    echo 'FATAL: experimental PDC1 flip devices survived in the DT' >&2
    exit 1
fi
grep -F 'N3DS_GLOBAL_NAVIGATION_KEYS' \
    "$NATIVE_ROOT/third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/PhoneWindowManager.java"
grep -F 'N3DS_SHADE_SWIPE_CLOSE' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/status/StatusBarService.java"
grep -F 'N3DS_SELECT_DIRECT_GLOBAL_ACTIONS' \
    "$NATIVE_ROOT/third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/PhoneWindowManager.java"
grep -F 'N3DS_POWER_MENU_WITHOUT_AUDIO_SERVICE' \
    "$NATIVE_ROOT/third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/GlobalActions.java"
GLOBAL_ACTIONS_SRC="$NATIVE_ROOT/third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/GlobalActions.java"
grep -F 'N3DS_POWER_OFF_LOG_FINALIZER' "$GLOBAL_ACTIONS_SRC"
grep -F 'SystemProperties.set("sys.n3ds.poweroff", "1");' "$GLOBAL_ACTIONS_SRC"
# N3DS_POWER_OFF_FIRST / N3DS_POWER_OFF_A_CONFIRMS (#323): "the 3DS refused
# to soft turn off" -- Eclair's first A press leaves touch mode and clicks
# item 0, which was Silent mode, and the confirm dialog's buttons are not
# focusable in touch mode.  Power off is item 0 now and A confirms it.
grep -F 'N3DS_POWER_OFF_FIRST' "$GLOBAL_ACTIONS_SRC"
grep -F 'N3DS_POWER_OFF_A_CONFIRMS' "$GLOBAL_ACTIONS_SRC"
unzip -p "$ANDROID_ROOT/system/framework/services.jar" classes.dex \
    | strings | grep -F 'N3DS finalized poweroff requested (A)' > /dev/null
if grep -Fq 'Power.shutdown();' "$GLOBAL_ACTIONS_SRC"; then
    echo 'FATAL: SELECT still has a direct unfinalized Power.shutdown() path' >&2
    exit 1
fi
grep -F 'N3DS_320X240_NONOVERLAP_GRID' \
    "$NATIVE_ROOT/third_party/launcher2/res/layout-land/workspace_screen.xml"
grep -F 'N3DS_320X240_WORKSPACE_MIGRATION' \
    "$NATIVE_ROOT/third_party/launcher2/src/com/android/launcher2/LauncherProvider.java"
grep -F 'N3DS_TOUCH_LATEST_SAMPLE_DELIVERY' "$TOUCH_SRC"
# N3DS_TOUCH_REALTIME_60HZ (#321): until the kernel clock was fixed
# (N3DS_TWD_PERIPHCLK) "8 ms" sent MOVEs at 375 Hz into a dispatcher that
# handed out 35/s and dropped none -- the multi-second finger trail.  MOVEs
# now go out at 60 Hz, WindowManagerService dispatches at 60 Hz, and a MOVE
# still queued is replaced by the next one.
grep -F '#define REPORT_INTERVAL_MS 16' "$TOUCH_SRC"
grep -F 'N3DS_TOUCH_REALTIME_60HZ' "$TOUCH_SRC"
grep -F 'N3DS_TOUCH_QUIET_INPUT' "$TOUCH_SRC"
if grep -Eq 'pr_info\("(DOWN raw|UP logical)' "$TOUCH_SRC"; then
    echo 'FATAL: per-tap touch pr_info is back on the fbcon console (N3DS_TOUCH_QUIET_INPUT)' >&2
    exit 1
fi
grep -F 'N3DS_TOUCH_MOVE_COALESCE' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/KeyInputQueue.java"
grep -F 'N3DS_TOUCH_DISPATCH_60HZ' \
    "$NATIVE_ROOT/third_party/frameworks/base/services/java/com/android/server/WindowManagerService.java"
grep -aF 'mCoalescedMoves' "$SERVICES_DEX_TMP" > /dev/null
grep -aF 'N3DS_DEFAULT_MAX_TOUCH_EVENTS_PER_SEC' "$SERVICES_DEX_TMP" > /dev/null
grep -aF 'debug.n3ds.touch_trace' "$SERVICES_DEX_TMP" > /dev/null
# N3DS_TWD_PERIPHCLK (#321): the TWD counts PERIPHCLK = core/2, which the
# loader's upclock() makes 3x the DTS refclk on a New 3DS.
grep -F 'N3DS_TWD_PERIPHCLK' "$NATIVE_ROOT/third_party/linux/arch/arm/kernel/smp_twd.c"
grep -F 'twd_timer_rate = twd_n3ds_scale(clk_get_rate(twd_clk));' \
    "$NATIVE_ROOT/third_party/linux/arch/arm/kernel/smp_twd.c"
grep -F '(N3DS_TWD_PERIPHCLK)' "$KERNEL_STRINGS_TMP" > /dev/null
grep -F 'N3DS_CACHE_FRIENDLY_ROTATE_V2' "$GRALLOC_FB"
grep -F 'N3DS_DIRTY_ROW_SCANOUT' "$GRALLOC_FB"
if grep -Fq 'N3DS_PICA_GRALLOC_DMA_POOL' "$GRALLOC_FB"; then
    echo 'FATAL: unqualified PICA DMA is still the boot gralloc allocator' >&2
    exit 1
fi
grep -F 'ashmem_create_region("n3ds-fb", poolSize)' "$GRALLOC_FB"
# N3DS_FB1_PAGE_OFFSET (#323): fb1's scanout (smem_start 0x18119400) is not
# page aligned; mmap() offset 0 is 1024 bytes before it.  That one
# misalignment was the "~100-row panel offset", the "3-cycled channels" and
# the red fringe a #322 tester saw on every letter.  Both writers of fb1 now
# point at smem_start, and the compensating tunables must not come back.
GRALLOC_PRIV="$NATIVE_ROOT/third_party/libhardware/modules/gralloc/gralloc_priv.h"
DISPLAY_TARGET="$NATIVE_ROOT/third_party/frameworks/base/cmds/bootanimation/DisplayTarget.cpp"
grep -F 'N3DS_FB1_PAGE_OFFSET' "$GRALLOC_FB"
grep -F 'N3DS_FB1_PAGE_OFFSET' "$DISPLAY_TARGET"
grep -F 'sourceRow[fbx] = span - 1 - fbx;' "$GRALLOC_FB"
grep -F 'const int fbx = span - 1 - y;' "$DISPLAY_TARGET"
if grep -Eq 'n3ds_y_offset|n3ds_chan|read_tunable' "$GRALLOC_FB" "$GRALLOC_PRIV" ||
   grep -Eq 'mPanelYOffset|getenv\("BOOTANIM_PANEL_YOFF"\)' "$DISPLAY_TARGET" ||
   grep -Eq '^[^#]*(panel_yoff|BOOTANIM_PANEL_YOFF)' "$ANDROID_ROOT/etc/bootanim.sh"; then
    echo 'FATAL: a panel y-offset/channel compensation is back (N3DS_FB1_PAGE_OFFSET)' >&2
    exit 1
fi
strings "$ANDROID_ROOT/system/bin/app_process" | grep -F 'N3DS_FB1_PAGE_OFFSET' > /dev/null
strings "$ANDROID_ROOT/system/bin/surfaceflinger" | grep -F 'N3DS_FB1_PAGE_OFFSET' > /dev/null
strings "$ANDROID_ROOT/system/bin/bootanimation" | grep -F 'N3DS_FB1_PAGE_OFFSET' > /dev/null
# N3DS_KEYBOARD_NO_TOUCH_POINTS (#323): KeyboardView shipped with DEBUG on,
# drawing the touch-point dots and lines over every LatinIME key.
grep -F 'N3DS_KEYBOARD_NO_TOUCH_POINTS' \
    "$NATIVE_ROOT/third_party/frameworks/base/core/java/android/inputmethodservice/KeyboardView.java"
grep -F 'private static final boolean DEBUG = false;' \
    "$NATIVE_ROOT/third_party/frameworks/base/core/java/android/inputmethodservice/KeyboardView.java"
# N3DS_HEARTBEAT_OPT_IN (#323): the 2 s heartbeat no longer scrolls the top
# screen unless sd:/linux/debug_heartbeat exists.
grep -F 'N3DS_HEARTBEAT_OPT_IN' "$ANDROID_ROOT/etc/heartbeat.sh"
grep -F 'N3DS_PICA_SOFTWARE_FALLBACK_GATE' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
grep -F 'N3DS_PICA_STAGED_QUALIFICATION' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
grep -F 'N3DS_PICA_QUALIFICATION_WATCHDOG' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
grep -F 'N3DS_PICA_LAZY_IRQ_ENABLE' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
grep -F 'N3DS_PICA_P3D_IRQ_ACK' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
grep -F 'N3DS_PICA_COMPLETION_IDLE_POLL' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
grep -F 'N3DS_PICA_SINGLE_DEFERRED_QUALIFY' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
grep -F 'work_on_cpu(0, pica_watchdog_arm_cpu0' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_pica.c"
grep -F 'PICA200_SAFE read-only status' \
    "$PICA_SMOKETEST_SOURCE"
grep -F 'N3DS_GLES11_JNI_REGISTRATION' \
    "$NATIVE_ROOT/third_party/frameworks/base/core/jni/AndroidRuntime.cpp"
python3 "$PROJECT_ROOT/scripts/test_n3ds_copybit.py"
bash "$PROJECT_ROOT/scripts/test_n3ds_copybit_qemu.sh"
grep -F 'N3DS_BUILTIN_COPYBIT' \
    "$NATIVE_ROOT/third_party/libhardware/modules/gralloc/hw_get_module_static.cpp"
strings "$ANDROID_ROOT/system/bin/app_process" \
    | grep -F 'N3DS_COPYBIT_READY backend=cpu'
strings "$ANDROID_ROOT/system/bin/surfaceflinger" \
    | grep -F 'N3DS_COPYBIT_READY backend=cpu'
strings "$ANDROID_ROOT/system/bin/app_process" \
    | grep -F 'N3DS_COPYBIT_QUARANTINED default=software'
strings "$ANDROID_ROOT/system/bin/surfaceflinger" \
    | grep -F 'N3DS_COPYBIT_QUARANTINED default=software'
if grep -R -F -q 'debug.n3ds.copybit' \
        "$ANDROID_ROOT/etc/init.rc" "$ANDROID_ROOT/system/build.prop"; then
    echo 'FATAL: deployable enables experimental copybit instead of boot-safe fallback' >&2
    exit 1
fi
strings "$ANDROID_ROOT/system/bin/app_process" \
    | grep -F 'com/google/android/gles_jni/EGLImpl'
grep -F 'N3DS_QUIET_BUILTIN_HAL_LOOKUP' \
    "$NATIVE_ROOT/third_party/libhardware/modules/gralloc/hw_get_module_static.cpp"
test -s "$ANDROID_ROOT/system/usr/keychars/qwerty.kcm.bin"
# #324: one map per key device, so no KeyCharacterMap fallback warnings.
# #325: mcu_buttons (HOME) was the one left out.
for dev in n3ds_navigation hid_buttons mcu_buttons; do
    cmp "$ANDROID_ROOT/system/usr/keychars/qwerty.kcm.bin" "$ANDROID_ROOT/system/usr/keychars/$dev.kcm.bin"
done
strings "$ANDROID_ROOT/system/bin/app_process" | grep -F 'android/view/KeyCharacterMap'
if strings "$SERVICES_DEX_TMP" | grep -q 'android/media/AudioService'; then
    echo 'FATAL: SystemServer can still initialize unavailable AudioSystem JNI' >&2
    exit 1
fi
if strings "$SERVICES_DEX_TMP" \
    | grep -Eq 'android[/\.]bluetooth|setBluetoothScanMode|bluetooth[.]a2dp[.]action'; then
    echo 'FATAL: services.jar still contains a concrete Bluetooth runtime integration' >&2
    exit 1
fi

echo '=== Dalvik transient rootfs I/O containment ==='
echo '=== ARMv6 SMP atomic synchronization ==='
python3 "$PROJECT_ROOT/scripts/test_armv6_smp_atomics.py"
bash "$PROJECT_ROOT/scripts/test_armv6_smp_atomics_qemu.sh"
grep -F 'N3DS_ARMV6_SMP_ATOMICS' \
    "$NATIVE_ROOT/third_party/system_core/libcutils/atomic-android-armv6.S"
grep -qx 'CONFIG_KUSER_HELPERS=y' "$KERNEL_CONFIG"
if strings "$ANDROID_ROOT/system/bin/app_process" | \
    grep -F 'this file is not safe with SMP systems'; then
    echo 'FATAL: app_process retains the UP-only ARMv6 atomic implementation' >&2
    exit 1
fi
DEXOPT_SRC="$NATIVE_ROOT/third_party/dalvik/vm/analysis/DexOptimize.c"
DALVIK_INIT_SRC="$NATIVE_ROOT/third_party/dalvik/vm/Init.c"
grep -F 'N3DS_TRANSIENT_ODEX_IO_RETRY' "$DEXOPT_SRC"
grep -F 'N3DS_TRANSIENT_DEXOPT_EXEC_RETRY' "$DEXOPT_SRC"
grep -F 'N3DS_DALVIK_ABORT_CALLER' "$DALVIK_INIT_SRC"
grep -F '#ifndef N3DS_QEMU_HOST_TEST' \
    "$NATIVE_ROOT/third_party/frameworks/base/cmds/app_process/app_main.cpp"
grep -F 'HOST_TEST_DEFINE=-DN3DS_QEMU_HOST_TEST' \
    "$PROJECT_ROOT/scripts/build_app_process_debug.sh"
grep -F 'N3DS_DALVIK_ABORT|surfaceflinger' \
    "$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/boot_progress.sh"
grep -F 'N3DS_SD_FAILURE_CAPTURE' \
    "$NATIVE_ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/boot_progress.sh"
strings "$ANDROID_ROOT/system/bin/app_process" \
    | grep -F 'N3DS_DALVIK_ABORT pid=%d caller=%p'

echo '=== PixelFlinger register-pressure retry safety ==='
grep -F 'N3DS_PIXELFLINGER_OOR_SENTINEL' \
    "$NATIVE_ROOT/third_party/system_core/libpixelflinger/codeflinger/GGLAssembler.h"
grep -F 'N3DS_PIXELFLINGER_OOR_RECYCLE' \
    "$NATIVE_ROOT/third_party/system_core/libpixelflinger/codeflinger/GGLAssembler.cpp"
grep -F 'N3DS_SD_SECTOR_READ_FALLBACK' \
    "$NATIVE_ROOT/third_party/arm9linuxfw/source/vdev/sdcard.c"

echo '=== SurfaceFlinger generated-code execution ==='
test -x "$ANDROID_ROOT/system/bin/surfaceflinger"
strings "$ANDROID_ROOT/system/bin/surfaceflinger" \
    | grep -F 'mprotect(PROT_EXEC) failed for generated code'
grep -F 'N3DS_CACHE_FRIENDLY_ROTATE_V2' \
    "$NATIVE_ROOT/third_party/libhardware/modules/gralloc/framebuffer.cpp"
grep -F '(uint8_t)((r5 << 3) | (r5 >> 2))' \
    "$NATIVE_ROOT/third_party/libhardware/modules/gralloc/framebuffer.cpp"
grep -F '(uint8_t)((g6 << 2) | (g6 >> 4))' \
    "$NATIVE_ROOT/third_party/libhardware/modules/gralloc/framebuffer.cpp"

echo '=== Scalar float/double JNI ABI coverage ==='
python3 "$PROJECT_ROOT/scripts/test_pica_app_render_contract.py"
# N3DS_WEBKIT_FLOAT_JNI (#322): WebKit, LatinIME and services/jni are linked
# into app_process too.  #321's blank Browser page was WebViewCore's
# SetSize(..., float scale, ...) reading s0 and shifting every later argument.
ABI_AUDIT="$(cd "$PROJECT_ROOT/scripts" && python3 apply_float_jni_abi.py \
    "$NATIVE_ROOT/third_party/frameworks/base/core/jni" \
    "$NATIVE_ROOT/third_party/frameworks/base/media/jni" \
    "$NATIVE_ROOT/third_party/frameworks/base/services/jni" \
    "$NATIVE_ROOT/third_party/webkit/WebKit/android" \
    "$NATIVE_ROOT/third_party/latinime/dictionary/jni" \
    "$NATIVE_ROOT/third_party/dalvik/libcore/luni/src/main/native" \
    "$NATIVE_ROOT/third_party/dalvik/libcore/icu/src/main/native")"
echo "$ABI_AUDIT"
test "$ABI_AUDIT" = 'identified 0 functions in 0 files'
grep -F 'static __attribute__((pcs("aapcs"))) void SetSize(' \
    "$NATIVE_ROOT/third_party/webkit/WebKit/android/jni/WebViewCore.cpp"
# N3DS_FLOAT_JNI_BINARY_GATE: the source audit above reported 0 for #314
# while every GLImpl float binding shipped without pcs("aapcs"), because its
# regex skipped "(void *) fn" registrations.  Check the machine code too.
# A binding built with the base-AAPCS boundary must move its float arguments
# from core registers/stack into VFP registers (vmov sN, rM / vldr sN) before
# calling libagl; the broken build tail-calls libagl with s0.. untouched.
# The unstripped link output names the functions; the staged stripped
# app_process must hold the same instruction bytes at the same addresses.
FLOAT_JNI_TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf
APP_PROCESS_UNSTRIPPED="$NATIVE_ROOT/build/app_process/app_process"
test -s "$APP_PROCESS_UNSTRIPPED"
FLOAT_JNI_SYMS="$("$FLOAT_JNI_TC-nm" -S "$APP_PROCESS_UNSTRIPPED")"
for fn in android_glTexParameterf__IIF android_glFrustumf__FFFFFF \
          android_glTranslatef__FFF android_glClearColor__FFFF \
          android_glRotatef__FFFF; do
    # The bindings are file-static C++, so nm shows _ZL<len><name>P7_JNIEnv...
    # No early awk exit: under pipefail a SIGPIPE'd printf would abort.
    sym="$(printf '%s\n' "$FLOAT_JNI_SYMS" | awk -v f="$fn" \
        'BEGIN {m = "_ZL" length(f) f "P"} ($4 == f || index($4, m) == 1) && !seen {print $1 " " $2; seen = 1}')"
    test -n "$sym" || {
        echo "FATAL: $fn missing from $APP_PROCESS_UNSTRIPPED" >&2
        exit 1
    }
    fn_start=$((16#${sym%% *}))
    fn_stop=$((fn_start + 16#${sym##* }))
    fn_asm="$("$FLOAT_JNI_TC-objdump" -d --start-address="$fn_start" \
        --stop-address="$fn_stop" "$APP_PROCESS_UNSTRIPPED")"
    printf '%s\n' "$fn_asm" | grep -E 'vldr[[:space:]]+s[0-9]+|vmov[[:space:]]+s[0-9]+, r[0-9]+' >/dev/null || {
        echo "FATAL: $fn in app_process reads its float arguments from unloaded VFP registers (libandroid_runtime lacks pcs(aapcs); rebuild libandroid_runtime + app_process)" >&2
        exit 1
    }
    fn_bytes="$(printf '%s\n' "$fn_asm" | awk '/^ *[0-9a-f]+:/ {print $1, $2}')"
    staged_bytes="$("$FLOAT_JNI_TC-objdump" -d --start-address="$fn_start" \
        --stop-address="$fn_stop" "$ANDROID_ROOT/system/bin/app_process" \
        | awk '/^ *[0-9a-f]+:/ {print $1, $2}')"
    test -n "$fn_bytes" && test "$fn_bytes" = "$staged_bytes" || {
        echo "FATAL: staged app_process does not match $APP_PROCESS_UNSTRIPPED at $fn" >&2
        exit 1
    }
    echo "float JNI ABI ok: $fn"
done
# N3DS_LIBAGL_HARDFLOAT_GATE: libagl's gglFloatToFixed/gglFloatToFixedFast
# (opengl/libagl/fixed_asm.S) were written for the soft-float ABI and read
# their float argument from r0, but fp.h declares them extern "C" taking a
# float and every hard-float caller passes it in s0 (matrix.o: "vmov s0, r3;
# bl gglFloatToFixed").  1.0f became 0x7fffffff, so every float transform,
# light and clear colour was garbage and anything drawn through libagl's
# vertex pipeline read back black (Global Time #314: nonBlack=0/256 even on
# the geometry fallback).  The source must keep the s0 entry move and both
# the unstripped link output and the staged app_process must start each
# routine with vmov r0, s0 (ee100a10).  Assembly symbols carry no nm size.
grep -F 'N3DS_LIBAGL_HARDFLOAT_FLOAT_TO_FIXED' \
    "$NATIVE_ROOT/third_party/frameworks/base/opengl/libagl/fixed_asm.S"
grep -F 'N3DS_FLOAT_ARG_TO_R0    vmov    r0, s0' \
    "$NATIVE_ROOT/third_party/frameworks/base/opengl/libagl/fixed_asm.S"
for fn in gglFloatToFixed gglFloatToFixedFast; do
    sym="$(printf '%s\n' "$FLOAT_JNI_SYMS" | awk -v f="$fn" \
        '$NF == f && !seen {print $1; seen = 1}')"
    test -n "$sym" || {
        echo "FATAL: $fn missing from $APP_PROCESS_UNSTRIPPED" >&2
        exit 1
    }
    fn_start=$((16#$sym))
    for bin in "$APP_PROCESS_UNSTRIPPED" "$ANDROID_ROOT/system/bin/app_process"; do
        first_word="$("$FLOAT_JNI_TC-objdump" -d --start-address="$fn_start" \
            --stop-address="$((fn_start + 4))" "$bin" \
            | awk '/^ *[0-9a-f]+:/ {print $2}')"
        test "$first_word" = 'ee100a10' || {
            echo "FATAL: $fn in $bin does not start with vmov r0, s0 (got '$first_word'); libagl.a predates N3DS_LIBAGL_HARDFLOAT_FLOAT_TO_FIXED (rebuild libagl, then app_process)" >&2
            exit 1
        }
    done
    echo "libagl hard-float entry ok: $fn"
done

echo '=== Final SD artifact hashes ==='
test -s "$CARD_ROOT/arm9linuxfw.bin"
cmp -s "$CARD_ROOT/arm9linuxfw.bin" \
    "$NATIVE_ROOT/third_party/arm9linuxfw/arm9linuxfw.bin"
sha256sum \
    "$CARD_ROOT/arm9linuxfw.bin" \
    "$CARD_ROOT/zImage" \
    "$CARD_ROOT/System.map" \
    "$CARD_ROOT/nintendo3ds_ctr.dtb" \
    "$CARD_ROOT/nintendo3ds_ktr.dtb" \
    "$CARD_ROOT/initramfs.cpio.gz" \
    "$ANDROID_ROOT/system/lib/modules/ath6kl.ko" \
    "$ANDROID_ROOT/system/bin/app_process" \
    "$ANDROID_ROOT/system/bin/surfaceflinger" \
    "$ANDROID_ROOT/system/framework/core.jar" \
    "$ANDROID_ROOT/system/framework/framework.jar" \
    "$ANDROID_ROOT/system/framework/services.jar" \
    "$ANDROID_ROOT/system/bin/installd" \
    "$ANDROID_ROOT/system/app/Launcher2.apk" \
    "$ANDROID_ROOT/system/app/Launcher2.odex" \
    "$ANDROID_ROOT/system/app/Browser.apk" \
    "$ANDROID_ROOT/system/app/Browser.odex" \
    "$ANDROID_ROOT/system/app/Settings.apk" \
    "$ANDROID_ROOT/system/app/Settings.odex" \
    "$ANDROID_ROOT/system/app/SettingsProvider.apk" \
    "$ANDROID_ROOT/system/app/SettingsProvider.odex" \
    "$ANDROID_ROOT/system/app/TouchDiagnostic.apk" \
    "$ANDROID_ROOT/system/app/TouchDiagnostic.odex" \
    "$ANDROID_ROOT/system/app/GlobalTime.apk" \
    "$ANDROID_ROOT/system/app/GlobalTime.odex" \
    "$ANDROID_ROOT/system/app/GPU-Z.apk" \
    "$ANDROID_ROOT/system/app/GPU-Z.odex" \
    "$ANDROID_ROOT/system/app/LatinIME.apk" \
    "$ANDROID_ROOT/system/app/LatinIME.odex" \
    "$ANDROID_ROOT/system/app/N3dsDialer.apk" \
    "$ANDROID_ROOT/system/app/N3dsDialer.odex" \
    "$ANDROID_ROOT/system/app/Camera.apk" \
    "$ANDROID_ROOT/system/app/Camera.odex" \
    "$ANDROID_ROOT/system/app/MicTest.apk" \
    "$ANDROID_ROOT/system/app/MicTest.odex"

# The AR6014 in Nintendo 3DS is 2.4-GHz-only.  Verify the canonical source
# cannot silently return to generic 5-GHz advertising or unrestricted WMI
# scans, and that direct firmware BSS records retain fail-closed security.
grep -F 'N3DS_AR6014_2GHZ_SCAN_CHANNELS' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_AR6014_2GHZ_ONLY_WIPHY' "$ATH6_CFG80211_SRC"
grep -F 'bands[NL80211_BAND_5GHZ] = NULL' "$ATH6_CFG80211_SRC"
grep -F 'num_channels, channel_list' "$ATH6_CFG80211_SRC"
grep -F 'N3DS_WMI_DIRECT_BSS_SECURITY_INTEGRITY' "$ATH6_WMI_SRC"
grep -F 'protected_ie && !(capability & IEEE80211_CAPINFO_PRIVACY)' "$ATH6_WMI_SRC"

# N3DS_GATE_325: build #325 -- no root shell on tty0, Wi-Fi monitor that
# blocks instead of spinning and restarts a dead supplicant, network time,
# and the 3DSTelco jitter buffer / ongoing call notification / dialer way
# back to the call.  Each marker is a string literal in the shipped code,
# not a comment, so it survives into the dex or the binary.
echo '=== #325 markers ==='
if grep -q '^service console ' "$ANDROID_ROOT/etc/init.rc"; then
    echo 'FATAL: init.rc still runs a root shell on tty0 (N3DS_NO_TTY0_SHELL)' >&2
    exit 1
fi
grep -F 'N3DS_NO_TTY0_SHELL' "$ANDROID_ROOT/etc/init.rc" > /dev/null
strings "$ANDROID_ROOT/system/bin/app_process" | grep -F 'N3DS_WIFI_MONITOR_POLL' > /dev/null
unzip -p "$ANDROID_ROOT/system/framework/framework.jar" classes.dex | strings \
    | grep -F 'N3DS_WIFI_SUPPLICANT_RESTART' > /dev/null
unzip -p "$ANDROID_ROOT/system/framework/services.jar" classes.dex | strings \
    | grep -F 'N3DS_NETWORK_TIME' > /dev/null
GATE325_TMP="$(mktemp)"
unzip -p "$ANDROID_ROOT/system/app/Phone.apk" classes.dex | strings > "$GATE325_TMP"
for marker in N3DS_TELCO_JITTER_BUFFER N3DS_TELCO_DOWNLINK_STATS N3DS_TELCO_CALL_WATCHDOG \
        N3DS_TELCO_STALE_EVENT N3DS_TELCO_BUSY N3DS_TELCO_RINGTONE N3DS_TELCO_RETURN_TO_CALL; do
    if ! grep -F "$marker" "$GATE325_TMP" > /dev/null; then
        echo "FATAL: Phone.apk is missing $marker" >&2
        rm -f "$GATE325_TMP"
        exit 1
    fi
done
if grep -F 'BTN_SPEAKER' "$GATE325_TMP" > /dev/null; then
    echo 'FATAL: Phone.apk still has the LOUD/QUIET speaker button' >&2
    rm -f "$GATE325_TMP"
    exit 1
fi
rm -f "$GATE325_TMP"
unzip -p "$ANDROID_ROOT/system/app/N3dsDialer.apk" classes.dex | strings \
    | grep -F 'N3DS_DIALER_RETURN_TO_CALL' > /dev/null
test -s "$ANDROID_ROOT/system/usr/keychars/mcu_buttons.kcm.bin"

# N3DS_GATE_326: build #326 -- louder downlink with echo suppression, contacts
# managed from the dialer and shown by name on calls, a visible Browser tab
# button, START as MENU, and a quiet top screen (no WebKit notImplemented()
# lines, no per-call mic dump).
echo '=== #326 markers ==='
GATE326_TMP="$(mktemp)"
gate326_dex() {
    # gate326_dex APK MARKER... -- every marker must be a string in the dex.
    local apk="$1"; shift
    unzip -p "$ANDROID_ROOT/system/app/$apk" classes.dex | strings > "$GATE326_TMP"
    local marker
    for marker in "$@"; do
        if ! grep -F "$marker" "$GATE326_TMP" > /dev/null; then
            echo "FATAL: $apk is missing $marker" >&2
            rm -f "$GATE326_TMP"
            exit 1
        fi
    done
}
gate326_dex Phone.apk N3DS_TELCO_LOUDER_DOWNLINK N3DS_TELCO_ECHO_SUPPRESS \
    N3DS_TELCO_CONTACT_NAMES N3DS_TELCO_DOWNLINK_STATS n3ds.telco.echo_duck
gate326_dex N3dsDialer.apk N3DS_CONTACTS_UPDATED N3DS_CONTACTS_DELETED \
    N3DS_CONTACTS_ADDED 'Hold to edit or delete' 'Save as contact'
gate326_dex Browser.apk N3DS_BROWSER_TABS_BUTTON
gate326_dex Launcher2.apk N3DS_LAUNCHER_NO_SEARCH_SERVICE
rm -f "$GATE326_TMP"
grep -Eq '^key[[:space:]]+139[[:space:]]+MENU([[:space:]]|$)' \
    "$ANDROID_ROOT/system/usr/keylayout/n3ds_navigation.kl"
grep -F 'N3DS_START_IS_MENU' "$NAV_SRC" > /dev/null
grep -F 'case BTN_START:' "$NAV_SRC" > /dev/null
grep -F 'input_set_capability(nav_input, EV_KEY, KEY_MENU);' "$NAV_SRC" > /dev/null
grep -F 'N3DS_MIC_QUIET' \
    "$NATIVE_ROOT/third_party/linux/drivers/platform/nintendo3ds/ctr_csnd.c" > /dev/null
grep -F 'N3DS_WEBKIT_QUIET_NOTIMPL' \
    "$NATIVE_ROOT/third_party/webkit/WebCore/platform/NotImplemented.h" > /dev/null
# The __PRETTY_FUNCTION__ literal only exists while notImplemented() prints
# it, so this also proves WebKit was rebuilt clean and app_process relinked.
if strings "$ANDROID_ROOT/system/bin/app_process" \
        | grep -F 'WebCore::Widget::setCursor(const WebCore::Cursor&)' > /dev/null; then
    echo 'FATAL: app_process still prints notImplemented() lines (N3DS_WEBKIT_QUIET_NOTIMPL)' >&2
    exit 1
fi

# N3DS_GATE_327: build #327 "Alpha 1" -- shipped zoneinfo (America/Chicago
# "did not exist"), the SNTP half-offset fix, stale/backlog calls logged as
# missed instead of rung, every call and voicemail saved on the 3DS, voicemail
# downloaded once, a 0.5 s SELECT hold with a pre-built power dialog, the
# firmware-version easter egg, and the framework debug flags back to false.
echo '=== #327 markers ==='
for f in zoneinfo.dat zoneinfo.idx zoneinfo.version; do
    test -s "$ANDROID_ROOT/system/usr/share/zoneinfo/$f"
done
grep -aF 'America/Chicago' "$ANDROID_ROOT/system/usr/share/zoneinfo/zoneinfo.idx" > /dev/null
grep -Fx 'ro.build.display.id=Android3DS Alpha 1 (a1)' "$ANDROID_ROOT/system/build.prop"
grep -Fx 'ro.build.version.incremental=a1' "$ANDROID_ROOT/system/build.prop"
grep -Fx 'ro.build.version.release=2.0' "$ANDROID_ROOT/system/build.prop"
GATE327_TMP="$(mktemp)"
gate327_strings() {
    # gate327_strings ZIP MARKER... -- every marker must be a string in its dex.
    local zip="$1"; shift
    unzip -p "$ANDROID_ROOT/$zip" classes.dex | strings > "$GATE327_TMP"
    local marker
    for marker in "$@"; do
        if ! grep -F -- "$marker" "$GATE327_TMP" > /dev/null; then
            echo "FATAL: $zip is missing $marker" >&2
            rm -f "$GATE327_TMP"
            exit 1
        fi
    done
}
gate327_strings system/framework/framework.jar N3DS_SNTP_HALF_OFFSET
# Debug-only log text: present only while ViewRoot's DEBUG_DRAW was forced on.
if grep -F 'Invalidate child: ' "$GATE327_TMP" > /dev/null; then
    echo 'FATAL: framework.jar still has forced-on ViewRoot debug logging' >&2
    rm -f "$GATE327_TMP"
    exit 1
fi
gate327_strings system/framework/services.jar N3DS_NETWORK_TIME_CROSSCHECK \
    N3DS_TZ_GMT_IS_UNSET N3DS_GLOBAL_ACTIONS_PREWARM
gate327_strings system/app/Phone.apk N3DS_TELCO_STALE_RING N3DS_TELCO_CALL_LOG \
    N3DS_TELCO_VOICEMAIL_SAVED N3DS_TELCO_UNSEEN_CALL voicemail_cursor \
    io.divergen.telco.action.CALL_LOG io.divergen.telco.action.MISSED_SEEN
gate327_strings system/app/N3dsDialer.apk N3DS_MISSED_CALL_SEEN log_key n3ds_tab \
    io.divergen.telco.action.MISSED_SEEN
# N3DS_GATE_328: the easter egg is the bugdroid (#328), drawn in code.
gate327_strings system/app/Settings.apk PlatLogoActivity N3DS_BUGDROID
# Nothing of 2.3's easter egg (its toast) ships, nor #327's boot-logo screen.
if grep -F -e 'REZZZ' -e 'N3DS_ECLAIR_LOGO' "$GATE327_TMP" > /dev/null; then
    echo 'FATAL: Settings.apk still carries an old easter egg' >&2
    rm -f "$GATE327_TMP"
    exit 1
fi
# The Settings screens that used to crash: Battery use tolerates missing
# stats, Language hides the user dictionary without a provider, and app
# details survives a missing manage-space activity.
gate327_strings system/app/Settings.apk N3DS_BATTERY_USE user_dict_settings \
    'no manage-space activity for '
rm -f "$GATE327_TMP"
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/N3dsDialer.apk" AndroidManifest.xml \
    > "$MANIFEST_TMP"
grep -F 'io.divergen.telco.action.CALL_LOG' "$MANIFEST_TMP" > /dev/null
# The STATE broadcast goes out on every poll; a manifest receiver for it
# started the dialer process every 12 s.
if grep -F 'io.divergen.telco.action.STATE' "$MANIFEST_TMP" > /dev/null; then
    echo 'FATAL: N3dsDialer still wakes on every 3DSTelco STATE broadcast' >&2
    exit 1
fi
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/Settings.apk" AndroidManifest.xml \
    | grep -F 'PlatLogoActivity' > /dev/null
# The bugdroid is drawn in code; Gingerbread's platlogo artwork must not
# ship in Settings.apk.
if "$AAPT" list "$ANDROID_ROOT/system/app/Settings.apk" | grep -F 'platlogo' > /dev/null; then
    echo 'FATAL: Settings.apk still carries Gingerbread platlogo artwork' >&2
    exit 1
fi
# Every screen the shipped preference XML and code open must be declared:
# an undeclared one is an ActivityNotFoundException that kills Settings.
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/Settings.apk" AndroidManifest.xml \
    > "$MANIFEST_TMP"
for activity in deviceinfo.Status fuelgauge.PowerUsageSummary \
        fuelgauge.PowerUsageDetail wifi.AdvancedSettings LocalePicker ZoneList \
        deviceinfo.Memory DeviceInfoSettings PlatLogoActivity; do
    if ! grep -F -- "$activity" "$MANIFEST_TMP" > /dev/null; then
        echo "FATAL: Settings.apk does not declare $activity" >&2
        exit 1
    fi
done
# N3DS_GATE_328_COMPILED: a declared activity whose class was left out of
# javac is a ClassNotFoundException on open (the fuelgauge package was).
GATE328_DEX="$(mktemp)"
unzip -p "$ANDROID_ROOT/system/app/Settings.apk" classes.dex | strings > "$GATE328_DEX"
for activity in $(awk '
        /E: activity/ { in_activity = 1; next }
        /E: / { in_activity = 0 }
        in_activity && /A: android:name\(0x01010003\)="/ {
            sub(/.*A: android:name\(0x01010003\)="/, ""); sub(/".*/, ""); print }
        ' "$MANIFEST_TMP"); do
    case "$activity" in
        .*) class="com.android.settings$activity" ;;
        *.*) class="$activity" ;;
        *) class="com.android.settings.$activity" ;;
    esac
    descriptor="L$(printf '%s' "$class" | tr . /);"
    if ! grep -F -- "$descriptor" "$GATE328_DEX" > /dev/null; then
        echo "FATAL: Settings.apk declares $class but its dex has no such class" >&2
        rm -f "$GATE328_DEX"
        exit 1
    fi
done
rm -f "$GATE328_DEX"
"$AAPT" list "$ANDROID_ROOT/system/framework/framework-res.apk" \
    | grep -Fx 'res/xml/power_profile.xml' > /dev/null
# Status runs in Settings' own process; in com.android.phone a crash there
# would take the telco stack down with it.
if grep -F '"com.android.phone"' "$MANIFEST_TMP" > /dev/null; then
    echo 'FATAL: a Settings activity runs in the com.android.phone process' >&2
    exit 1
fi
# The SD card holds /system, /data and the kernel: no Unmount or Format.
"$AAPT" dump xmltree "$ANDROID_ROOT/system/app/Settings.apk" res/xml/device_info_memory.xml \
    > "$MANIFEST_TMP"
grep -F 'memory_sd_avail' "$MANIFEST_TMP" > /dev/null
if grep -F -e 'memory_sd_unmount' -e 'memory_sd_format' "$MANIFEST_TMP" > /dev/null; then
    echo 'FATAL: the SD card screen still offers Unmount or Format' >&2
    exit 1
fi
grep -F 'N3DS_SELECT_HOLD_FAST' "$NAV_SRC" > /dev/null
grep -F 'N3DS_GLOBAL_ACTIONS_PREWARM' \
    "$NATIVE_ROOT/third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/GlobalActions.java" > /dev/null

# N3DS_SCRUB_BUILD_PATHS (#328): nothing on the card may name the build
# machine. sync_android_to_sdcard.sh masks the ELF files; a hit anywhere else
# has to be fixed where that file is made. The initramfs Wi-Fi module is
# compared byte-for-byte with the card copy above, and verify_zimage_strings.py
# checks the kernel.
echo '=== #328 build-path scrub ==='
python3 "$PROJECT_ROOT/scripts/scrub_build_paths.py" --check "$CARD_ROOT"
grep -F 'N3DS_SCRUB_BUILD_PATHS' "$PROJECT_ROOT/scripts/sync_android_to_sdcard.sh" > /dev/null
grep -F 'N3DS_SCRUB_BUILD_PATHS' "$PROJECT_ROOT/scripts/build_minimal_initramfs.sh" > /dev/null

echo '=== verify_release_artifacts: ALL OK ==='
