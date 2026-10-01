/*
 * N3DS_TELCO_VOICEMAIL_LOCAL (#327): voicemail is saved on this 3DS, once.
 *
 * Every message is downloaded the first time this phone sees it and kept in
 * /sdcard/persistent/shared/voicemail -- on the SD card, not /data, which is
 * RAM here -- as <id>.pcm (the server's raw 8 kHz mono 16-bit audio) next to
 * <id>.json (who, when, how long, whether it was played). The mailbox screen
 * plays those files; nothing is fetched to listen.
 *
 * "Downloaded at least once, never pulled again" is two things:
 *  - the audio is requested only for an id with no complete local copy, and
 *  - the mailbox listing itself is asked only for ids above a cursor, which
 *    moves past a message once it is saved (or turned out to be empty). A
 *    message still "recording" holds the cursor back so it is seen again
 *    when it is ready; anything above it that is already saved is skipped.
 * A message deleted here leaves an <id>.deleted tombstone so that, should the
 * server-side delete not get through, the next listing does not bring it
 * back.
 *
 * The server finalizes a recording only when its owner lists the mailbox, so
 * TelcoService runs sync() on a timer as well as on "voicemail" events: that
 * listing is what turns a finished recording into a message at all.
 */
package com.android.phone;

import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

final class TelcoVoicemailStore {
    private static final String TAG = "TelcoVoicemail";
    static final File DIR = new File("/sdcard/persistent/shared/voicemail");
    static final String KEY_CURSOR = "voicemail_cursor";
    /** True while a message is still recording on the server. */
    static final String KEY_PENDING = "voicemail_pending";
    private static final Object LOCK = new Object();

    static final class Item {
        long id;
        String from;
        long createdAt;
        int durationMs;
        boolean read;
        File audio;
    }

    private TelcoVoicemailStore() {}

    /** Saved messages, newest first. */
    static List<Item> list() {
        List<Item> items = new ArrayList<Item>();
        synchronized (LOCK) {
            File[] files = DIR.listFiles();
            if (files == null) return items;
            for (File file : files) {
                String name = file.getName();
                if (!name.endsWith(".json")) continue;
                Item item = load(file);
                if (item != null) items.add(item);
            }
        }
        Collections.sort(items, new Comparator<Item>() {
            public int compare(Item a, Item b) {
                if (a.createdAt != b.createdAt) return a.createdAt > b.createdAt ? -1 : 1;
                return a.id > b.id ? -1 : (a.id < b.id ? 1 : 0);
            }
        });
        return items;
    }

    static int unreadCount() {
        int unread = 0;
        for (Item item : list()) if (!item.read) unread++;
        return unread;
    }

    static byte[] audio(Item item) throws IOException {
        File file = item.audio;
        long length = file.length();
        if (length <= 0 || length > 16L * 1024 * 1024) throw new IOException("Saved message is unreadable.");
        byte[] data = new byte[(int) length];
        FileInputStream in = new FileInputStream(file);
        try {
            int off = 0;
            while (off < data.length) {
                int n = in.read(data, off, data.length - off);
                if (n <= 0) break;
                off += n;
            }
            if (off != data.length) throw new IOException("Saved message is truncated.");
        } finally {
            in.close();
        }
        return data;
    }

    static void markRead(long id) {
        synchronized (LOCK) {
            File meta = new File(DIR, id + ".json");
            try {
                JSONObject json = new JSONObject(readText(meta));
                if (json.optBoolean("read", false)) return;
                json.put("read", true);
                writeAtomically(meta, json.toString().getBytes("UTF-8"));
            } catch (Exception error) {
                Log.w(TAG, "N3DS_TELCO_VOICEMAIL_MARK_READ_LOCAL_FAILED id=" + id + ": " + error);
            }
        }
    }

    static void delete(long id) {
        synchronized (LOCK) {
            try {
                new FileOutputStream(new File(DIR, id + ".deleted")).close();
            } catch (IOException error) {
                Log.w(TAG, "N3DS_TELCO_VOICEMAIL_TOMBSTONE_FAILED id=" + id + ": " + error);
            }
            new File(DIR, id + ".json").delete();
            new File(DIR, id + ".pcm").delete();
        }
    }

    /**
     * Saves every ready message not already on this 3DS. Returns the ones
     * saved by this call, so the caller can log and announce exactly those.
     */
    static List<Item> sync(TelcoHttp http, SharedPreferences state) throws Exception {
        synchronized (LOCK) {
            List<Item> saved = new ArrayList<Item>();
            long cursor = state.getLong(KEY_CURSOR, 0);
            JSONArray rows = http.request("GET", "/v1/voicemails?after=" + cursor, null, true)
                    .getJSONArray("voicemails");
            long next = cursor;
            boolean blocked = false;
            boolean pending = false;
            for (int i = 0; i < rows.length(); i++) {
                JSONObject row = rows.getJSONObject(i);
                long id = row.getLong("id");
                String status = row.isNull("status") ? "" : row.optString("status", "");
                boolean settled;
                if ("ready".equals(status)) {
                    settled = true;
                    if (!have(id)) {
                        try {
                            byte[] pcm = http.requestBinary("/v1/voicemails/" + id + "/audio");
                            saved.add(save(id, row, pcm));
                            Log.i(TAG, "N3DS_TELCO_VOICEMAIL_SAVED id=" + id + " bytes=" + pcm.length);
                        } catch (Exception error) {
                            // Leave it above the cursor and try again next sync.
                            Log.w(TAG, "N3DS_TELCO_VOICEMAIL_DOWNLOAD_FAILED id=" + id + ": " + error);
                            settled = false;
                        }
                    }
                } else if ("recording".equals(status)) {
                    settled = false;
                    pending = true;
                } else {
                    settled = true;     // "empty": the caller hung up at the tone
                }
                if (!settled) blocked = true;
                if (settled && !blocked) next = Math.max(next, id);
            }
            SharedPreferences.Editor edit = state.edit().putBoolean(KEY_PENDING, pending);
            if (next != cursor) edit.putLong(KEY_CURSOR, next);
            edit.commit();
            return saved;
        }
    }

    /** A complete local copy, or a tombstone: either way, never fetch it again. */
    private static boolean have(long id) {
        if (new File(DIR, id + ".deleted").exists()) return true;
        return new File(DIR, id + ".json").exists() && new File(DIR, id + ".pcm").exists();
    }

    private static Item save(long id, JSONObject row, byte[] pcm) throws Exception {
        if (!DIR.isDirectory() && !DIR.mkdirs()) throw new IOException("Cannot create " + DIR);
        // Audio first, metadata last: a .json is the "complete" marker.
        writeAtomically(new File(DIR, id + ".pcm"), pcm);
        JSONObject meta = new JSONObject();
        meta.put("id", id);
        meta.put("from", row.isNull("from") ? "" : row.optString("from", ""));
        long created = TelcoContract.parseUtc(row.isNull("created_at") ? null
                : row.optString("created_at", null));
        meta.put("created_at_ms", created > 0 ? created : System.currentTimeMillis());
        int durationMs = row.isNull("duration_ms") ? pcm.length / 16 : row.optInt("duration_ms", 0);
        meta.put("duration_ms", durationMs);
        meta.put("read", !row.isNull("read_at"));
        meta.put("saved_at_ms", System.currentTimeMillis());
        File file = new File(DIR, id + ".json");
        writeAtomically(file, meta.toString().getBytes("UTF-8"));
        return load(file);
    }

    private static Item load(File meta) {
        try {
            JSONObject json = new JSONObject(readText(meta));
            Item item = new Item();
            item.id = json.getLong("id");
            item.from = json.optString("from", "");
            item.createdAt = json.optLong("created_at_ms", meta.lastModified());
            item.durationMs = json.optInt("duration_ms", 0);
            item.read = json.optBoolean("read", false);
            item.audio = new File(DIR, item.id + ".pcm");
            return item.audio.exists() ? item : null;
        } catch (Exception unreadable) {
            Log.w(TAG, "N3DS_TELCO_VOICEMAIL_BAD_META " + meta + ": " + unreadable);
            return null;
        }
    }

    private static String readText(File file) throws IOException {
        byte[] data = new byte[(int) Math.min(file.length(), 65536)];
        FileInputStream in = new FileInputStream(file);
        try {
            int off = 0;
            while (off < data.length) {
                int n = in.read(data, off, data.length - off);
                if (n <= 0) break;
                off += n;
            }
            return new String(data, 0, off, "UTF-8");
        } finally {
            in.close();
        }
    }

    /** Written to a temporary name, synced, then renamed: never half a file. */
    private static void writeAtomically(File target, byte[] data) throws IOException {
        File tmp = new File(target.getPath() + ".tmp");
        FileOutputStream out = new FileOutputStream(tmp);
        try {
            out.write(data);
            out.getFD().sync();
        } finally {
            out.close();
        }
        if (!tmp.renameTo(target)) {
            // vfat will not rename over an existing file.
            target.delete();
            if (!tmp.renameTo(target)) throw new IOException("Cannot save " + target);
        }
    }
}
