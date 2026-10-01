/*
 * Persistent, shared (non-app-private) storage for N3dsDialer's contacts and
 * call history.
 *
 * ARCHITECTURE NOTE: this build's PackageManagerService/ActivityManagerService
 * do register <provider> tags (mProviders / resolveContentProvider exist and
 * are wired) and the stock ContactsProvider/CallLogProvider apk is present on
 * the image, but nothing in this tree has ever exercised the full
 * cross-process path -- AMS spawning a *dedicated* zygote-forked process to
 * *host* a provider, publishing it, and a second app resolving + binder
 * -transacting into that other process's IContentProvider. Every existing
 * ContentResolver caller here (Settings.System, Sms.*) only ever talks to
 * providers hosted inside system_server itself, which is a strictly easier
 * case. Given that gap, and this project's history of subtle boot-breaking
 * regressions from framework-level changes, this app deliberately does NOT
 * depend on ContactsProvider/CallLogProvider. Instead it keeps its own real
 * SQLiteDatabase (android.database.sqlite.SQLiteDatabase -- confirmed
 * present and working; see core.jar/Dalvik status in project notes) at an
 * explicit path OUTSIDE this app's private /data/data/com.android.n3dsdialer/
 * directory, so any future app can reach it without needing a running
 * ContentProvider process.
 *
 * PERSISTENCE: /data on this device is itself SD-card backed (mounted from
 * sd:/linux/android/data, not tmpfs -- see project notes on the FCRAM/data
 * layout), so anything under /data already survives a reboot. This class
 * additionally stores its database under /data/shared/n3dsdialer/ rather
 * than the app-private /data/data/com.android.n3dsdialer/databases/ that
 * SQLiteOpenHelper would otherwise pick, specifically so a future consumer
 * app does not need to be the same Linux uid as N3dsDialer to read it.
 *
 * N3DS_DIALER_STORE_PATH_FIX (2026-09-11): this class used to extend
 * SQLiteOpenHelper and pass the ABSOLUTE path above as the helper's "name"
 * argument. SQLiteOpenHelper forwards that straight to
 * Context.openOrCreateDatabase(), which is documented to take a bare file
 * name and rejects anything containing a separator. Every single call
 * therefore died with
 *     IllegalArgumentException: File /data/shared/n3dsdialer/
 *     n3dsdialer_shared.db contains a path separator
 * which is exactly the N3DS_DIALER_CALL_LOG_FAILED line in the hardware
 * captures, and is why the calls table has never held a single row. The fix
 * is to drop SQLiteOpenHelper entirely and open the database by File via
 * SQLiteDatabase.openOrCreateDatabase(File, CursorFactory), which has no such
 * restriction. Schema versioning is done here with PRAGMA user_version, the
 * same mechanism SQLiteOpenHelper itself uses.
 *
 * SHARING CAVEAT (be honest about what is proven): this app runs with
 * sharedUserId="android.uid.system", so installd should create it with the
 * same uid/gid as every other android.uid.system app, and /data itself is
 * normally group-writable by "system". The mkdir + FileUtils.setPermissions
 * calls below widen the shared directory/file to world rwx/rw as defense in
 * depth. Whether a *non-system* app can actually open this file has not
 * been exercised on hardware -- there is currently no second consumer app.
 * Only the storage location and its reboot-persistence are demonstrated.
 */
package com.android.n3dsdialer;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.os.FileUtils;
import android.util.Log;

import java.io.File;

final class ContactsStore {
    private static final String TAG = "N3dsDialerContacts";
    private static final int VERSION = 3;
    private static final String DB_FILE = "n3dsdialer_shared.db";

    private static final File SHARED_DIR = new File("/data/shared/n3dsdialer");

    // These match android.provider.CallLog.Calls deliberately, so a future
    // migration onto the real CallLogProvider does not have to renumber rows.
    // VOICEMAIL (4) and REJECTED (5) are the values later releases gave them.
    static final int TYPE_INCOMING = 1;
    static final int TYPE_OUTGOING = 2;
    static final int TYPE_MISSED = 3;
    static final int TYPE_VOICEMAIL = 4;
    static final int TYPE_REJECTED = 5;

    private static ContactsStore sInstance;

    private final SQLiteDatabase mDb;
    private final boolean mShared;

    static synchronized ContactsStore get(Context context) {
        if (sInstance == null) {
            sInstance = new ContactsStore(context.getApplicationContext());
        }
        return sInstance;
    }

    private ContactsStore(Context context) {
        File file = resolveFile(context);
        mShared = file.getAbsolutePath().startsWith(SHARED_DIR.getAbsolutePath());
        mDb = SQLiteDatabase.openOrCreateDatabase(file, null);
        createSchema(mDb);
        Log.i(TAG, "N3DS_DIALER_STORE_PATH " + file.getAbsolutePath()
                + " shared=" + mShared + " version=" + mDb.getVersion());
    }

    // Prefers the shared, world-reachable /data/shared/n3dsdialer path; if
    // that directory cannot be created or written (e.g. /data denies this
    // uid), falls back to this app's own private storage so the feature
    // still works (just not shared) instead of crashing the dialer.
    private static File resolveFile(Context context) {
        try {
            if (!SHARED_DIR.isDirectory() && !SHARED_DIR.mkdirs()) {
                throw new java.io.IOException("mkdirs failed: " + SHARED_DIR);
            }
            widenPermissions(SHARED_DIR, 0777);
            File db = new File(SHARED_DIR, DB_FILE);
            if (db.exists() || db.createNewFile()) {
                widenPermissions(db, 0666);
                return db;
            }
            throw new java.io.IOException("cannot create " + db);
        } catch (Throwable t) {
            Log.w(TAG, "N3DS_DIALER_SHARED_STORE_UNAVAILABLE, falling back to private storage: " + t);
            return new File(context.getDir("n3dsdialer_store", Context.MODE_PRIVATE), DB_FILE);
        }
    }

    private static void widenPermissions(File f, int mode) {
        try {
            FileUtils.setPermissions(f.getAbsolutePath(), mode, -1, -1);
        } catch (Throwable t) {
            // Best-effort only: android.os.FileUtils.setPermissions is a
            // native method; if it is not linked into this build's
            // libandroid_runtime, swallow it rather than crash the dialer.
            Log.w(TAG, "N3DS_DIALER_CHMOD_FAILED " + f + ": " + t);
        }
    }

    // Replaces SQLiteOpenHelper's onCreate/onUpgrade pair. Everything here is
    // IF NOT EXISTS / additive, so it is safe to run on every open, and
    // PRAGMA user_version (SQLiteDatabase.getVersion/setVersion) records which
    // migrations have already been applied.
    private static void createSchema(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE IF NOT EXISTS contacts (" +
                "_id INTEGER PRIMARY KEY AUTOINCREMENT," +
                "name TEXT NOT NULL," +
                "number TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS calls (" +
                "_id INTEGER PRIMARY KEY AUTOINCREMENT," +
                "number TEXT NOT NULL," +
                "name TEXT," +
                "call_type INTEGER NOT NULL," +
                "call_date INTEGER NOT NULL," +
                "duration INTEGER NOT NULL DEFAULT 0," +
                "new INTEGER NOT NULL DEFAULT 0," +
                "log_key TEXT)");

        int version = db.getVersion();
        if (version < 2) {
            // v1 shipped without duration/new. The CREATE above only fires on
            // a fresh file, so an existing v1 table needs the columns added.
            addColumnIfMissing(db, "calls", "duration", "INTEGER NOT NULL DEFAULT 0");
            addColumnIfMissing(db, "calls", "new", "INTEGER NOT NULL DEFAULT 0");
        }
        if (version < 3) {
            // v3 (#327): Phone's TelcoService writes the log, keyed by its
            // call id, so a call reported twice is still one row.
            addColumnIfMissing(db, "calls", "log_key", "TEXT");
        }
        db.execSQL("CREATE INDEX IF NOT EXISTS calls_log_key ON calls (log_key)");
        if (version != VERSION) {
            db.setVersion(VERSION);
        }
    }

    private static void addColumnIfMissing(SQLiteDatabase db, String table,
            String column, String decl) {
        try {
            db.execSQL("ALTER TABLE " + table + " ADD COLUMN " + column + " " + decl);
        } catch (Throwable t) {
            // "duplicate column name" is the expected outcome when the table
            // was already created at the current schema.
            Log.i(TAG, "N3DS_DIALER_SCHEMA_COLUMN_PRESENT " + table + "." + column + ": " + t);
        }
    }

    // ---- contacts ---------------------------------------------------

    /**
     * N3DS_CONTACTS_NUMBER_KEY (#326): the comparison key for a number.
     * Digits only, and a leading country code 1 dropped from an 11-digit
     * number, so "(678) 009-3808", "16780093808" and "6780093808" are one
     * contact. Phone's TelcoNames uses the same rule; keep them in sync.
     */
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

    long addContact(String name, String number) {
        ContentValues values = new ContentValues();
        values.put("name", name);
        values.put("number", number);
        return mDb.insert("contacts", null, values);
    }

    int updateContact(long id, String name, String number) {
        ContentValues values = new ContentValues();
        values.put("name", name);
        values.put("number", number);
        return mDb.update("contacts", values, "_id=?", new String[] { String.valueOf(id) });
    }

    int deleteContact(long id) {
        return mDb.delete("contacts", "_id=?", new String[] { String.valueOf(id) });
    }

    Cursor queryContacts() {
        return mDb.query("contacts",
                new String[] { "_id", "name", "number" },
                null, null, null, null, "name COLLATE NOCASE ASC");
    }

    /** The contact saved under this number, or -1. */
    long idForNumber(String number) {
        String key = numberKey(number);
        if (key.length() == 0) return -1;
        Cursor c = queryContacts();
        try {
            while (c.moveToNext()) {
                if (key.equals(numberKey(c.getString(2)))) return c.getLong(0);
            }
            return -1;
        } finally {
            c.close();
        }
    }

    String nameForNumber(String number) {
        String key = numberKey(number);
        if (key.length() == 0) return null;
        // The table is a handful of rows: scanning it with the normalised key
        // is simpler than storing a second, normalised column.
        Cursor c = queryContacts();
        try {
            while (c.moveToNext()) {
                if (key.equals(numberKey(c.getString(2)))) return c.getString(1);
            }
            return null;
        } finally {
            c.close();
        }
    }

    // ---- call history -------------------------------------------------

    long logCall(String number, String name, int type) {
        return logCall(number, name, type, 0L);
    }

    long logCall(String number, String name, int type, long durationSeconds) {
        ContentValues values = new ContentValues();
        values.put("number", number);
        values.put("name", name);
        values.put("call_type", type);
        values.put("call_date", System.currentTimeMillis());
        values.put("duration", durationSeconds);
        values.put("new", type == TYPE_MISSED ? 1 : 0);
        long id = mDb.insert("calls", null, values);
        Log.i(TAG, "N3DS_DIALER_CALL_LOGGED id=" + id + " number=" + number
                + " type=" + type + " duration=" + durationSeconds);
        return id;
    }

    /**
     * N3DS_CALL_LOG_UPSERT (#327): one row per call, however many times Phone
     * reports it. A call is first written when it starts (or, for a missed
     * one, when it is known to be missed) and rewritten when it ends; the row
     * keeps its first date, and only a newly inserted missed call or
     * voicemail counts as unseen.
     */
    long recordCall(String key, String number, int type, long dateMs, long durationSeconds) {
        if (key == null || key.length() == 0) {
            return logCall(number, null, type, durationSeconds);
        }
        Cursor c = mDb.query("calls", new String[] { "_id" }, "log_key=?",
                new String[] { key }, null, null, null);
        long id = -1;
        try {
            if (c.moveToFirst()) id = c.getLong(0);
        } finally {
            c.close();
        }
        ContentValues values = new ContentValues();
        values.put("number", number == null ? "" : number);
        values.put("call_type", type);
        values.put("duration", durationSeconds);
        if (id >= 0) {
            if (type != TYPE_MISSED && type != TYPE_VOICEMAIL) values.put("new", 0);
            mDb.update("calls", values, "_id=?", new String[] { String.valueOf(id) });
            Log.i(TAG, "N3DS_DIALER_CALL_UPDATED id=" + id + " key=" + key
                    + " type=" + type + " duration=" + durationSeconds);
            return id;
        }
        values.put("log_key", key);
        values.put("call_date", dateMs > 0 ? dateMs : System.currentTimeMillis());
        values.put("new", type == TYPE_MISSED || type == TYPE_VOICEMAIL ? 1 : 0);
        id = mDb.insert("calls", null, values);
        Log.i(TAG, "N3DS_DIALER_CALL_LOGGED id=" + id + " key=" + key + " number=" + number
                + " type=" + type + " duration=" + durationSeconds);
        return id;
    }

    Cursor queryCalls() {
        return mDb.query("calls",
                new String[] { "_id", "number", "name", "call_type", "call_date", "duration", "new" },
                null, null, null, null, "call_date DESC");
    }

    int countNewMissed() {
        Cursor c = mDb.rawQuery("SELECT COUNT(*) FROM calls WHERE new<>0", null);
        try {
            return c.moveToFirst() ? c.getInt(0) : 0;
        } finally {
            c.close();
        }
    }

    void markAllCallsSeen() {
        ContentValues values = new ContentValues();
        values.put("new", 0);
        mDb.update("calls", values, "new<>0", null);
    }

    int deleteCall(long id) {
        return mDb.delete("calls", "_id=?", new String[] { String.valueOf(id) });
    }

    int clearCalls() {
        return mDb.delete("calls", null, null);
    }
}
