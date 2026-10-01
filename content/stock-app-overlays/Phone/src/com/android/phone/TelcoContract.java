package com.android.phone;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.SystemClock;
import android.provider.Settings;

import java.net.URI;

final class TelcoContract {
    static final String READY = "N3DS_TELCO_ORIGINAL_PHONE_READY";
    static final String DEFAULT_ENDPOINT = "https://3dstelco.divergen.io";
    static final String KEY_ENABLED = "n3ds_telco_enabled";
    static final String KEY_ENDPOINT = "n3ds_telco_endpoint";
    static final String KEY_STATUS = "n3ds_telco_status";
    static final String KEY_NUMBER = "n3ds_telco_number";
    // Authenticated /v1/status round-trip duration.  This measures service
    // reachability over the configured Wi-Fi transport; it is not radio RSSI.
    static final String KEY_LATENCY_MS = "n3ds_telco_latency_ms";
    static final String KEY_LATENCY_SAMPLE = "n3ds_telco_latency_sample_elapsed_ms";
    static final String AUTHORITY = "io.divergen.telco";
    static final String ACCESS_PERMISSION = "io.divergen.telco.ACCESS";
    static final String ACTION_ENROLL = "io.divergen.telco.action.ENROLL";
    static final String ACTION_CONFIG_CHANGED = "io.divergen.telco.action.CONFIG_CHANGED";
    static final String ACTION_POLL = "io.divergen.telco.action.POLL";
    static final String ACTION_CALL = "io.divergen.telco.action.CALL";
    static final String ACTION_ANSWER = "io.divergen.telco.action.ANSWER";
    static final String ACTION_REJECT = "io.divergen.telco.action.REJECT";
    static final String ACTION_END = "io.divergen.telco.action.END";
    static final String ACTION_STATE = "io.divergen.telco.action.STATE";
    static final String ACTION_LEAVE_VOICEMAIL = "io.divergen.telco.action.LEAVE_VOICEMAIL";
    /** Toggle the microphone on the live VoIP session; extra "muted" boolean. */
    static final String ACTION_MUTE = "io.divergen.telco.action.MUTE";
    // Fixed device-range number the dialer recognizes and routes straight to
    // VoicemailActivity instead of placing a call -- "same number for
    // everyone, only your own mailbox" is enforced server-side by scoping
    // every /v1/voicemails request to the authenticated device's own number.
    static final String VOICEMAIL_NUMBER = "100";

    /*
     * N3DS_TELCO_STATE_EXTRAS (2026-09-11): ACTION_STATE used to carry only a
     * human-readable "message" string, so anything that wanted to react to a
     * call transition had to substring-match English prose. That is brittle
     * and it is why the dialer had no incoming/missed call log at all.
     *
     * The broadcast now also carries a stable EXTRA_EVENT (one of the EVENT_*
     * values below) and, where known, EXTRA_PEER (the other party's number).
     * The prose message is unchanged and is still what the in-call screen
     * displays -- these are additions, not a replacement.
     */
    static final String EXTRA_MESSAGE = "message";
    static final String EXTRA_CALL_ID = "call_id";
    static final String EXTRA_EVENT = "event";
    static final String EXTRA_PEER = "peer";

    /** An outgoing call was accepted by the server and is now ringing. */
    static final String EVENT_OUTGOING = "outgoing";
    /** A call is ringing in. */
    static final String EVENT_INCOMING = "incoming";
    /** Media is flowing in both directions. */
    static final String EVENT_CONNECTED = "connected";
    /** The call finished after having connected, or was hung up while ringing. */
    static final String EVENT_ENDED = "ended";
    /** The call was refused by either side before connecting. */
    static final String EVENT_REJECTED = "rejected";
    /** A status line with no call attached (Online, an error, voicemail). */
    static final String EVENT_STATUS = "status";

    /*
     * N3DS_TELCO_CALL_LOG (#327): one broadcast per call-log write, received
     * by com.android.n3dsdialer, which keeps the log. Extras: "log_key" (the
     * call id, or "vm:<id>" for a voicemail), "peer", "type" (LOG_*), "date"
     * (ms, when the call started) and "duration" (seconds). The same key may
     * be sent again as a call progresses; the dialer keeps one row per key.
     */
    static final String ACTION_CALL_LOG = "io.divergen.telco.action.CALL_LOG";
    /** android.provider.CallLog.Calls values, plus the two later releases added. */
    static final int LOG_INCOMING = 1;
    static final int LOG_OUTGOING = 2;
    static final int LOG_MISSED = 3;
    static final int LOG_VOICEMAIL = 4;
    static final int LOG_REJECTED = 5;
    /** From the dialer: Recents has been looked at, so drop the missed-call count. */
    static final String ACTION_MISSED_SEEN = "io.divergen.telco.action.MISSED_SEEN";
    /** Fetch any voicemail not yet saved on this 3DS. */
    static final String ACTION_SYNC_VOICEMAIL = "io.divergen.telco.action.SYNC_VOICEMAIL";

    private TelcoContract() {}

    /** Server timestamps are "YYYY-MM-DDTHH:MM:SSZ" (UTC); 0 if absent or unreadable. */
    static long parseUtc(String value) {
        if (value == null || value.length() < 19 || "null".equals(value)) return 0L;
        try {
            java.util.Calendar c = java.util.Calendar.getInstance(java.util.TimeZone.getTimeZone("UTC"));
            c.clear();
            c.set(Integer.parseInt(value.substring(0, 4)), Integer.parseInt(value.substring(5, 7)) - 1,
                    Integer.parseInt(value.substring(8, 10)), Integer.parseInt(value.substring(11, 13)),
                    Integer.parseInt(value.substring(14, 16)), Integer.parseInt(value.substring(17, 19)));
            return c.getTimeInMillis();
        } catch (RuntimeException unreadable) {
            return 0L;
        }
    }

    static boolean enabled(Context context) {
        return Settings.System.getInt(context.getContentResolver(), KEY_ENABLED, 0) == 1;
    }

    static String endpoint(Context context) {
        String value = Settings.System.getString(context.getContentResolver(), KEY_ENDPOINT);
        if (!validEndpoint(value)) value = DEFAULT_ENDPOINT;
        while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
        return value;
    }

    static boolean validEndpoint(String value) {
        if (value == null || value.length() > 512) return false;
        try {
            URI uri = new URI(value.trim());
            return "https".equalsIgnoreCase(uri.getScheme()) && uri.getHost() != null
                    && uri.getHost().length() > 0 && uri.getUserInfo() == null
                    && uri.getQuery() == null && uri.getFragment() == null;
        } catch (Exception ignored) { return false; }
    }

    static boolean wifiConnected(Context context) {
        ConnectivityManager manager = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        NetworkInfo wifi = manager == null ? null : manager.getNetworkInfo(ConnectivityManager.TYPE_WIFI);
        return wifi != null && wifi.isConnected();
    }

    static void publishStatus(Context context, String status, String number) {
        Settings.System.putString(context.getContentResolver(), KEY_STATUS, status);
        Settings.System.putString(context.getContentResolver(), KEY_NUMBER, number);
    }

    static void publishLatency(Context context, long latencyMs) {
        if (latencyMs < 0 || latencyMs > Integer.MAX_VALUE) {
            clearLatency(context);
        } else {
            Settings.System.putLong(context.getContentResolver(), KEY_LATENCY_MS, latencyMs);
            Settings.System.putLong(context.getContentResolver(), KEY_LATENCY_SAMPLE,
                    SystemClock.elapsedRealtime());
        }
    }

    static void clearLatency(Context context) {
        Settings.System.putString(context.getContentResolver(), KEY_LATENCY_MS, null);
        Settings.System.putString(context.getContentResolver(), KEY_LATENCY_SAMPLE, null);
    }
}
