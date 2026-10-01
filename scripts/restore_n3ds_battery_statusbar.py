#!/usr/bin/env python3
"""Restore the pre-2026-08-25 StreetPass-era battery policy.

The later property-backed battery patch replaced one bounded block spanning a
marker, status constants, ``updateBattery``, and two helper methods.  This
restorer recognizes that exact block and removes it as one unit, leaving the
surrounding SystemUI policy (including Mobile Data indicators) untouched.  It
is idempotent for the already-restored historical source and rejects unknown
variants instead of guessing at an icon policy.
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


HISTORICAL_METHOD = r'''    private final void updateBattery(Intent intent) {
        mBatteryData.iconId = intent.getIntExtra("icon-small", 0);
        mBatteryData.iconLevel = intent.getIntExtra("level", 0);
        mService.updateIcon(mBatteryIcon, mBatteryData, null);

        boolean plugged = intent.getIntExtra("plugged", 0) != 0;
        int level = intent.getIntExtra("level", -1);
        if (false) {
            Log.d(TAG, "updateBattery level=" + level
                    + " plugged=" + plugged
                    + " mBatteryPlugged=" + mBatteryPlugged
                    + " mBatteryLevel=" + mBatteryLevel
                    + " mBatteryFirst=" + mBatteryFirst);
        }

        boolean oldPlugged = mBatteryPlugged;
        mBatteryPlugged = plugged;
        mBatteryLevel = level;

        if (mBatteryFirst) {
            mBatteryFirst = false;
        }
        /*
         * No longer showing the battery view because it draws attention away
         * from the USB storage notification. We could still show it when
         * connected to a brick, but that could lead to the user into thinking
         * the device does not charge when plugged into USB (since he/she
         * would not see the same battery screen on USB as he sees on brick).
         */
        if (false) {
            Log.d(TAG, "plugged=" + plugged + " oldPlugged=" + oldPlugged
                    + " level=" + level);
        }
    }

'''


MARKED_BLOCK_V1 = r'''    // N3DS_BATTERY_STATUSBAR: BatteryService may omit icon-small on 3DS.
    // Use only validated power-supply properties; an absent/invalid level or
    // status remains the framework's explicit unknown icon, never 0 percent.
    private static final int N3DS_BATTERY_STATUS_UNKNOWN = 1;
    private static final int N3DS_BATTERY_STATUS_CHARGING = 2;
    private static final int N3DS_BATTERY_STATUS_DISCHARGING = 3;
    private static final int N3DS_BATTERY_STATUS_NOT_CHARGING = 4;
    private static final int N3DS_BATTERY_STATUS_FULL = 5;

    private final void updateBattery(Intent intent) {
        int level = batteryLevelPercent(intent);
        int iconId = intent.getIntExtra("icon-small", 0);
        if (level < 0) {
            // Do not display a stale or fabricated capacity when the power
            // supply did not publish a bounded level/scale pair.
            iconId = com.android.internal.R.drawable.stat_sys_battery_unknown;
            mBatteryData.iconLevel = 0;
        } else {
            if (iconId <= 0) iconId = batteryIconForProperties(intent);
            mBatteryData.iconLevel = level;
        }
        mBatteryData.iconId = iconId > 0
                ? iconId : com.android.internal.R.drawable.stat_sys_battery_unknown;
        mService.updateIcon(mBatteryIcon, mBatteryData, null);

        boolean plugged = intent.getIntExtra("plugged", 0) != 0;
        if (false) {
            Log.d(TAG, "updateBattery level=" + level
                    + " plugged=" + plugged
                    + " mBatteryPlugged=" + mBatteryPlugged
                    + " mBatteryLevel=" + mBatteryLevel
                    + " mBatteryFirst=" + mBatteryFirst);
        }

        boolean oldPlugged = mBatteryPlugged;
        mBatteryPlugged = plugged;
        mBatteryLevel = level;

        if (mBatteryFirst) {
            mBatteryFirst = false;
        }
        /*
         * No longer showing the battery view because it draws attention away
         * from the USB storage notification. We could still show it when
         * connected to a brick, but that could lead to the user into thinking
         * the device does not charge when plugged into USB (since he/she
         * would not see the same battery screen on USB as he sees on brick).
         */
        if (false) {
            Log.d(TAG, "plugged=" + plugged + " oldPlugged=" + oldPlugged
                    + " level=" + level);
        }
    }

    private int batteryLevelPercent(Intent intent) {
        int raw = intent.getIntExtra("level", -1);
        int scale = intent.getIntExtra("scale", -1);
        if (raw < 0 || scale <= 0 || raw > scale || scale > 1000) return -1;
        return (int) (((long) raw * 100L) / (long) scale);
    }

    private int batteryIconForProperties(Intent intent) {
        // BatteryService's present and status fields are direct power-supply
        // facts.  Missing status is not equivalent to discharging.
        if (!intent.getBooleanExtra("present", false)) {
            return com.android.internal.R.drawable.stat_sys_battery_unknown;
        }
        int status = intent.getIntExtra("status", N3DS_BATTERY_STATUS_UNKNOWN);
        if (status == N3DS_BATTERY_STATUS_CHARGING
                || (status == N3DS_BATTERY_STATUS_FULL
                && intent.getIntExtra("plugged", 0) != 0)) {
            return com.android.internal.R.drawable.stat_sys_battery_charge;
        }
        if (status == N3DS_BATTERY_STATUS_DISCHARGING
                || status == N3DS_BATTERY_STATUS_NOT_CHARGING
                || status == N3DS_BATTERY_STATUS_FULL) {
            return com.android.internal.R.drawable.stat_sys_battery;
        }
        return com.android.internal.R.drawable.stat_sys_battery_unknown;
    }

'''

# Keep the old public name for callers which used the first restoration
# regression fixture.  New code should use the versioned name: this is an
# exact source block, not a pattern for partially matching a method.
MARKED_BLOCK = MARKED_BLOCK_V1


MARKER_PREFIX = "    // N3DS_BATTERY_STATUSBAR"
METHOD_MARKER = "    private final void updateBattery(Intent intent) {"
END_MARKER = "    private void onBatteryLow(Intent intent) {"


LATER_BATTERY_TOKENS = (
    "N3DS_BATTERY_STATUSBAR",
    "N3DS_BATTERY_STATUS_UNKNOWN",
    "N3DS_BATTERY_STATUS_CHARGING",
    "N3DS_BATTERY_STATUS_DISCHARGING",
    "N3DS_BATTERY_STATUS_NOT_CHARGING",
    "N3DS_BATTERY_STATUS_FULL",
    "batteryLevelPercent",
    "batteryIconForProperties",
)


def _normalise_newlines(text: str) -> str:
    """Make source matching independent of a Windows checkout's line ending."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalised_offsets(text: str):
    """Return normalized text and raw offsets for each normalized character."""
    normalized = []
    offsets = [0]
    index = 0
    while index < len(text):
        if text.startswith("\r\n", index):
            normalized.append("\n")
            index += 2
        elif text[index] == "\r":
            normalized.append("\n")
            index += 1
        else:
            normalized.append(text[index])
            index += 1
        offsets.append(index)
    return "".join(normalized), offsets


def _battery_marker_positions(text: str):
    """Return line starts carrying the battery marker, including unknown forms."""
    positions = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.startswith(MARKER_PREFIX):
            positions.append(offset)
        offset += len(line)
    return positions


def _restore_text(text: str):
    """Return ``(changed, restored_text)`` for normalized source text."""
    text = _normalise_newlines(text)
    method_start = text.find(METHOD_MARKER)
    end = text.find(END_MARKER, method_start)
    if method_start < 0 or end < 0 or end <= method_start:
        raise SystemExit("updateBattery anchor not found")

    method = text[method_start:end]
    marker_positions = _battery_marker_positions(text)

    # Historical source is the only accepted unmarked state.  A stale marker
    # or helper anywhere in the source means that restoration was incomplete,
    # so do not silently claim a no-op.
    if not marker_positions:
        if method == HISTORICAL_METHOD:
            if any(token in text for token in LATER_BATTERY_TOKENS):
                raise SystemExit("historical battery method has leftover later patch code")
            return False, text
        raise SystemExit("unmarked battery method differs from the historical source")

    # Match the complete known v1 block.  In particular, do not stop at the
    # updateBattery closing brace: the constants and both property helpers are
    # part of the later patch and must be removed atomically.
    block_start = text.find(MARKED_BLOCK_V1)
    expected_method_start = MARKED_BLOCK_V1.find(METHOD_MARKER)
    if (block_start < 0
            or block_start + expected_method_start != method_start):
        raise SystemExit("marked battery block differs from the known later patch")

    # A duplicate marker or any later token outside the matched block is an
    # unfamiliar variant.  Failing closed avoids deleting unrelated policy.
    if marker_positions != [block_start] or any(
            token in text[:block_start] + text[block_start + len(MARKED_BLOCK_V1):]
            for token in LATER_BATTERY_TOKENS):
        raise SystemExit("marked battery block differs from the known later patch")

    block_end = block_start + len(MARKED_BLOCK_V1)
    return True, text[:block_start] + HISTORICAL_METHOD + text[block_end:]


def restore(path: Path = STATUSBAR) -> bool:
    if not path.is_file():
        raise SystemExit(f"missing StatusBarPolicy source: {path}")
    # Read/write with explicit newline handling.  Matching is normalized, and
    # the replacement is spliced into the raw source so a Windows invocation
    # does not rewrite unrelated mixed-ending Java text.
    with path.open("r", encoding="utf-8", newline="") as stream:
        raw = stream.read()
    normalized, offsets = _normalised_offsets(raw)
    changed, _ = _restore_text(normalized)
    if not changed:
        return False
    block_start = normalized.find(MARKED_BLOCK_V1)
    block_end = block_start + len(MARKED_BLOCK_V1)
    raw_start = offsets[block_start]
    raw_end = offsets[block_end]
    raw_block = raw[raw_start:raw_end]
    eol = "\r\n" if "\r\n" in raw_block else "\n"
    replacement = HISTORICAL_METHOD.replace("\n", eol)
    restored = raw[:raw_start] + replacement + raw[raw_end:]
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(restored)
    return True


def main() -> None:
    changed = restore()
    print(
        "restore_n3ds_battery_statusbar: "
        + ("restored historical block" if changed else "already restored")
    )


if __name__ == "__main__":
    main()
