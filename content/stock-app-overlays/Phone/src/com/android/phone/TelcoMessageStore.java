package com.android.phone;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.Telephony.Sms;
import android.util.Log;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/** Durable, credential-free 3DSTelco message journal and retry queue. */
final class TelcoMessageStore {
    static final String READY = "N3DS_TELCO_MESSAGE_JOURNAL_V1";
    static final String ROOT = "/sdcard/persistent/shared/messages";
    private static final String TAG = "TelcoMessageStore";
    private static final int MAX_RECORD_BYTES = 8192;
    private static final int MAX_RECORDS = 2048;
    private static TelcoMessageStore singleton;

    static final class Record {
        final File file;
        final JSONObject json;
        Record(File file, JSONObject json) { this.file = file; this.json = json; }
        String value(String name) { return json.optString(name, ""); }
        long number(String name) { return json.optLong(name, 0); }
        boolean flag(String name) { return json.optBoolean(name, false); }
    }

    private final Context context;
    private final File pending = new File(ROOT, "pending");
    private final File sent = new File(ROOT, "sent");
    private final File received = new File(ROOT, "received");

    private TelcoMessageStore(Context context) { this.context = context; }

    static synchronized TelcoMessageStore get(Context context) {
        if (singleton == null) singleton = new TelcoMessageStore(context.getApplicationContext());
        return singleton;
    }

    synchronized Record queue(String to, String body, String clientId) throws Exception {
        ensureDirectories();
        File file = new File(pending, safe(clientId) + ".json");
        Record existing = load(file);
        if (existing != null) return existing;
        JSONObject json = base("outgoing", to, body, System.currentTimeMillis());
        json.put("state", "pending");
        json.put("client_id", clientId);
        write(file, json);
        return read(file);
    }

    synchronized List<Record> pending() throws Exception {
        ensureDirectories();
        return records(pending);
    }

    synchronized boolean sentExists(long serverId) {
        return new File(sent, Long.toString(serverId) + ".json").isFile();
    }

    synchronized Record beginSent(Record queued, long serverId) throws Exception {
        ensureDirectories();
        File file = new File(sent, Long.toString(serverId) + ".json");
        Record archived = load(file);
        if (archived == null) {
            JSONObject json = queued.json;
            json.put("state", "sent");
            json.put("server_id", serverId);
            write(file, json);
            archived = read(file);
        }
        if (queued.file.isFile() && !queued.file.delete())
            throw new Exception("Unable to retire the delivered message retry record.");
        return archived;
    }

    synchronized Record beginIncoming(long serverId, String from, String body,
                                      long timestamp) throws Exception {
        ensureDirectories();
        File file = new File(received, Long.toString(serverId) + ".json");
        Record existing = load(file);
        if (existing != null) return existing;
        JSONObject json = base("incoming", from, body, timestamp);
        json.put("state", "archived");
        json.put("server_id", serverId);
        json.put("read", false);
        write(file, json);
        return read(file);
    }

    synchronized void completeSmsRow(Record record, Uri uri) throws Exception {
        record.json.put("sms_uri", uri == null ? "" : uri.toString());
        record.json.put("state", "stored");
        write(record.file, record.json);
    }

    synchronized void reconcileSmsRows() throws Exception {
        ensureDirectories();
        reconcile(records(received), true);
        reconcile(records(sent), false);
    }

    private void reconcile(List<Record> records, boolean inbox) throws Exception {
        ContentResolver resolver = context.getContentResolver();
        for (Record record : records) {
            String uriText = record.value("sms_uri");
            Cursor cursor = null;
            boolean exists = false;
            try {
                if (uriText.length() > 0) {
                    cursor = resolver.query(Uri.parse(uriText), new String[] {"read"},
                            null, null, null);
                    if (cursor != null && cursor.moveToFirst()) {
                        exists = true;
                        if (inbox && cursor.getInt(0) != 0 && !record.flag("read")) {
                            record.json.put("read", true);
                            write(record.file, record.json);
                        }
                    }
                }
            } catch (RuntimeException ignored) {
                exists = false;
            } finally {
                if (cursor != null) cursor.close();
            }
            if (!exists) {
                Uri restored = inbox
                        ? Sms.Inbox.addMessage(resolver, record.value("address"),
                                record.value("body"), null, record.number("timestamp"),
                                record.flag("read"))
                        : Sms.Sent.addMessage(resolver, record.value("address"),
                                record.value("body"), null, record.number("timestamp"));
                if (restored == null) throw new Exception("Unable to restore a journaled message.");
                completeSmsRow(record, restored);
            }
        }
        resolver.notifyChange(Sms.CONTENT_URI, null);
    }

    private static JSONObject base(String direction, String address, String body,
                                   long timestamp) throws Exception {
        JSONObject json = new JSONObject();
        json.put("version", 1);
        json.put("direction", direction);
        json.put("address", address);
        json.put("body", body);
        json.put("timestamp", timestamp);
        return json;
    }

    private void ensureDirectories() throws Exception {
        for (File directory : new File[] {new File(ROOT), pending, sent, received}) {
            if (!directory.isDirectory() && !directory.mkdirs() && !directory.isDirectory())
                throw new Exception("Unable to create " + directory.getAbsolutePath());
        }
    }

    // N3DS_TELCO_JOURNAL_QUARANTINE: the journal lives on a FAT card that is
    // routinely power-cut ("Volume was not properly unmounted"), so a record
    // can come back empty or torn.  One such record used to throw out of
    // records() and abort every poll with "Invalid message journal record
    // size: 1.json".  A bad record is now recovered from its .tmp when that
    // is intact, otherwise set aside as .corrupt, and the rest of the journal
    // carries on.  The server stays authoritative: a lost received record is
    // re-archived from the next event, a lost sent record is re-restored by
    // reconcile, so quarantine loses nothing the server cannot replay.
    private static List<Record> records(File directory) throws Exception {
        recoverTemporaries(directory);
        File[] files = directory.listFiles();
        if (files == null) return new ArrayList<Record>();
        Arrays.sort(files, new Comparator<File>() {
            public int compare(File left, File right) { return left.getName().compareTo(right.getName()); }
        });
        List<Record> result = new ArrayList<Record>();
        for (int i = 0; i < files.length && result.size() < MAX_RECORDS; i++) {
            if (files[i].isFile() && files[i].getName().endsWith(".json")) {
                Record record = load(files[i]);
                if (record != null) result.add(record);
            }
        }
        return result;
    }

    /** The record at file, or null when it is absent or had to be quarantined. */
    private static Record load(File file) {
        if (!file.isFile()) return null;
        try {
            return read(file);
        } catch (Exception error) {
            File temporary = new File(file.getParentFile(), file.getName() + ".tmp");
            if (temporary.isFile()) {
                try {
                    Record recovered = read(temporary);
                    if (temporary.renameTo(file)) {
                        Log.w(TAG, "N3DS_TELCO_JOURNAL_QUARANTINE recovered " + file.getName()
                                + " from its interrupted write");
                        return new Record(file, recovered.json);
                    }
                } catch (Exception ignored) {
                    // Torn as well; fall through and quarantine the record.
                }
            }
            quarantine(file, error);
            return null;
        }
    }

    private static void quarantine(File file, Exception reason) {
        boolean empty = file.length() <= 0;
        File aside = new File(file.getParentFile(), file.getName() + ".corrupt");
        boolean moved = !empty && !aside.exists() && file.renameTo(aside);
        if (!moved) file.delete();
        Log.w(TAG, "N3DS_TELCO_JOURNAL_QUARANTINE " + file.getAbsolutePath()
                + (moved ? " moved aside: " : " removed: ") + reason.getMessage());
    }

    /** Finish or discard the .tmp files a power cut left behind. */
    private static void recoverTemporaries(File directory) {
        File[] files = directory.listFiles();
        if (files == null) return;
        for (File temporary : files) {
            String name = temporary.getName();
            if (!temporary.isFile() || !name.endsWith(".json.tmp")) continue;
            File file = new File(directory, name.substring(0, name.length() - 4));
            if (file.isFile() && file.length() > 0) {
                temporary.delete();
                continue;
            }
            try {
                read(temporary);
                if (temporary.renameTo(file)) {
                    Log.w(TAG, "N3DS_TELCO_JOURNAL_QUARANTINE committed interrupted " + file.getName());
                    continue;
                }
            } catch (Exception ignored) {
                // Unusable; the delete below is all that is left to do.
            }
            temporary.delete();
        }
    }

    private static Record read(File file) throws Exception {
        if (file.length() <= 0 || file.length() > MAX_RECORD_BYTES)
            throw new Exception("Invalid message journal record size: " + file.getName());
        FileInputStream input = new FileInputStream(file);
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream((int) file.length());
            byte[] buffer = new byte[1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (output.size() + count > MAX_RECORD_BYTES)
                    throw new Exception("Message journal record exceeded its bound.");
                output.write(buffer, 0, count);
            }
            return new Record(file, new JSONObject(new String(output.toByteArray(), "UTF-8")));
        } finally { input.close(); }
    }

    private static void write(File file, JSONObject json) throws Exception {
        byte[] data = (json.toString() + "\n").getBytes("UTF-8");
        if (data.length > MAX_RECORD_BYTES) throw new Exception("Message journal record is too large.");
        File temporary = new File(file.getParentFile(), file.getName() + ".tmp");
        FileOutputStream output = new FileOutputStream(temporary);
        try {
            output.write(data);
            output.flush();
            output.getFD().sync();
        } finally { output.close(); }
        // N3DS_TELCO_JOURNAL_ATOMIC_RENAME: rename(2) replaces the target in
        // one step.  The old delete-then-rename left a window in which a power
        // cut lost the record outright or left a zero-length 1.json.
        if (temporary.renameTo(file)) return;
        if (file.exists() && !file.delete()) throw new Exception("Unable to replace " + file.getName());
        if (!temporary.renameTo(file)) throw new Exception("Unable to commit " + file.getName());
    }

    private static String safe(String value) throws Exception {
        if (value == null || !value.matches("[A-Za-z0-9_-]{8,80}"))
            throw new Exception("Invalid message journal identity.");
        return value;
    }
}
