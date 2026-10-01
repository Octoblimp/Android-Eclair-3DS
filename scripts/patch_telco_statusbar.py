#!/usr/bin/env python3
"""Install the service-state and endpoint-latency 3DSTelco status policy."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path
import re


HERE = Path(__file__).resolve().parents[1]
REL = Path("third_party/frameworks/base/services/java/com/android/server/status/StatusBarPolicy.java")
POLICIES = [HERE / REL, Path(A3DS_ROOT) / REL]

OLD_SIGNAL = '''        boolean telcoEnabled = Settings.System.getInt(mContext.getContentResolver(), "n3ds_telco_enabled", 0) == 1;
        long ping = Settings.System.getLong(mContext.getContentResolver(), "n3ds_telco_ping", -1);
        if (telcoEnabled && ping >= 0) {
            int level;
            if (ping < 50) level = 4;
            else if (ping < 150) level = 3;
            else if (ping < 300) level = 2;
            else if (ping < 600) level = 1;
            else level = 0;
            mPhoneData.iconId = sSignalImages[level];
'''
NEW_SIGNAL = '''        if (isN3dsTelcoOnline()) {
            // N3DS_TELCO_STATUSBAR_ONLINE_STATE and
            // N3DS_TELCO_STATUSBAR_LATENCY_BARS: this is the authenticated
            // /v1/status endpoint round trip, not Wi-Fi RSSI or radio power.
            mPhoneData.iconId = sSignalImages[getN3dsTelcoSignalLevel()];
'''
OLD_DATA = '''        boolean telcoEnabled = Settings.System.getInt(mContext.getContentResolver(), "n3ds_telco_enabled", 0) == 1;
        long ping = Settings.System.getLong(mContext.getContentResolver(), "n3ds_telco_ping", -1);
        if (telcoEnabled && ping >= 0) {
'''
NEW_DATA = '''        if (isN3dsTelcoOnline()) {
'''
OLD_HELPER = '''    private final void updateMobileData() {
        updateSignalStrength();
        updateDataIcon();
    }
'''
NEW_HELPER = '''    private final void updateMobileData() {
        updateSignalStrength();
        updateDataIcon();
    }

    private boolean isN3dsTelcoOnline() {
        if (Settings.System.getInt(mContext.getContentResolver(),
                "n3ds_telco_enabled", 0) != 1) return false;
        long sample = Settings.System.getLong(mContext.getContentResolver(),
                "n3ds_telco_latency_sample_elapsed_ms", -1);
        long now = android.os.SystemClock.elapsedRealtime();
        if (sample < 0 || sample > now || now - sample > 45000) return false;
        String status = Settings.System.getString(mContext.getContentResolver(),
                "n3ds_telco_status");
        return status != null && (status.startsWith("Online")
                || status.startsWith("Registered and online"));
    }

    private int getN3dsTelcoSignalLevel() {
        long latency = Settings.System.getLong(mContext.getContentResolver(),
                "n3ds_telco_latency_ms", -1);
        if (latency < 0) return 0;
        if (latency < 150) return 4;
        if (latency < 400) return 3;
        if (latency < 1000) return 2;
        if (latency < 2500) return 1;
        return 0;
    }
'''
OLD_RECEIVER = '''            else if (action.equals(TtyIntent.TTY_ENABLED_CHANGE_ACTION)) {
                updateTTY(intent);
            }
'''
NEW_RECEIVER = OLD_RECEIVER + '''            else if (action.equals("io.divergen.telco.action.STATE")) {
                updateMobileData();
            }
'''
OLD_FILTER = '        filter.addAction(TtyIntent.TTY_ENABLED_CHANGE_ACTION);\n'
NEW_FILTER = OLD_FILTER + '        filter.addAction("io.divergen.telco.action.STATE");\n'


def install(policy: Path) -> None:
    source = policy.read_text(encoding="utf-8")
    if "N3DS_TELCO_STATUSBAR_ONLINE_STATE" not in source:
        for old, new, label in (
            (OLD_SIGNAL, NEW_SIGNAL, "signal policy"),
            (OLD_DATA, NEW_DATA, "data icon policy"),
            (OLD_HELPER, NEW_HELPER, "online helper"),
            (OLD_RECEIVER, NEW_RECEIVER, "state receiver"),
            (OLD_FILTER, NEW_FILTER, "state filter"),
        ):
            if source.count(old) != 1:
                raise SystemExit(f"patch_telco_statusbar: {label} anchor count={source.count(old)} in {policy}")
            source = source.replace(old, new, 1)

    # Upgrade both the prior online-only repair and earlier latency candidates.
    if 'sSignalImages[4]' in source and 'not a fabricated radio-strength' in source:
        source = source.replace('mPhoneData.iconId = sSignalImages[4];',
                'mPhoneData.iconId = sSignalImages[getN3dsTelcoSignalLevel()];', 1)
    helper = NEW_HELPER[NEW_HELPER.index('    private boolean isN3dsTelcoOnline()'):]
    source, count = re.subn(r'    private boolean isN3dsTelcoOnline\(\) \{.*?\n    \}\n(?:\n    private int getN3dsTelcoSignalLevel\(\) \{.*?\n    \}\n)?',
                            lambda match: helper, source, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f'patch_telco_statusbar: online helper missing in {policy}')
    if 'N3DS_TELCO_STATUSBAR_LATENCY_BARS' not in source:
        source = source.replace('N3DS_TELCO_STATUSBAR_ONLINE_STATE:',
                'N3DS_TELCO_STATUSBAR_LATENCY_BARS / N3DS_TELCO_STATUSBAR_ONLINE_STATE:', 1)
    if 'action.equals("io.divergen.telco.action.STATE")' not in source:
        if source.count(OLD_RECEIVER) != 1: raise SystemExit('Missing receiver anchor')
        source = source.replace(OLD_RECEIVER, NEW_RECEIVER, 1)
    if 'filter.addAction("io.divergen.telco.action.STATE")' not in source:
        if source.count(OLD_FILTER) != 1: raise SystemExit('Missing filter anchor')
        source = source.replace(OLD_FILTER, NEW_FILTER, 1)

    for required in (
        "N3DS_TELCO_STATUSBAR_ONLINE_STATE",
        "N3DS_TELCO_STATUSBAR_LATENCY_BARS",
        "isN3dsTelcoOnline()",
        "getN3dsTelcoSignalLevel()",
        "n3ds_telco_status",
        "n3ds_telco_latency_ms",
        'io.divergen.telco.action.STATE',
    ):
        if required not in source:
            raise SystemExit(f"patch_telco_statusbar: missing {required} in {policy}")
    if "n3ds_telco_ping" in source:
        raise SystemExit(f"patch_telco_statusbar: obsolete synthetic ping gate remains in {policy}")
    policy.write_text(source, encoding="utf-8")
    print(f"patch_telco_statusbar: service-state latency icon policy ready in {policy}")


found = False
for policy in dict.fromkeys(POLICIES):
    if policy.is_file():
        found = True
        install(policy)
if not found:
    raise SystemExit("patch_telco_statusbar: no StatusBarPolicy source found")
