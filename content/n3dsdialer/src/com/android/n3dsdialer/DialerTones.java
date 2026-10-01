/*
 * DTMF key tones for the 3DS dialer.
 *
 * HONEST FRAMING, same as the rest of this app: there is no radio here, so
 * these tones are never sent anywhere. A real handset plays a local tone AND
 * asks the RIL to put the tone on the line; this one only does the first
 * half, because the second half has nothing to talk to. That still matters --
 * the tone is the feedback that tells you the key registered, which on a
 * resistive touch panel is worth more than it is on a capacitive one.
 *
 * Everything here is best-effort and non-fatal by construction. ToneGenerator
 * is an AudioTrack on AudioFlinger's STREAM_DTMF, and on this device that is
 * one CSND channel driving both speakers; if mediaserver is not up yet the
 * constructor throws, and the dialer must keep working silently rather than
 * crash. The generator is also released on every pause instead of being held
 * for the process lifetime, for the same reason.
 */
package com.android.n3dsdialer;

import android.content.Context;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Handler;
import android.provider.Settings;
import android.util.Log;

final class DialerTones {
    private static final String TAG = "N3dsDialer";

    /*
     * 150 ms is what AOSP's own dialpad uses for local feedback. The ITU
     * minimum for a tone that has to survive a phone line is 70 ms of tone
     * plus 65 ms of silence, but nothing here is going down a line, so the
     * number that matters is the one that feels responsive.
     */
    private static final int KEY_TONE_MS = 150;
    private static final int SEQ_TONE_MS = 120;
    private static final int SEQ_GAP_MS = 80;

    /* 0-100, scaled against whatever the user has STREAM_DTMF set to. */
    private static final int VOLUME = 80;

    private final Context mContext;
    private final Handler mHandler = new Handler();

    private ToneGenerator mTone;
    private boolean mEnabled = true;
    private boolean mFailed;

    private String mSequence;
    private int mSequenceIndex;

    DialerTones(Context context) {
        mContext = context;
    }

    /**
     * Re-read the user setting. Called from onResume rather than per keypress:
     * Settings is a ContentProvider query, and a provider round trip on every
     * tap is measurable on this hardware.
     */
    void refresh() {
        try {
            mEnabled = Settings.System.getInt(mContext.getContentResolver(),
                    Settings.System.DTMF_TONE_WHEN_DIALING, 1) != 0;
        } catch (RuntimeException e) {
            // A missing or unreadable row is not a reason to be silent --
            // SettingsProvider inserts this default, so an exception here
            // means something much bigger is wrong than the dialpad.
            mEnabled = true;
        }
    }

    /** One tone for one key. Does nothing at all for a non-DTMF character. */
    void playDigit(char digit) {
        int tone = toneFor(digit);
        if (tone < 0) {
            return;
        }
        start(tone, KEY_TONE_MS);
    }

    /**
     * Play the number back as the call goes out, one tone per digit, the way
     * a handset does when it seizes the line. Bounded by construction: the
     * dialer caps entry at 4 digits, so this is at most ~800 ms.
     */
    void playNumber(String number) {
        stopSequence();
        if (!mEnabled || number == null || number.length() == 0) {
            return;
        }
        if (generator() == null) {
            return;
        }
        mSequence = number;
        mSequenceIndex = 0;
        mHandler.post(mStep);
    }

    /**
     * Drop the AudioTrack. Called from onPause -- a paused dialer has no
     * business holding an output open on a device with a single mixer
     * channel, and re-acquiring it costs one binder call.
     */
    void release() {
        stopSequence();
        if (mTone != null) {
            try {
                mTone.stopTone();
                mTone.release();
            } catch (RuntimeException e) {
                Log.w(TAG, "N3DS_DTMF_RELEASE_FAILED: " + e);
            }
            mTone = null;
        }
        // Clear the latch too, so a failure caused by mediaserver still
        // starting up does not silence the dialer for the rest of its life.
        mFailed = false;
    }

    // ------------------------------------------------------------------

    private final Runnable mStep = new Runnable() {
        public void run() {
            String seq = mSequence;
            if (seq == null || mSequenceIndex >= seq.length()) {
                mSequence = null;
                return;
            }
            char c = seq.charAt(mSequenceIndex++);
            int tone = toneFor(c);
            if (tone >= 0) {
                start(tone, SEQ_TONE_MS);
            }
            mHandler.postDelayed(this, SEQ_TONE_MS + SEQ_GAP_MS);
        }
    };

    private void stopSequence() {
        mHandler.removeCallbacks(mStep);
        mSequence = null;
        mSequenceIndex = 0;
    }

    private void start(int tone, int durationMs) {
        if (!mEnabled) {
            return;
        }
        ToneGenerator g = generator();
        if (g == null) {
            return;
        }
        try {
            // startTone(tone, durationMs) stops itself natively, so there is
            // no stopTone() timer to leak or to fire after the Activity dies.
            g.startTone(tone, durationMs);
        } catch (RuntimeException e) {
            Log.w(TAG, "N3DS_DTMF_START_FAILED: " + e);
        }
    }

    private ToneGenerator generator() {
        if (mTone != null) {
            return mTone;
        }
        if (mFailed) {
            return null;
        }
        try {
            mTone = new ToneGenerator(AudioManager.STREAM_DTMF, VOLUME);
        } catch (RuntimeException e) {
            // ToneGenerator's constructor throws when AudioFlinger will not
            // hand out an output. Latch it for this foreground stretch so a
            // dead audio path does not add a failed binder call to every
            // single tap; release() clears the latch on the next pause.
            mFailed = true;
            Log.w(TAG, "N3DS_DTMF_UNAVAILABLE: " + e);
        }
        return mTone;
    }

    private static int toneFor(char c) {
        if (c >= '0' && c <= '9') {
            return ToneGenerator.TONE_DTMF_0 + (c - '0');
        }
        if (c == '*') {
            return ToneGenerator.TONE_DTMF_S;
        }
        if (c == '#') {
            return ToneGenerator.TONE_DTMF_P;
        }
        return -1;
    }
}
