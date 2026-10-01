/*
 * Your own 3DSTelco mailbox, reached by dialing the fixed "100" shortcut --
 * TelcoCallActivity intercepts that number and opens this instead of placing
 * a call. "Same number for everyone, only your own messages" needs no
 * client-side routing at all: every request below is authenticated as this
 * device, and the backend scopes /v1/voicemails to the caller's own
 * subscriber_id.
 *
 * N3DS_TELCO_VOICEMAIL_UI (2026-09-11). This was a stock ListView of
 * "from - status (Ns)" strings with a Refresh button. It is now a proper
 * inbox drawn on the same Canvas theme as the dialer and the in-call screen:
 * unread marks, relative timestamps, durations, a selected-row action bar
 * (PLAY / CALL BACK / DELETE) instead of a destructive long-press, and a
 * playback bar with a real position readout that can be tapped to seek.
 *
 * N3DS_TELCO_VOICEMAIL_LOCAL (#327): the inbox is the messages saved on this
 * 3DS (see TelcoVoicemailStore). Opening it shows them at once and then asks
 * the server only for messages this phone has not saved yet; playing one
 * reads the SD card, so a message plays with Wi-Fi off, and no message is
 * ever downloaded twice. Marking read and deleting are applied here first
 * and sent to the server best-effort.
 *
 * An AudioTrack that cannot be created (N3DS_TELCO_AUDIO_OPTIONAL_GUARD, the
 * same guard VoipSession uses) is reported on screen rather than pretending
 * to have played anything.
 */
package com.android.phone;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.os.Vibrator;
import android.util.Log;
import android.view.MotionEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

public final class VoicemailActivity extends Activity {
    private static final String TAG = "TelcoVoicemail";
    private static final String CALL_ACTION = "io.divergen.telco.action.CALL";

    /** 8 kHz, mono, 16-bit: two bytes per frame, 16000 bytes per second. */
    private static final int RATE = 8000;
    private static final int BYTES_PER_SECOND = RATE * 2;

    private static final int ACT_PLAY = 1;
    private static final int ACT_CALLBACK = 2;
    private static final int ACT_DELETE = 3;
    private static final int ACT_REFRESH = 4;

    private TelcoHttp http;
    private InboxView view;

    private final List<TelcoVoicemailStore.Item> voicemails =
            new ArrayList<TelcoVoicemailStore.Item>();
    private int selected = -1;
    private String status = "Loading...";
    private boolean busy;

    private Player player;
    private long playingId = -1;

    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN);
        http = new TelcoHttp(this);
        view = new InboxView(this);
        setContentView(view);
        load();
        Log.i(TAG, "N3DS_TELCO_VOICEMAIL_UI_READY");
    }

    protected void onPause() {
        stopPlayback();
        super.onPause();
    }

    // ---- network -------------------------------------------------------

    private void load() {
        // What is saved is shown at once; the network only adds to it.
        populate(TelcoVoicemailStore.list());
        busy = true;
        view.invalidate();
        new Thread(new Runnable() {
            public void run() {
                String failure = null;
                try {
                    TelcoVoicemailStore.sync(http,
                            getSharedPreferences("n3ds_telco_state", MODE_PRIVATE));
                } catch (Exception error) {
                    failure = message(error, "Could not check for new voicemail.");
                }
                final String problem = failure;
                final List<TelcoVoicemailStore.Item> saved = TelcoVoicemailStore.list();
                post(new Runnable() {
                    public void run() {
                        populate(saved);
                        if (problem != null) status = status + " (offline: " + problem + ")";
                        view.invalidate();
                    }
                });
            }
        }, "3DSTelco-voicemail-load").start();
    }

    private void post(Runnable r) {
        runOnUiThread(r);
    }

    private void populate(List<TelcoVoicemailStore.Item> fetched) {
        busy = false;
        voicemails.clear();
        voicemails.addAll(fetched);
        if (selected >= voicemails.size()) selected = -1;
        int unread = 0;
        for (int i = 0; i < voicemails.size(); i++) {
            if (!voicemails.get(i).read) unread++;
        }
        if (voicemails.isEmpty()) {
            status = "No voicemail.";
        } else {
            status = voicemails.size() + (voicemails.size() == 1 ? " message" : " messages")
                    + (unread > 0 ? ", " + unread + " new" : "") + ", saved on this 3DS";
        }
        view.invalidate();
    }

    /** Applied here at once; the server is told when it can be reached. */
    private void delete(final TelcoVoicemailStore.Item item) {
        stopPlayback();
        TelcoVoicemailStore.delete(item.id);
        selected = -1;
        populate(TelcoVoicemailStore.list());
        status = "Deleted.";
        new Thread(new Runnable() {
            public void run() {
                try {
                    http.request("DELETE", "/v1/voicemails/" + item.id, null, true);
                } catch (Exception error) {
                    Log.w(TAG, "N3DS_TELCO_VOICEMAIL_SERVER_DELETE_FAILED id=" + item.id + ": " + error);
                }
            }
        }, "3DSTelco-voicemail-delete").start();
    }

    private void play(final TelcoVoicemailStore.Item item) {
        stopPlayback();
        byte[] audio;
        try {
            audio = TelcoVoicemailStore.audio(item);
        } catch (Exception error) {
            status = message(error, "Could not read the saved message.");
            view.invalidate();
            return;
        }
        if (!item.read) {
            item.read = true;
            TelcoVoicemailStore.markRead(item.id);
            new Thread(new Runnable() {
                public void run() {
                    try {
                        http.request("POST", "/v1/voicemails/" + item.id + "/read",
                                new JSONObject(), true);
                    } catch (Exception ignored) {
                        Log.w(TAG, "N3DS_TELCO_VOICEMAIL_MARK_READ_FAILED id=" + item.id);
                    }
                }
            }, "3DSTelco-voicemail-read").start();
        }
        startPlayback(item.id, audio);
    }

    private void startPlayback(long id, byte[] pcm) {
        busy = false;
        try {
            player = new Player(pcm);
            player.start();
            playingId = id;
            status = "Playing.";
        } catch (Throwable t) {
            // LinkageError included: there is no DSP-backed AudioTrack yet.
            Log.w(TAG, "N3DS_TELCO_AUDIO_UNAVAILABLE: " + t);
            player = null;
            playingId = -1;
            status = "Audio output is unavailable right now.";
        }
        view.invalidate();
    }

    private void stopPlayback() {
        if (player != null) {
            player.stop();
            player = null;
        }
        playingId = -1;
    }

    private void callBack(String number) {
        if (number == null || !number.matches("(?:[1-9][0-9]{2,3}|[2-9][0-9]{9})")) {
            status = "That message has no dialable 3DSTelco number.";
            view.invalidate();
            return;
        }
        stopPlayback();
        Intent intent = new Intent(CALL_ACTION, Uri.fromParts("tel", number, null));
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(intent);
    }

    private static String message(Exception error, String fallback) {
        return error.getMessage() == null ? fallback : error.getMessage();
    }

    private void vibrate() {
        try {
            Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (v != null) v.vibrate(35);
        } catch (RuntimeException e) {
            Log.w(TAG, "N3DS_TELCO_VIBRATOR_UNAVAILABLE: " + e);
        }
    }

    private void onAction(int action) {
        vibrate();
        if (action == ACT_REFRESH) {
            stopPlayback();
            load();
            return;
        }
        if (selected < 0 || selected >= voicemails.size()) return;
        TelcoVoicemailStore.Item item = voicemails.get(selected);
        switch (action) {
            case ACT_PLAY:
                if (player != null && playingId == item.id) {
                    stopPlayback();
                    status = "Stopped.";
                } else {
                    play(item);
                }
                break;
            case ACT_CALLBACK:
                callBack(item.from);
                break;
            case ACT_DELETE:
                delete(item);
                break;
            default:
                break;
        }
        view.invalidate();
    }

    // ---- playback ------------------------------------------------------

    /**
     * Streams the fetched PCM through an AudioTrack from a byte offset that
     * seeking can move.
     *
     * MODE_STREAM rather than MODE_STATIC: static mode would need the whole
     * clip resident in the track's buffer and gives no way to restart from a
     * new offset without rewriting it, and a 60-second mailbox message is
     * ~960 KB on a 246 MB device.
     */
    private final class Player {
        private final byte[] pcm;
        private volatile int offset;
        private volatile boolean running;
        private AudioTrack track;

        Player(byte[] data) {
            pcm = data == null ? new byte[0] : data;
        }

        void start() {
            int min = AudioTrack.getMinBufferSize(RATE,
                    AudioFormat.CHANNEL_CONFIGURATION_MONO, AudioFormat.ENCODING_PCM_16BIT);
            track = new AudioTrack(AudioManager.STREAM_MUSIC, RATE,
                    AudioFormat.CHANNEL_CONFIGURATION_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    Math.max(min, 4096), AudioTrack.MODE_STREAM);
            if (track.getState() != AudioTrack.STATE_INITIALIZED) {
                track.release();
                track = null;
                throw new IllegalStateException("3DS audio could not initialize for playback.");
            }
            running = true;
            track.play();
            new Thread(new Runnable() {
                public void run() { pump(); }
            }, "3DSTelco-voicemail-play").start();
        }

        private void pump() {
            byte[] chunk = new byte[1600];
            while (running && offset < pcm.length) {
                int count = Math.min(chunk.length, pcm.length - offset);
                System.arraycopy(pcm, offset, chunk, 0, count);
                int written;
                try {
                    written = track.write(chunk, 0, count);
                } catch (Throwable t) {
                    break;
                }
                if (written <= 0) break;
                offset += written;
            }
            running = false;
            post(new Runnable() {
                public void run() {
                    if (player == Player.this) {
                        stopPlayback();
                        status = "Finished.";
                        view.invalidate();
                    }
                }
            });
        }

        void seekFraction(float fraction) {
            if (pcm.length == 0) return;
            if (fraction < 0) fraction = 0;
            if (fraction > 1) fraction = 1;
            // Snap to a frame boundary: a byte-odd offset would swap the
            // high and low halves of every sample and play as loud noise.
            int target = (int) (pcm.length * fraction) & ~1;
            offset = target;
            try {
                if (track != null) track.flush();
            } catch (Throwable ignored) {
            }
        }

        float progress() {
            return pcm.length == 0 ? 0f : (float) offset / (float) pcm.length;
        }

        long positionSeconds() { return offset / BYTES_PER_SECOND; }

        long totalSeconds() { return pcm.length / BYTES_PER_SECOND; }

        void stop() {
            running = false;
            try { if (track != null) track.stop(); } catch (Throwable ignored) {}
            try { if (track != null) track.release(); } catch (Throwable ignored) {}
            track = null;
        }
    }

    // ---- the screen ----------------------------------------------------

    private static final class ActionButton {
        final RectF bounds = new RectF();
        int id;
        String label;
        int color;
    }

    private final class InboxView extends View {
        private final Paint bg = TelcoTheme.fill(TelcoTheme.BG);
        private final Paint panel = TelcoTheme.fill(TelcoTheme.SURFACE);
        private final Paint panelHi = TelcoTheme.fill(TelcoTheme.SURFACE_HI);
        private final Paint divider = TelcoTheme.fill(TelcoTheme.DIVIDER);
        private final Paint accent = TelcoTheme.fill(TelcoTheme.ACCENT);
        private final Paint unreadDot = TelcoTheme.fill(TelcoTheme.CALL_HI);
        private final Paint surface = TelcoTheme.fill(TelcoTheme.SURFACE);
        private final Paint titlePaint =
                TelcoTheme.text(TelcoTheme.TEXT, 14f, Paint.Align.LEFT, false);
        private final Paint subPaint =
                TelcoTheme.text(TelcoTheme.TEXT_DIM, 9f, Paint.Align.LEFT, false);
        private final Paint metaPaint =
                TelcoTheme.text(TelcoTheme.TEXT_DIM, 9f, Paint.Align.RIGHT, false);
        private final Paint headPaint =
                TelcoTheme.text(TelcoTheme.TEXT, 15f, Paint.Align.LEFT, false);
        private final Paint statusPaint =
                TelcoTheme.text(TelcoTheme.TEXT_DIM, 9f, Paint.Align.LEFT, false);
        private final Paint buttonTextPaint =
                TelcoTheme.text(TelcoTheme.TEXT, 9f, Paint.Align.CENTER, false);

        private final List<ActionButton> actions = new ArrayList<ActionButton>();
        private final RectF header = new RectF();
        private final RectF listBounds = new RectF();
        private final RectF barBounds = new RectF();
        private final RectF actionBounds = new RectF();
        private final RectF refreshBounds = new RectF();
        private final RectF scratch = new RectF();

        private float rowHeight = 30f;
        private float scroll;
        private float maxScroll;

        private int pressedRow = -1;
        private int pressedAction = -1;
        private boolean pressedRefresh;
        private boolean scrolling;
        private boolean draggingBar;
        private float downY;
        private float downScroll;

        InboxView(Context context) {
            super(context);
            setFocusable(true);
            setBackgroundColor(TelcoTheme.BG);
        }

        protected void onSizeChanged(int w, int h, int ow, int oh) {
            float headerHeight = h * 0.17f;
            float actionHeight = h * 0.17f;
            float barHeight = h * 0.11f;
            header.set(0, 0, w, headerHeight);
            refreshBounds.set(w - w * 0.28f, 4, w - 4, headerHeight - 4);
            barBounds.set(6, h - actionHeight - barHeight, w - 6, h - actionHeight);
            actionBounds.set(0, h - actionHeight, w, h);
            listBounds.set(0, headerHeight, w, barBounds.top);
            rowHeight = Math.max(22f, h * 0.155f);

            headPaint.setTextSize(headerHeight * 0.42f);
            statusPaint.setTextSize(Math.max(7f, headerHeight * 0.26f));
            titlePaint.setTextSize(rowHeight * 0.40f);
            subPaint.setTextSize(rowHeight * 0.28f);
            metaPaint.setTextSize(rowHeight * 0.28f);
            buttonTextPaint.setTextSize(Math.max(7f, actionHeight * 0.26f));
            recomputeScroll();
        }

        private void recomputeScroll() {
            maxScroll = Math.max(0, voicemails.size() * rowHeight - listBounds.height());
            if (scroll > maxScroll) scroll = maxScroll;
            if (scroll < 0) scroll = 0;
        }

        protected void onDraw(Canvas canvas) {
            recomputeScroll();
            rebuildActions();
            canvas.drawRect(0, 0, getWidth(), getHeight(), bg);

            // Header.
            canvas.drawRect(header, panel);
            canvas.drawRect(header.left, header.bottom - 1, header.right,
                    header.bottom, divider);
            canvas.drawText("Voicemail", 6, header.top + header.height() * 0.46f, headPaint);
            canvas.drawText(status, 6, header.bottom - header.height() * 0.16f, statusPaint);
            TelcoTheme.roundRect(canvas, refreshBounds, refreshBounds.height() * 0.25f,
                    pressedRefresh ? panelHi : surfaceFor(TelcoTheme.SURFACE_HI));
            buttonTextPaint.setColor(TelcoTheme.ACCENT);
            canvas.drawText(busy ? "..." : "REFRESH", refreshBounds.centerX(),
                    TelcoTheme.centeredBaseline(buttonTextPaint, refreshBounds.top,
                            refreshBounds.bottom),
                    buttonTextPaint);
            buttonTextPaint.setColor(TelcoTheme.TEXT);

            drawList(canvas);
            drawPlaybackBar(canvas);

            for (int i = 0; i < actions.size(); i++) {
                ActionButton b = actions.get(i);
                surface.setColor(i == pressedAction ? TelcoTheme.SURFACE_HI : b.color);
                TelcoTheme.roundRect(canvas, b.bounds, b.bounds.height() * 0.22f, surface);
                canvas.drawText(b.label, b.bounds.centerX(),
                        TelcoTheme.centeredBaseline(buttonTextPaint, b.bounds.top,
                                b.bounds.bottom),
                        buttonTextPaint);
            }
        }

        private Paint surfaceFor(int color) {
            surface.setColor(color);
            return surface;
        }

        private void drawList(Canvas canvas) {
            if (voicemails.isEmpty()) {
                canvas.drawText(busy ? "Loading..." : "Your mailbox is empty.", 8,
                        TelcoTheme.centeredBaseline(titlePaint, listBounds.top,
                                listBounds.bottom),
                        titlePaint);
                return;
            }
            canvas.save();
            canvas.clipRect(listBounds);
            float pad = rowHeight * 0.16f;
            for (int i = 0; i < voicemails.size(); i++) {
                float top = listBounds.top + i * rowHeight - scroll;
                float bottom = top + rowHeight;
                if (bottom < listBounds.top || top > listBounds.bottom) continue;
                TelcoVoicemailStore.Item item = voicemails.get(i);
                scratch.set(listBounds.left + 2, top + 1, listBounds.right - 2, bottom - 1);
                surface.setColor(i == pressedRow ? TelcoTheme.SURFACE_HI
                        : (i == selected ? TelcoTheme.SURFACE_HI : TelcoTheme.SURFACE));
                TelcoTheme.roundRect(canvas, scratch, rowHeight * 0.12f, surface);
                if (i == selected) {
                    canvas.drawRect(scratch.left, scratch.top, scratch.left + 2,
                            scratch.bottom, accent);
                }

                float textLeft = scratch.left + pad * 2;
                if (!item.read) {
                    canvas.drawCircle(scratch.left + pad, scratch.centerY(),
                            rowHeight * 0.08f, unreadDot);
                    textLeft = scratch.left + pad * 2.6f;
                }
                String from = item.from == null || item.from.length() == 0 ? "Unknown"
                        : TelcoNames.display(item.from);
                canvas.drawText(from, textLeft,
                        TelcoTheme.centeredBaseline(titlePaint, scratch.top,
                                scratch.centerY() + rowHeight * 0.06f),
                        titlePaint);

                int durationMs = item.durationMs;
                StringBuilder sub = new StringBuilder();
                if (durationMs > 0) sub.append(TelcoTheme.duration(durationMs / 1000));
                if (playingId == item.id) {
                    if (sub.length() > 0) sub.append("  -  ");
                    sub.append("playing");
                }
                canvas.drawText(sub.toString(), textLeft, scratch.bottom - pad, subPaint);
                canvas.drawText(relative(item), scratch.right - pad,
                        TelcoTheme.centeredBaseline(metaPaint, scratch.top, scratch.bottom),
                        metaPaint);
            }
            canvas.restore();

            if (maxScroll > 0) {
                float trackHeight = listBounds.height();
                float thumb = Math.max(trackHeight * 0.12f,
                        trackHeight * (trackHeight / (voicemails.size() * rowHeight)));
                float y = listBounds.top + (trackHeight - thumb) * (scroll / maxScroll);
                scratch.set(listBounds.right - 3, y, listBounds.right - 1, y + thumb);
                canvas.drawRect(scratch, divider);
            }
        }

        private String relative(TelcoVoicemailStore.Item item) {
            long when = item.createdAt;
            if (when <= 0) return "";
            long delta = System.currentTimeMillis() - when;
            if (delta < 0) delta = 0;
            long minutes = delta / 60000L;
            if (minutes < 1) return "Just now";
            if (minutes < 60) return minutes + " min ago";
            long hours = minutes / 60;
            if (hours < 24) return hours + (hours == 1 ? " hr ago" : " hrs ago");
            long days = hours / 24;
            if (days < 7) return days + (days == 1 ? " day ago" : " days ago");
            return android.text.format.DateFormat.format("MM/dd HH:mm", when).toString();
        }

        private void drawPlaybackBar(Canvas canvas) {
            canvas.drawRect(barBounds.left, barBounds.top, barBounds.right,
                    barBounds.bottom, panel);
            if (player == null) {
                metaPaint.setTextAlign(Paint.Align.CENTER);
                canvas.drawText("Select a message, then PLAY.", barBounds.centerX(),
                        TelcoTheme.centeredBaseline(metaPaint, barBounds.top,
                                barBounds.bottom),
                        metaPaint);
                metaPaint.setTextAlign(Paint.Align.RIGHT);
                return;
            }
            float inset = barBounds.height() * 0.30f;
            scratch.set(barBounds.left + 4, barBounds.centerY() - inset * 0.35f,
                    barBounds.right - 4, barBounds.centerY() + inset * 0.35f);
            canvas.drawRect(scratch, panelHi);
            float filled = scratch.left + scratch.width() * player.progress();
            canvas.drawRect(scratch.left, scratch.top, filled, scratch.bottom, accent);
            subPaint.setColor(TelcoTheme.TEXT_DIM);
            canvas.drawText(TelcoTheme.duration(player.positionSeconds()) + " / "
                            + TelcoTheme.duration(player.totalSeconds()),
                    barBounds.left + 4, barBounds.bottom - 2, subPaint);
        }

        private void rebuildActions() {
            actions.clear();
            boolean hasSelection = selected >= 0 && selected < voicemails.size();
            boolean playingThis = hasSelection && player != null
                    && playingId == voicemails.get(selected).id;
            add(ACT_PLAY, playingThis ? "STOP" : "PLAY",
                    hasSelection ? TelcoTheme.CALL : TelcoTheme.SURFACE);
            add(ACT_CALLBACK, "CALL BACK",
                    hasSelection ? TelcoTheme.SURFACE_HI : TelcoTheme.SURFACE);
            add(ACT_DELETE, "DELETE",
                    hasSelection ? TelcoTheme.DANGER : TelcoTheme.SURFACE);

            float gap = Math.max(3f, actionBounds.height() * 0.14f);
            int n = actions.size();
            float width = (actionBounds.width() - gap * (n + 1)) / n;
            for (int i = 0; i < n; i++) {
                float left = actionBounds.left + gap + i * (width + gap);
                actions.get(i).bounds.set(left, actionBounds.top + gap,
                        left + width, actionBounds.bottom - gap);
            }
        }

        private void add(int id, String label, int color) {
            ActionButton b = new ActionButton();
            b.id = id;
            b.label = label;
            b.color = color;
            actions.add(b);
        }

        public boolean onTouchEvent(MotionEvent event) {
            float x = event.getX();
            float y = event.getY();
            switch (event.getAction()) {
                case MotionEvent.ACTION_DOWN:
                    downY = y;
                    downScroll = scroll;
                    scrolling = false;
                    pressedRow = -1;
                    pressedAction = -1;
                    pressedRefresh = false;
                    draggingBar = false;
                    if (refreshBounds.contains(x, y)) {
                        pressedRefresh = true;
                    } else if (barBounds.contains(x, y)) {
                        draggingBar = player != null;
                        if (draggingBar) seekTo(x);
                    } else if (actionBounds.contains(x, y)) {
                        pressedAction = actionIndexAt(x, y);
                    } else if (listBounds.contains(x, y)) {
                        pressedRow = rowIndexAt(y);
                    }
                    invalidate();
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    if (draggingBar) {
                        seekTo(x);
                        invalidate();
                        return true;
                    }
                    float dy = y - downY;
                    if (!scrolling && pressedRow >= 0 && Math.abs(dy) > rowHeight * 0.35f) {
                        scrolling = true;
                        pressedRow = -1;
                    }
                    if (scrolling) {
                        scroll = downScroll - dy;
                        if (scroll < 0) scroll = 0;
                        if (scroll > maxScroll) scroll = maxScroll;
                        invalidate();
                    }
                    return true;
                }
                case MotionEvent.ACTION_UP: {
                    int row = pressedRow;
                    int action = pressedAction;
                    boolean refresh = pressedRefresh;
                    boolean wasScrolling = scrolling;
                    pressedRow = -1;
                    pressedAction = -1;
                    pressedRefresh = false;
                    draggingBar = false;
                    scrolling = false;
                    if (!wasScrolling) {
                        if (refresh && refreshBounds.contains(x, y)) {
                            onAction(ACT_REFRESH);
                        } else if (action >= 0 && action < actions.size()
                                && actions.get(action).bounds.contains(x, y)) {
                            onAction(actions.get(action).id);
                        } else if (row >= 0 && row < voicemails.size()) {
                            // Tap selects; the destructive choices live in the
                            // action bar rather than behind a long press.
                            vibrate();
                            selected = (selected == row) ? -1 : row;
                        }
                    }
                    invalidate();
                    return true;
                }
                case MotionEvent.ACTION_CANCEL:
                    pressedRow = -1;
                    pressedAction = -1;
                    pressedRefresh = false;
                    draggingBar = false;
                    scrolling = false;
                    invalidate();
                    return true;
                default:
                    return true;
            }
        }

        private void seekTo(float x) {
            if (player == null) return;
            float fraction = (x - (barBounds.left + 4))
                    / Math.max(1f, barBounds.width() - 8);
            player.seekFraction(fraction);
        }

        private int rowIndexAt(float y) {
            int index = (int) ((y - listBounds.top + scroll) / rowHeight);
            return (index >= 0 && index < voicemails.size()) ? index : -1;
        }

        private int actionIndexAt(float x, float y) {
            for (int i = 0; i < actions.size(); i++) {
                if (actions.get(i).bounds.contains(x, y)) return i;
            }
            return -1;
        }
    }
}
