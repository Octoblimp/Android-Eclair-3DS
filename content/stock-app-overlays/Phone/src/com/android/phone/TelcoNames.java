/*
 * N3DS_TELCO_CONTACT_NAMES (#326): the name a call is shown under.
 *
 * Contacts live in N3dsDialer's own SQLite file, not in ContactsProvider
 * (the stock Contacts app is retired and nothing on this device writes the
 * real provider). The dialer keeps that file world-readable under
 * /data/shared/n3dsdialer/ precisely so another process can label numbers
 * with it, so the Phone process -- a different uid -- reads it directly,
 * read-only, with no locale collators (opening with collators writes the
 * android_metadata table, which a read-only handle cannot).
 *
 * A missing or unreadable file is not an error: the caller just shows the
 * number, which is what every call showed before this class existed.
 */
package com.android.phone;

import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.SystemClock;
import android.util.Log;

import java.io.File;

final class TelcoNames {
    private static final String TAG = "3DSTelco";
    private static final String DB = "/data/shared/n3dsdialer/n3dsdialer_shared.db";
    /** A call screen redraws every second; it must not reopen SQLite each time. */
    private static final long CACHE_MS = 5000;

    private static String cachedKey;
    private static String cachedName;
    private static long cachedAtMs;

    private TelcoNames() {}

    /** Same rule as N3dsDialer's ContactsStore.numberKey; keep them in sync. */
    static String numberKey(String number) {
        if (number == null) return "";
        StringBuilder digits = new StringBuilder(number.length());
        for (int i = 0; i < number.length(); i++) {
            char c = number.charAt(i);
            if (c >= '0' && c <= '9') digits.append(c);
        }
        if (digits.length() == 11 && digits.charAt(0) == '1') digits.deleteCharAt(0);
        return digits.toString();
    }

    /** The saved contact name for this number, or null. */
    static synchronized String lookup(String number) {
        String key = numberKey(number);
        if (key.length() == 0) return null;
        long now = SystemClock.elapsedRealtime();
        if (key.equals(cachedKey) && now - cachedAtMs < CACHE_MS) return cachedName;
        String name = query(key);
        cachedKey = key;
        cachedName = name;
        cachedAtMs = now;
        return name;
    }

    /** The contact name if one is saved, else the formatted number. */
    static String display(String number) {
        String name = lookup(number);
        return name != null ? name : formatNumber(number);
    }

    /** "(678) 009-3808" for a web number; 3DS numbers stay bare. */
    static String formatNumber(String number) {
        if (number == null) return "";
        String key = numberKey(number);
        if (key.length() == 10) {
            return "(" + key.substring(0, 3) + ") " + key.substring(3, 6) + "-" + key.substring(6);
        }
        return number;
    }

    private static String query(String key) {
        if (!new File(DB).canRead()) return null;
        SQLiteDatabase db = null;
        Cursor c = null;
        try {
            db = SQLiteDatabase.openDatabase(DB, null,
                    SQLiteDatabase.OPEN_READONLY | SQLiteDatabase.NO_LOCALIZED_COLLATORS);
            c = db.query("contacts", new String[] { "name", "number" },
                    null, null, null, null, null);
            while (c.moveToNext()) {
                if (key.equals(numberKey(c.getString(1)))) {
                    String name = c.getString(0);
                    if (name != null && name.trim().length() > 0) {
                        Log.i(TAG, "N3DS_TELCO_CONTACT_NAMES hit for " + key);
                        return name.trim();
                    }
                }
            }
            return null;
        } catch (Throwable t) {
            Log.w(TAG, "N3DS_TELCO_CONTACT_NAMES lookup failed: " + t);
            return null;
        } finally {
            if (c != null) c.close();
            if (db != null) db.close();
        }
    }
}
