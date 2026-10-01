package com.android.providers.telephony;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import java.io.File;

/** Runs the original provider schema and triggers on the ARM SQLite/JNI stack. */
public final class TelephonyProviderSmoke {
    private static void require(boolean condition, String label) {
        if (!condition) throw new AssertionError(label);
    }
    private static long scalar(SQLiteDatabase db, String query) {
        Cursor cursor = db.rawQuery(query, null);
        try { require(cursor.moveToFirst(), "missing result"); return cursor.getLong(0); }
        finally { cursor.close(); }
    }
    public static void main(String[] args) {
        String path = "/data/telephony-provider-smoke.db";
        new File(path).delete();
        SQLiteDatabase db = SQLiteDatabase.openOrCreateDatabase(path, null);
        MmsSmsDatabaseHelper.getInstance(null).onCreate(db);
        db.execSQL("INSERT INTO canonical_addresses(_id,address) VALUES(1,'4321')");
        db.execSQL("INSERT INTO threads(_id,recipient_ids) VALUES(1,'1')");
        ContentValues inbox = new ContentValues();
        inbox.put("thread_id", 1); inbox.put("address", "4321");
        inbox.put("body", "fixture incoming"); inbox.put("date", 1000L);
        inbox.put("type", 1); inbox.put("read", 0);
        require(db.insertOrThrow("sms", null, inbox) > 0, "inbox insertion");
        ContentValues sent = new ContentValues(inbox);
        sent.put("body", "fixture outgoing"); sent.put("type", 2); sent.put("read", 1);
        require(db.insertOrThrow("sms", null, sent) > 0, "sent insertion");
        require(scalar(db, "SELECT message_count FROM threads WHERE _id=1") == 2,
                "thread counter trigger");
        require(scalar(db, "SELECT read FROM threads WHERE _id=1") == 0,
                "unread thread trigger");
        ContentValues queued = new ContentValues(sent); queued.put("type", 4);
        db.insertOrThrow("sms", null, queued);
        ContentValues recovery = new ContentValues(); recovery.put("type", 6);
        require(db.update("sms", recovery, "type=4", null) == 1, "boot outbox recovery");
        require(db.update("sms", recovery, "type=4", null) == 0, "boot recovery repeat");
        db.close();
        db = SQLiteDatabase.openOrCreateDatabase(path, null);
        require(scalar(db, "SELECT count(*) FROM sms") == 3, "stored messages survive reopen");
        require(scalar(db, "SELECT count(*) FROM sms WHERE type=6") == 1,
                "queue survives reopen");
        db.close();
        System.out.println("PASS: TelephonyProvider ARM schema, SMS storage, triggers, boot recovery and reopen");
        System.exit(0);
    }
}
