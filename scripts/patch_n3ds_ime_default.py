#!/usr/bin/env python3
"""Select the bundled Nintendo 3DS keyboard on fresh and existing data."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PATH = Path(f"{A3DS_ROOT}/third_party/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java")
IME = "com.android.inputmethod.latin/.LatinIME"
text = PATH.read_text()

text = text.replace(
    "private static final int DATABASE_VERSION = 42;",
    "private static final int DATABASE_VERSION = 43;",
)

anchor = """        if (upgradeVersion != currentVersion) {
"""
migration = f"""        if (upgradeVersion == 42) {{
            /* N3DS_DEFAULT_TOUCH_IME: older images had no keyboard, leaving
             * these rows absent or empty.  Preserve a user's non-empty choice
             * but make the bundled 3DS-sized keyboard immediately usable. */
            db.beginTransaction();
            try {{
                db.execSQL("INSERT OR IGNORE INTO secure(name,value) values('" +
                        Settings.Secure.ENABLED_INPUT_METHODS + "','{IME}');");
                db.execSQL("UPDATE secure SET value='{IME}' WHERE name='" +
                        Settings.Secure.ENABLED_INPUT_METHODS +
                        "' AND (value IS NULL OR value='');");
                db.execSQL("INSERT OR IGNORE INTO secure(name,value) values('" +
                        Settings.Secure.DEFAULT_INPUT_METHOD + "','{IME}');");
                db.execSQL("UPDATE secure SET value='{IME}' WHERE name='" +
                        Settings.Secure.DEFAULT_INPUT_METHOD +
                        "' AND (value IS NULL OR value='');");
                db.setTransactionSuccessful();
            }} finally {{
                db.endTransaction();
            }}
            upgradeVersion = 43;
        }}

"""
if "N3DS_DEFAULT_TOUCH_IME" not in text:
    if text.count(anchor) != 1:
        raise SystemExit("SettingsProvider migration anchor not found exactly once")
    text = text.replace(anchor, migration + anchor)

fresh_anchor = """        loadBooleanSetting(stmt, Settings.Secure.WIFI_NETWORKS_AVAILABLE_NOTIFICATION_ON,
                R.bool.def_networks_available_notification_on);
"""
fresh = fresh_anchor + f"""
        // N3DS_DEFAULT_TOUCH_IME: the console has no hardware text keyboard.
        loadSetting(stmt, Settings.Secure.ENABLED_INPUT_METHODS,
                "{IME}");
        loadSetting(stmt, Settings.Secure.DEFAULT_INPUT_METHOD,
                "{IME}");
"""
if text.count(fresh_anchor) == 1 and text.count("N3DS_DEFAULT_TOUCH_IME") == 1:
    text = text.replace(fresh_anchor, fresh)
elif text.count("N3DS_DEFAULT_TOUCH_IME") < 2:
    raise SystemExit("SettingsProvider fresh-default anchor not found exactly once")

PATH.write_text(text)
print("patch_n3ds_ime_default: SettingsProvider v43 selects bundled LatinIME keyboard")
