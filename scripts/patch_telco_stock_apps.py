#!/usr/bin/env python3
"""Apply fail-closed 3DSTelco hooks to copied stock Eclair app trees."""

from __future__ import annotations

import argparse
from pathlib import Path


PHONE_PERMISSION_ANCHOR = """    <protected-broadcast android:name="android.intent.action.SERVICE_STATE" />
"""
PHONE_PERMISSION_NEW = """    <permission android:name="io.divergen.telco.ACCESS" android:protectionLevel="signature" />
    <uses-permission android:name="io.divergen.telco.ACCESS" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
    <uses-permission android:name="android.permission.CHANGE_WIFI_STATE" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" />

    <protected-broadcast android:name="android.intent.action.SERVICE_STATE" />
"""
PHONE_COMPONENT_ANCHOR = """    </application>
</manifest>
"""
PHONE_COMPONENT_NEW = """        <!-- Android3DS: original Phone package owns all 3DSTelco credentials/calls. -->
        <provider android:name=".TelcoProvider"
            android:authorities="io.divergen.telco"
            android:readPermission="io.divergen.telco.ACCESS"
            android:writePermission="io.divergen.telco.ACCESS" />
        <service android:name=".TelcoService"
            android:exported="true"
            android:permission="io.divergen.telco.ACCESS" />
        <receiver android:name=".TelcoBootReceiver">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
                <action android:name="io.divergen.telco.action.CONFIG_CHANGED" />
            </intent-filter>
        </receiver>
        <!-- N3DS_TELCO_RETURN_TO_CALL (#325): one call screen, in its own
             task, so the ongoing-call notification and the dialer bring the
             live call back instead of stacking a second screen. -->
        <activity android:name=".TelcoCallActivity"
            android:label="3DSTelco call"
            android:launchMode="singleTask"
            android:taskAffinity="io.divergen.telco.call"
            android:permission="android.permission.CALL_PRIVILEGED">
            <intent-filter>
                <action android:name="io.divergen.telco.action.CALL" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:scheme="tel" />
            </intent-filter>
        </activity>
        <!-- N3DS_DIALER_VOICEMAIL: reached only via TelcoCallActivity's
             client-side "100" interception, never through an intent-filter. -->
        <activity android:name=".VoicemailActivity"
            android:label="3DSTelco voicemail"
            android:permission="io.divergen.telco.ACCESS" />
    </application>
</manifest>
"""
MMS_PERMISSION_ANCHOR = """    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
"""
MMS_PERMISSION_NEW = """    <uses-permission android:name="io.divergen.telco.ACCESS" />
    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
"""
PHONE_BLUETOOTH_START_OLD = """            if (BluetoothAdapter.getDefaultAdapter() != null) {
                mBtHandsfree = new BluetoothHandsfree(this, phone);
                startService(new Intent(this, BluetoothHeadsetService.class));
            } else {
                // Device is not bluetooth capable
                mBtHandsfree = null;
            }
"""
PHONE_BLUETOOTH_START_NEW = """            // Android3DS has no Bluetooth telephony profile; 3DSTelco uses Wi-Fi audio.
            mBtHandsfree = null;
"""
PHONE_BLUETOOTH_MANIFEST_OLD = """        <!-- bluetooth headset service -->
        <service android:name="BluetoothHeadsetService">
            <intent-filter>
                <action android:name="android.bluetooth.IBluetoothHeadset" />
            </intent-filter>
        </service>

"""
PHONE_BLUETOOTH_MANIFEST_NEW = """        <!-- Android3DS: Bluetooth headset telephony removed; 3DSTelco audio uses Wi-Fi. -->

"""
PHONE_PROXIMITY_OLD = """                        int flags =
                            (screenOnImmediately ? 0 : PowerManager.WAIT_FOR_PROXIMITY_NEGATIVE);
                        mProximityWakeLock.release(flags);
"""
PHONE_PROXIMITY_NEW = """                        // This framework exposes only the no-argument Eclair wake-lock release.
                        mProximityWakeLock.release();
"""
PHONE_AUDIO_MODE_OLD = """            AudioManager audioManager =
                    (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
            // Enable stack dump only when actively debugging ("new Throwable()" is expensive!)
            if (DBG_SETAUDIOMODE_STACK) Log.d(LOG_TAG, "Stack:", new Throwable("stack dump"));
            audioManager.setMode(mode);
"""
PHONE_AUDIO_MODE_NEW = """            AudioManager audioManager =
                    (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
            // N3DS_PHONE_AUDIO_STARTUP_GUARD: the DSP-backed AudioService may not
            // be published yet while core applications are starting. Telephony
            // must remain alive and retry on its next state transition.
            if (audioManager == null) {
                Log.w(LOG_TAG, "AudioService unavailable; deferring mode "
                        + audioModeToString(mode));
                return;
            }
            // Enable stack dump only when actively debugging ("new Throwable()" is expensive!)
            if (DBG_SETAUDIOMODE_STACK) Log.d(LOG_TAG, "Stack:", new Throwable("stack dump"));
            try {
                audioManager.setMode(mode);
            } catch (NullPointerException e) {
                Log.w(LOG_TAG, "AudioService unavailable (NPE in setMode); deferring.");
            }
"""
RINGER_LIGHT_BLUE_OLD = "mHardwareService.setAttentionLight(true, 0x000000ff);"
RINGER_LIGHT_BLUE_NEW = "mHardwareService.setAttentionLight(true); // N3DS_ATTENTION_BLUE_COMPAT"
RINGER_LIGHT_WHITE_OLD = "mHardwareService.setAttentionLight(true, 0x00ffffff);"
RINGER_LIGHT_WHITE_NEW = "mHardwareService.setAttentionLight(true); // N3DS_ATTENTION_WHITE_COMPAT"
RINGER_LIGHT_OFF_OLD = "mHardwareService.setAttentionLight(false, 0x00000000);"
RINGER_LIGHT_OFF_NEW = "mHardwareService.setAttentionLight(false);"
CONTACTS_SOURCE_BOUNDS_OLD = """        Rect target = intent.getSourceBounds();
"""
CONTACTS_SOURCE_BOUNDS_NEW = """        // This Android3DS framework predates Intent.getSourceBounds(); use the
        // existing QuickContact.EXTRA_TARGET_RECT fallback below.
        Rect target = null;
"""
MMS_CONTACT_HEADER_CLEAR_OLD = """        mContactHeader.wipeClean();
        mContactHeader.invalidate();
"""
MMS_CONTACT_HEADER_CLEAR_NEW = """        // This Android3DS framework predates ContactHeaderWidget.wipeClean().
        // Clear the same user-visible state through the APIs this snapshot exposes.
        mContactHeader.setContactUri(null);
        mContactHeader.setDisplayName("", null);
        mContactHeader.setPhoto(null);
        mContactHeader.setPresence(0);
        mContactHeader.setSocialSnippet(null);
        mContactHeader.invalidate();
"""
MMS_DRAFT_QUERY_OLD = """        HashSet<Long> newDraftSet = new HashSet<Long>(oldDraftSet.size());
        
        Cursor cursor = SqliteWrapper.query(
                mContext,
                mContext.getContentResolver(),
                MmsSms.CONTENT_DRAFT_URI,
                DRAFT_PROJECTION, null, null, null);

        if (cursor == null) return;
        try {
"""
MMS_DRAFT_QUERY_NEW = """        HashSet<Long> newDraftSet = new HashSet<Long>(oldDraftSet.size());

        if (mContext.getPackageManager().resolveContentProvider("mms-sms", 0) == null) {
            Log.i(TAG, "N3DS_MMS_MISSING_PROVIDER_GUARD drafts provider unavailable");
            return;
        }

        Cursor cursor = SqliteWrapper.query(
                mContext,
                mContext.getContentResolver(),
                MmsSms.CONTENT_DRAFT_URI,
                DRAFT_PROJECTION, null, null, null);

        // N3DS_MMS_MISSING_PROVIDER_GUARD: the minimal image may start Mms
        // before (or without) TelephonyProvider.  An unavailable provider is
        // an empty cache, not a process-fatal null cursor.
        if (cursor == null) {
            Log.w("Mms", "N3DS_MMS_MISSING_PROVIDER_GUARD drafts");
            return;
        }
        try {
"""
MMS_RECIPIENT_QUERY_OLD = """        Context context = sInstance.mContext;
        Cursor c = SqliteWrapper.query(context, context.getContentResolver(),
                sAllCanonical, null, null, null, null);

        if (c == null) return;
        try {
"""
MMS_RECIPIENT_QUERY_NEW = """        Context context = sInstance.mContext;
        if (context.getPackageManager().resolveContentProvider("mms-sms", 0) == null) {
            Log.i(TAG, "N3DS_MMS_MISSING_PROVIDER_GUARD recipients provider unavailable");
            return;
        }
        Cursor c = SqliteWrapper.query(context, context.getContentResolver(),
                sAllCanonical, null, null, null, null);

        // N3DS_MMS_MISSING_PROVIDER_GUARD: retain an empty recipient cache
        // until the provider becomes available instead of crashing at boot.
        if (c == null) {
            Log.w("Mms", "N3DS_MMS_MISSING_PROVIDER_GUARD recipients");
            return;
        }
        try {
"""
MMS_OUTBOX_RECOVERY_OLD = """    private void moveOutboxMessagesToQueuedBox() {
        ContentValues values = new ContentValues(1);

        values.put(Sms.TYPE, Sms.MESSAGE_TYPE_QUEUED);

        SqliteWrapper.update(
                getApplicationContext(), getContentResolver(), Outbox.CONTENT_URI,
                values, "type = " + Sms.MESSAGE_TYPE_OUTBOX, null);
    }
"""
MMS_OUTBOX_RECOVERY_NEW = """    private void moveOutboxMessagesToQueuedBox() {
        if (getPackageManager().resolveContentProvider("sms", 0) == null) {
            Log.i(TAG, "N3DS_MMS_MISSING_SMS_PROVIDER_GUARD outbox provider unavailable");
            return;
        }

        ContentValues values = new ContentValues(1);

        values.put(Sms.TYPE, Sms.MESSAGE_TYPE_QUEUED);

        // N3DS_MMS_MISSING_SMS_PROVIDER_GUARD: the minimal image has no
        // TelephonyProvider.  SqliteWrapper only handles SQLite failures;
        // ContentResolver reports an absent authority as IllegalArgumentException.
        // There is no legacy SMS outbox to recover, so let boot continue and
        // keep the 3DSTelco transport available through its own provider.
        try {
            SqliteWrapper.update(
                    getApplicationContext(), getContentResolver(), Outbox.CONTENT_URI,
                    values, "type = " + Sms.MESSAGE_TYPE_OUTBOX, null);
        } catch (IllegalArgumentException e) {
            Log.w(TAG, "N3DS_MMS_MISSING_SMS_PROVIDER_GUARD outbox unavailable");
        }
    }
"""
MMS_QUEUED_SEND_OLD = """    public synchronized void sendFirstQueuedMessage() {
        boolean success = true;
        // get all the queued messages from the database
"""
MMS_QUEUED_SEND_NEW = """    public synchronized void sendFirstQueuedMessage() {
        if (getPackageManager().resolveContentProvider("sms", 0) == null) {
            Log.i(TAG, "N3DS_MMS_MISSING_SMS_PROVIDER_GUARD queued messages skipped");
            return;
        }
        boolean success = true;
        // get all the queued messages from the database
"""
MMS_NOTIFICATION_UPDATE_OLD = """    public static void updateNewMessageIndicator(Context context, boolean isNew) {
        SortedSet<MmsSmsNotificationInfo> accumulator =
"""
MMS_NOTIFICATION_UPDATE_NEW = """    public static void updateNewMessageIndicator(Context context, boolean isNew) {
        if (context.getPackageManager().resolveContentProvider("mms-sms", 0) == null) {
            android.util.Log.i(TAG,
                    "N3DS_MMS_MISSING_PROVIDER_GUARD notification provider unavailable");
            return;
        }
        SortedSet<MmsSmsNotificationInfo> accumulator =
"""
MMS_STATUS_UPDATE_OLD = """        Cursor cursor = SqliteWrapper.query(context, context.getContentResolver(),
                            messageUri, ID_PROJECTION, null, null, null);
        try {
"""
MMS_STATUS_UPDATE_NEW = """        if (context.getPackageManager().resolveContentProvider("sms", 0) == null) {
            Log.w(LOG_TAG, "N3DS_MMS_MISSING_SMS_PROVIDER_GUARD status update skipped");
            return;
        }
        Cursor cursor = SqliteWrapper.query(context, context.getContentResolver(),
                            messageUri, ID_PROJECTION, null, null, null);
        if (cursor == null) {
            Log.w(LOG_TAG, "N3DS_MMS_MISSING_SMS_PROVIDER_GUARD status cursor unavailable");
            return;
        }
        try {
"""
MMS_DRM_INIT_OLD = """        RateController.init(this);
        DrmUtils.cleanupStorage(this);
        LayoutManager.init(this);
"""
MMS_DRM_INIT_NEW = """        RateController.init(this);
        cleanupDrmStorage();
        LayoutManager.init(this);
"""
MMS_DRM_TERMINATE_OLD = """    @Override
    public void onTerminate() {
        DrmUtils.cleanupStorage(this);
    }
"""
MMS_DRM_TERMINATE_NEW = """    // N3DS_MMS_MISSING_DRM_PROVIDER_GUARD: DRM cleanup is optional on
    // this minimal image and must not make the entire Messages app fatal.
    private void cleanupDrmStorage() {
        if (getPackageManager().resolveContentProvider("mms", 0) == null) {
            android.util.Log.i(LOG_TAG,
                    "N3DS_MMS_MISSING_DRM_PROVIDER_GUARD provider unavailable");
            return;
        }
        try {
            DrmUtils.cleanupStorage(this);
        } catch (IllegalArgumentException e) {
            android.util.Log.w(LOG_TAG,
                    "N3DS_MMS_MISSING_DRM_PROVIDER_GUARD provider unavailable");
        }
    }

    @Override
    public void onTerminate() {
        cleanupDrmStorage();
    }
"""


def replace_exact(path: Path, old: str, new: str) -> bool:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return False
    if source.count(old) != 1:
        raise SystemExit(f"3DSTelco stock-app patch anchor mismatch: {path}")
    path.write_text(source.replace(old, new), encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phone", type=Path)
    parser.add_argument("mms", type=Path)
    # N3DS_NO_STOCK_CONTACTS (#317): Contacts is no longer built; the
    # argument stays optional for rebuilding an old tree.
    parser.add_argument("contacts", type=Path, nargs="?")
    args = parser.parse_args()
    changed = False
    changed |= replace_exact(args.phone / "AndroidManifest.xml", PHONE_PERMISSION_ANCHOR, PHONE_PERMISSION_NEW)
    changed |= replace_exact(args.phone / "AndroidManifest.xml", PHONE_COMPONENT_ANCHOR, PHONE_COMPONENT_NEW)
    changed |= replace_exact(
        args.phone / "AndroidManifest.xml", PHONE_BLUETOOTH_MANIFEST_OLD, PHONE_BLUETOOTH_MANIFEST_NEW
    )
    changed |= replace_exact(args.mms / "AndroidManifest.xml", MMS_PERMISSION_ANCHOR, MMS_PERMISSION_NEW)
    changed |= replace_exact(
        args.phone / "src/com/android/phone/PhoneApp.java", PHONE_BLUETOOTH_START_OLD, PHONE_BLUETOOTH_START_NEW
    )
    changed |= replace_exact(
        args.phone / "src/com/android/phone/PhoneApp.java", PHONE_PROXIMITY_OLD, PHONE_PROXIMITY_NEW
    )
    changed |= replace_exact(
        args.phone / "src/com/android/phone/PhoneUtils.java", PHONE_AUDIO_MODE_OLD, PHONE_AUDIO_MODE_NEW
    )
    changed |= replace_exact(
        args.phone / "src/com/android/phone/Ringer.java", RINGER_LIGHT_BLUE_OLD, RINGER_LIGHT_BLUE_NEW
    )
    changed |= replace_exact(
        args.phone / "src/com/android/phone/Ringer.java", RINGER_LIGHT_WHITE_OLD, RINGER_LIGHT_WHITE_NEW
    )
    changed |= replace_exact(
        args.phone / "src/com/android/phone/Ringer.java", RINGER_LIGHT_OFF_OLD, RINGER_LIGHT_OFF_NEW
    )
    if args.contacts is not None:
        changed |= replace_exact(
            args.contacts / "src/com/android/contacts/ui/QuickContactActivity.java",
            CONTACTS_SOURCE_BOUNDS_OLD,
            CONTACTS_SOURCE_BOUNDS_NEW,
        )
    changed |= replace_exact(
        args.mms / "src/com/android/mms/ui/ComposeMessageActivity.java",
        MMS_CONTACT_HEADER_CLEAR_OLD,
        MMS_CONTACT_HEADER_CLEAR_NEW,
    )
    changed |= replace_exact(
        args.mms / "src/com/android/mms/util/DraftCache.java",
        MMS_DRAFT_QUERY_OLD,
        MMS_DRAFT_QUERY_NEW,
    )
    changed |= replace_exact(
        args.mms / "src/com/android/mms/data/RecipientIdCache.java",
        MMS_RECIPIENT_QUERY_OLD,
        MMS_RECIPIENT_QUERY_NEW,
    )
    changed |= replace_exact(
        args.mms / "src/com/android/mms/transaction/SmsReceiverService.java",
        MMS_QUEUED_SEND_OLD,
        MMS_QUEUED_SEND_NEW,
    )
    changed |= replace_exact(
        args.mms / "src/com/android/mms/transaction/MessagingNotification.java",
        MMS_NOTIFICATION_UPDATE_OLD,
        MMS_NOTIFICATION_UPDATE_NEW,
    )
    changed |= replace_exact(
        args.mms / "src/com/android/mms/transaction/MessageStatusReceiver.java",
        MMS_STATUS_UPDATE_OLD,
        MMS_STATUS_UPDATE_NEW,
    )
    changed |= replace_exact(
        args.mms / "src/com/android/mms/transaction/SmsReceiverService.java",
        MMS_OUTBOX_RECOVERY_OLD,
        MMS_OUTBOX_RECOVERY_NEW,
    )
    changed |= replace_exact(
        args.mms / "src/com/android/mms/MmsApp.java", MMS_DRM_INIT_OLD, MMS_DRM_INIT_NEW
    )
    changed |= replace_exact(
        args.mms / "src/com/android/mms/MmsApp.java",
        MMS_DRM_TERMINATE_OLD,
        MMS_DRM_TERMINATE_NEW,
    )
    print("telco_stock_apps: " + ("patched" if changed else "already patched"))


if __name__ == "__main__":
    main()
