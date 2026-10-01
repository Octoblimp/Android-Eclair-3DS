#!/usr/bin/env python3
"""Repair the SettingsProvider DATABASE_VERSION assertion in
verify_release_artifacts.sh, and extend it to cover the new sound defaults.

Why the gate broke
------------------
The gate pinned:

    private static final int DATABASE_VERSION = 43;

That line was correct when N3DS_DEFAULT_TOUCH_IME was the newest default:
the pin is what stops someone adding a default row without bumping the
version, which would leave every already-provisioned device on the old
database with the new row missing forever.

Adding the N3DS sound defaults bumped it to 44 and added the matching
`upgradeVersion == 43` block, which is exactly the discipline the pin
exists to enforce.  So the gate is now asserting a superseded design --
repair it, do not delete it.

What the repaired gate asserts
------------------------------
  * DATABASE_VERSION is 44 (still pinned: a future default must bump it
    again and update this line, which is the whole point);
  * the 43 -> 44 upgrade block exists, so devices already carrying a v43
    database actually receive the sound rows instead of silently keeping
    a database with no ringtone, no notification and no DTMF setting;
  * loadN3dsSoundSettings is called twice -- once from the fresh-create
    path and once from the upgrade path.  One call site is the classic
    way this goes wrong: sounds work on a wiped device and are missing on
    an upgraded one, or vice versa, and neither is reproducible without
    knowing which database the tester started from.

Idempotent: keyed on the exact old line, and a no-op once repaired.
"""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

import io
import sys

COPIES = [
    f"{A3DS_ROOT}/scripts/verify_release_artifacts.sh",
    f"{A3DS_WIN}"
    "/scripts/verify_release_artifacts.sh",
]

OLD = """grep -F 'private static final int DATABASE_VERSION = 43;' \\
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java"
"""

NEW = """# N3DS_SETTINGS_DB_V44: pinned on purpose. Adding a default row without
# bumping DATABASE_VERSION leaves every already-provisioned device on the
# old database with the new row missing forever, and the symptom -- a
# setting that works on a wiped device and not on an upgraded one -- is
# invisible unless you know which database the tester started from. Bump
# this line together with the version and add the matching upgrade block.
grep -F 'private static final int DATABASE_VERSION = 44;' \\
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java"
# ...and the 43 -> 44 upgrade must exist, or devices carrying a v43
# database get no ringtone, no notification sound and no DTMF row.
grep -F 'if (upgradeVersion == 43) {' \\
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java"
grep -F 'N3DS_DEFAULT_SOUNDS' \\
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java"
# Both paths, fresh-create and upgrade: 2 calls plus the declaration = 3.
test "$(grep -c 'loadN3dsSoundSettings' \\
    "$NATIVE_ROOT/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java")" = 3
# The default URIs must name files that are actually on the card, or the
# first notification silently falls back to nothing.
test -s "$ANDROID_ROOT/system/media/audio/notifications/F1_New_SMS.wav"
test -s "$ANDROID_ROOT/system/media/audio/ringtones/Ring_Synth_04.wav"
test -s "$ANDROID_ROOT/system/media/audio/alarms/Alarm_Classic.wav"
"""

changed = 0
for path in COPIES:
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except IOError as e:
        print("  SKIP (unreadable): %s (%s)" % (path, e))
        continue

    if "N3DS_SETTINGS_DB_V44" in src:
        print("  already repaired: %s" % path)
        continue
    if OLD not in src:
        print("  ANCHOR NOT FOUND: %s" % path)
        sys.exit(1)

    src = src.replace(OLD, NEW, 1)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print("  repaired: %s" % path)
    changed += 1

print("changed=%d" % changed)
