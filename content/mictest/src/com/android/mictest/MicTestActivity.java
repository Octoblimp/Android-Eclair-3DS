package com.android.mictest;

import android.app.Activity;
import android.graphics.Color;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Record from the microphone, play it back, and say honestly what arrived.
 *
 * This is a test instrument as much as it is a toy recorder.  The 3DS
 * microphone path is complete from AudioRecord down to ctr_csnd's capture
 * device, but the sample source at the bottom is an undocumented block: when
 * the driver cannot find a sample register it delivers correctly paced
 * silence, which is indistinguishable from a working recorder pointed at a
 * quiet room -- unless something counts the samples.  So this reports peak
 * amplitude, the proportion of non-zero samples and the DC mean, and says in
 * so many words when every sample it received was a zero.
 *
 * MediaRecorder is deliberately not used.  register_android_media_MediaRecorder
 * is not in gRegJNI in this build, so every MediaRecorder method would throw
 * UnsatisfiedLinkError -- an Error, not a RuntimeException, which is exactly
 * the shape of failure that crashed the dialer once already.  AudioRecord's
 * JNI is registered, so this uses AudioRecord and writes the WAV header
 * itself.
 */
public class MicTestActivity extends Activity {
    private static final String TAG = "MicTest";

    /** Grep target for the release gate: proves the shipped dex is this app. */
    private static final String READY = "N3DS_MIC_TEST_READY AudioRecord 8000 Hz mono 16-bit WAV recorder";

    /** ctr_csnd captures at 8 kHz mono; asking for anything else resamples. */
    private static final int RATE = 8000;
    private static final int CHANNEL = AudioFormat.CHANNEL_CONFIGURATION_MONO;
    private static final int FORMAT = AudioFormat.ENCODING_PCM_16BIT;

    private static final int MAX_SECONDS = 30;
    private static final int WAV_HEADER_BYTES = 44;

    /**
     * N3DS_MIC_TEST_NORMALIZE: playback is scaled so the loudest sample lands
     * here (90% of full scale), by at most MAX_GAIN.  A 3DS recording of
     * speech at arm's length peaks around 30% with an RMS near -25 dBFS, and
     * the stock media volume takes another 13.5 dB off that; together they
     * made #317's perfectly good recordings inaudible on the speaker.
     */
    private static final int TARGET_PEAK = 29490;
    private static final float MAX_GAIN = 8f;                // +18 dB

    private static final int IDLE = 0;
    private static final int RECORDING = 1;
    private static final int PLAYING = 2;

    private final Handler ui = new Handler();

    private volatile int mode = IDLE;
    private volatile boolean cancel;

    private LevelView meter;
    private TextView status;
    private Button recordButton;
    private Button stopButton;
    private Button playButton;
    private File file;

    @Override
    public void onCreate(Bundle saved) {
        super.onCreate(saved);
        Log.i(TAG, READY);
        setContentView(buildUi());
        file = chooseFile();
        say("Ready.\nRecording goes to " + file.getPath()
                + "\n" + RATE + " Hz mono 16-bit, " + MAX_SECONDS + " s maximum.");
        updateButtons();
    }

    @Override
    protected void onPause() {
        super.onPause();
        // Holding the recorder open behind another activity would keep the
        // capture device claimed for a recording nobody is watching.
        cancel = true;
    }

    // ---------------------------------------------------------------- the ui

    private View buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xff101418);
        int pad = dp(6);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Microphone Test");
        title.setTextColor(0xff00e5ff);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        root.addView(title, wrap());

        meter = new LevelView(this);
        LinearLayout.LayoutParams meterParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.FILL_PARENT, dp(22));
        meterParams.topMargin = dp(4);
        root.addView(meter, meterParams);

        status = new TextView(this);
        status.setTextColor(0xffdfe6ea);
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.FILL_PARENT, 0, 1f);
        statusParams.topMargin = dp(4);
        root.addView(status, statusParams);

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        recordButton = addButton(buttons, "Record", new View.OnClickListener() {
            public void onClick(View v) { startRecording(); }
        });
        stopButton = addButton(buttons, "Stop", new View.OnClickListener() {
            public void onClick(View v) { cancel = true; }
        });
        playButton = addButton(buttons, "Play", new View.OnClickListener() {
            public void onClick(View v) { startPlayback(); }
        });
        root.addView(buttons, wrap());
        return root;
    }

    private Button addButton(LinearLayout row, String label, View.OnClickListener click) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        button.setOnClickListener(click);
        row.addView(button, new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        return button;
    }

    private static LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.FILL_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int value) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP,
                value, getResources().getDisplayMetrics());
    }

    private void updateButtons() {
        recordButton.setEnabled(mode == IDLE);
        stopButton.setEnabled(mode != IDLE);
        playButton.setEnabled(mode == IDLE && file != null
                && file.length() > WAV_HEADER_BYTES);
    }

    private void say(final String text) {
        ui.post(new Runnable() {
            public void run() {
                status.setText(text);
                updateButtons();
            }
        });
    }

    private void level(final float value) {
        ui.post(new Runnable() {
            public void run() { meter.setLevel(value); }
        });
    }

    private void finished() {
        mode = IDLE;
        ui.post(new Runnable() {
            public void run() {
                meter.setLevel(0);
                updateButtons();
            }
        });
    }

    // ----------------------------------------------------------- the storage

    /**
     * The SD card if it will take the file, the private data directory if not.
     * The card is much the more useful of the two -- a recording there can be
     * pulled off and looked at on a real machine, which is the whole point of
     * a test recorder -- so it is tried first and the choice is reported.
     */
    private File chooseFile() {
        try {
            File external = Environment.getExternalStorageDirectory();
            if (external != null && external.isDirectory() && external.canWrite()) {
                return new File(external, "mictest.wav");
            }
        } catch (Throwable error) {
            Log.w(TAG, "External storage unusable", error);
        }
        return new File(getFilesDir(), "mictest.wav");
    }

    // --------------------------------------------------------- the recording

    private void startRecording() {
        if (mode != IDLE) {
            return;
        }
        mode = RECORDING;
        cancel = false;
        updateButtons();
        new Thread(new Runnable() {
            public void run() { record(); }
        }, "mictest-record").start();
    }

    private void record() {
        AudioRecord recorder = null;
        OutputStream out = null;
        try {
            int min = AudioRecord.getMinBufferSize(RATE, CHANNEL, FORMAT);
            // Two seconds of slack. getMinBufferSize() can report an error
            // as a negative number, which would otherwise reach the
            // constructor as a nonsense buffer size.
            int bufferBytes = Math.max(min > 0 ? min : 0, RATE * 2 * 2);
            recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, RATE,
                    CHANNEL, FORMAT, bufferBytes);
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
                throw new IOException("AudioRecord would not initialise at "
                        + RATE + " Hz. Is /dev/eac present and readable?");
            }

            // N3DS_MIC_TEST_IN_MEMORY: the whole recording is held in RAM and
            // written once it stops.  Writing each 100 ms chunk to the SD
            // card from this loop let one slow SD write stall the reader
            // long enough for AudioFlinger to drop audio ("RecordThread:
            // buffer overflow", seven times in one 30 s take on #314).
            byte[] pcm = new byte[RATE * 2 * MAX_SECONDS];
            short[] chunk = new short[RATE / 10];          // 100 ms
            long frames = 0;
            long limit = (long) RATE * MAX_SECONDS;
            int peak = 0;
            long nonZero = 0;
            long sum = 0;
            int secondPeak = 0;
            long lastUi = 0;

            recorder.startRecording();
            say("Recording…");
            while (!cancel && frames < limit) {
                int want = (int) Math.min(chunk.length, limit - frames);
                int n = recorder.read(chunk, 0, want);
                if (n <= 0) {
                    if (n < 0) {
                        throw new IOException("AudioRecord.read returned " + n);
                    }
                    continue;
                }
                int chunkPeak = 0;
                int at = (int) frames * 2;
                for (int i = 0; i < n; i++) {
                    int sample = chunk[i];
                    int magnitude = sample < 0 ? -sample : sample;
                    if (magnitude > chunkPeak) {
                        chunkPeak = magnitude;
                    }
                    if (sample != 0) {
                        nonZero++;
                    }
                    sum += sample;
                    pcm[at + i * 2] = (byte) (sample & 0xff);
                    pcm[at + i * 2 + 1] = (byte) ((sample >> 8) & 0xff);
                }
                long before = frames;
                frames += n;
                if (chunkPeak > peak) {
                    peak = chunkPeak;
                }
                if (chunkPeak > secondPeak) {
                    secondPeak = chunkPeak;
                }
                if (frames / RATE != before / RATE) {
                    // One line a second, so a logcat from a test run says
                    // what the microphone heard without anyone reading the
                    // screen.
                    Log.i(TAG, "second " + (frames / RATE) + ": peak " + secondPeak);
                    secondPeak = 0;
                }
                long now = System.currentTimeMillis();
                if (now - lastUi >= 250) {
                    lastUi = now;
                    level(chunkPeak / 32767f);
                    say("Recording… " + seconds(frames) + " s   peak " + chunkPeak);
                }
            }

            recorder.stop();
            say("Saving…");
            out = new BufferedOutputStream(new FileOutputStream(file), 65536);
            out.write(header((int) (frames * 2)));
            out.write(pcm, 0, (int) (frames * 2));
            out.flush();
            out.close();
            out = null;
            String verdict = report(frames, peak, nonZero, sum);
            Log.i(TAG, "N3DS_MIC_TEST_RESULT " + verdict.replace('\n', ' '));
            say(verdict);
        } catch (Throwable error) {
            Log.e(TAG, "Recording failed", error);
            say("Recording failed:\n" + describe(error));
        } finally {
            close(out);
            release(recorder);
            finished();
        }
    }

    /**
     * The whole reason this app exists.  A recorder that only says "3.0 s
     * recorded" cannot tell a working microphone from a driver handing out
     * zeros on schedule, and on this port that is the actual open question.
     */
    private String report(long frames, int peak, long nonZero, long sum) {
        StringBuilder text = new StringBuilder();
        text.append("Recorded ").append(seconds(frames)).append(" s  (")
                .append(frames).append(" samples)\n");
        text.append(file.getPath()).append('\n');
        if (frames == 0) {
            text.append("Nothing was captured at all.");
            return text.toString();
        }
        long percent = nonZero * 100 / frames;
        text.append("peak ").append(peak).append(" of 32767  (")
                .append(peak * 100 / 32767).append("%)\n");
        text.append("non-zero ").append(percent).append("%   mean ")
                .append(sum / frames).append('\n');
        if (peak == 0) {
            text.append("SILENT: every sample was zero. The capture path is "
                    + "running at the right rate but the driver has no sample "
                    + "source yet -- see ctr_csnd mic_data_off.");
        } else if (peak < 64) {
            text.append("Almost silent. Real but very quiet, or noise only.");
        } else {
            text.append("Real audio. Press Play to hear it back.");
        }
        return text.toString();
    }

    // ---------------------------------------------------------- the playback

    private void startPlayback() {
        if (mode != IDLE) {
            return;
        }
        mode = PLAYING;
        cancel = false;
        updateButtons();
        new Thread(new Runnable() {
            public void run() { playBack(); }
        }, "mictest-play").start();
    }

    private void playBack() {
        AudioTrack track = null;
        InputStream in = null;
        AudioManager audio = null;
        int oldVolume = -1;
        try {
            long dataBytes = file.length() - WAV_HEADER_BYTES;
            if (dataBytes <= 0) {
                throw new IOException("Nothing recorded yet.");
            }
            int filePeak = peakOf(file);
            float gain = filePeak > 0 ? (float) TARGET_PEAK / filePeak : 1f;
            if (gain > MAX_GAIN) {
                gain = MAX_GAIN;
            }
            if (gain < 1f) {
                gain = 1f;
            }
            int gainDb = (int) Math.round(20 * Math.log10(gain));

            // N3DS_MIC_TEST_FULL_VOLUME: the music stream at its maximum for
            // the length of the playback, and put back afterwards.  The
            // stock default index is 11 of 15, about -13.5 dB.
            audio = (AudioManager) getSystemService(AUDIO_SERVICE);
            if (audio != null) {
                oldVolume = audio.getStreamVolume(AudioManager.STREAM_MUSIC);
                audio.setStreamVolume(AudioManager.STREAM_MUSIC,
                        audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC), 0);
            }
            Log.i(TAG, "N3DS_MIC_TEST_PLAYBACK file peak " + filePeak
                    + ", gain x" + gain + " (+" + gainDb + " dB), music volume "
                    + oldVolume + " -> max");

            int min = AudioTrack.getMinBufferSize(RATE, CHANNEL, FORMAT);
            int bufferBytes = Math.max(min > 0 ? min : 0, RATE);
            track = new AudioTrack(AudioManager.STREAM_MUSIC, RATE, CHANNEL,
                    FORMAT, bufferBytes, AudioTrack.MODE_STREAM);
            if (track.getState() != AudioTrack.STATE_INITIALIZED) {
                throw new IOException("AudioTrack would not initialise at "
                        + RATE + " Hz.");
            }

            in = new BufferedInputStream(new FileInputStream(file), 8192);
            skip(in, WAV_HEADER_BYTES);

            byte[] bytes = new byte[RATE / 5 * 2];         // 200 ms
            long played = 0;
            String boost = gainDb > 0 ? "  (+" + gainDb + " dB)" : "";
            track.play();
            say("Playing…" + boost);
            while (!cancel) {
                int n = in.read(bytes);
                if (n <= 0) {
                    break;
                }
                n &= ~1;                                   // whole samples only
                int chunkPeak = 0;
                for (int i = 0; i + 1 < n; i += 2) {
                    int sample = (short) ((bytes[i] & 0xff) | (bytes[i + 1] << 8));
                    int scaled = Math.round(sample * gain);
                    if (scaled > 32767) {
                        scaled = 32767;
                    } else if (scaled < -32768) {
                        scaled = -32768;
                    }
                    bytes[i] = (byte) (scaled & 0xff);
                    bytes[i + 1] = (byte) ((scaled >> 8) & 0xff);
                    int magnitude = scaled < 0 ? -scaled : scaled;
                    if (magnitude > chunkPeak) {
                        chunkPeak = magnitude;
                    }
                }
                level(chunkPeak / 32767f);
                int wrote = track.write(bytes, 0, n);
                if (wrote <= 0) {
                    throw new IOException("AudioTrack.write returned " + wrote);
                }
                played += wrote;
                say("Playing… " + seconds(played / 2) + " s of "
                        + seconds(dataBytes / 2) + " s" + boost);
            }
            drain(track, played / 2);
            say(cancel ? "Playback stopped." : "Playback finished." + boost);
        } catch (Throwable error) {
            Log.e(TAG, "Playback failed", error);
            say("Playback failed:\n" + describe(error));
        } finally {
            close(in);
            release(track);
            if (audio != null && oldVolume >= 0) {
                try {
                    audio.setStreamVolume(AudioManager.STREAM_MUSIC, oldVolume, 0);
                } catch (Throwable ignored) {
                    // The volume is a convenience; the playback already ran.
                }
            }
            finished();
        }
    }

    /** The largest sample magnitude in the recording, for the playback gain. */
    private static int peakOf(File wav) throws IOException {
        InputStream in = new BufferedInputStream(new FileInputStream(wav), 8192);
        try {
            skip(in, WAV_HEADER_BYTES);
            byte[] bytes = new byte[8192];
            int peak = 0;
            int carry = -1;
            while (true) {
                int n = in.read(bytes);
                if (n <= 0) {
                    return peak;
                }
                int i = 0;
                if (carry >= 0) {
                    int sample = (short) (carry | (bytes[0] << 8));
                    peak = Math.max(peak, sample < 0 ? -sample : sample);
                    carry = -1;
                    i = 1;
                }
                for (; i + 1 < n; i += 2) {
                    int sample = (short) ((bytes[i] & 0xff) | (bytes[i + 1] << 8));
                    int magnitude = sample < 0 ? -sample : sample;
                    if (magnitude > peak) {
                        peak = magnitude;
                    }
                }
                if (i < n) {
                    carry = bytes[i] & 0xff;
                }
            }
        } finally {
            close(in);
        }
    }

    /**
     * AudioTrack.write() only hands buffers to the mixer, so stopping the
     * track as soon as the last write returns cuts off whatever is still
     * queued -- about a fifth of a second of the recording.
     */
    private void drain(AudioTrack track, long frames) {
        long deadline = System.currentTimeMillis() + frames * 1000 / RATE + 500;
        int last = -1;
        int stalled = 0;
        while (!cancel && System.currentTimeMillis() < deadline) {
            int head = track.getPlaybackHeadPosition();
            if (head >= frames) {
                return;
            }
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

    // ------------------------------------------------------------- wav files

    /** A canonical 44-byte RIFF/WAVE header for mono 16-bit PCM at RATE. */
    private static byte[] header(int dataBytes) {
        byte[] h = new byte[WAV_HEADER_BYTES];
        tag(h, 0, "RIFF");
        le32(h, 4, 36 + dataBytes);
        tag(h, 8, "WAVE");
        tag(h, 12, "fmt ");
        le32(h, 16, 16);                  // PCM fmt chunk size
        le16(h, 20, 1);                   // PCM
        le16(h, 22, 1);                   // mono
        le32(h, 24, RATE);
        le32(h, 28, RATE * 2);            // byte rate
        le16(h, 32, 2);                   // block align
        le16(h, 34, 16);                  // bits per sample
        tag(h, 36, "data");
        le32(h, 40, dataBytes);
        return h;
    }

    private static void tag(byte[] buffer, int at, String value) {
        for (int i = 0; i < 4; i++) {
            buffer[at + i] = (byte) value.charAt(i);
        }
    }

    private static void le16(byte[] buffer, int at, int value) {
        buffer[at] = (byte) (value & 0xff);
        buffer[at + 1] = (byte) ((value >> 8) & 0xff);
    }

    private static void le32(byte[] buffer, int at, int value) {
        buffer[at] = (byte) (value & 0xff);
        buffer[at + 1] = (byte) ((value >> 8) & 0xff);
        buffer[at + 2] = (byte) ((value >> 16) & 0xff);
        buffer[at + 3] = (byte) ((value >> 24) & 0xff);
    }

    // ---------------------------------------------------------------- odds

    private static void skip(InputStream in, long count) throws IOException {
        long left = count;
        while (left > 0) {
            long n = in.skip(left);
            if (n <= 0) {
                if (in.read() < 0) {
                    throw new IOException("File is shorter than its header.");
                }
                n = 1;
            }
            left -= n;
        }
    }

    private static String seconds(long frames) {
        long tenths = frames * 10 / RATE;
        return (tenths / 10) + "." + (tenths % 10);
    }

    private static String describe(Throwable error) {
        String message = error.getMessage();
        return (message == null || message.length() == 0)
                ? error.getClass().getName() : message;
    }

    private static void close(java.io.Closeable stream) {
        if (stream != null) {
            try {
                stream.close();
            } catch (IOException ignored) {
                // Nothing useful can be done about a failed close here; the
                // recording is already on disk or already lost.
            }
        }
    }

    private static void release(AudioRecord recorder) {
        if (recorder != null) {
            try {
                recorder.release();
            } catch (Throwable ignored) {
                // Releasing twice, or releasing one that never initialised.
            }
        }
    }

    private static void release(AudioTrack track) {
        if (track != null) {
            try {
                track.stop();
            } catch (Throwable ignored) {
                // stop() throws only on an uninitialised track.
            }
            try {
                track.release();
            } catch (Throwable ignored) {
                // Same.
            }
        }
    }
}
