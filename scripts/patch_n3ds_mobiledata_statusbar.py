#!/usr/bin/env python3
"""Add the service-owned 3DS Telco indicators to legacy StatusBarPolicy.

The source tree is built from WSL, while this workspace carries a small
Windows mirror for review/tests.  The patch is deliberately idempotent and
supports both locations.  It never reads request properties as connected
state: the AP service must publish an active backend, a known state,
and a bounded positive client count.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
WSL_STATUSBAR = Path(
    f"{A3DS_ROOT}/third_party/frameworks/base/services/java/"
    "com/android/server/status/StatusBarPolicy.java"
)
MIRROR_STATUSBAR = PROJECT / (
    "third_party/frameworks/base/services/java/com/android/server/status/"
    "StatusBarPolicy.java"
)
STATUSBAR = WSL_STATUSBAR if WSL_STATUSBAR.is_file() else MIRROR_STATUSBAR
MARKER = "N3DS_MOBILE_DATA_STATUSBAR"
NULL_CONTENT_INTENT = """        notification.setLatestEventInfo(mContext, "3DS Telco",
                detail, null);
"""
SAFE_CONTENT_INTENT = """        // Eclair rejects notifications without a content intent.  Use an
        // explicit Settings destination so a stale AP error cannot abort
        // StatusBarPolicy construction and take the battery receiver with it.
        Intent settingsIntent = new Intent();
        settingsIntent.setClassName("com.android.settings",
                "com.android.settings.MobileDataSettings");
        settingsIntent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent contentIntent = PendingIntent.getActivity(
                mContext, 0, settingsIntent, 0);
        notification.setLatestEventInfo(mContext, "3DS Telco",
                detail, contentIntent);
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


MOBILE_DATA_FIELDS = """    // N3DS_MOBILE_DATA_STATUSBAR: service-owned 3DS Telco indicators.
    private static final int EVENT_MOBILE_DATA_POLL = 5;
    private static final long MOBILE_DATA_POLL_MS = 1000;

    // The AP service owns these properties.  StatusBarPolicy never treats a
    // request property as proof that the AP is running or has a client.
    private static final String MOBILE_DATA_BACKEND = "sys.mobiledata.backend";
    private static final String MOBILE_DATA_STATE = "sys.mobiledata.state";
    private static final String MOBILE_DATA_CLIENT_COUNT =
            "sys.mobiledata.client_count";
    private static final String MOBILE_DATA_RSSI = "sys.mobiledata.rssi";
    private static final int MOBILE_DATA_NOTIFICATION_ID = 0x3d73;
"""

MOBILE_DATA_MEMBERS = """    // 3DS Telco / Mobile Data is deliberately separate from the legacy
    // telephony data icon.  Phone callbacks may hide mDataIcon at any time;
    // they must not be able to erase service-owned AP state.
    private IBinder mMobileDataIcon;
    private IconData mMobileDataIconData;
    private boolean mMobileDataIconVisible;
    private IBinder mMobileDataSignalIcon;
    private IconData mMobileDataSignalIconData;
    private boolean mMobileDataSignalVisible;
    private boolean mMobileDataNotificationVisible;
    private NotificationManager mNotificationManager;
"""

LEGACY_MOBILE_DATA_CONSTRUCTOR = """        // 3DS Telco uses the normal Android mobile-data glyph plus a signal
        // glyph.  Both remain hidden until the AP service reports a valid
        // connected client; no telephony state is used as a substitute.
        mMobileDataIconData = IconData.makeIcon("n3ds_mobile_data",
                null, com.android.internal.R.drawable.stat_sys_data_connected_g, 0, 0);
        mMobileDataIcon = service.addIcon(mMobileDataIconData, null);
        service.setIconVisibility(mMobileDataIcon, false);
        mMobileDataSignalIconData = IconData.makeIcon("n3ds_mobile_data_signal",
                null, com.android.internal.R.drawable.stat_sys_signal_0, 0, 0);
        mMobileDataSignalIcon = service.addIcon(mMobileDataSignalIconData, null);
        service.setIconVisibility(mMobileDataSignalIcon, false);
        mNotificationManager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        updateMobileData();
        mHandler.sendEmptyMessageDelayed(EVENT_MOBILE_DATA_POLL, MOBILE_DATA_POLL_MS);
"""

MOBILE_DATA_CONSTRUCTOR = """        // StatusBarService validates icon slots against its fixed
        // Eclair slot table.  The 3DS AP status therefore uses the service
        // notification below rather than unconfigured custom slots.
        mMobileDataIconData = null;
        mMobileDataIcon = null;
        mMobileDataSignalIconData = null;
        mMobileDataSignalIcon = null;
        mNotificationManager = (NotificationManager)
                context.getSystemService(Context.NOTIFICATION_SERVICE);
        updateMobileData();
        mHandler.sendEmptyMessageDelayed(EVENT_MOBILE_DATA_POLL, MOBILE_DATA_POLL_MS);
"""

LEGACY_MOBILE_DATA_METHOD = r'''    /**
     * Reflect the service-owned 3DS Telco AP state in SystemUI.
     *
     * A request such as service.mobiledata.enable is intentionally ignored:
     * it can remain set while the AP is starting, failed, or torn down.  The
     * AP service must publish an active backend, a known state, and a bounded
     * client count before the notification is shown; the connected icons also
     * require a positive client count.
     */
    private final void updateMobileData() {
        final String state = SystemProperties.get(MOBILE_DATA_STATE, "");
        final int clients = readMobileDataClientCount();
        final boolean serviceActive = isMobileDataServiceActive(state, clients);
        final boolean connected = isMobileDataConnected(state, clients);
        final int rssi = readMobileDataRssi();
        final boolean rssiKnown = connected && rssi != Integer.MIN_VALUE;

        if (connected) {
            mMobileDataIconData.iconId =
                    com.android.internal.R.drawable.stat_sys_data_connected_g;
            mService.updateIcon(mMobileDataIcon, mMobileDataIconData, null);
            mService.setIconVisibility(mMobileDataIcon, true);
            mMobileDataIconVisible = true;

            if (rssiKnown) {
                mMobileDataSignalIconData.iconId = mobileDataSignalIcon(rssi);
                mService.updateIcon(mMobileDataSignalIcon,
                        mMobileDataSignalIconData, null);
                mService.setIconVisibility(mMobileDataSignalIcon, true);
                mMobileDataSignalVisible = true;
            } else {
                // Unknown is not a signal level.  Do not manufacture bars.
                mService.setIconVisibility(mMobileDataSignalIcon, false);
                mMobileDataSignalVisible = false;
            }
        } else {
            mService.setIconVisibility(mMobileDataIcon, false);
            mService.setIconVisibility(mMobileDataSignalIcon, false);
            mMobileDataIconVisible = false;
            mMobileDataSignalVisible = false;
        }

        updateMobileDataNotification(serviceActive, state, clients, rssi);
    }

    private boolean isMobileDataServiceActive(String state, int clients) {
        final String backend = SystemProperties.get(MOBILE_DATA_BACKEND, "");
        // "ready" is emitted before AP capability is proven.  Keep the
        // status bar fail-closed until the service publishes "active".
        if (!"active".equals(backend) || clients < 0) {
            return false;
        }
        return "starting".equals(state) || "disconnected".equals(state)
                || "connected".equals(state) || "stopping".equals(state)
                || "error".equals(state) || "failed".equals(state);
    }

    private boolean isMobileDataConnected(String state, int clients) {
        if (!isMobileDataServiceActive(state, clients)
                || !"connected".equals(state) || clients <= 0) {
            return false;
        }
        return true;
    }

    private int readMobileDataClientCount() {
        final String raw = SystemProperties.get(MOBILE_DATA_CLIENT_COUNT, "-1");
        final int clients;
        try {
            clients = Integer.parseInt(raw);
        } catch (NumberFormatException e) {
            return -1;
        }
        return clients >= 0 && clients <= 32 ? clients : -1;
    }

    /** Return Integer.MIN_VALUE unless the service published a valid dBm RSSI. */
    private int readMobileDataRssi() {
        final String raw = SystemProperties.get(MOBILE_DATA_RSSI, "unknown");
        try {
            final int rssi = Integer.parseInt(raw);
            return (rssi >= -127 && rssi <= 0) ? rssi : Integer.MIN_VALUE;
        } catch (NumberFormatException e) {
            return Integer.MIN_VALUE;
        }
    }

    private int mobileDataSignalLevel(int rssi) {
        if (rssi >= -55) return 4;
        if (rssi >= -67) return 3;
        if (rssi >= -75) return 2;
        if (rssi >= -85) return 1;
        return 0;
    }

    private int mobileDataSignalIcon(int rssi) {
        switch (mobileDataSignalLevel(rssi)) {
            case 4: return com.android.internal.R.drawable.stat_sys_signal_4;
            case 3: return com.android.internal.R.drawable.stat_sys_signal_3;
            case 2: return com.android.internal.R.drawable.stat_sys_signal_2;
            case 1: return com.android.internal.R.drawable.stat_sys_signal_1;
            default: return com.android.internal.R.drawable.stat_sys_signal_0;
        }
    }

    private void updateMobileDataNotification(boolean serviceActive, String state,
            int clients, int rssi) {
        if (mNotificationManager == null) return;
        if (!serviceActive) {
            if (mMobileDataNotificationVisible) {
                mNotificationManager.cancel(MOBILE_DATA_NOTIFICATION_ID);
                mMobileDataNotificationVisible = false;
            }
            return;
        }

        String detail;
        if ("connected".equals(state) && clients > 0) {
            detail = "Connected: " + clients + " client"
                    + (clients == 1 ? "" : "s");
            if (rssi != Integer.MIN_VALUE) detail += ", average " + rssi + " dBm";
        } else if ("starting".equals(state)) {
            detail = "Starting AP";
        } else if ("stopping".equals(state)) {
            detail = "Stopping AP";
        } else if ("error".equals(state) || "failed".equals(state)) {
            detail = "AP unavailable; Wi-Fi remains usable";
        } else {
            detail = "Waiting for client connection (" + clients + " clients)";
        }

        // notify() both posts and updates the ongoing notification if the AP
        // service changes state, clients, or RSSI between polls.
        Notification notification = new Notification(
                com.android.internal.R.drawable.stat_sys_data_connected_g,
                "3DS Telco", System.currentTimeMillis());
        notification.flags |= Notification.FLAG_ONGOING_EVENT
                | Notification.FLAG_NO_CLEAR;
        // Eclair rejects notifications without a content intent.  Use an
        // explicit Settings destination so a stale AP error cannot abort
        // StatusBarPolicy construction and take the battery receiver with it.
        Intent settingsIntent = new Intent();
        settingsIntent.setClassName("com.android.settings",
                "com.android.settings.MobileDataSettings");
        settingsIntent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent contentIntent = PendingIntent.getActivity(
                mContext, 0, settingsIntent, 0);
        notification.setLatestEventInfo(mContext, "3DS Telco",
                detail, contentIntent);
        mNotificationManager.notify(MOBILE_DATA_NOTIFICATION_ID, notification);
        mMobileDataNotificationVisible = true;
    }

'''

LEGACY_MOBILE_DATA_ICON_BODY = r'''        if (connected) {
            mMobileDataIconData.iconId =
                    com.android.internal.R.drawable.stat_sys_data_connected_g;
            mService.updateIcon(mMobileDataIcon, mMobileDataIconData, null);
            mService.setIconVisibility(mMobileDataIcon, true);
            mMobileDataIconVisible = true;

            if (rssiKnown) {
                mMobileDataSignalIconData.iconId = mobileDataSignalIcon(rssi);
                mService.updateIcon(mMobileDataSignalIcon,
                        mMobileDataSignalIconData, null);
                mService.setIconVisibility(mMobileDataSignalIcon, true);
                mMobileDataSignalVisible = true;
            } else {
                // Unknown is not a signal level.  Do not manufacture bars.
                mService.setIconVisibility(mMobileDataSignalIcon, false);
                mMobileDataSignalVisible = false;
            }
        } else {
            mService.setIconVisibility(mMobileDataIcon, false);
            mService.setIconVisibility(mMobileDataSignalIcon, false);
            mMobileDataIconVisible = false;
            mMobileDataSignalVisible = false;
        }
'''

MOBILE_DATA_ICON_BODY = r'''        if (connected) {
            // Custom n3ds slots are not present in Eclair's fixed slot table.
            // Keep AP state in the service-owned notification instead.
            mMobileDataIconVisible = false;
            mMobileDataSignalVisible = false;
        } else {
            mMobileDataIconVisible = false;
            mMobileDataSignalVisible = false;
        }
'''

if LEGACY_MOBILE_DATA_ICON_BODY not in LEGACY_MOBILE_DATA_METHOD:
    raise RuntimeError("mobile-data legacy icon body anchor missing")
MOBILE_DATA_METHOD = LEGACY_MOBILE_DATA_METHOD.replace(
    LEGACY_MOBILE_DATA_ICON_BODY, MOBILE_DATA_ICON_BODY, 1)


def migrate_unconfigured_slots(text: str) -> str:
    """Migrate the known pre-#220 custom-slot source, or fail closed."""
    custom_slot_tokens = (
        '"n3ds_mobile_data"',
        '"n3ds_mobile_data_signal"',
        "mMobileDataIcon = service.addIcon",
        "mMobileDataSignalIcon = service.addIcon",
    )
    if not any(token in text for token in custom_slot_tokens):
        return text
    text = replace_once(
        text, LEGACY_MOBILE_DATA_CONSTRUCTOR, MOBILE_DATA_CONSTRUCTOR,
        "legacy mobile-data icon constructor",
    )
    text = replace_once(
        text, LEGACY_MOBILE_DATA_METHOD, MOBILE_DATA_METHOD,
        "legacy mobile-data icon update method",
    )
    if any(token in text for token in custom_slot_tokens):
        raise RuntimeError("unconfigured Mobile Data icon slot survived migration")
    return text


def main() -> None:
    if not STATUSBAR.is_file():
        raise SystemExit(f"missing StatusBarPolicy source: {STATUSBAR}")
    text = STATUSBAR.read_text(encoding="utf-8")
    if MARKER in text:
        if NULL_CONTENT_INTENT in text:
            text = replace_once(
                text, NULL_CONTENT_INTENT, SAFE_CONTENT_INTENT,
                "null Mobile Data notification content intent",
            )
            if "import android.app.PendingIntent;" not in text:
                text = replace_once(
                    text, "import android.app.NotificationManager;\n",
                    "import android.app.NotificationManager;\n"
                    "import android.app.PendingIntent;\n",
                    "PendingIntent import",
                )
            STATUSBAR.write_text(text, encoding="utf-8")
            print("patch_n3ds_mobiledata_statusbar: migrated safe content intent")
            return
        migrated_slots = migrate_unconfigured_slots(text)
        if migrated_slots != text:
            STATUSBAR.write_text(migrated_slots, encoding="utf-8")
            print("patch_n3ds_mobiledata_statusbar: migrated invalid custom slots")
            return
        # A previous release installed the marker before the capability gate
        # and state/client notification were complete.  Migrate that exact
        # bounded region instead of silently treating the stale source as a
        # successful idempotent run.  The replacement ends at updateVolume,
        # so all old helper methods are removed together.
        if "isMobileDataServiceActive" not in text:
            method = "    private final void updateMobileData()"
            start = text.find(method)
            doc = text.rfind("    /**", 0, start)
            end = text.find("    private final void updateVolume()", start)
            if start < 0 or doc < 0 or end < 0 or not (doc < start < end):
                raise SystemExit(
                    "existing Mobile Data marker has an unknown method layout; "
                    "manual migration required")
            text = text[:doc] + MOBILE_DATA_METHOD + text[end:]
            STATUSBAR.write_text(text, encoding="utf-8")
            print("patch_n3ds_mobiledata_statusbar: migrated capability gate")
            return
        for required in (
                "sys.mobiledata.backend", "sys.mobiledata.state",
                "sys.mobiledata.client_count", "sys.mobiledata.rssi",
                "Connected: \" + clients", "EVENT_MOBILE_DATA_POLL"):
            if required not in text:
                raise SystemExit(f"existing marker but missing {required}")
        print("patch_n3ds_mobiledata_statusbar: already applied")
        return

    text = replace_once(
        text, "import android.app.AlertDialog;\n",
        "import android.app.AlertDialog;\n"
        "import android.app.Notification;\n"
        "import android.app.NotificationManager;\n"
        "import android.app.PendingIntent;\n",
        "notification imports",
    )
    text = replace_once(
        text, "import android.os.ServiceManager;\n",
        "import android.os.ServiceManager;\n"
        "import android.os.SystemProperties;\n",
        "SystemProperties import",
    )
    text = replace_once(
        text, "    private static final int EVENT_BATTERY_CLOSE = 4;\n",
        "    private static final int EVENT_BATTERY_CLOSE = 4;\n"
        + MOBILE_DATA_FIELDS,
        "mobile-data constants",
    )
    text = replace_once(
        text, "    private boolean mHspaDataDistinguishable;\n",
        "    private boolean mHspaDataDistinguishable;\n\n"
        + MOBILE_DATA_MEMBERS,
        "mobile-data members",
    )
    text = replace_once(
        text,
        "        mDataIcon = service.addIcon(mDataData, null);\n"
        "        service.setIconVisibility(mDataIcon, false);\n",
        "        mDataIcon = service.addIcon(mDataData, null);\n"
        "        service.setIconVisibility(mDataIcon, false);\n\n"
        + MOBILE_DATA_CONSTRUCTOR,
        "mobile-data icon setup",
    )
    text = replace_once(
        text, "    private final void updateVolume() {\n",
        MOBILE_DATA_METHOD + "    private final void updateVolume() {\n",
        "mobile-data policy methods",
    )
    text = replace_once(
        text,
        "            case EVENT_BATTERY_CLOSE:\n"
        "                if (msg.arg1 == mBatteryViewSequence) {\n"
        "                    closeLastBatteryView();\n"
        "                }\n"
        "                break;\n",
        "            case EVENT_BATTERY_CLOSE:\n"
        "                if (msg.arg1 == mBatteryViewSequence) {\n"
        "                    closeLastBatteryView();\n"
        "                }\n"
        "                break;\n"
        "            case EVENT_MOBILE_DATA_POLL:\n"
        "                updateMobileData();\n"
        "                mHandler.sendEmptyMessageDelayed(EVENT_MOBILE_DATA_POLL,\n"
        "                        MOBILE_DATA_POLL_MS);\n"
        "                break;\n",
        "mobile-data poll handler",
    )
    STATUSBAR.write_text(text, encoding="utf-8")
    print("patch_n3ds_mobiledata_statusbar: service-owned indicators installed")


if __name__ == "__main__":
    main()
