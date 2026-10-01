#!/usr/bin/env python3
"""Regression checks for the fail-closed 3DS Telco StatusBarPolicy slice."""

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / (
    "third_party/frameworks/base/services/java/com/android/server/status/"
    "StatusBarPolicy.java"
)
PIPELINE = ROOT / "scripts/rebuild_everything.sh"


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "n3ds_mobiledata_statusbar_patcher",
        ROOT / "scripts/patch_n3ds_mobiledata_statusbar.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fresh_fixture() -> str:
    # The patch has deliberately narrow anchors.  This fixture is enough to
    # prove first application and is intentionally not a copy of the deployed
    # source, so an accidental marker-only no-op cannot pass.
    return """package com.android.server.status;

import android.app.AlertDialog;
import android.os.ServiceManager;

class StatusBarPolicy {
    private static final int EVENT_BATTERY_CLOSE = 4;
    private boolean mHspaDataDistinguishable;
    private IBinder mDataIcon;

    StatusBarPolicy(Context context, StatusBarService service) {
        mDataIcon = service.addIcon(mDataData, null);
        service.setIconVisibility(mDataIcon, false);
    }

    private final void updateVolume() {
    }

    private class StatusBarHandler extends Handler {
        public void handleMessage(Message msg) {
            switch (msg.what) {
            case EVENT_BATTERY_CLOSE:
                if (msg.arg1 == mBatteryViewSequence) {
                    closeLastBatteryView();
                }
                break;
            }
        }
    }
}
"""


def legacy_fixture() -> str:
    # This represents the earlier marked source that accepted "ready" as
    # capability and only exposed a connected-client icon.  The patcher must
    # migrate it instead of treating the marker as a successful no-op.
    return """package com.android.server.status;

class StatusBarPolicy {
    // N3DS_MOBILE_DATA_STATUSBAR: old implementation
    private static final int EVENT_MOBILE_DATA_POLL = 5;
    private static final String MOBILE_DATA_BACKEND = "sys.mobiledata.backend";
    private static final String MOBILE_DATA_STATE = "sys.mobiledata.state";
    private static final String MOBILE_DATA_CLIENT_COUNT = "sys.mobiledata.client_count";
    private static final String MOBILE_DATA_RSSI = "sys.mobiledata.rssi";

    /**
     * Reflect the service-owned 3DS Telco AP state in SystemUI.
     */
    private final void updateMobileData() {
        final boolean connected = isMobileDataConnected();
        updateMobileDataNotification(connected);
    }

    private boolean isMobileDataConnected() {
        return true;
    }

    private void updateMobileDataNotification(boolean connected) {
    }

    private final void updateVolume() {
    }
}
"""


def invalid_slot_fixture(patcher) -> str:
    # This is the exact complete post-v1 region that caused #220: the
    # constructor allocates two slots that StatusBarService does not expose,
    # while the policy method updates those binders.
    return """package com.android.server.status;

class StatusBarPolicy {
""" + patcher.MOBILE_DATA_FIELDS + patcher.LEGACY_MOBILE_DATA_CONSTRUCTOR + patcher.LEGACY_MOBILE_DATA_METHOD + """    private final void updateVolume() {
    }
}
"""


def main() -> None:
    assert MIRROR.is_file(), MIRROR
    deployed = MIRROR.read_text(encoding="utf-8")
    assert "N3DS_MOBILE_DATA_STATUSBAR" in deployed
    assert '"ready".equals(backend)' not in deployed
    for marker in (
        '"sys.mobiledata.backend"',
        '"sys.mobiledata.state"',
        '"sys.mobiledata.client_count"',
        '"sys.mobiledata.rssi"',
        '"active".equals(backend)',
        'isMobileDataServiceActive',
        'readMobileDataClientCount',
        '"connected".equals(state)',
        'clients >= 0 && clients <= 32',
        'rssi >= -127 && rssi <= 0',
        'mMobileDataSignalVisible = false',
        'mNotificationManager.notify(MOBILE_DATA_NOTIFICATION_ID, notification)',
        'mNotificationManager.cancel(MOBILE_DATA_NOTIFICATION_ID)',
        'Connected: " + clients',
        'Waiting for client connection',
        'EVENT_MOBILE_DATA_POLL',
        'StatusBarService validates icon slots',
        'PendingIntent.getActivity',
        'com.android.settings.MobileDataSettings',
    ):
        assert marker in deployed, marker
    for invalid in (
        '"n3ds_mobile_data"',
        '"n3ds_mobile_data_signal"',
        'mMobileDataIcon = service.addIcon',
        'mMobileDataSignalIcon = service.addIcon',
    ):
        assert invalid not in deployed, invalid
    assert 'detail, null' not in deployed
    assert 'import android.app.PendingIntent;' in deployed

    pipeline = PIPELINE.read_text(encoding="utf-8")
    assert "run patch_n3ds_mobiledata_statusbar.py" in pipeline
    assert "run test_n3ds_mobiledata_statusbar.py" in pipeline
    assert pipeline.index("run patch_n3ds_mobiledata_statusbar.py") < pipeline.index(
        "run build_services_jar.sh"
    )

    patcher = load_patcher()
    patch_source = (ROOT / "scripts/patch_n3ds_mobiledata_statusbar.py").read_text(
        encoding="utf-8")
    assert "existing Mobile Data marker has an unknown method layout" in patch_source
    assert "migrate_unconfigured_slots" in patch_source
    assert "unconfigured Mobile Data icon slot survived migration" in patch_source
    with tempfile.TemporaryDirectory() as temp_dir:
        status = Path(temp_dir) / "StatusBarPolicy.java"
        status.write_text(fresh_fixture(), encoding="utf-8")
        patcher.STATUSBAR = status
        patcher.main()
        first = status.read_text(encoding="utf-8")
        assert "N3DS_MOBILE_DATA_STATUSBAR" in first
        assert "NotificationManager" in first
        assert "updateMobileDataNotification" in first
        assert "PendingIntent.getActivity" in first
        assert "detail, null" not in first
        patcher.main()
        assert first == status.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as temp_dir:
        status = Path(temp_dir) / "StatusBarPolicy.java"
        status.write_text(legacy_fixture(), encoding="utf-8")
        patcher.STATUSBAR = status
        patcher.main()
        migrated = status.read_text(encoding="utf-8")
        assert "isMobileDataServiceActive" in migrated
        assert "isMobileDataConnected()" not in migrated
        before = migrated
        patcher.main()
        assert before == status.read_text(encoding="utf-8")

    # The deployed mirror is already patched; running the actual patcher on a
    # temporary copy must be a byte-for-byte no-op as well.
    with tempfile.TemporaryDirectory() as temp_dir:
        status = Path(temp_dir) / "StatusBarPolicy.java"
        status.write_text(deployed, encoding="utf-8")
        patcher.STATUSBAR = status
        before = status.read_text(encoding="utf-8")
        patcher.main()
        assert before == status.read_text(encoding="utf-8")

    # The exact #220 invalid-slot region migrates atomically to the
    # notification-only implementation and remains idempotent.
    with tempfile.TemporaryDirectory() as temp_dir:
        status = Path(temp_dir) / "StatusBarPolicy.java"
        status.write_text(invalid_slot_fixture(patcher), encoding="utf-8")
        patcher.STATUSBAR = status
        patcher.main()
        migrated = status.read_text(encoding="utf-8")
        assert "StatusBarService validates icon slots" in migrated
        assert "updateMobileDataNotification" in migrated
        assert "n3ds_mobile_data" not in migrated
        assert "n3ds_mobile_data_signal" not in migrated
        assert "service.addIcon(mMobileDataIconData" not in migrated
        assert "service.addIcon(mMobileDataSignalIconData" not in migrated
        before = migrated
        patcher.main()
        assert before == status.read_text(encoding="utf-8")

    # A changed invalid-slot region is not guessed at or partially repaired.
    with tempfile.TemporaryDirectory() as temp_dir:
        status = Path(temp_dir) / "StatusBarPolicy.java"
        status.write_text(
            invalid_slot_fixture(patcher).replace(
                '"n3ds_mobile_data_signal"',
                '"n3ds_mobile_data_signal_changed"',
            ),
            encoding="utf-8",
        )
        patcher.STATUSBAR = status
        before = status.read_text(encoding="utf-8")
        try:
            patcher.main()
        except RuntimeError as exc:
            assert "legacy mobile-data icon constructor" in str(exc)
        else:
            raise AssertionError("unknown invalid-slot layout was overwritten")
        assert before == status.read_text(encoding="utf-8")

    print("n3ds_mobiledata_statusbar: PASS")


if __name__ == "__main__":
    main()
