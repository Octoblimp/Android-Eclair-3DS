#!/usr/bin/env python3
"""Regression checks for the StreetPass-era battery policy restoration."""

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / (
    "third_party/frameworks/base/services/java/com/android/server/status/"
    "StatusBarPolicy.java"
)
PIPELINE = ROOT / "scripts/rebuild_everything.sh"
RESTORER_PATH = ROOT / "scripts/restore_n3ds_battery_statusbar.py"


def load_restorer():
    spec = importlib.util.spec_from_file_location(
        "n3ds_battery_statusbar_restorer", RESTORER_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def method(source: str) -> str:
    start = source.index("    private final void updateBattery(Intent intent) {")
    end = source.index("    private void onBatteryLow(Intent intent) {", start)
    return source[start:end]


def canonical_marked_v1_fixture(restorer) -> str:
    return """package com.android.server.status;

import android.content.Intent;

class StatusBarPolicy {
    private IconData mBatteryData;
    private IBinder mBatteryIcon;
    private StatusBarService mService;
    private boolean mBatteryPlugged;
    private int mBatteryLevel;
    private boolean mBatteryFirst = true;
    // N3DS_MOBILE_DATA_STATUSBAR: unrelated policy must survive.
""" + restorer.MARKED_BLOCK_V1 + """    private void onBatteryLow(Intent intent) {
    }
}
"""


def assert_no_later_battery_block(source: str) -> None:
    for token in (
            "N3DS_BATTERY_STATUSBAR",
            "N3DS_BATTERY_STATUS_UNKNOWN",
            "N3DS_BATTERY_STATUS_CHARGING",
            "N3DS_BATTERY_STATUS_DISCHARGING",
            "N3DS_BATTERY_STATUS_NOT_CHARGING",
            "N3DS_BATTERY_STATUS_FULL",
            "batteryLevelPercent",
            "batteryIconForProperties"):
        assert token not in source, token


def main() -> None:
    assert MIRROR.is_file(), MIRROR
    assert RESTORER_PATH.is_file(), RESTORER_PATH
    deployed = MIRROR.read_text(encoding="utf-8")
    restorer = load_restorer()

    # The deployed source must be the exact known historical method, while
    # unrelated later Mobile Data policy remains in the enclosing source.
    assert method(deployed) == restorer.HISTORICAL_METHOD
    assert_no_later_battery_block(deployed)
    assert "N3DS_MOBILE_DATA_STATUSBAR" in deployed
    historical = restorer.HISTORICAL_METHOD
    assert 'mBatteryData.iconId = intent.getIntExtra("icon-small", 0);' in historical
    assert 'mBatteryData.iconLevel = intent.getIntExtra("level", 0);' in historical
    assert 'int level = intent.getIntExtra("level", -1);' in historical
    assert "batteryLevelPercent" not in historical
    assert "batteryIconForProperties" not in historical

    marked = restorer.MARKED_BLOCK_V1
    assert marked.index("N3DS_BATTERY_STATUSBAR") < marked.index(
        "private final void updateBattery")
    assert marked.index("N3DS_BATTERY_STATUS_FULL") < marked.index(
        "batteryLevelPercent")
    assert marked.index("batteryLevelPercent") < marked.index(
        "batteryIconForProperties")

    pipeline = PIPELINE.read_text(encoding="utf-8")
    assert "run patch_n3ds_battery_statusbar.py" not in pipeline
    assert "run restore_n3ds_battery_statusbar.py" in pipeline
    assert "run test_n3ds_battery_statusbar.py" in pipeline
    assert pipeline.index("run restore_n3ds_battery_statusbar.py") < pipeline.index(
        "run build_services_jar.sh"
    )

    # The canonical marked-v1 source is repaired as one complete block, and a
    # second run is byte-for-byte a no-op.
    with tempfile.TemporaryDirectory() as temp_dir:
        status = Path(temp_dir) / "StatusBarPolicy.java"
        status.write_text(canonical_marked_v1_fixture(restorer), encoding="utf-8")
        assert restorer.restore(status) is True
        first = status.read_text(encoding="utf-8")
        assert method(first) == historical
        assert first.count("private final void updateBattery(Intent intent) {") == 1
        assert_no_later_battery_block(first)
        assert "private int batteryLevelPercent(Intent intent)" not in first
        assert "private int batteryIconForProperties(Intent intent)" not in first
        assert "N3DS_MOBILE_DATA_STATUSBAR" in first
        assert restorer.restore(status) is False
        assert first == status.read_text(encoding="utf-8")

    # A marked but changed block is rejected rather than partially replaced.
    with tempfile.TemporaryDirectory() as temp_dir:
        status = Path(temp_dir) / "StatusBarPolicy.java"
        status.write_text(canonical_marked_v1_fixture(restorer).replace(
            "N3DS_BATTERY_STATUS_FULL = 5",
            "N3DS_BATTERY_STATUS_FULL = 6",
        ), encoding="utf-8")
        try:
            restorer.restore(status)
        except SystemExit as exc:
            assert "marked battery block differs" in str(exc)
        else:
            raise AssertionError("changed marked battery block was overwritten")

    # An unmarked unknown method is also rejected instead of being overwritten
    # by a speculative icon policy.
    with tempfile.TemporaryDirectory() as temp_dir:
        status = Path(temp_dir) / "StatusBarPolicy.java"
        status.write_text(canonical_marked_v1_fixture(restorer).replace(
            "N3DS_BATTERY_STATUSBAR",
            "unrelated battery implementation",
        ), encoding="utf-8")
        try:
            restorer.restore(status)
        except SystemExit as exc:
            assert "unmarked battery method differs" in str(exc)
        else:
            raise AssertionError("unmarked battery implementation was overwritten")

    print("n3ds_battery_statusbar_restore: PASS")


if __name__ == "__main__":
    main()
