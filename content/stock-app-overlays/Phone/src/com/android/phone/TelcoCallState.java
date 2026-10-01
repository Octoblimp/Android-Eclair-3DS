package com.android.phone;

import android.os.SystemClock;

/**
 * N3DS_TELCO_CALL_STATE (#325): the one call this phone can be on, as
 * TelcoService last saw it.
 *
 * The call screen used to hold the only copy of the call's state, in its own
 * fields, kept current by a broadcast receiver it unregisters in onPause.  So
 * leaving the screen mid-call lost the call: nothing could reopen it (opening
 * it with no extras dialled a fresh call to nobody), and a hang-up that
 * arrived meanwhile was never seen.  TelcoService now records every
 * transition here, and the screen restores itself from it on every resume.
 *
 * TelcoService and TelcoCallActivity share the com.android.phone process,
 * so a static is the whole mechanism; an immutable snapshot in a volatile
 * field means no reader can see half an update.
 */
final class TelcoCallState {
    static final int NONE = 0;
    static final int DIALING = 1;
    static final int RINGING_IN = 2;
    static final int CONNECTED = 3;

    private static final TelcoCallState IDLE = new TelcoCallState(null, null, NONE, false, 0L, false);
    private static volatile TelcoCallState current = IDLE;

    final String callId;
    final String peer;
    final int phase;
    final boolean incoming;
    /** SystemClock.elapsedRealtime() when the call connected; 0 before. */
    final long connectedAtMs;
    final boolean muted;

    private TelcoCallState(String callId, String peer, int phase, boolean incoming,
            long connectedAtMs, boolean muted) {
        this.callId = callId;
        this.peer = peer;
        this.phase = phase;
        this.incoming = incoming;
        this.connectedAtMs = connectedAtMs;
        this.muted = muted;
    }

    static TelcoCallState current() { return current; }

    boolean active() { return phase != NONE; }

    static void dialing(String callId, String peer) {
        current = new TelcoCallState(callId, peer, DIALING, false, 0L, false);
    }

    static void ringing(String callId, String peer) {
        current = new TelcoCallState(callId, peer, RINGING_IN, true, 0L, false);
    }

    static void connected(String callId) {
        TelcoCallState was = current;
        String peer = was.peer;
        boolean incoming = was.incoming;
        if (callId != null && !callId.equals(was.callId)) {
            peer = null;
            incoming = false;
        }
        long at = was.phase == CONNECTED && was.connectedAtMs != 0L
                ? was.connectedAtMs : SystemClock.elapsedRealtime();
        current = new TelcoCallState(callId != null ? callId : was.callId, peer, CONNECTED,
                incoming, at, was.muted);
    }

    static void muted(boolean value) {
        TelcoCallState was = current;
        if (!was.active()) return;
        current = new TelcoCallState(was.callId, was.peer, was.phase, was.incoming,
                was.connectedAtMs, value);
    }

    /** Ends the current call -- only if it is the given one, when one is given. */
    static boolean clear(String callId) {
        TelcoCallState was = current;
        if (callId != null && was.callId != null && !callId.equals(was.callId)) return false;
        current = IDLE;
        return was.active();
    }
}
