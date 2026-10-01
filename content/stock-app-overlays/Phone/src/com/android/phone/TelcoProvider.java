package com.android.phone;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.provider.Telephony.Sms;

import org.json.JSONObject;

import java.util.UUID;

public final class TelcoProvider extends ContentProvider {
    private TelcoHttp http;
    private TelcoMessageStore messages;

    public boolean onCreate() {
        http = new TelcoHttp(getContext());
        messages = TelcoMessageStore.get(getContext());
        return true;
    }

    public Uri insert(Uri uri, ContentValues values) {
        if (!"messages".equals(first(uri))) throw new IllegalArgumentException("Unsupported 3DSTelco insert URI.");
        String to = values.getAsString("to");
        String body = values.getAsString("body");
        if (to != null) to = to.replaceAll("[^0-9]", "");
        // N3DS_TELCO_WEB_NUMBERS: 3DS (3-4), service (6) or web account (10) digits.
        if (to == null || !to.matches("(?:[1-9][0-9]{2,3}|[1-9][0-9]{5}|[2-9][0-9]{9})") || body == null || body.length() == 0) {
            throw new IllegalArgumentException("3DSTelco texts need a 3–4 digit 3DS, 6 digit service or 10 digit web number, and a body.");
        }
        try {
            if (body.getBytes("UTF-8").length > 1000) throw new IllegalArgumentException("3DSTelco text exceeds 1000 UTF-8 bytes.");
            String clientId = UUID.randomUUID().toString();
            TelcoMessageStore.Record queued = messages.queue(to, body, clientId);
            JSONObject request = new JSONObject();
            request.put("to", queued.value("address"));
            request.put("body", queued.value("body"));
            request.put("client_id", queued.value("client_id"));
            JSONObject message = http.request("POST", "/v1/messages", request, true).getJSONObject("message");
            long serverId = message.getLong("id");
            boolean alreadyArchived = messages.sentExists(serverId);
            TelcoMessageStore.Record archived = messages.beginSent(queued, serverId);
            // The server response is authoritative for a 3DSTelco send.  The
            // stock SMS provider is optional on this image; do not turn a
            // successful server POST into a client failure just because the
            // legacy carrier store is absent during migration.
            Uri sent = null;
            if (!alreadyArchived && getContext().getPackageManager().resolveContentProvider("sms", 0) != null) {
                try {
                    sent = Sms.Sent.addMessage(getContext().getContentResolver(), to, body, null,
                            System.currentTimeMillis());
                    if (sent != null) messages.completeSmsRow(archived, sent);
                    getContext().getContentResolver().notifyChange(Sms.CONTENT_URI, null);
                } catch (IllegalArgumentException error) {
                    android.util.Log.w("TelcoProvider",
                            "N3DS_TELCO_OPTIONAL_SMS_STORE unavailable after accepted send");
                }
            }
            return sent == null ? Uri.withAppendedPath(uri, Long.toString(serverId)) : sent;
        } catch (RuntimeException error) { throw error; }
        catch (Exception error) { throw new IllegalStateException(error.getMessage(), error); }
    }

    public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
        if (!"status".equals(first(uri))) throw new IllegalArgumentException("Unsupported 3DSTelco query URI.");
        MatrixCursor cursor = new MatrixCursor(new String[] {"enabled", "registered", "number", "status"});
        String status = android.provider.Settings.System.getString(getContext().getContentResolver(), TelcoContract.KEY_STATUS);
        cursor.addRow(new Object[] {TelcoContract.enabled(getContext()) ? 1 : 0, http.token() == null ? 0 : 1,
                http.number(), status == null ? "" : status});
        return cursor;
    }

    public int delete(Uri uri, String selection, String[] args) { return 0; }
    public int update(Uri uri, ContentValues values, String selection, String[] args) { return 0; }
    public String getType(Uri uri) { return "vnd.android.cursor.item/vnd.io.divergen.telco." + first(uri); }

    private static String first(Uri uri) {
        return uri.getPathSegments().size() == 0 ? "" : uri.getPathSegments().get(0);
    }
}
