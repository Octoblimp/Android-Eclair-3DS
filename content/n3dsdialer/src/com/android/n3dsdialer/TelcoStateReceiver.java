/*
 * N3DS_CALL_LOG_RECEIVER (#327): writes the call log Phone's TelcoService
 * reports on io.divergen.telco.action.CALL_LOG -- every outgoing, incoming,
 * missed and declined call, and every voicemail it downloads.
 *
 * Before #327 this listened to io.divergen.telco.action.STATE and rebuilt the
 * log from the call's transitions in static fields of this process. That
 * missed every call placed from anywhere but this app's own keypad, every
 * call whose events arrived while the dialer was not running, and every
 * missed call this phone never rang for -- and since TelcoService sends a
 * STATE broadcast on every 12 s poll, the manifest receiver also started the
 * dialer's process every 12 seconds just to ignore an "Online". Phone now
 * owns the call's lifecycle and says what to log, keyed by call id.
 *
 * The broadcast carries the io.divergen.telco.ACCESS signature permission and
 * this receiver requires it, so only the Phone package (same platform key)
 * can write here.
 */
package com.android.n3dsdialer;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

public final class TelcoStateReceiver extends BroadcastReceiver {
    static final String ACTION_CALL_LOG = "io.divergen.telco.action.CALL_LOG";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !ACTION_CALL_LOG.equals(intent.getAction())) return;
        String key = intent.getStringExtra("log_key");
        String peer = intent.getStringExtra("peer");
        int type = intent.getIntExtra("type", 0);
        if (type < ContactsStore.TYPE_INCOMING || type > ContactsStore.TYPE_REJECTED) return;
        try {
            ContactsStore.get(context.getApplicationContext()).recordCall(key, peer, type,
                    intent.getLongExtra("date", 0L), intent.getLongExtra("duration", 0L));
        } catch (Throwable t) {
            Log.w("N3dsDialerCallLog", "N3DS_DIALER_CALL_LOG_FAILED: key=" + key + " " + t);
        }
    }
}
