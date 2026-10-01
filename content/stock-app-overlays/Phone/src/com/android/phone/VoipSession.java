package com.android.phone;

import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.os.SystemClock;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.SocketTimeoutException;

/**
 * The media half of a 3DSTelco call: 8 kHz mono PCM over the relay's UDP
 * protocol, 20 ms per packet, T3V1 up and T3A1 down.
 *
 * N3DS_TELCO_AUDIO_OPTIONAL_GUARD, formerly N3DS_VOIP_UPLINK_OPTIONAL: the
 * downlink is what makes a call a call, and it no longer depends on the
 * uplink.
 *
 * This used to build an AudioRecord and an AudioTrack and abandon the whole
 * session if either one failed, which is how dialling a number ended in "3DS
 * audio backend is unavailable for VoIP" -- our own string, thrown from here,
 * with nothing wrong at the server end at all.  The microphone works now
 * (/dev/eac capture, kernel #317), but a recorder that will not open is still
 * no reason to refuse the call.
 *
 * Refusing the call over that is the wrong trade.  A call with working
 * downlink and a silent uplink is a call you can take; a call that will not
 * start is not.  So the recorder is optional, its absence is reported once and
 * carried in the session state rather than thrown, and the send loop keeps
 * emitting correctly sequenced silence on the wire.  That last part is not
 * cosmetic: the relay keys a call's media on an unbroken sequence of T3V1
 * packets, so a session that simply stopped sending would look to the server
 * like the caller had dropped off, and the downlink would go with it.
 *
 * Downlink packets are T3A1; a T3E1 from the relay means the call is over
 * (N3DS_TELCO_T3E1) and fires onEnded once.
 *
 * N3DS_TELCO_JITTER_BUFFER (#325): the downlink no longer writes straight
 * from the socket into the AudioTrack.  It used to, and that one blocking
 * write was the whole of "the other side is 2-3 seconds late, and silent
 * unless they talk constantly":
 *
 *  - AudioTrack.write() blocks while the track is full, so the receive thread
 *    stopped draining the socket.  Packets arrive at exactly the rate the
 *    mixer plays them, so any backlog -- the call's first second, a GC pause,
 *    a relay burst -- sat in the kernel's UDP queue for the rest of the call.
 *    That queue holds a couple of seconds of 8 kHz audio.
 *  - Eclair's AudioFlinger drops a track from the mixer after ~1 s with no
 *    data, and the client only restarts it after its own 1 s obtainBuffer
 *    timeout, with a full buffer required before the first frame plays.
 *    Every gap in the downlink cost another second of silence and lag.
 *
 * Now the receive thread only queues packets, and a playout thread feeds the
 * track: the next packet when there is one, 20 ms of silence when the track
 * is about to run dry (so it is never dropped from the mixer), and once a
 * second whatever queue depth persisted for that whole second is discarded.
 * A burst that drains by itself is kept; latency that would stay is not.
 *
 * N3DS_TELCO_DOWNLINK_AGC: the downlink also gets an automatic gain stage.
 * The web side sends speech at whatever level the browser's own AGC settled
 * on, which on the 3DS's small speakers was often barely audible.
 *
 * N3DS_TELCO_ECHO_SUPPRESS (#326): the louder the downlink, the more of it
 * the 3DS microphone hears and sends back -- the caller hears themselves.
 * The browser's echo canceller cannot help: it cancels the echo of what the
 * PC played, not what the 3DS played.  So while the far end is audible (and
 * for ECHO_HOLD_MS after, which covers the track, the mixer, the speaker and
 * the capture buffer), the uplink is turned down by ECHO_DUCK.  That is how a
 * half-duplex speakerphone does it: talking over the other side is quieter,
 * but nothing comes back.
 */
final class VoipSession {
    private static final String LOG_TAG = "3DSTelcoVoip";
    private static final int RATE = 8000;
    /** 320 bytes = 160 frames = 20 ms of 8 kHz mono 16-bit PCM. */
    private static final int PAYLOAD = 320;
    private static final int PACKET_MS = 20;

    /** Downlink queue capacity: 1 s.  A burst bigger than that is stale anyway. */
    private static final int QUEUE_SLOTS = 50;
    /** Packets (20 ms each) a latency trim leaves queued. */
    private static final int QUEUE_TARGET = 2;
    /** Playout decisions per latency check: 1 s. */
    private static final int TRIM_WINDOW = 50;
    /**
     * Fill a gap with silence once the track holds fewer than this many
     * frames (30 ms).  The mixer takes ~186 frames of an 8 kHz track per
     * 23 ms cycle on this HAL (44.1 kHz, 1024-frame buffer), so this is one
     * cycle's worth with a little to spare.
     */
    private static final int CONCEAL_BELOW_FRAMES = 240;
    private static final long STATS_MS = 5000;

    /** Downlink output RMS above which the far end counts as audible. */
    private static final float ECHO_ACTIVE_RMS = 900f;
    /** How long after an audible frame is written the uplink stays ducked. */
    private static final long ECHO_HOLD_MS = 400;
    /** Uplink gain while ducked; adb setprop n3ds.telco.echo_duck to tune. */
    private static final float ECHO_DUCK = 0.2f;    // -14 dB
    /** Per 20 ms frame, how fast the uplink comes back once the far end stops. */
    private static final float ECHO_RECOVER = 0.12f;

    private final String host;
    private final int port;
    private final byte[] token;
    private volatile boolean active;
    /*
     * N3DS_TELCO_MUTE: muting zeroes the outgoing PCM rather than stopping the
     * send loop. The relay keys a call's media on an unbroken sequence of
     * T3V1 packets; going silent on the wire would look like the caller
     * dropped off, and unmuting would have to re-establish the stream.
     */
    private volatile boolean muted;
    private DatagramSocket socket;
    private AudioRecord recorder;
    private AudioTrack player;
    /** The track's buffer, in frames. */
    private int trackFrames;
    /** Why the microphone is not on this call, or null if it is. */
    private volatile String uplinkFault;
    private final Runnable onEnded;
    private boolean endReported;

    // The downlink queue: a ring of 20 ms slots, guarded by queueLock.
    private final byte[][] queue = new byte[QUEUE_SLOTS][PAYLOAD];
    private final int[] queueLength = new int[QUEUE_SLOTS];
    private final Object queueLock = new Object();
    private int queueHead;
    private int queueCount;

    // N3DS_TELCO_DOWNLINK_STATS: logged every STATS_MS while a call is up.
    private int statReceived;
    private int statOverflow;
    private int statPlayed;
    private int statConcealed;
    private int statTrimmed;
    private int statSent;
    private int statPeakIn;
    private int statDucked;
    private final Agc agc = new Agc(floatProperty("n3ds.telco.agc_rms", Agc.TARGET_RMS));
    private final float echoDuck = floatProperty("n3ds.telco.echo_duck", ECHO_DUCK);
    /** elapsedRealtime until which the far end may still be in the microphone. */
    private volatile long farEndAudibleUntilMs;

    VoipSession(String host, int port, String encodedToken, Runnable onEnded) throws Exception {
        this.host = host; this.port = port; this.onEnded = onEnded; token = decode(encodedToken);
        if (token.length != 32) throw new Exception("Invalid VoIP media ticket.");
    }

    void start() throws Exception {
        player = openPlayer();
        recorder = openRecorder();

        socket = new DatagramSocket(); socket.setSoTimeout(1000); active = true;
        try {
            player.play();
        } catch (IllegalStateException error) {
            stop();
            throw new Exception("3DS audio could not start playback for VoIP.", error);
        }
        if (recorder != null) {
            try {
                recorder.startRecording();
            } catch (IllegalStateException error) {
                // Initialised but refused to run. Same trade as above: drop
                // the uplink, keep the call.
                uplinkFault = "microphone would not start";
                releaseRecorder();
            }
        }
        if (uplinkFault != null)
            Log.w(LOG_TAG, "call has downlink only: " + uplinkFault);

        new Thread(new Runnable() { public void run() {
            raisePriority();
            send();
        } }, "3DSTelco-audio-send").start();
        new Thread(new Runnable() { public void run() {
            raisePriority();
            receive();
        } }, "3DSTelco-audio-receive").start();
        new Thread(new Runnable() { public void run() {
            raisePriority();
            play();
        } }, "3DSTelco-audio-play").start();
        Log.i(LOG_TAG, "N3DS_TELCO_JITTER_BUFFER session started, relay " + host + ":" + port);
        Log.i(LOG_TAG, "N3DS_TELCO_LOUDER_DOWNLINK target_rms=" + agc.targetRms
                + " max_gain=" + Agc.MAX_GAIN + "; N3DS_TELCO_ECHO_SUPPRESS duck=" + echoDuck
                + " hold=" + ECHO_HOLD_MS + "ms");
    }

    /** A tuning knob for the next call, without a rebuild; bad values are ignored. */
    private static float floatProperty(String key, float fallback) {
        try {
            String value = android.os.SystemProperties.get(key, "");
            if (value.length() == 0) return fallback;
            float parsed = Float.parseFloat(value);
            return parsed > 0f && parsed < 100000f ? parsed : fallback;
        } catch (Throwable ignored) {
            return fallback;
        }
    }

    private static void raisePriority() {
        try {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_URGENT_AUDIO);
        } catch (RuntimeException error) {
            Log.w(LOG_TAG, "could not raise audio thread priority: " + error);
        }
    }

    /**
     * The downlink. This one is genuinely required, and a failure here is
     * worth the call, so it reports what it actually saw rather than a
     * generic "audio is unavailable".
     */
    private AudioTrack openPlayer() throws Exception {
        int size;
        try {
            size = Math.max(PAYLOAD * 4, AudioTrack.getMinBufferSize(RATE,
                    AudioFormat.CHANNEL_CONFIGURATION_MONO, AudioFormat.ENCODING_PCM_16BIT));
        } catch (LinkageError error) {
            throw new Exception("3DS audio output is not built into this system image.", error);
        }
        AudioTrack track;
        try {
            track = new AudioTrack(AudioManager.STREAM_VOICE_CALL, RATE,
                    AudioFormat.CHANNEL_CONFIGURATION_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    size, AudioTrack.MODE_STREAM);
        } catch (IllegalArgumentException error) {
            throw new Exception("3DS audio output rejected " + RATE + " Hz mono (buffer "
                    + size + " bytes).", error);
        } catch (LinkageError error) {
            throw new Exception("3DS audio output is not built into this system image.", error);
        }
        if (track.getState() != AudioTrack.STATE_INITIALIZED) {
            track.release();
            throw new Exception("3DS audio output would not initialise at " + RATE
                    + " Hz (buffer " + size + " bytes).");
        }
        trackFrames = size / 2;
        Log.i(LOG_TAG, "downlink track: " + size + " bytes ("
                + (size / 2 * 1000 / RATE) + " ms)");
        return track;
    }

    /**
     * The uplink. Optional by design -- see the class comment. Every failure
     * path here records why and returns null; none of them throws.
     */
    private AudioRecord openRecorder() {
        int size;
        try {
            // 200 ms rather than 80: a send() that stalls on Wi-Fi for a
            // moment used to overflow it ("RecordThread: buffer overflow").
            size = Math.max(PAYLOAD * 10, AudioRecord.getMinBufferSize(RATE,
                    AudioFormat.CHANNEL_CONFIGURATION_MONO, AudioFormat.ENCODING_PCM_16BIT));
        } catch (LinkageError error) {
            uplinkFault = "audio capture is not built into this system image";
            Log.w(LOG_TAG, uplinkFault, error);
            return null;
        }
        if (size <= 0) {
            // getMinBufferSize reports 0 for an unsupported combination and
            // -1 when it could not ask AudioFlinger at all.
            uplinkFault = "no capture path for " + RATE + " Hz mono (getMinBufferSize " + size + ")";
            Log.w(LOG_TAG, uplinkFault);
            return null;
        }
        AudioRecord record;
        try {
            record = new AudioRecord(MediaRecorder.AudioSource.MIC, RATE,
                    AudioFormat.CHANNEL_CONFIGURATION_MONO, AudioFormat.ENCODING_PCM_16BIT, size);
        } catch (IllegalArgumentException error) {
            uplinkFault = "capture rejected " + RATE + " Hz mono (buffer " + size + " bytes)";
            Log.w(LOG_TAG, uplinkFault, error);
            return null;
        } catch (LinkageError error) {
            uplinkFault = "audio capture is not built into this system image";
            Log.w(LOG_TAG, uplinkFault, error);
            return null;
        }
        if (record.getState() != AudioRecord.STATE_INITIALIZED) {
            record.release();
            uplinkFault = "microphone would not initialise (buffer " + size + " bytes)";
            Log.w(LOG_TAG, uplinkFault);
            return null;
        }
        return record;
    }

    void setMuted(boolean value) { muted = value; }

    boolean isMuted() { return muted; }

    /** Null while the microphone is working; otherwise why it is not. */
    String uplinkFault() { return uplinkFault; }

    void stop() {
        active = false;
        synchronized (queueLock) { queueLock.notifyAll(); }
        if (socket != null) socket.close();
        releaseRecorder();
        // The playout thread may be inside write(); stop() releases it.
        try { if (player != null) player.stop(); } catch (Exception ignored) {} catch (LinkageError ignored) {}
        try { if (player != null) player.release(); } catch (RuntimeException ignored) {} catch (LinkageError ignored) {}
        player = null; socket = null;
    }

    private void releaseRecorder() {
        AudioRecord record = recorder;
        recorder = null;
        if (record == null) return;
        try { record.stop(); } catch (Exception ignored) {} catch (LinkageError ignored) {}
        try { record.release(); } catch (RuntimeException ignored) {} catch (LinkageError ignored) {}
    }

    /**
     * Uplink. One packet every 20 ms, sequence unbroken, whether or not there
     * is a microphone behind it.
     */
    private void send() {
        int sequence = 0;
        byte[] pcm = new byte[PAYLOAD];
        byte[] packet = new byte[40 + PAYLOAD];
        packet[0] = 'T'; packet[1] = '3'; packet[2] = 'V'; packet[3] = '1';
        System.arraycopy(token, 0, packet, 4, 32);
        try {
            InetAddress address = InetAddress.getByName(host);
            long due = System.currentTimeMillis();
            float upGain = 1f;
            while (active) {
                int count;
                AudioRecord record = recorder;
                if (record != null) {
                    count = record.read(pcm, 0, pcm.length);
                    if (count <= 0) continue;
                } else {
                    /*
                     * No microphone on this call. Pace the silence off the
                     * clock -- read() is what normally provides the timing,
                     * and without it this loop would spin a core flat and
                     * flood the relay with a call's worth of packets in a
                     * fraction of a second.
                     */
                    due += PACKET_MS;
                    long wait = due - System.currentTimeMillis();
                    if (wait > 0) {
                        Thread.sleep(wait);
                    } else if (wait < -1000) {
                        due = System.currentTimeMillis();  // fell far behind; do not chase
                    }
                    java.util.Arrays.fill(pcm, (byte) 0);
                    count = pcm.length;
                }
                if (muted) {
                    java.util.Arrays.fill(pcm, 0, count, (byte) 0);
                } else {
                    // N3DS_TELCO_ECHO_SUPPRESS: down at once (the hold starts
                    // when the frame is written, before it reaches the
                    // speaker), back up over about 150 ms.
                    boolean farEnd = SystemClock.elapsedRealtime() < farEndAudibleUntilMs;
                    float wanted = farEnd ? echoDuck : 1f;
                    float next = wanted < upGain ? wanted
                            : Math.min(wanted, upGain + ECHO_RECOVER);
                    if (upGain < 0.999f || next < 0.999f) ramp(pcm, count, upGain, next);
                    upGain = next;
                    if (farEnd) statDucked++;
                }
                packet[36] = (byte) (sequence >>> 24); packet[37] = (byte) (sequence >>> 16);
                packet[38] = (byte) (sequence >>> 8);   packet[39] = (byte) sequence;
                System.arraycopy(pcm, 0, packet, 40, count);
                socket.send(new DatagramPacket(packet, 40 + count, address, port));
                sequence++;
                statSent++;
            }
        } catch (Exception error) {
            if (active) Log.w(LOG_TAG, "uplink stopped: " + error);
            active = false;
        }
    }

    /** Scales 16-bit PCM in place, gliding from one gain to the other. */
    private static void ramp(byte[] pcm, int length, float from, float to) {
        int samples = length / 2;
        if (samples == 0) return;
        float step = (to - from) / samples;
        float g = from;
        for (int i = 0; i + 1 < length; i += 2) {
            g += step;
            int v = (int) ((short) ((pcm[i] & 0xff) | (pcm[i + 1] << 8)) * g);
            pcm[i] = (byte) v;
            pcm[i + 1] = (byte) (v >> 8);
        }
    }

    /** Socket to queue, and nothing else: this thread must never block on audio. */
    private void receive() {
        byte[] bytes = new byte[1320];
        while (active) {
            DatagramPacket packet = new DatagramPacket(bytes, bytes.length);
            try {
                socket.receive(packet);
                int length = packet.getLength();
                if (length > 8 && bytes[0]=='T' && bytes[1]=='3' && bytes[2]=='A' && bytes[3]=='1') {
                    enqueue(bytes, 8, Math.min(PAYLOAD, length - 8) & ~1);
                } else if (length >= 4 && bytes[0]=='T' && bytes[1]=='3' && bytes[2]=='E' && bytes[3]=='1'
                        && !endReported) {
                    endReported = true;
                    Log.i(LOG_TAG, "relay reports the call ended (T3E1)");
                    if (onEnded != null) onEnded.run();
                }
            } catch (SocketTimeoutException ignored) {
            } catch (Exception error) {
                if (active) Log.w(LOG_TAG, "downlink socket stopped: " + error);
                active = false;
            }
        }
        synchronized (queueLock) { queueLock.notifyAll(); }
    }

    private void enqueue(byte[] source, int offset, int length) {
        if (length <= 0) return;
        synchronized (queueLock) {
            statReceived++;
            if (queueCount == QUEUE_SLOTS) {
                // Full: the oldest packet is the stalest; it goes.
                queueHead = (queueHead + 1) % QUEUE_SLOTS;
                queueCount--;
                statOverflow++;
            }
            int slot = (queueHead + queueCount) % QUEUE_SLOTS;
            System.arraycopy(source, offset, queue[slot], 0, length);
            queueLength[slot] = length;
            queueCount++;
            queueLock.notifyAll();
        }
    }

    /**
     * Queue to track.  Blocking in write() is fine here: it is what paces
     * this thread to the mixer, and the receive thread no longer waits on it.
     */
    private void play() {
        byte[] frame = new byte[PAYLOAD];
        long written = 0;            // frames handed to the track
        int windowMin = Integer.MAX_VALUE;
        int windowCount = 0;
        long statsDue = SystemClock.elapsedRealtime() + STATS_MS;
        try {
            while (active) {
                AudioTrack track = player;
                if (track == null) break;
                int length = 0;
                boolean conceal = false;
                synchronized (queueLock) {
                    if (queueCount == 0) {
                        long played = track.getPlaybackHeadPosition() & 0xffffffffL;
                        // AudioFlinger mixes nothing of a new track until its
                        // whole buffer is full, so until it starts consuming,
                        // fill it rather than wait on a head that cannot move.
                        boolean starting = played == 0 && written < trackFrames;
                        if (!starting && written - played > CONCEAL_BELOW_FRAMES) {
                            // Still enough in the track; give the network a
                            // few more milliseconds before inventing audio.
                            queueLock.wait(5);
                            continue;
                        }
                        conceal = true;
                    } else {
                        length = queueLength[queueHead];
                        System.arraycopy(queue[queueHead], 0, frame, 0, length);
                        queueHead = (queueHead + 1) % QUEUE_SLOTS;
                        queueCount--;
                    }
                    windowMin = Math.min(windowMin, queueCount);
                    if (++windowCount >= TRIM_WINDOW) {
                        // Every slot that stayed queued for a whole second
                        // is pure delay.  Drop it, down to the target.
                        int excess = Math.min(windowMin, queueCount) - QUEUE_TARGET;
                        if (excess > 0) {
                            queueHead = (queueHead + excess) % QUEUE_SLOTS;
                            queueCount -= excess;
                            statTrimmed += excess;
                        }
                        windowMin = Integer.MAX_VALUE;
                        windowCount = 0;
                    }
                }
                if (conceal) {
                    java.util.Arrays.fill(frame, (byte) 0);
                    length = PAYLOAD;
                    statConcealed++;
                } else {
                    int peak = agc.apply(frame, length);
                    if (peak > statPeakIn) statPeakIn = peak;
                    statPlayed++;
                    if (agc.outRms > ECHO_ACTIVE_RMS) {
                        farEndAudibleUntilMs = SystemClock.elapsedRealtime() + ECHO_HOLD_MS;
                    }
                }
                int n = track.write(frame, 0, length);
                if (n > 0) written += n / 2;
                else if (n < 0) {
                    Log.w(LOG_TAG, "downlink write failed: " + n);
                    break;
                }

                long now = SystemClock.elapsedRealtime();
                if (now >= statsDue) {
                    statsDue = now + STATS_MS;
                    logStats();
                }
            }
        } catch (InterruptedException ignored) {
        } catch (RuntimeException error) {
            if (active) Log.w(LOG_TAG, "downlink playout stopped: " + error);
        }
    }

    private void logStats() {
        int queued;
        synchronized (queueLock) { queued = queueCount; }
        Log.i(LOG_TAG, "N3DS_TELCO_DOWNLINK_STATS 5s: received=" + statReceived
                + " played=" + statPlayed + " concealed=" + statConcealed
                + " trimmed=" + statTrimmed + " overflow=" + statOverflow
                + " queued=" + queued + " peak_in=" + statPeakIn
                + " gain=" + agc.gainText() + " sent=" + statSent
                + " ducked=" + statDucked);
        statReceived = statPlayed = statConcealed = statTrimmed = statOverflow = 0;
        statPeakIn = 0;
        statSent = 0;
        statDucked = 0;
    }

    /**
     * N3DS_TELCO_DOWNLINK_AGC, second version (N3DS_TELCO_LOUDER_DOWNLINK,
     * #326).  The first aimed the sample PEAK at -4 dBFS.  Speech peaks sit
     * 10-15 dB above its loudness, so that left the far end quiet even at
     * full volume on these speakers.  Now:
     *  - the gain aims the loud-syllable level (an RMS envelope that jumps to
     *    each frame's RMS and decays over ~0.4 s) at targetRms;
     *  - the peaks that pushes past KNEE are rounded off by a soft limiter
     *    instead of clipping, and the gain is still held down so no peak is
     *    driven more than PEAK_CEILING into it;
     *  - pauses (frames under GATE_RMS) hold the gain instead of letting it
     *    climb onto the line noise, so the hiss between words stays put;
     *  - the gain glides across each frame, so a fast drop does not click.
     */
    private static final class Agc {
        // 12000 measured on a real 3DS speech capture: +4 dB louder than the
        // peak AGC it replaces, ~3% of samples in the limiter, none clipped.
        static final float TARGET_RMS = 12000f;          // about -9 dBFS
        static final float MAX_GAIN = 12f;               // +21.6 dB
        private static final float MIN_GAIN = 0.5f;
        private static final float PEAK_CEILING = 52000f; // ~+4 dB into the limiter at most
        private static final float GATE_RMS = 150f;
        private static final float RMS_RELEASE = 0.95f;  // per 20 ms
        private static final float PEAK_RELEASE = 0.985f;
        private static final float RISE = 0.05f;          // gain approach per 20 ms
        private static final int KNEE = 16000;
        private static final int RANGE = 32767 - KNEE;

        final float targetRms;
        private float rmsEnvelope;
        private float peakEnvelope;
        private float gain = 1f;
        /** RMS of the last frame as played; the echo suppressor keys on it. */
        volatile float outRms;

        Agc(float targetRms) {
            this.targetRms = targetRms;
        }

        /** Applies the gain in place; returns the frame's input peak. */
        int apply(byte[] pcm, int length) {
            int samples = length / 2;
            if (samples == 0) return 0;
            int peak = 0;
            double sumSquares = 0;
            for (int i = 0; i + 1 < length; i += 2) {
                int s = (short) ((pcm[i] & 0xff) | (pcm[i + 1] << 8));
                sumSquares += (double) s * s;
                if (s < 0) s = -s;
                if (s > peak) peak = s;
            }
            float rms = (float) Math.sqrt(sumSquares / samples);
            peakEnvelope = Math.max(peak, peakEnvelope * PEAK_RELEASE);
            float wanted;
            if (rms >= GATE_RMS) {
                rmsEnvelope = Math.max(rms, rmsEnvelope * RMS_RELEASE);
                wanted = Math.min(MAX_GAIN, targetRms / rmsEnvelope);
            } else {
                wanted = gain;   // a pause: hold
            }
            if (peakEnvelope > 0f) wanted = Math.min(wanted, PEAK_CEILING / peakEnvelope);
            wanted = Math.max(MIN_GAIN, wanted);
            float from = gain;
            gain = wanted < gain ? wanted : gain + (wanted - gain) * RISE;

            float step = (gain - from) / samples;
            float g = from;
            double outSquares = 0;
            for (int i = 0; i + 1 < length; i += 2) {
                g += step;
                int s = (short) ((pcm[i] & 0xff) | (pcm[i + 1] << 8));
                int v = limit((int) (s * g));
                outSquares += (double) v * v;
                pcm[i] = (byte) v;
                pcm[i + 1] = (byte) (v >> 8);
            }
            outRms = (float) Math.sqrt(outSquares / samples);
            return peak;
        }

        /** Unity below KNEE; above it, approaches full scale and never reaches it. */
        private static int limit(int v) {
            int a = v < 0 ? -v : v;
            if (a <= KNEE) return v;
            float u = (a - KNEE) / (float) RANGE;
            int y = KNEE + (int) (RANGE * u / (1f + u));
            return v < 0 ? -y : y;
        }

        String gainText() {
            return String.valueOf(Math.round(gain * 10f) / 10f) + "x";
        }
    }

    private static byte[] decode(String value) throws Exception {
        String alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
        ByteArrayOutputStream output = new ByteArrayOutputStream(); int bits = 0; int count = 0;
        for (int i = 0; i < value.length(); i++) {
            int digit = alphabet.indexOf(value.charAt(i)); if (digit < 0) throw new Exception("Invalid media ticket.");
            bits = (bits << 6) | digit; count += 6;
            if (count >= 8) { count -= 8; output.write((bits >>> count) & 255); }
        }
        return output.toByteArray();
    }
}
