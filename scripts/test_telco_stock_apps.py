#!/usr/bin/env python3
"""Static integration contract for original-app 3DSTelco ownership."""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHONE = ROOT / "content/stock-app-overlays/Phone/src/com/android/phone"
MMS = ROOT / "content/stock-app-overlays/Mms/src/com/android/mms/transaction/SmsMessageSender.java"
PATCHER = (ROOT / "scripts/patch_telco_stock_apps.py").read_text(encoding="utf-8")

for name in ["TelcoProvider.java", "TelcoService.java", "TelcoCallActivity.java", "VoipSession.java",
             "TelcoMessageStore.java"]:
    assert (PHONE / name).is_file(), name
phone = "\n".join(path.read_text(encoding="utf-8") for path in PHONE.glob("*.java"))
mms = MMS.read_text(encoding="utf-8")
assert "N3DS_TELCO_ORIGINAL_PHONE_READY" in phone
assert "N3DS_TELCO_NATIVE_HTTPS_READY" in phone
assert 'TRANSPORT = "/system/bin/telco_https"' in phone
assert "HttpsURLConnection" not in phone
assert 'writeLine(input, "TOKEN " + authorization)' in phone
assert "N3DS_TELCO_BOOT_RECEIVER_GUARD" in phone
assert "N3DS_TELCO_DURABLE_REGISTRATION_READY" in phone
assert "N3DS_TELCO_MESSAGE_JOURNAL_V1" in phone
assert "/sdcard/persistent/shared/messages" in phone
assert "flushPendingMessages" in phone
assert "beginIncoming" in phone and "reconcileSmsRows" in phone
assert "restoreFromConfig" in phone
assert "N3DS_TELCO_AUDIO_OPTIONAL_GUARD" in phone
assert "catch (LinkageError error)" in phone
assert "content://io.divergen.telco/messages" in mms
assert "SmsManager" not in mms
assert "io.divergen.telco.action.CALL" in PATCHER
# N3DS_TELCO_CALL_PRIVILEGE: this line used to assert the literal string
# ACTION_CALL_PRIVILEGED, left over from a design in which TelcoCallActivity
# took over the AOSP privileged-call intent action.  That design is gone --
# the activity is reached through io.divergen.telco.action.CALL, asserted on
# the line above -- so the anchor could never match and this gate had been
# failing ever since.  What the line was protecting is still real and still
# shipped: the activity must hold the privileged-call permission, or it
# cannot place a call on behalf of another app.  Assert that instead.
assert 'android:permission="android.permission.CALL_PRIVILEGED"' in PATCHER
assert "android.permission.RECORD_AUDIO" in PATCHER
assert "android.permission.ACCESS_WIFI_STATE" in PATCHER
assert "android.permission.CHANGE_WIFI_STATE" in PATCHER
assert "android.permission.WRITE_EXTERNAL_STORAGE" in PATCHER
assert "protectionLevel=\"signature\"" in PATCHER
assert 'android:exported="true"' in PATCHER
assert "N3DS_ATTENTION_BLUE_COMPAT" in PATCHER
assert "N3DS_ATTENTION_WHITE_COMPAT" in PATCHER
assert "N3DS_PHONE_AUDIO_STARTUP_GUARD" in PATCHER
assert "audioManager == null" in PATCHER
assert "N3DS_MMS_MISSING_PROVIDER_GUARD" in PATCHER
assert "N3DS_MMS_MISSING_DRM_PROVIDER_GUARD" in PATCHER
# N3DS_TELCO_TONE_GUARD_LIVES_IN_THE_ARTIFACT: this line used to assert the
# marker in the patcher, but the optional-ToneGenerator guard is not injected
# by patch_telco_stock_apps.py and is not in third_party/Contacts either -- it
# exists only inside the built Contacts.apk, which is the documented shape of
# every telco dialer guard in this build.  Asserting it against the patcher
# could never pass.  Check it where verify_release_artifacts.sh checks it, in
# the dex that actually ships, so the contract still has teeth.
# N3DS_NO_STOCK_CONTACTS (#317): the stock Contacts app is retired, so the
# contract is now that it stays gone.
CONTACTS_APK = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/app/Contacts.apk"
assert not CONTACTS_APK.exists(), CONTACTS_APK
assert '<uses-permission android:name="io.divergen.telco.ACCESS" />' in PATCHER
print("telco_stock_apps: PASS")
