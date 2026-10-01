#!/usr/bin/env python3
"""Compile and exercise the real TelcoConfig persistence code offline.

The harness substitutes only the absolute SD-card path with a temporary file;
all parser, validation, fsync, atomic-rename, and failure behavior comes from
the checked-in Java source.  No Android device, network, credential, or user
registration is touched.
"""

from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PHONE = ROOT / "content/stock-app-overlays/Phone/src/com/android/phone"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


with tempfile.TemporaryDirectory(prefix="telco-java-") as directory:
    root = Path(directory)
    package = root / "src/com/android/phone"
    classes = root / "classes"
    classes.mkdir()
    config_path = (root / "sdcard/persistent/shared/mobile_registration.conf").as_posix()

    config = (PHONE / "TelcoConfig.java").read_text(encoding="utf-8")
    config = config.replace(
        '"/sdcard/persistent/shared/mobile_registration.conf"',
        '"' + config_path + '"',
    )
    write(package / "TelcoConfig.java", config)
    write(package / "TelcoContract.java", (PHONE / "TelcoContract.java").read_text(encoding="utf-8"))
    write(package / "TelcoHttp.java", (PHONE / "TelcoHttp.java").read_text(encoding="utf-8"))
    write(root / "src/org/json/JSONObject.java", """
package org.json;
public class JSONObject {
    private java.util.Map<String,String> values = new java.util.HashMap<String,String>();
    public JSONObject() {}
    public JSONObject(String value) {}
    public JSONObject put(String key, String value) { values.put(key,value); return this; }
    public String getString(String key) { return values.get(key); }
    public String optString(String key, String fallback) { return values.containsKey(key) ? values.get(key) : fallback; }
}
""")
    write(root / "src/android/content/SharedPreferences.java", """
package android.content;
public class SharedPreferences {
    private java.util.Map<String,Object> values = new java.util.HashMap<String,Object>();
    public String getString(String key, String fallback) { return values.containsKey(key) ? (String)values.get(key) : fallback; }
    public boolean getBoolean(String key, boolean fallback) { return values.containsKey(key) ? (Boolean)values.get(key) : fallback; }
    public Editor edit() { return new Editor(); }
    public class Editor {
        public Editor putString(String key, String value) { values.put(key,value); return this; }
        public Editor putBoolean(String key, boolean value) { values.put(key,value); return this; }
        public Editor clear() { values.clear(); return this; }
        public boolean commit() { return true; }
    }
}
""")

    write(root / "src/android/content/ContentResolver.java", """
package android.content;
public class ContentResolver {}
""")
    write(root / "src/android/content/Context.java", """
package android.content;
public class Context {
    public static final String CONNECTIVITY_SERVICE = "connectivity";
    public static final int MODE_PRIVATE = 0;
    private SharedPreferences prefs = new SharedPreferences();
    public SharedPreferences getSharedPreferences(String name, int mode) { return prefs; }
    public ContentResolver getContentResolver() { return new ContentResolver(); }
    public Object getSystemService(String name) { return null; }
}
""")
    write(root / "src/android/os/SystemClock.java", """
package android.os;
public class SystemClock { public static long elapsedRealtime() { return 1234; } }
""")
    write(root / "src/android/net/NetworkInfo.java", """
package android.net;
public class NetworkInfo { public boolean isConnected() { return false; } }
""")
    write(root / "src/android/net/ConnectivityManager.java", """
package android.net;
public class ConnectivityManager {
    public static final int TYPE_WIFI = 1;
    public NetworkInfo getNetworkInfo(int type) { return null; }
}
""")
    write(root / "src/android/provider/Settings.java", """
package android.provider;
import android.content.ContentResolver;
public final class Settings {
    public static final class System {
        public static int getInt(ContentResolver c, String k, int d) { return d; }
        public static String getString(ContentResolver c, String k) { return null; }
        public static boolean putInt(ContentResolver c, String k, int v) { return true; }
        public static boolean putLong(ContentResolver c, String k, long v) { return true; }
        public static boolean putString(ContentResolver c, String k, String v) { return true; }
    }
}
""")
    write(root / "src/com/android/phone/Harness.java", """
package com.android.phone;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;

public final class Harness {
    private static void check(boolean value, String message) throws Exception {
        if (!value) throw new Exception(message);
    }
    public static void main(String[] args) throws Exception {
        String token = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
        TelcoConfig.writeEnrollment(token, "3270", "https://example.invalid",
                "2026-10-06T05:00:48Z", true);
        Map<String, String> saved = TelcoConfig.read();
        check("1".equals(saved.get(TelcoConfig.KEY_MOBILE_DATA_ON_BOOT)), "toggle was not saved");
        check(token.equals(saved.get(TelcoConfig.KEY_TOKEN)), "token was not saved");
        check("3270".equals(saved.get(TelcoConfig.KEY_NUMBER)), "number was not saved");
        check("https://example.invalid".equals(saved.get(TelcoConfig.KEY_ENDPOINT)), "endpoint was not saved");
        check("2026-10-06T05:00:48Z".equals(saved.get(TelcoConfig.KEY_EXPIRES_AT)), "expiry was not saved");

        TelcoConfig.setMobileDataOnBoot(false);
        check("0".equals(TelcoConfig.read().get(TelcoConfig.KEY_MOBILE_DATA_ON_BOOT)), "disable was not durable");
        TelcoConfig.writeEnrollment(token, "3270", "https://example.invalid",
                "2026-10-06 05:00:48Z", true);
        check("2026-10-06 05:00:48Z".equals(TelcoConfig.read().get(TelcoConfig.KEY_EXPIRES_AT)),
                "server legacy expiry format must survive");
        try {
            TelcoConfig.writeEnrollment(token, "3270", "https://example.invalid",
                    "2026-10-06Z" + (char) 10 + "mobile_data_on_boot=0", true);
            throw new Exception("config injection accepted");
        } catch (java.io.IOException expected) { }

        Path config = Paths.get(TelcoConfig.REGISTRATION_CONFIG);
        byte[] malformed = ("broken-line" + (char) 10).getBytes(StandardCharsets.UTF_8);
        Files.write(config, malformed);
        try {
            TelcoConfig.setMobileDataOnBoot(true);
            throw new Exception("malformed config was overwritten");
        } catch (java.io.IOException expected) {
            check(java.util.Arrays.equals(malformed, Files.readAllBytes(config)),
                    "failed update clobbered malformed config");
        }
        Files.delete(config);
        Files.createDirectory(config); // simulate an unwritable registration-file target
        TelcoHttp http = new TelcoHttp(new android.content.Context());
        org.json.JSONObject response = new org.json.JSONObject().put("token", token)
                .put("number", "3270").put("expires_at", "2026-10-06 05:00:48Z");
        try {
            http.saveEnrollment(response);
            throw new Exception("SD save failure was hidden");
        } catch (TelcoHttp.Failure expected) {
            check("registration_storage_failed".equals(expected.code), "incorrect save error");
        }
        check(token.equals(http.token()), "issued token lost after SD save failure");
        Files.delete(config);
        http.persistPendingEnrollment();
        check(token.equals(TelcoConfig.read().get(TelcoConfig.KEY_TOKEN)), "retry did not save issued token");
        TelcoHttp restarted = new TelcoHttp(new android.content.Context());
        check(restarted.token() == null, "fresh private preferences expected");
        restarted.restoreFromConfig();
        check(token.equals(restarted.token()), "reboot restore lost token");
        System.out.println("telco_config_java: PASS (atomic persistence, toggle, non-clobber, failed-save retry, reboot restore)");
    }
}
""")

    sources = [str(path) for path in (root / "src").rglob("*.java")]
    compile_result = subprocess.run(
        ["javac", "-source", "1.7", "-target", "1.7", "-d", str(classes)] + sources,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if compile_result.returncode:
        raise SystemExit(compile_result.stderr)
    result = subprocess.run(["java", "-cp", str(classes), "com.android.phone.Harness"],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print(result.stdout.strip())
