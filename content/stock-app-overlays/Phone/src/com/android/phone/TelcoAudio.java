package com.android.phone;

import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * The sounds a call makes: ringback while the far end rings, the spoken
 * "the caller N is unavailable" announcement, and the record tone.
 *
 * Everything here is AudioTrack and arithmetic, deliberately.
 *
 *   - ToneGenerator's JNI is registered in this build, but its native backend
 *     synthesises against a table of region tone descriptors this image has
 *     never exercised.  Two sine waves summed in a float loop is a dozen lines
 *     and cannot fail differently on hardware than it does in review.
 *   - There is no TTS engine: Eclair's pico/SVOX is not built.  The sentence
 *     is assembled from clips that scripts/build_audio_assets.sh synthesises
 *     with espeak-ng at build time, one per digit, so every 3- and 4-digit
 *     subscriber number reads out without shipping a synthesiser.
 *
 * STREAM_MUSIC, not STREAM_VOICE_CALL: this plays before any call is
 * connected, and the music stream is the one whose volume this image actually
 * initialises.  VoipSession keeps STREAM_VOICE_CALL for connected audio.
 *
 * One sound plays at a time.  Every job takes a generation number on the way
 * in, and both the ringback loop and the clip writer stop the moment a newer
 * job appears, so starting a sound is also how you cancel the previous one --
 * a call that is answered mid-ring never has to race its own ringback.
 */
final class TelcoAudio {
    private static final String TAG = "3DSTelcoAudio";

    /** Where scripts/build_audio_assets.sh puts the espeak-ng clips. */
    private static final String CLIPS = "/system/media/audio/telco/";

    /** Matches the clips, and is what the CSND driver resamples best from. */
    private static final int RATE = 22050;
    private static final int STREAM = AudioManager.STREAM_MUSIC;

    /** Precise-tone ringback: 440 + 480 Hz, two seconds on, four off. */
    private static final int RINGBACK_ON_MS = 2000;
    private static final int RINGBACK_OFF_MS = 4000;

    /** The record tone the announcement promises. */
    private static final int BEEP_HZ = 1000;
    private static final int BEEP_MS = 400;

    /*
     * N3DS_TELCO_RINGTONE (#325): an incoming call rings with the stock
     * Android 2 default ringtone.  Ringtone.play() is not an option here --
     * this build runs no AudioService, so every AudioManager call it makes
     * throws -- so the WAV that build_audio_assets.sh transcodes is looped
     * through an AudioTrack at its own sample rate, like every other sound.
     */
    private static final String RINGTONE = "/system/media/audio/ringtones/Ring_Synth_04.wav";

    /** True while startRingtone()'s loop owns the speaker. */
    private static volatile boolean ringing;

    private static TelcoAudio instance;

    private final Object lock = new Object();
    private int generation;

    private TelcoAudio() {
    }

    static synchronized TelcoAudio get() {
        if (instance == null) {
            instance = new TelcoAudio();
        }
        return instance;
    }

    // ------------------------------------------------------------------ api

    /** Ring until something else plays or {@link #stop()} is called. */
    void startRingback() {
        final int gen = begin();
        start("3DSTelco-ringback", new Runnable() {
            public void run() {
                ringback(gen);
            }
        });
    }

    /**
     * "The caller &lt;digits&gt; is unavailable.  Please leave a message after
     * the tone."  Runs <code>then</code> when the sentence has finished
     * playing -- or immediately, if it could not be played at all.  A caller
     * that cannot hear the announcement still gets the mailbox: the clips are
     * a courtesy, the recording slot is the feature.
     */
    void announceUnavailable(final String number, final Runnable then) {
        final int gen = begin();
        start("3DSTelco-announce", new Runnable() {
            public void run() {
                try {
                    play(gen, load(sentence(number)));
                } catch (Throwable error) {
                    Log.w(TAG, "Could not play the unavailable announcement", error);
                }
                if (then != null && current(gen)) {
                    then.run();
                }
            }
        });
    }

    /** "Your message has been saved.  Goodbye." */
    void playSaved() {
        final int gen = begin();
        start("3DSTelco-saved", new Runnable() {
            public void run() {
                try {
                    play(gen, load(one("recorded.wav")));
                } catch (Throwable error) {
                    Log.w(TAG, "Could not play the voicemail confirmation", error);
                }
            }
        });
    }

    /**
     * The record tone, played synchronously: the caller has to hear it finish
     * before VoipSession opens the microphone, or the tone lands in the
     * recording.  Callers are already on a worker thread.
     */
    void beepBlocking() {
        int gen = begin();
        try {
            play(gen, tone(BEEP_MS, BEEP_HZ, 0, 0.5));
        } catch (Throwable error) {
            Log.w(TAG, "Could not play the record tone", error);
        }
    }

    /** Loop the default ringtone until something else plays or stop(). */
    void startRingtone() {
        final int gen = begin();
        ringing = true;
        start("3DSTelco-ringtone", new Runnable() {
            public void run() {
                try {
                    ringtone(gen);
                } finally {
                    if (current(gen)) {
                        ringing = false;
                    }
                }
            }
        });
    }

    static boolean isRinging() {
        return ringing;
    }

    /** Silence whatever is playing. */
    void stop() {
        begin();
    }

    // -------------------------------------------------------------- plumbing

    private int begin() {
        synchronized (lock) {
            ringing = false;
            return ++generation;
        }
    }

    private boolean current(int gen) {
        synchronized (lock) {
            return gen == generation;
        }
    }

    private static void start(String name, Runnable body) {
        Thread thread = new Thread(body, name);
        thread.setDaemon(true);
        thread.start();
    }

    // ------------------------------------------------------------- the clips

    private static List<String> one(String clip) {
        List<String> names = new ArrayList<String>(1);
        names.add(clip);
        return names;
    }

    /** caller.wav, one d&lt;n&gt;.wav per digit dialled, then unavailable.wav. */
    private static List<String> sentence(String number) {
        List<String> names = new ArrayList<String>();
        names.add("caller.wav");
        for (int i = 0; number != null && i < number.length(); i++) {
            char digit = number.charAt(i);
            if (digit >= '0' && digit <= '9') {
                names.add("d" + (digit - '0') + ".wav");
            }
        }
        names.add("unavailable.wav");
        return names;
    }

    /**
     * Reads the whole sentence into one buffer before a note of it is played.
     * Half a megabyte of transient allocation buys the guarantee that an SD
     * read cannot open a gap in the middle of a spoken number -- this card has
     * a documented habit of stalling for entire seconds under load.
     */
    private static byte[] load(List<String> names) throws Exception {
        byte[][] parts = new byte[names.size()][];
        int total = 0;
        for (int i = 0; i < names.size(); i++) {
            parts[i] = readWav(CLIPS + names.get(i));
            total += parts[i].length;
        }
        byte[] pcm = new byte[total];
        int at = 0;
        for (int i = 0; i < parts.length; i++) {
            System.arraycopy(parts[i], 0, pcm, at, parts[i].length);
            at += parts[i].length;
        }
        return pcm;
    }

    /**
     * Returns the PCM payload of a canonical RIFF/WAVE file.  Chunks are
     * walked rather than assumed at fixed offsets, because a 44-byte header is
     * a convention of ffmpeg's muxer and not a property of the format.
     */
    private static byte[] readWav(String path) throws Exception {
        return readWav(path, null);
    }

    /** As readWav(path), but reports the clip's own rate instead of warning. */
    private static byte[] readWav(String path, int[] rateOut) throws Exception {
        File file = new File(path);
        long length = file.length();
        if (length < 44 || length > 4 * 1024 * 1024) {
            throw new Exception("Not a usable clip: " + path + " (" + length + " bytes)");
        }
        byte[] raw = new byte[(int) length];
        InputStream in = new FileInputStream(file);
        try {
            int at = 0;
            while (at < raw.length) {
                int read = in.read(raw, at, raw.length - at);
                if (read < 0) {
                    throw new Exception("Short read on " + path);
                }
                at += read;
            }
        } finally {
            in.close();
        }

        if (!tag(raw, 0, "RIFF") || !tag(raw, 8, "WAVE")) {
            throw new Exception("Not RIFF/WAVE: " + path);
        }
        int at = 12;
        int channels = 0;
        int rate = 0;
        int bits = 0;
        while (at + 8 <= raw.length) {
            int size = le32(raw, at + 4);
            int body = at + 8;
            if (size < 0 || body + size > raw.length) {
                size = raw.length - body;      // truncated final chunk
            }
            if (tag(raw, at, "fmt ") && size >= 16) {
                channels = le16(raw, body + 2);
                rate = le32(raw, body + 4);
                bits = le16(raw, body + 14);
            } else if (tag(raw, at, "data")) {
                if (channels != 1 || bits != 16) {
                    throw new Exception(path + " is " + channels + "ch/" + bits
                            + "-bit; the clips must be mono 16-bit");
                }
                if (rateOut != null) {
                    rateOut[0] = rate;
                } else if (rate != RATE) {
                    // Audible but wrong-pitch beats silent: say so and play it.
                    Log.w(TAG, path + " is " + rate + " Hz, expected " + RATE);
                }
                byte[] pcm = new byte[size & ~1];
                System.arraycopy(raw, body, pcm, 0, pcm.length);
                return pcm;
            }
            at = body + size + (size & 1);     // chunks are word-aligned
        }
        throw new Exception("No data chunk in " + path);
    }

    private static boolean tag(byte[] raw, int at, String want) {
        if (at + 4 > raw.length) {
            return false;
        }
        for (int i = 0; i < 4; i++) {
            if ((raw[at + i] & 0xff) != want.charAt(i)) {
                return false;
            }
        }
        return true;
    }

    private static int le16(byte[] raw, int at) {
        return (raw[at] & 0xff) | ((raw[at + 1] & 0xff) << 8);
    }

    private static int le32(byte[] raw, int at) {
        return (raw[at] & 0xff) | ((raw[at + 1] & 0xff) << 8)
                | ((raw[at + 2] & 0xff) << 16) | ((raw[at + 3] & 0xff) << 24);
    }

    // ------------------------------------------------------------- the tones

    /**
     * One or two summed sine waves as little-endian 16-bit PCM, with a five
     * millisecond ramp at each end.  Without the ramp the step from zero to
     * full amplitude is a click, and on a single-channel amplifier a click is
     * louder than the tone.
     */
    private static byte[] tone(int millis, double hz1, double hz2, double amplitude) {
        int frames = (int) ((long) millis * RATE / 1000);
        byte[] pcm = new byte[frames * 2];
        int ramp = Math.min(RATE / 200, frames / 2);      // 5 ms, or half a very short tone
        double step1 = 2 * Math.PI * hz1 / RATE;
        double step2 = 2 * Math.PI * hz2 / RATE;
        double peak = amplitude * 32767.0 / (hz2 > 0 ? 2 : 1);
        for (int i = 0; i < frames; i++) {
            double sample = Math.sin(step1 * i);
            if (hz2 > 0) {
                sample += Math.sin(step2 * i);
            }
            double gain = 1.0;
            if (ramp > 0) {
                if (i < ramp) {
                    gain = (double) i / ramp;
                } else if (i >= frames - ramp) {
                    gain = (double) (frames - 1 - i) / ramp;
                }
            }
            int value = (int) (sample * peak * gain);
            pcm[i * 2] = (byte) (value & 0xff);
            pcm[i * 2 + 1] = (byte) ((value >> 8) & 0xff);
        }
        return pcm;
    }

    private void ringback(int gen) {
        byte[] on = tone(RINGBACK_ON_MS, 440, 480, 0.6);
        byte[] off = new byte[RATE / 10 * 2];             // 100 ms of silence
        Track track = null;
        try {
            track = new Track();
            while (current(gen)) {
                if (!track.write(gen, on)) {
                    break;
                }
                for (int i = 0; i < RINGBACK_OFF_MS / 100; i++) {
                    if (!track.write(gen, off)) {
                        return;
                    }
                }
            }
        } catch (Throwable error) {
            Log.w(TAG, "Ringback stopped", error);
        } finally {
            if (track != null) {
                track.close();
            }
        }
    }

    /**
     * The ringtone, looped with a second of silence between passes.  If the
     * file cannot be read the phone still rings: with the ringback cadence,
     * because a silent incoming call is the failure that matters.
     */
    private void ringtone(int gen) {
        byte[] pcm;
        int[] rate = new int[] { RATE };
        try {
            pcm = readWav(RINGTONE, rate);
            if (rate[0] < 8000 || rate[0] > 48000) {
                throw new Exception(RINGTONE + " is " + rate[0] + " Hz");
            }
        } catch (Throwable error) {
            Log.w(TAG, "N3DS_TELCO_RINGTONE: falling back to a tone", error);
            ringback(gen);
            return;
        }
        byte[] gap = new byte[(rate[0] / 10) * 2];        // 100 ms of silence
        Track track = null;
        try {
            track = new Track(rate[0]);
            while (current(gen)) {
                if (!track.write(gen, pcm)) {
                    break;
                }
                for (int i = 0; i < 10; i++) {
                    if (!track.write(gen, gap)) {
                        return;
                    }
                }
            }
        } catch (Throwable error) {
            Log.w(TAG, "Ringtone stopped", error);
        } finally {
            if (track != null) {
                track.close();
            }
        }
    }

    private void play(int gen, byte[] pcm) throws Exception {
        Track track = new Track();
        try {
            track.write(gen, pcm);
            track.drain(gen, pcm.length);
        } finally {
            track.close();
        }
    }

    // ------------------------------------------------------------- the track

    /**
     * A short-lived AudioTrack.  Writes go out in tenth-of-a-second pieces so
     * that cancelling a sound never has to interrupt a blocked write(): the
     * longest a stop can be delayed is one piece.
     */
    private final class Track {
        private final AudioTrack track;
        private final int piece;                          // 100 ms

        Track() throws Exception {
            this(RATE);
        }

        Track(int rate) throws Exception {
            piece = rate / 10 * 2;
            int min = AudioTrack.getMinBufferSize(rate,
                    AudioFormat.CHANNEL_CONFIGURATION_MONO,
                    AudioFormat.ENCODING_PCM_16BIT);
            // A quarter second of slack.  getMinBufferSize() reports what the
            // mixer needs, which on this HAL is small enough that a scheduling
            // hiccup would underrun it.
            //
            // N3DS_TELCO_AUDIO_FRAME_ALIGN (#325): in whole frames.  RATE / 2
            // was 11025 bytes -- half a 16-bit frame over -- and AudioTrack
            // rejects a buffer that is not a multiple of the frame size.
            int size = Math.max(min > 0 ? min : 0, (rate / 4) * 2);
            size &= ~1;
            track = new AudioTrack(STREAM, rate,
                    AudioFormat.CHANNEL_CONFIGURATION_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, size, AudioTrack.MODE_STREAM);
            if (track.getState() != AudioTrack.STATE_INITIALIZED) {
                track.release();
                throw new Exception("AudioTrack would not initialise at " + rate + " Hz");
            }
            track.play();
        }

        /** False once the sound has been superseded or the track has failed. */
        boolean write(int gen, byte[] pcm) {
            int at = 0;
            while (at < pcm.length) {
                if (!current(gen)) {
                    return false;
                }
                int n = Math.min(piece, pcm.length - at);
                int wrote = track.write(pcm, at, n);
                if (wrote <= 0) {
                    Log.w(TAG, "AudioTrack.write returned " + wrote);
                    return false;
                }
                at += wrote;
            }
            return true;
        }

        /**
         * Waits for the samples already queued to actually come out of the
         * speaker.  AudioTrack.write() only hands buffers to the mixer, so
         * releasing the track straight after the last write truncates the tail
         * -- which on a 400 ms beep is most of the beep.
         */
        void drain(int gen, int bytes) {
            int frames = bytes / 2;
            long deadline = System.currentTimeMillis() + (long) frames * 1000 / RATE + 500;
            int last = -1;
            int stalled = 0;
            while (current(gen) && System.currentTimeMillis() < deadline) {
                int head = track.getPlaybackHeadPosition();
                if (head >= frames) {
                    return;
                }
                // A head that has stopped moving means the mixer is done with
                // us and nothing further is going to come out; three idle
                // polls is a quarter of a second, far longer than a hiccup.
                stalled = (head == last) ? stalled + 1 : 0;
                if (stalled >= 3) {
                    return;
                }
                last = head;
                try {
                    Thread.sleep(40);
                } catch (InterruptedException stop) {
                    return;
                }
            }
        }

        void close() {
            try {
                track.stop();
            } catch (Throwable ignored) {
                // stop() throws only if the track was never initialised, which
                // the constructor already rules out; release() must still run.
            }
            track.release();
        }
    }
}
