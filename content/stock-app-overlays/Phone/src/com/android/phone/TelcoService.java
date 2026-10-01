package com.android.phone;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.IBinder;
import android.os.SystemClock;
import android.provider.Telephony.Sms;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.URI;
import java.util.UUID;

public final class TelcoService extends Service {
    private static final String TAG = "3DSTelco";
    private static final long POLL_MS = 12000;
    /*
     * N3DS_TELCO_CALL_WATCHDOG (#325): while a call is up the service polls
     * every 5 s and asks the server for the call's own status.  A hang-up the
     * relay never reported (no T3E1 reached us) and an event that was never
     * queued -- the server's voicemail path queues nothing to the callee --
     * both used to leave this phone on a call that no longer existed.
     */
    private static final long IN_CALL_POLL_MS = 5000;
    /*
     * N3DS_TELCO_ONGOING_NOTIFICATION (#325): the call's notification.  It is
     * the service's foreground notification, so it cannot be swiped away and
     * it keeps this process from being reclaimed mid-call; touching it reopens
     * the call screen, which is where the hang-up button is (Eclair
     * notifications cannot carry buttons of their own).
     */
    private static final int CALL_NOTIFICATION_ID = 21;
    private static final int MISSED_NOTIFICATION_ID = 22;
    private static final int VOICEMAIL_NOTIFICATION_ID = 23;
    /*
     * N3DS_TELCO_STALE_RING (#327): the event queue is durable, so a phone
     * that was off or out of Wi-Fi range when a call came in still receives
     * its incoming_call when it is back -- and used to ring for it, briefly,
     * until the call_ended right behind it hung the ghost up. An incoming
     * call now rings only if it is alive: queued less than FRESH_RING_MS ago
     * by the server's own clock, or confirmed still ringing by the server and
     * younger than STALE_RING_MS (a caller is sent to voicemail after 45 s).
     * Anything else is a missed call: logged, announced as "Missed call",
     * never put on screen.
     */
    private static final long FRESH_RING_MS = 15000;
    private static final long STALE_RING_MS = 45000;
    /** The server only finalizes a recording when its owner lists the mailbox. */
    private static final long VOICEMAIL_SYNC_MS = 60000;
    /** Call ids already given their final log row; bounded, oldest dropped. */
    private static final int LOGGED_CALLS_KEPT = 40;
    /** Read by com.android.n3dsdialer to offer the way back to the call. */
    static final String SETTING_CALL_ACTIVE = "n3ds_telco_call_active";
    /*
     * N3DS_TELCO_RINGBACK: how long an outgoing call rings before the caller
     * is offered the mailbox instead.  The callee polls every 12 s and the
     * server only queues the incoming_call event for a device it has heard
     * from inside the presence window, so this is three chances to pick up,
     * not three chances to be told the phone is ringing.
     */
    private static final long RING_TIMEOUT_MS = 45000;
    private static final String REGISTRATION_CONFIG =
            "/sdcard/persistent/shared/mobile_registration.conf";
    private final Object workerLock = new Object();
    private TelcoHttp http;
    private SharedPreferences state;
    private VoipSession voip;
    private TelcoMessageStore messages;
    private android.os.Handler main;
    private Runnable ringTimeout;
    private boolean foreground;
    private int shownPhase = TelcoCallState.NONE;
    private String shownCallId;
    /** Server clock minus this one, from /v1/status; see noteServerClock(). */
    private long serverSkewMs;
    private boolean serverSkewKnown;
    /** Calls a later event in the batch being processed ends or rejects. */
    private final java.util.HashSet<String> batchClosed = new java.util.HashSet<String>();
    /** When the event being processed was queued, on this phone's clock; 0 if unknown. */
    private long eventQueuedMs;
    private long lastVoicemailSyncMs;
    private boolean voicemailSyncWanted;

    public void onCreate() {
        super.onCreate();
        main = new android.os.Handler(getMainLooper());
        http = new TelcoHttp(this);
        state = getSharedPreferences("n3ds_telco_state", MODE_PRIVATE);
        messages = TelcoMessageStore.get(this);
        TelcoContract.clearLatency(this);
        // A fresh process holds no call: whatever the last one advertised died
        // with it, and a stale flag would send the dialer to a dead call.
        publishCallActive(null);
    }

    public int onStartCommand(final Intent intent, int flags, int startId) {
        new Thread(new Runnable() {
            public void run() {
                synchronized (workerLock) {
                    try { handle(intent == null ? TelcoContract.ACTION_POLL : intent.getAction(), intent); }
                    catch (Exception error) { report(error); }
                    finally { schedule(); }
                }
            }
        }, "3DSTelco-worker").start();
        return START_STICKY;
    }

    public IBinder onBind(Intent intent) { return null; }
    public void onDestroy() {
        TelcoAudio.get().stop();
        cancelRingTimeout();
        stopVoip();
        TelcoCallState.clear(null);
        callStateChanged();
        super.onDestroy();
    }

    private void handle(String action, Intent intent) throws Exception {
        if (TelcoContract.ACTION_ENROLL.equals(action)) enroll(extra(intent, "provisioning_code"));
        else if (TelcoContract.ACTION_CONFIG_CHANGED.equals(action)) configure(intent);
        else if (TelcoContract.ACTION_CALL.equals(action)) startCall(numberFrom(intent));
        else if (TelcoContract.ACTION_ANSWER.equals(action)) answer(extra(intent, "call_id"));
        else if (TelcoContract.ACTION_REJECT.equals(action)) transition(extra(intent, "call_id"), "reject");
        else if (TelcoContract.ACTION_END.equals(action)) transition(extra(intent, "call_id"), "end");
        else if (TelcoContract.ACTION_LEAVE_VOICEMAIL.equals(action)) leaveVoicemail(extra(intent, "call_id"));
        else if (TelcoContract.ACTION_MUTE.equals(action)) setMuted(intent != null
                && intent.getBooleanExtra("muted", false));
        else if (TelcoContract.ACTION_MISSED_SEEN.equals(action)) clearMissed();
        else if (TelcoContract.ACTION_SYNC_VOICEMAIL.equals(action)) syncVoicemail(true);
        else poll();
    }

    private void configure(Intent intent) throws Exception {
        String autoEnableValue = null;
        String setupCode = null;
        boolean endpointChanged = intent != null
                && intent.getBooleanExtra("endpoint_changed", false);
        if (new java.io.File(REGISTRATION_CONFIG).exists()) {
            java.util.Map<String, String> conf = TelcoConfig.read();
            autoEnableValue = conf.get(TelcoConfig.KEY_MOBILE_DATA_ON_BOOT);
            setupCode = conf.get(TelcoConfig.KEY_SETUP_CODE);
            // The durable endpoint is the source of truth after a reboot.
            // An explicit Settings endpoint change is handled below first.
            String configuredEndpoint = conf.get(TelcoConfig.KEY_ENDPOINT);
            if (!endpointChanged && configuredEndpoint != null) {
                android.provider.Settings.System.putString(getContentResolver(),
                        "n3ds_telco_endpoint", configuredEndpoint);
            }
        }

        // An endpoint change invalidates stored credentials: clear both the
        // app-private copy and the user-owned configuration file so the old
        // token cannot be rehydrated against a new server.
        if (endpointChanged) {
            http.clear();
            TelcoConfig.clearSetupCode();
            TelcoConfig.setEndpoint(TelcoContract.endpoint(this));
            setupCode = null;
        }

        // Persist the explicit Settings toggle as part of the same durable
        // registration file.  A value in that file is authoritative on boot,
        // including an explicit 0, so a user-disabled service stays disabled.
        if (intent != null && intent.getBooleanExtra("mobile_data_on_boot_set", false)) {
            boolean requested = intent.getBooleanExtra("mobile_data_on_boot", false);
            TelcoConfig.setMobileDataOnBoot(requested);
            autoEnableValue = requested ? "1" : "0";
        }
        if (autoEnableValue != null) {
            android.provider.Settings.System.putInt(getContentResolver(),
                    "n3ds_telco_enabled", "1".equals(autoEnableValue) ? 1 : 0);
        }

        // Durable registration: rehydrate credentials recorded in the
        // user-owned configuration file when the app-private store is empty.
        if (http.token() == null) http.restoreFromConfig();

        if (TelcoContract.enabled(this) && setupCode != null && setupCode.length() > 0 && http.token() == null) {
            enroll(setupCode);
            return;
        }

        if (!TelcoContract.enabled(this)) {
            TelcoContract.clearLatency(this);
            cancelSchedule();
            TelcoContract.publishStatus(this, "Mobile Data is off", http.number());
            sendState("Mobile Data is off", null);
            return;
        }
        poll();
    }

    private void enroll(String code) throws Exception {
        code = normalizeProvisioningCode(code);
        if (code == null || !code.matches("[A-Z0-9]{8,80}"))
            throw new Exception("Enter the one-time code from the 3DSTelco website.");
        WifiManager wifi = (WifiManager) getSystemService(WIFI_SERVICE);
        String mac = readDeviceMac(wifi);
        JSONObject request = new JSONObject();
        request.put("mac", mac);
        request.put("provisioning_code", code);
        JSONObject response = http.request("POST", "/v1/enroll", request, false);
        http.saveEnrollment(response);
        // A new enrollment replays the server's whole event window; calls
        // from before it are history, not missed calls (see recordMissed).
        state.edit().putLong("event_cursor", 0).putLong(TelcoVoicemailStore.KEY_CURSOR, 0)
                .putLong("enrolled_at_ms", System.currentTimeMillis()).commit();
        // saveEnrollment has already durably committed the token, number,
        // endpoint, expiry, and the enabled boot toggle.  Only poll is
        // allowed to claim online after an authenticated endpoint response.
        poll();
    }

    private String readDeviceMac(WifiManager wifi) throws Exception {
        WifiInfo info = wifi == null ? null : wifi.getConnectionInfo();
        String mac = info == null ? null : info.getMacAddress();
        if (!validMac(mac)) {
            java.io.BufferedReader reader = null;
            try {
                reader = new java.io.BufferedReader(
                        new java.io.FileReader("/sys/class/net/wlan0/address"));
                mac = reader.readLine();
            } catch (java.io.IOException ignored) {
                mac = null;
            } finally {
                if (reader != null) {
                    try { reader.close(); } catch (java.io.IOException ignored) { }
                }
            }
        }
        if (!validMac(mac)) {
            // Mobile Data is transported over Wi-Fi.  A boot-time enrollment
            // may run before wlan0 exists; request the dependency and let the
            // normal bounded poll retry after the driver publishes its MAC.
            if (wifi != null && !wifi.isWifiEnabled()) {
                wifi.setWifiEnabled(true);
            }
            throw new Exception("Waiting for Wi-Fi hardware before registration.");
        }
        return mac.trim().toLowerCase();
    }

    private static boolean validMac(String mac) {
        if (mac == null) return false;
        String normalized = mac.trim().toLowerCase();
        if (!normalized.matches("[0-9a-f]{2}(:[0-9a-f]{2}){5}")) return false;
        // Android commonly reports this privacy placeholder before the real
        // wlan0 interface is available.  It must never be sent to the server
        // as a device identity.  Keep other locally-administered unicast MACs.
        if ("00:00:00:00:00:00".equals(normalized)
                || "ff:ff:ff:ff:ff:ff".equals(normalized)
                || "02:00:00:00:00:00".equals(normalized)) return false;
        int first = Integer.parseInt(normalized.substring(0, 2), 16);
        return (first & 1) == 0;
    }

    private void poll() throws Exception {
        if (http.token() == null) http.restoreFromConfig();
        if (http.token() == null) {
            TelcoContract.clearLatency(this);
            TelcoContract.publishStatus(this, "Not registered — register the MAC on the website", null);
            notifyUser("3DSTelco registration required", "Register this 3DS MAC on the website, then enter its code in Settings.", null, 10);
            return;
        }
        long start = SystemClock.elapsedRealtime();
        http.persistPendingEnrollment();
        start = SystemClock.elapsedRealtime();
        JSONObject status = http.request("GET", "/v1/status", null, true);
        long latency = Math.max(0, SystemClock.elapsedRealtime() - start);
        TelcoContract.publishLatency(this, latency);
        noteServerClock(status, latency);
        messages.reconcileSmsRows();
        flushPendingMessages();
        JSONObject voipStatus = status.optJSONObject("voip");
        rememberVoip(voipStatus);
        boolean relayDown = voipStatus != null && "down".equals(voipStatus.optString("relay", ""));
        TelcoContract.publishStatus(this, relayDown ? "Online over Wi-Fi \u2014 call audio relay is offline"
                : "Online over Wi-Fi", status.optString("number", http.number()));
        long cursor = state.getLong("event_cursor", 0);
        JSONArray events = http.request("GET", "/v1/events?after=" + cursor, null, true).optJSONArray("events");
        if (events == null) throw new Exception("3DSTelco returned an invalid events response.");
        batchClosed.clear();
        for (int i = 0; i < events.length(); i++) {
            JSONObject event = events.getJSONObject(i);
            String type = event.optString("type", "");
            JSONObject payload = event.optJSONObject("payload");
            if (payload != null && !payload.isNull("call_id")
                    && ("call_ended".equals(type) || "call_rejected".equals(type))) {
                batchClosed.add(payload.optString("call_id", ""));
            }
        }
        try {
            for (int i = 0; i < events.length(); i++) {
                JSONObject event = events.getJSONObject(i);
                long queued = TelcoContract.parseUtc(event.isNull("created_at") ? null
                        : event.optString("created_at", null));
                eventQueuedMs = queued > 0 && serverSkewKnown ? queued - serverSkewMs : 0;
                processEvent(event.getString("type"), event.getJSONObject("payload"));
                cursor = Math.max(cursor, event.getLong("id"));
                state.edit().putLong("event_cursor", cursor).commit();
            }
        } finally {
            batchClosed.clear();
            eventQueuedMs = 0;
        }
        checkLiveCall();
        syncVoicemail(voicemailSyncWanted);
        sendState("Online", null);
    }

    /**
     * N3DS_TELCO_SERVER_CLOCK (#327): ages are measured on the server's clock,
     * never this one -- this phone's clock was wrong by hours until #327 and
     * may be again before NTP has answered. Second resolution is plenty.
     */
    private void noteServerClock(JSONObject status, long latencyMs) {
        long server = TelcoContract.parseUtc(status.isNull("server_time") ? null
                : status.optString("server_time", null));
        if (server <= 0) {
            serverSkewKnown = false;
            return;
        }
        serverSkewMs = server - (System.currentTimeMillis() - latencyMs / 2);
        serverSkewKnown = true;
    }

    /** How long ago, by the server's clock, a server timestamp was; -1 if unknown. */
    private long serverAge(long serverTimeMs) {
        if (serverTimeMs <= 0 || !serverSkewKnown) return -1;
        return Math.max(0, System.currentTimeMillis() + serverSkewMs - serverTimeMs);
    }

    /** A server timestamp on this phone's clock, for the call log. */
    private long localTime(long serverTimeMs) {
        if (serverTimeMs <= 0) return System.currentTimeMillis();
        return serverSkewKnown ? serverTimeMs - serverSkewMs : serverTimeMs;
    }

    private void processEvent(String type, JSONObject payload) throws Exception {
        if ("message".equals(type)) {
            String from = payload.getString("from");
            String body = payload.getString("body");
            if (getPackageManager().resolveContentProvider("sms", 0) == null)
                throw new Exception("Message storage unavailable; incoming text will be retried.");
            long messageId = payload.getLong("id");
            long timestamp = payload.optLong("created_at_ms", System.currentTimeMillis());
            TelcoMessageStore.Record archived = messages.beginIncoming(
                    messageId, from, body, timestamp);
            boolean firstNotification = !"stored".equals(archived.value("state"));
            if (firstNotification) {
                android.net.Uri stored = Sms.Inbox.addMessage(getContentResolver(), from, body,
                        null, timestamp, archived.flag("read"));
                if (stored == null) throw new Exception("Unable to save incoming text; delivery will be retried.");
                messages.completeSmsRow(archived, stored);
            }
            getContentResolver().notifyChange(Sms.CONTENT_URI, null);
            http.request("POST", "/v1/messages/" + payload.getLong("id") + "/delivered", new JSONObject(), true);
            if (firstNotification && !archived.flag("read")) {
                Intent open = new Intent("android.intent.action.MAIN");
                open.setClassName("com.android.mms", "com.android.mms.ui.ConversationList");
                notifyUser("Message from " + TelcoNames.display(from), body, open,
                        1000 + (int) (payload.getLong("id") % 100000));
            }
        } else if ("incoming_call".equals(type)) {
            String callId = payload.getString("call_id");
            String from = payload.getString("from");
            if (!ringable(callId, from)) return;
            TelcoCallState live = TelcoCallState.current();
            if (live.active() && !callId.equals(live.callId)) {
                // N3DS_TELCO_BUSY (#325): one call at a time.  Decline the new
                // one on the server and leave the live call's state alone.
                Log.i(TAG, "N3DS_TELCO_BUSY: declining " + callId + " during " + live.callId);
                try {
                    http.request("POST", "/v1/calls/" + callId + "/reject", new JSONObject(), true);
                } catch (Exception error) {
                    Log.w(TAG, "Could not decline a call that arrived mid-call", error);
                }
                recordMissed(callId, from, System.currentTimeMillis());
                return;
            }
            state.edit().putString("call_id", callId).putString("call_peer", from).commit();
            beginCallLog(callId, from, TelcoContract.LOG_INCOMING,
                    eventQueuedMs > 0 ? eventQueuedMs : System.currentTimeMillis());
            TelcoCallState.ringing(callId, from);
            callStateChanged();
            /*
             * N3DS_TELCO_INCOMING_TAKEOVER (#325): an incoming call takes the
             * screen, the way a handset's does -- the call screen shows over
             * whatever is running and over the keyguard, and BACK cannot
             * dismiss it; only Answer or Decline can.  The ongoing
             * notification stays as the way back if HOME is pressed anyway.
             */
            Intent open = new Intent(this, TelcoCallActivity.class);
            open.putExtra("call_id", callId);
            open.putExtra("peer", from);
            open.putExtra("incoming", true);
            open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try {
                startActivity(open);
            } catch (RuntimeException error) {
                Log.w(TAG, "Could not open the call screen for an incoming call", error);
            }
            TelcoAudio.get().startRingtone();
            sendState("Incoming call from " + TelcoNames.display(from), callId,
                    TelcoContract.EVENT_INCOMING, from);
        } else if ("call_answered".equals(type)) {
            String callId = payload.getString("call_id");
            if (!callId.equals(state.getString("call_id", null))) {
                // Answered after this phone already hung up on it, or for a
                // call it never placed: starting media for it would only
                // open a session to nobody.
                Log.w(TAG, "N3DS_TELCO_STALE_EVENT: call_answered for " + callId);
                return;
            }
            TelcoAudio.get().stop();
            cancelRingTimeout();
            rememberVoip(payload.optJSONObject("voip"));
            startVoip(callId, payload.getString("media_token"));
            TelcoCallState.connected(callId);
            callStateChanged();
            sendState(connectedMessage(), callId, TelcoContract.EVENT_CONNECTED, null);
        } else if ("call_rejected".equals(type) || "call_ended".equals(type)) {
            boolean rejected = "call_rejected".equals(type);
            String callId = payload.isNull("call_id") ? null : payload.optString("call_id", null);
            String current = state.getString("call_id", null);
            if (callId != null && !callId.equals(current)
                    && !callId.equals(TelcoCallState.current().callId)) {
                // N3DS_TELCO_STALE_EVENT (#325): the end of some earlier call
                // must not hang up the one that is live now. #327: nor ring
                // up a "Call ended" for a call this phone never had -- but a
                // call that ended while this phone was off is a missed call.
                Log.w(TAG, "N3DS_TELCO_STALE_EVENT: " + type + " for " + callId + " during " + current);
                TelcoCallState.clear(callId);
                if (!alreadyLogged(callId)) logUnseenCall(callId);
                return;
            }
            endLocally(callId, rejected);
        } else if ("voicemail".equals(type)) {
            // Saved, logged and announced by syncVoicemail() after this batch.
            voicemailSyncWanted = true;
        }
    }

    /**
     * N3DS_TELCO_STALE_RING: whether an incoming_call is a call to ring for
     * now. Not: it is recorded as missed (or, if it was answered before --
     * events replay after a reboot that lost the cursor -- as answered).
     */
    private boolean ringable(String callId, String from) {
        if (alreadyLogged(callId)) {
            Log.i(TAG, "N3DS_TELCO_STALE_RING: " + callId + " is already in the call log");
            return false;
        }
        long age = eventQueuedMs > 0 ? Math.max(0, System.currentTimeMillis() - eventQueuedMs) : -1;
        boolean closed = batchClosed.contains(callId);
        if (!closed && age >= 0 && age < FRESH_RING_MS) return true;

        // Older, undated, or already over: the server knows what became of it.
        JSONObject row = null;
        try {
            row = http.request("GET", "/v1/calls/" + callId, null, true).optJSONObject("call");
        } catch (TelcoHttp.Failure failure) {
            if ("call_not_found".equals(failure.code)) closed = true;
        } catch (Exception unreachable) {
            Log.w(TAG, "N3DS_TELCO_STALE_RING: could not check " + callId + ": " + unreachable);
        }
        String status = row == null || row.isNull("status") ? null : row.optString("status", null);
        long created = row == null || row.isNull("created_at") ? 0
                : TelcoContract.parseUtc(row.optString("created_at", null));
        long when = created > 0 ? localTime(created)
                : (eventQueuedMs > 0 ? eventQueuedMs : System.currentTimeMillis());
        if (row != null && !row.isNull("answered_at")) {
            long answered = TelcoContract.parseUtc(row.optString("answered_at", null));
            long ended = row.isNull("ended_at") ? 0 : TelcoContract.parseUtc(row.optString("ended_at", null));
            if (!"ringing".equals(status)) {
                Log.i(TAG, "N3DS_TELCO_STALE_RING: " + callId + " was answered; logging it");
                markLogged(callId);
                logCall(callId, from, TelcoContract.LOG_INCOMING, when,
                        ended > answered && answered > 0 ? (ended - answered) / 1000 : 0);
                return false;
            }
        }
        long serverAge = serverAge(created);
        if (serverAge >= 0) age = serverAge;
        String why = null;
        if (closed) why = "ended before this phone was told";
        else if (status != null && !"ringing".equals(status)) why = "is " + status + " on the server";
        else if (age > STALE_RING_MS) why = "rang " + (age / 1000) + " s ago";
        if (why == null) return true;
        Log.i(TAG, "N3DS_TELCO_STALE_RING: " + callId + " from " + from + " " + why);
        recordMissed(callId, from, when);
        return false;
    }

    /**
     * A call_ended for a call this phone never rang for: if it was a call to
     * this phone that nobody answered, it was missed while the phone was off
     * or out of range, and that belongs in the log.
     */
    private void logUnseenCall(String callId) {
        JSONObject row;
        try {
            row = http.request("GET", "/v1/calls/" + callId, null, true).optJSONObject("call");
        } catch (Exception unknown) {
            return;
        }
        if (row == null || !row.isNull("answered_at")) return;
        String from = row.isNull("from") ? null : row.optString("from", null);
        String to = row.isNull("to") ? null : row.optString("to", null);
        String me = http.number();
        if (to == null || me == null || !TelcoNames.numberKey(to).equals(TelcoNames.numberKey(me))) return;
        long created = row.isNull("created_at") ? 0 : TelcoContract.parseUtc(row.optString("created_at", null));
        Log.i(TAG, "N3DS_TELCO_UNSEEN_CALL: " + callId + " from " + from + " was missed");
        recordMissed(callId, from, localTime(created));
    }

    private void flushPendingMessages() throws Exception {
        java.util.List<TelcoMessageStore.Record> queued = messages.pending();
        for (TelcoMessageStore.Record record : queued) {
            JSONObject request = new JSONObject();
            request.put("to", record.value("address"));
            request.put("body", record.value("body"));
            request.put("client_id", record.value("client_id"));
            JSONObject response = http.request("POST", "/v1/messages", request, true);
            long serverId = response.getJSONObject("message").getLong("id");
            boolean alreadyArchived = messages.sentExists(serverId);
            TelcoMessageStore.Record archived = messages.beginSent(record, serverId);
            if (!alreadyArchived) {
                android.net.Uri stored = Sms.Sent.addMessage(getContentResolver(),
                        archived.value("address"), archived.value("body"), null,
                        archived.number("timestamp"));
                if (stored == null) throw new Exception("Unable to save a retried sent text.");
                messages.completeSmsRow(archived, stored);
                getContentResolver().notifyChange(Sms.CONTENT_URI, null);
            }
        }
    }

    private void startCall(String number) throws Exception {
        // N3DS_TELCO_WEB_NUMBERS: a 3DS (3-4 digits) or a web account (10).
        if (!number.matches("(?:[1-9][0-9]{2,3}|[2-9][0-9]{9})"))
            throw new Exception("Calls need a 3–4 digit 3DS number or a 10 digit web number.");
        JSONObject request = new JSONObject();
        String clientId = UUID.randomUUID().toString();
        request.put("to", number);
        request.put("client_id", clientId);
        long placedAt = System.currentTimeMillis();
        JSONObject call;
        try {
            call = http.request("POST", "/v1/calls", request, true).getJSONObject("call");
        } catch (Exception error) {
            // A call that never got through was still dialled; log it.
            logCall(clientId, number, TelcoContract.LOG_OUTGOING, placedAt, 0);
            throw error;
        }
        String callId = call.getString("id");
        state.edit().putString("call_id", callId).putString("call_peer", number).commit();
        beginCallLog(callId, number, TelcoContract.LOG_OUTGOING, placedAt);
        logCall(callId, number, TelcoContract.LOG_OUTGOING, placedAt, 0);
        TelcoCallState.dialing(callId, number);
        callStateChanged();
        sendState("Calling " + number + "…", callId,
                TelcoContract.EVENT_OUTGOING, number);
        /*
         * The server says whether the callee has been heard from recently
         * enough to be rung at all.  Older servers do not send the flag;
         * defaulting it to true keeps them behaving exactly as before rather
         * than sending every call straight to voicemail.
         */
        if (call.optBoolean("callee_available", true)) {
            TelcoAudio.get().startRingback();
            armRingTimeout(callId, number);
        } else {
            announceUnavailable(callId, number);
        }
    }

    /**
     * Tell the caller the number cannot be reached, then open a mailbox.
     *
     * The call row on the server is 'ringing' either way -- it is created
     * that way whether or not the callee is reachable, precisely so that it
     * can be converted into a recording slot -- so the ordinary voicemail
     * path takes it from here.  The announcement is a courtesy; the
     * recording happens even if not a note of it could be played.
     */
    private void announceUnavailable(final String callId, final String number) {
        TelcoAudio.get().stop();
        cancelRingTimeout();
        sendState(number + " is unavailable", callId,
                TelcoContract.EVENT_STATUS, number);
        TelcoAudio.get().announceUnavailable(number, new Runnable() {
            public void run() {
                synchronized (workerLock) {
                    try { leaveVoicemail(callId); }
                    catch (Exception error) { report(error); }
                }
            }
        });
    }

    /**
     * A call nobody picks up must not ring forever.  The timeout is posted to
     * the main looper because that is the only thread here that has one; the
     * work it starts goes straight back onto a worker, because it makes an
     * HTTP request and must not run on the UI thread.
     */
    private void armRingTimeout(final String callId, final String number) {
        cancelRingTimeout();
        ringTimeout = new Runnable() {
            public void run() {
                ringTimeout = null;
                // Answered, rejected or hung up in the meantime: every one of
                // those paths clears the stored call id.
                if (!callId.equals(state.getString("call_id", null))) return;
                new Thread(new Runnable() {
                    public void run() {
                        synchronized (workerLock) { announceUnavailable(callId, number); }
                    }
                }, "3DSTelco-ringout").start();
            }
        };
        main.postDelayed(ringTimeout, RING_TIMEOUT_MS);
    }

    private void cancelRingTimeout() {
        Runnable pending = ringTimeout;
        if (pending != null) {
            ringTimeout = null;
            main.removeCallbacks(pending);
        }
    }

    private void answer(String callId) throws Exception {
        TelcoAudio.get().stop();
        cancelRingTimeout();
        JSONObject response = http.request("POST", "/v1/calls/" + callId + "/answer", new JSONObject(), true);
        rememberVoip(response.optJSONObject("voip"));
        startVoip(callId, response.getString("media_token"));
        TelcoCallState.connected(callId);
        callStateChanged();
        if (callId.equals(state.getString("log_key", null))) {
            logCall(callId, state.getString("log_peer", null), TelcoContract.LOG_INCOMING,
                    state.getLong("log_date", System.currentTimeMillis()), 0);
        }
        sendState(connectedMessage(), callId, TelcoContract.EVENT_CONNECTED, null);
    }

    private void transition(String callId, String action) throws Exception {
        // Before the request, not after: a hang-up has to silence the ringback
        // immediately, and this call can take a whole round trip.
        TelcoAudio.get().stop();
        cancelRingTimeout();
        boolean rejected = "reject".equals(action);
        try {
            http.request("POST", "/v1/calls/" + callId + "/" + action, new JSONObject(), true);
        } finally {
            // Hang up locally even when the server cannot be told: a failed
            // request must not leave the microphone streaming and the call
            // notification up with no way to end either.
            String peer = state.getString("call_peer", null);
            TelcoCallState was = TelcoCallState.current();
            stopVoip();
            clearCall();
            TelcoCallState.clear(callId);
            callStateChanged();
            // Declining or hanging up a ringing call is this phone's choice,
            // not a miss.
            finishCallLog(callId, was, TelcoContract.LOG_REJECTED);
            sendState(rejected ? "Call rejected" : "Call ended", callId,
                    rejected ? TelcoContract.EVENT_REJECTED : TelcoContract.EVENT_ENDED, peer);
        }
    }

    /**
     * The other side (or the server) ended the call: silence it, stop the
     * media, drop the notification.  A call that was still ringing here when
     * it ended is a missed call, and says so.
     */
    private void endLocally(String callId, boolean rejected) {
        TelcoCallState was = TelcoCallState.current();
        TelcoAudio.get().stop();
        cancelRingTimeout();
        // clearCall() wipes call_peer, so read it before, not after.
        String peer = state.getString("call_peer", null);
        stopVoip();
        clearCall();
        TelcoCallState.clear(callId);
        callStateChanged();
        if (was.phase == TelcoCallState.RINGING_IN
                && (callId == null || callId.equals(was.callId))) {
            String key = state.getString("log_key", null);
            recordMissed(callId != null ? callId : (key != null ? key : was.callId),
                    peer != null ? peer : was.peer, state.getLong("log_date", 0L));
            clearCallLog();
        } else {
            finishCallLog(callId, was, TelcoContract.LOG_MISSED);
        }
        sendState(rejected ? "Call rejected" : "Call ended", callId,
                rejected ? TelcoContract.EVENT_REJECTED : TelcoContract.EVENT_ENDED, peer);
    }

    /** N3DS_TELCO_CALL_WATCHDOG: see IN_CALL_POLL_MS. */
    private void checkLiveCall() {
        TelcoCallState call = TelcoCallState.current();
        if (!call.active() || call.callId == null) return;
        String status;
        try {
            JSONObject row = http.request("GET", "/v1/calls/" + call.callId, null, true)
                    .optJSONObject("call");
            status = row == null || row.isNull("status") ? null : row.optString("status", null);
        } catch (TelcoHttp.Failure failure) {
            if (!"call_not_found".equals(failure.code)) return;
            status = "ended";
        } catch (Exception unreachable) {
            return;     // a network blip is not a hang-up
        }
        if (status == null || "ringing".equals(status) || "active".equals(status)) return;
        if (TelcoCallState.current() != call) return;   // moved on meanwhile
        Log.i(TAG, "N3DS_TELCO_CALL_WATCHDOG: " + call.callId + " is " + status + " on the server");
        endLocally(call.callId, "rejected".equals(status));
    }

    /**
     * The caller gave up on a ringing call, or was rejected: transition it
     * to 'missed' server-side and start a one-way media session that only
     * sends (VoipSession already tolerates never receiving T3A1 packets
     * back). The relay appends this call's audio to a recording file
     * instead of forwarding it to a peer, keyed by the fresh media token
     * the voicemail endpoint returns.
     */
    private void leaveVoicemail(String callId) throws Exception {
        JSONObject response = http.request("POST", "/v1/calls/" + callId + "/voicemail", new JSONObject(), true);
        rememberVoip(response.optJSONObject("voip"));
        String token = response.getString("media_token");
        final int maxSeconds = response.optInt("max_seconds", 60);
        // The outgoing row was written when the call was placed; that is all
        // there is to say about a call that went to the callee's mailbox.
        if (callId.equals(state.getString("log_key", null))) {
            markLogged(callId);
            clearCallLog();
        }
        clearCall();
        cancelRingTimeout();
        TelcoCallState.clear(callId);
        callStateChanged();
        /*
         * The tone the announcement promised, and the only cue the caller
         * gets that the microphone is live.  Played synchronously: it has to
         * finish before VoipSession opens the recorder, or the tone is the
         * first thing on the recording.
         */
        TelcoAudio.get().beepBlocking();
        startVoip(callId, token);
        sendState("Leaving voicemail…", null);
        final VoipSession session = voip;
        new android.os.Handler(getMainLooper()).postDelayed(new Runnable() {
            public void run() {
                if (voip == session) {
                    stopVoip();
                    sendState("Voicemail sent", null);
                    TelcoAudio.get().playSaved();
                }
            }
        }, maxSeconds * 1000L);
    }

    /*
     * Mute is deliberately not a no-op when there is no live session: the
     * in-call screen can be shown while the call is still ringing, and a mute
     * chosen then should simply be reported honestly rather than silently
     * pretending to have taken effect.
     */
    private void setMuted(boolean value) {
        VoipSession session = voip;
        if (session == null) {
            sendState("Microphone control needs a connected call", null);
            return;
        }
        session.setMuted(value);
        TelcoCallState.muted(value);
        sendState(value ? "Microphone muted" : "Microphone on", null);
    }

    /**
     * "Call connected", plus the truth about the microphone when there is
     * something to say.  The in-call screen shows this string verbatim, and
     * VoipSession now connects a call whose uplink it could not open rather
     * than throwing the whole session away -- so a call really can be live
     * and one-way, and saying nothing about it would read as a fault.
     */
    private String connectedMessage() {
        VoipSession session = voip;
        String fault = session == null ? null : session.uplinkFault();
        return fault == null ? "Call connected"
                             : "Call connected \u2014 no microphone (" + fault + ")";
    }

    private void startVoip(String callId, String token) throws Exception {
        stopVoip();
        voip = new VoipSession(mediaHost(), state.getInt("voip_port", 3478), token, new Runnable() {
            public void run() { pollNow(); }
        });
        voip.start();
        state.edit().putString("call_id", callId).commit();
    }

    /*
     * N3DS_TELCO_VOIP_HOST: where call audio goes. UDP cannot pass through
     * an HTTP proxy such as Cloudflare, so the server can name a separate
     * DNS-only media host ("voip": {"host": ...}) in /v1/status and in every
     * response that hands out a media token. With none, audio goes to the
     * API host, which must then not be proxied.
     */
    private void rememberVoip(JSONObject voipStatus) {
        SharedPreferences.Editor edit = state.edit();
        if (voipStatus == null) {
            edit.putInt("voip_port", 3478).remove("voip_host").commit();
            return;
        }
        int port = voipStatus.optInt("port", 3478);
        edit.putInt("voip_port", port > 0 && port < 65536 ? port : 3478);
        // optString() turns JSON null into the string "null" on this org.json.
        String host = voipStatus.isNull("host") ? null : voipStatus.optString("host", null);
        if (host != null && host.length() <= 253
                && host.matches("[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")) {
            edit.putString("voip_host", host.toLowerCase());
        } else {
            edit.remove("voip_host");
        }
        edit.commit();
    }

    private String mediaHost() throws Exception {
        String host = state.getString("voip_host", null);
        return host != null ? host : new URI(TelcoContract.endpoint(this)).getHost();
    }

    /*
     * N3DS_TELCO_T3E1: the relay says this call is over (the other side hung
     * up). Poll at once instead of at the next alarm, so the call_ended
     * event tears the call down within a second or two.
     */
    private void pollNow() {
        Intent intent = new Intent(this, TelcoService.class);
        intent.setAction(TelcoContract.ACTION_POLL);
        startService(intent);
    }

    private void stopVoip() { if (voip != null) { voip.stop(); voip = null; } }
    private void clearCall() { state.edit().remove("call_id").remove("call_peer").commit(); }

    private void schedule() {
        if (!TelcoContract.enabled(this)) { cancelSchedule(); return; }
        Intent intent = new Intent(this, TelcoService.class);
        intent.setAction(TelcoContract.ACTION_POLL);
        PendingIntent pending = PendingIntent.getService(this, 1, intent, PendingIntent.FLAG_UPDATE_CURRENT);
        AlarmManager alarms = (AlarmManager) getSystemService(ALARM_SERVICE);
        long delay = TelcoCallState.current().active() ? IN_CALL_POLL_MS : POLL_MS;
        if (alarms != null) alarms.set(AlarmManager.ELAPSED_REALTIME_WAKEUP, SystemClock.elapsedRealtime() + delay, pending);
    }

    private void cancelSchedule() {
        Intent intent = new Intent(this, TelcoService.class);
        intent.setAction(TelcoContract.ACTION_POLL);
        PendingIntent pending = PendingIntent.getService(this, 1, intent, PendingIntent.FLAG_UPDATE_CURRENT);
        AlarmManager alarms = (AlarmManager) getSystemService(ALARM_SERVICE);
        if (alarms != null) alarms.cancel(pending);
    }

    private void report(Exception error) {
        String message = error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage();
        TelcoContract.clearLatency(this);
        TelcoContract.publishStatus(this, message, http.number());
        if (error instanceof TelcoHttp.Failure) {
            String code = ((TelcoHttp.Failure) error).code;
            if ("not_enrolled".equals(code) || "device_not_registered".equals(code))
                notifyUser("3DSTelco registration required", message, null, 10);
        }
        sendState(message, null);
    }

    private static String normalizeProvisioningCode(String code) {
        if (code == null) return null;
        String value = code.trim();
        StringBuilder normalized = new StringBuilder(value.length());
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c != '-' && !Character.isWhitespace(c) && !Character.isSpaceChar(c)) normalized.append(c);
        }
        return normalized.toString().toUpperCase(java.util.Locale.US);
    }

    private void sendState(String message, String callId) {
        sendState(message, callId, TelcoContract.EVENT_STATUS, null);
    }

    /*
     * N3DS_TELCO_STATE_EXTRAS: every call transition also publishes a stable
     * event key and the peer number alongside the prose message, so consumers
     * (the in-call screen, and the dialer call log in com.android.n3dsdialer)
     * do not have to match on English text. See TelcoContract.EVENT_*.
     */
    private void sendState(String message, String callId, String event, String peer) {
        Intent intent = new Intent(TelcoContract.ACTION_STATE);
        intent.putExtra(TelcoContract.EXTRA_MESSAGE, message);
        if (callId != null) intent.putExtra(TelcoContract.EXTRA_CALL_ID, callId);
        if (event != null) intent.putExtra(TelcoContract.EXTRA_EVENT, event);
        // Fall back to the peer recorded when the call was set up: the server
        // does not repeat the number on every event.
        if (peer == null) peer = state.getString("call_peer", null);
        if (peer != null) intent.putExtra(TelcoContract.EXTRA_PEER, peer);
        sendBroadcast(intent, TelcoContract.ACCESS_PERMISSION);
    }

    /**
     * N3DS_TELCO_ONGOING_NOTIFICATION: puts the call's notification in line
     * with TelcoCallState.  The ticker scrolls only when the phase changes,
     * so a re-post after every poll does not re-announce the call.
     */
    private void callStateChanged() {
        TelcoCallState call = TelcoCallState.current();
        publishCallActive(call.active() ? call.callId : null);
        if (!call.active()) {
            if (foreground) {
                stopForeground(true);
                foreground = false;
            }
            shownPhase = TelcoCallState.NONE;
            shownCallId = null;
            return;
        }
        String peer = call.peer == null || call.peer.length() == 0 ? "3DSTelco"
                : TelcoNames.display(call.peer);
        String title;
        String text;
        if (call.phase == TelcoCallState.CONNECTED) {
            title = "Call in progress: " + peer;
            text = "Touch to return to the call or hang up";
        } else if (call.phase == TelcoCallState.RINGING_IN) {
            title = "Incoming call from " + peer;
            text = "Touch to answer or decline";
        } else {
            title = "Calling " + peer;
            text = "Touch to return to the call or hang up";
        }
        boolean changed = call.phase != shownPhase
                || (call.callId == null ? shownCallId != null : !call.callId.equals(shownCallId));
        long when = System.currentTimeMillis();
        if (call.connectedAtMs != 0L) when -= SystemClock.elapsedRealtime() - call.connectedAtMs;
        Notification notification = new Notification(android.R.drawable.stat_sys_phone_call,
                changed ? title : null, when);
        PendingIntent pending = PendingIntent.getActivity(this, CALL_NOTIFICATION_ID,
                TelcoCallActivity.showIntent(this), PendingIntent.FLAG_UPDATE_CURRENT);
        notification.setLatestEventInfo(this, title, text, pending);
        notification.flags |= Notification.FLAG_ONGOING_EVENT | Notification.FLAG_NO_CLEAR;
        try {
            startForeground(CALL_NOTIFICATION_ID, notification);
            foreground = true;
        } catch (RuntimeException error) {
            Log.w(TAG, "Could not post the call notification", error);
        }
        shownPhase = call.phase;
        shownCallId = call.callId;
    }

    private void publishCallActive(String callId) {
        try {
            android.provider.Settings.System.putString(getContentResolver(),
                    SETTING_CALL_ACTIVE, callId == null ? "" : callId);
        } catch (RuntimeException error) {
            Log.w(TAG, "Could not publish the call flag", error);
        }
    }

    // ---- N3DS_TELCO_CALL_LOG (#327) -------------------------------------------

    /** The live call's log row: what it is and when it started. */
    private void beginCallLog(String key, String peer, int type, long dateMs) {
        state.edit().putString("log_key", key).putString("log_peer", peer)
                .putInt("log_type", type).putLong("log_date", dateMs).commit();
    }

    private void clearCallLog() {
        state.edit().remove("log_key").remove("log_peer").remove("log_type").remove("log_date")
                .commit();
    }

    /**
     * The live call is over: write its final row. {@code was} is the call state
     * from just before it was cleared, for the duration; {@code unanswered} is
     * what an incoming call that never connected counts as.
     */
    private void finishCallLog(String callId, TelcoCallState was, int unanswered) {
        String key = state.getString("log_key", null);
        if (key == null || (callId != null && !callId.equals(key))) return;
        int type = state.getInt("log_type", TelcoContract.LOG_OUTGOING);
        String peer = state.getString("log_peer", null);
        long date = state.getLong("log_date", System.currentTimeMillis());
        boolean connected = was != null && key.equals(was.callId) && was.connectedAtMs != 0L;
        long seconds = connected ? (SystemClock.elapsedRealtime() - was.connectedAtMs) / 1000L : 0;
        if (type == TelcoContract.LOG_INCOMING && !connected) {
            clearCallLog();
            if (unanswered == TelcoContract.LOG_MISSED) {
                recordMissed(key, peer, date);
                return;
            }
            type = unanswered;
        }
        markLogged(key);
        logCall(key, peer, type, date, seconds);
        clearCallLog();
    }

    /** One call-log write, to com.android.n3dsdialer (TelcoStateReceiver). */
    private void logCall(String key, String peer, int type, long dateMs, long seconds) {
        Intent intent = new Intent(TelcoContract.ACTION_CALL_LOG);
        intent.putExtra("log_key", key);
        intent.putExtra("peer", peer == null ? "" : peer);
        intent.putExtra("type", type);
        intent.putExtra("date", dateMs);
        intent.putExtra("duration", Math.max(0L, seconds));
        sendBroadcast(intent, TelcoContract.ACCESS_PERMISSION);
        Log.i(TAG, "N3DS_TELCO_CALL_LOG key=" + key + " type=" + type + " duration=" + seconds);
    }

    private boolean alreadyLogged(String callId) {
        if (callId == null) return false;
        String logged = state.getString("logged_calls", "");
        return ("," + logged + ",").indexOf("," + callId + ",") >= 0;
    }

    private void markLogged(String callId) {
        if (callId == null || alreadyLogged(callId)) return;
        String logged = state.getString("logged_calls", "");
        String[] ids = logged.length() == 0 ? new String[0] : logged.split(",");
        StringBuilder kept = new StringBuilder(callId);
        for (int i = 0, n = 1; i < ids.length && n < LOGGED_CALLS_KEPT; i++, n++) {
            kept.append(',').append(ids[i]);
        }
        state.edit().putString("logged_calls", kept.toString()).commit();
    }

    /**
     * N3DS_TELCO_MISSED_CALLS (#327): a missed call is logged and counted into
     * one "Missed call" notification ("3 missed calls"), which opens Recents.
     * The count goes back to zero when Recents is looked at (the dialer sends
     * ACTION_MISSED_SEEN) or the notification is cleared.
     */
    private void recordMissed(String callId, String from, long whenMs) {
        if (alreadyLogged(callId)) return;
        markLogged(callId);
        long enrolled = state.getLong("enrolled_at_ms", 0L);
        if (whenMs > 0 && enrolled > 0 && whenMs < enrolled - 60000L) {
            Log.i(TAG, "N3DS_TELCO_MISSED_BEFORE_ENROLLMENT: " + callId);
            return;
        }
        long when = whenMs > 0 ? whenMs : System.currentTimeMillis();
        logCall(callId != null ? callId : "missed:" + when, from, TelcoContract.LOG_MISSED, when, 0);
        int count = state.getInt("missed_count", 0) + 1;
        state.edit().putInt("missed_count", count).commit();
        showMissed(count, from, when);
    }

    private void showMissed(int count, String from, long when) {
        String who = from == null || from.length() == 0 ? "an unknown number"
                : TelcoNames.display(from);
        Intent open = new Intent("android.intent.action.MAIN");
        open.setClassName("com.android.n3dsdialer", "com.android.n3dsdialer.N3dsDialerActivity");
        open.putExtra("n3ds_tab", "recents");
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pending = PendingIntent.getActivity(this, MISSED_NOTIFICATION_ID, open,
                PendingIntent.FLAG_UPDATE_CURRENT);
        Intent seen = new Intent(this, TelcoService.class);
        seen.setAction(TelcoContract.ACTION_MISSED_SEEN);
        Notification notification = new Notification(android.R.drawable.stat_notify_missed_call,
                "Missed call from " + who, when);
        notification.setLatestEventInfo(this, count == 1 ? "Missed call" : count + " missed calls",
                (count == 1 ? "From " : "Latest from ") + who, pending);
        notification.deleteIntent = PendingIntent.getService(this, MISSED_NOTIFICATION_ID, seen,
                PendingIntent.FLAG_UPDATE_CURRENT);
        if (count > 1) notification.number = count;
        notification.flags |= Notification.FLAG_AUTO_CANCEL;
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.notify(MISSED_NOTIFICATION_ID, notification);
    }

    private void clearMissed() {
        state.edit().putInt("missed_count", 0).commit();
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.cancel(MISSED_NOTIFICATION_ID);
    }

    /**
     * N3DS_TELCO_VOICEMAIL_LOCAL (#327): saves new voicemail on this 3DS (see
     * TelcoVoicemailStore), logs each message and announces it. Runs on the
     * first poll, on a "voicemail" event, every VOICEMAIL_SYNC_MS, and on
     * every poll while a message is still recording -- never mid-call.
     */
    private void syncVoicemail(boolean force) {
        voicemailSyncWanted = false;
        long now = SystemClock.elapsedRealtime();
        boolean due = force || lastVoicemailSyncMs == 0 || now - lastVoicemailSyncMs >= VOICEMAIL_SYNC_MS
                || state.getBoolean(TelcoVoicemailStore.KEY_PENDING, false);
        if (!due || TelcoCallState.current().active() || http.token() == null) return;
        lastVoicemailSyncMs = now;
        java.util.List<TelcoVoicemailStore.Item> saved;
        try {
            saved = TelcoVoicemailStore.sync(http, state);
        } catch (Exception error) {
            Log.w(TAG, "N3DS_TELCO_VOICEMAIL_SYNC_FAILED: " + error);
            return;
        }
        if (saved.isEmpty()) return;
        TelcoVoicemailStore.Item newest = null;
        for (TelcoVoicemailStore.Item item : saved) {
            logCall("vm:" + item.id, item.from, TelcoContract.LOG_VOICEMAIL, item.createdAt,
                    item.durationMs / 1000);
            if (!item.read && (newest == null || item.createdAt >= newest.createdAt)) newest = item;
        }
        if (newest != null) showVoicemail(newest);
    }

    private void showVoicemail(TelcoVoicemailStore.Item newest) {
        int unread = TelcoVoicemailStore.unreadCount();
        String who = newest.from == null || newest.from.length() == 0 ? "an unknown number"
                : TelcoNames.display(newest.from);
        Intent open = new Intent(this, VoicemailActivity.class);
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pending = PendingIntent.getActivity(this, VOICEMAIL_NOTIFICATION_ID, open,
                PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification = new Notification(android.R.drawable.stat_notify_voicemail,
                "Voicemail from " + who, newest.createdAt);
        notification.setLatestEventInfo(this,
                unread <= 1 ? "New voicemail" : unread + " new voicemails",
                "From " + who + " (" + TelcoTheme.duration(newest.durationMs / 1000)
                        + "), saved on this 3DS", pending);
        if (unread > 1) notification.number = unread;
        notification.flags |= Notification.FLAG_AUTO_CANCEL;
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.notify(VOICEMAIL_NOTIFICATION_ID, notification);
    }

    private void notifyUser(String title, String message, Intent open, int id) {
        // Not a bare TelcoCallActivity: opened with no extras, that dials.
        if (open == null) open = TelcoCallActivity.showIntent(this);
        PendingIntent pending = PendingIntent.getActivity(this, id, open, PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification = new Notification(android.R.drawable.stat_notify_more, title, System.currentTimeMillis());
        notification.setLatestEventInfo(this, title, message, pending);
        notification.flags |= Notification.FLAG_AUTO_CANCEL;
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.notify(id, notification);
    }

    private static String extra(Intent intent, String name) throws Exception {
        String value = intent == null ? null : intent.getStringExtra(name);
        if (value == null || value.length() == 0) throw new Exception("Missing " + name + ".");
        return value;
    }

    private static String numberFrom(Intent intent) throws Exception {
        String number = intent == null || intent.getData() == null ? null : intent.getData().getSchemeSpecificPart();
        if (number == null) number = extra(intent, "number");
        return number;
    }
}
