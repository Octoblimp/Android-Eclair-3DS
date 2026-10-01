/*
 * The 3DSTelco call screen: outgoing, incoming and connected.
 *
 * N3DS_TELCO_INCALL_UI (2026-09-11). What this replaces: a vertical
 * LinearLayout with a TextView and three stock Buttons, whose only knowledge
 * of call state came from substring-matching the English prose in the
 * ACTION_STATE broadcast ("ended", "rejected", "connected"). TelcoService now
 * publishes a stable TelcoContract.EVENT_* key on that broadcast, so this
 * screen keys off the event and uses the prose purely as a caption.
 *
 * Drawn with Canvas/Paint for the same reason the dialer is: the 320x240
 * bottom panel and its imprecise resistive digitizer want deliberately large,
 * hand-placed targets, and stock widgets on a 2009 framework give neither.
 *
 * Honest framing, and it is stated on screen rather than hidden: this device
 * has no cellular radio and no RIL. rild is never started. A "call" is a UDP
 * PCM session to the io.divergen.telco relay over Wi-Fi, and a "number" is a
 * 3-4 digit device id. The screen says "3DSTelco over Wi-Fi" and never
 * imitates a carrier.
 *
 * Controls, and why these and not the stock set:
 *  - MUTE is real: it zeroes the outgoing PCM in VoipSession.
 *  - There is no SPEAKER button (#325).  The 3DS has no earpiece, audio is
 *    always on the speakers, and with no AudioService on this build the old
 *    LOUD/QUIET toggle could only ever report that it had failed.
 *  - There is no HOLD and no in-call dialpad. The relay has no hold endpoint,
 *    and DTMF would need ToneGenerator, whose native backend is absent on
 *    this build (it is what used to crash the old dialer). Shipping dead
 *    buttons would be worse than not shipping them.
 *
 * N3DS_TELCO_RETURN_TO_CALL (#325): the screen restores the live call from
 * TelcoCallState on every resume, so leaving it mid-call is no longer
 * leaving the call behind.  TelcoService's ongoing "call in progress"
 * notification, and the dialer, reopen it with ACTION_SHOW_CALL; opening it
 * for a new number while a call is up shows that call instead of dialling.
 *
 * N3DS_TELCO_INCOMING_TAKEOVER: an incoming call shows over the lock screen,
 * turns the screen on, and BACK cannot dismiss it -- ANSWER or DECLINE.
 */
package com.android.phone;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.Bundle;
import android.os.Handler;
import android.os.SystemClock;
import android.os.Vibrator;
import android.util.Log;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;

import java.util.ArrayList;
import java.util.List;

public final class TelcoCallActivity extends Activity {
    private static final String TAG = "TelcoCall";

    // Call phases. Named rather than inferred from button enabled-ness, which
    // is what the previous version did.
    private static final int PHASE_DIALING = 0;
    private static final int PHASE_RINGING_IN = 1;
    private static final int PHASE_CONNECTED = 2;
    private static final int PHASE_FINISHED = 3;

    // Button ids.
    private static final int BTN_ANSWER = 1;
    private static final int BTN_DECLINE = 2;
    private static final int BTN_END = 3;
    private static final int BTN_MUTE = 4;
    private static final int BTN_VOICEMAIL = 6;
    private static final int BTN_CLOSE = 7;

    /** Bring the current call back to the front; never starts one. */
    static final String ACTION_SHOW_CALL = "io.divergen.telco.action.SHOW_CALL";

    static Intent showIntent(Context context) {
        Intent intent = new Intent(context, TelcoCallActivity.class);
        intent.setAction(ACTION_SHOW_CALL);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return intent;
    }

    private CallView view;
    private String callId;
    private String peer;
    private boolean incoming;
    private int phase = PHASE_DIALING;
    private String caption = "";
    private boolean muted;
    private long connectedAtMs;

    private final Handler ticker = new Handler();
    private final Runnable tick = new Runnable() {
        public void run() {
            if (phase == PHASE_CONNECTED) {
                view.invalidate();
                ticker.postDelayed(this, 1000);
            }
        }
    };

    private final BroadcastReceiver updates = new BroadcastReceiver() {
        public void onReceive(Context context, Intent intent) {
            String message = intent.getStringExtra(TelcoContract.EXTRA_MESSAGE);
            String event = intent.getStringExtra(TelcoContract.EXTRA_EVENT);
            String id = intent.getStringExtra(TelcoContract.EXTRA_CALL_ID);
            String who = intent.getStringExtra(TelcoContract.EXTRA_PEER);
            if (id != null) callId = id;
            if (who != null && who.length() > 0) peer = who;
            if (message != null) caption = message;

            if (TelcoContract.EVENT_CONNECTED.equals(event)) {
                setPhase(PHASE_CONNECTED);
            } else if (TelcoContract.EVENT_ENDED.equals(event)
                    || TelcoContract.EVENT_REJECTED.equals(event)) {
                setPhase(PHASE_FINISHED);
            } else if (TelcoContract.EVENT_INCOMING.equals(event)) {
                incoming = true;
                setPhase(PHASE_RINGING_IN);
            } else if (TelcoContract.EVENT_OUTGOING.equals(event)) {
                setPhase(PHASE_DIALING);
            }
            view.invalidate();
        }
    };

    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN);
        // A call screen that the screen timeout blanks mid-call is unusable,
        // and there is no proximity sensor here to take over.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        // N3DS_TELCO_INCOMING_TAKEOVER: a ringing call is answered from here,
        // so it has to be able to reach the user past a blank or locked screen.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD);
        view = new CallView(this);
        setContentView(view);
        configure(getIntent());
        Log.i(TAG, "N3DS_TELCO_CALL_UI_READY incoming=" + incoming);
    }

    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        configure(intent);
    }

    protected void onResume() {
        super.onResume();
        registerReceiver(updates, new IntentFilter(TelcoContract.ACTION_STATE),
                TelcoContract.ACCESS_PERMISSION, null);
        // Broadcasts sent while paused were missed; catch up.
        syncFromService();
        if (phase == PHASE_CONNECTED) ticker.postDelayed(tick, 1000);
        view.invalidate();
    }

    /**
     * Adopts TelcoService's view of the call.  An active call there is the
     * truth; no call there while this screen still shows one (other than a
     * just-dialled call the service has not registered yet) means it ended
     * while we were not listening.
     */
    private void syncFromService() {
        TelcoCallState call = TelcoCallState.current();
        if (call.active()) {
            callId = call.callId;
            if (call.peer != null && call.peer.length() > 0) peer = call.peer;
            incoming = call.incoming;
            muted = call.muted;
            if (call.phase == TelcoCallState.CONNECTED) {
                connectedAtMs = call.connectedAtMs;
                if (phase != PHASE_CONNECTED) {
                    phase = PHASE_CONNECTED;
                    ticker.removeCallbacks(tick);
                }
            } else if (call.phase == TelcoCallState.RINGING_IN) {
                setPhase(PHASE_RINGING_IN);
            } else {
                setPhase(PHASE_DIALING);
            }
        } else if (phase == PHASE_CONNECTED || phase == PHASE_RINGING_IN
                || (phase == PHASE_DIALING && callId != null)) {
            caption = "Call ended";
            setPhase(PHASE_FINISHED);
        }
    }

    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // N3DS_TELCO_INCOMING_TAKEOVER: ANSWER or DECLINE, not BACK.
        if (keyCode == KeyEvent.KEYCODE_BACK && phase == PHASE_RINGING_IN) return true;
        return super.onKeyDown(keyCode, event);
    }

    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && phase == PHASE_RINGING_IN) return true;
        return super.onKeyUp(keyCode, event);
    }

    protected void onPause() {
        ticker.removeCallbacks(tick);
        unregisterReceiver(updates);
        super.onPause();
    }

    private void setPhase(int value) {
        if (phase == value) return;
        phase = value;
        ticker.removeCallbacks(tick);
        if (phase == PHASE_CONNECTED) {
            connectedAtMs = SystemClock.elapsedRealtime();
            ticker.postDelayed(tick, 1000);
        }
        view.invalidate();
    }

    private void configure(Intent intent) {
        TelcoCallState live = TelcoCallState.current();
        String number = intent.getData() == null
                ? null : intent.getData().getSchemeSpecificPart();
        if (number == null) number = intent.getStringExtra("number");
        boolean wantsIncoming = intent.getBooleanExtra("incoming", false);

        // N3DS_TELCO_RETURN_TO_CALL: "show the call", or anything at all while
        // a call is up, shows the live call.  It never dials a second one.
        if (ACTION_SHOW_CALL.equals(intent.getAction()) || (!wantsIncoming && number == null)
                || (live.active() && !wantsIncoming)) {
            if (!live.active()) {
                Log.i(TAG, "N3DS_TELCO_RETURN_TO_CALL: no call in progress");
                callId = null;
                caption = "No call in progress";
                setPhase(PHASE_FINISHED);
                view.invalidate();
                return;
            }
            if (number != null && !number.equals(live.peer)) {
                Log.i(TAG, "N3DS_TELCO_RETURN_TO_CALL: already on a call; not dialling " + number);
                caption = "Already on a call";
            }
            syncFromService();
            view.invalidate();
            return;
        }

        incoming = wantsIncoming;
        callId = intent.getStringExtra("call_id");
        peer = intent.getStringExtra("peer");
        muted = false;
        if (incoming) {
            setPhase(PHASE_RINGING_IN);
            caption = "Incoming call";
            view.invalidate();
            return;
        }

        if (TelcoContract.VOICEMAIL_NUMBER.equals(number)) {
            // Dialling the mailbox opens the mailbox; it is not a call.
            startActivity(new Intent(this, VoicemailActivity.class));
            finish();
            return;
        }
        peer = number;
        setPhase(PHASE_DIALING);
        caption = "Dialing";
        Intent service = new Intent(this, TelcoService.class);
        service.setAction(TelcoContract.ACTION_CALL);
        service.putExtra("number", number);
        startService(service);
        view.invalidate();
    }

    private void vibrate() {
        try {
            Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (v != null) v.vibrate(35);
        } catch (RuntimeException e) {
            Log.w(TAG, "N3DS_TELCO_VIBRATOR_UNAVAILABLE: " + e);
        }
    }

    private void onButton(int id) {
        vibrate();
        switch (id) {
            case BTN_ANSWER:
                caption = "Answering";
                send(TelcoContract.ACTION_ANSWER);
                break;
            case BTN_DECLINE:
                caption = "Declining";
                setPhase(PHASE_FINISHED);
                send(TelcoContract.ACTION_REJECT);
                break;
            case BTN_END:
                caption = "Hanging up";
                setPhase(PHASE_FINISHED);
                send(incoming && phase == PHASE_RINGING_IN
                        ? TelcoContract.ACTION_REJECT : TelcoContract.ACTION_END);
                break;
            case BTN_VOICEMAIL:
                caption = "Leaving a voicemail";
                send(TelcoContract.ACTION_LEAVE_VOICEMAIL);
                break;
            case BTN_MUTE:
                muted = !muted;
                if (callId != null) {
                    Intent mute = new Intent(this, TelcoService.class);
                    mute.setAction(TelcoContract.ACTION_MUTE);
                    mute.putExtra("muted", muted);
                    startService(mute);
                }
                break;
            case BTN_CLOSE:
                finish();
                break;
            default:
                break;
        }
        view.invalidate();
    }

    private void send(String action) {
        if (callId == null) {
            caption = "That call is no longer active";
            return;
        }
        Intent service = new Intent(this, TelcoService.class);
        service.setAction(action);
        service.putExtra("call_id", callId);
        startService(service);
    }

    // ---- the screen ---------------------------------------------------

    private static final class Button {
        final RectF bounds = new RectF();
        int id;
        String label;
        int color;
        int pressedColor;
        int textColor;
        /** 0 none, 1 handset, 2 handset-down, 3 microphone, 4 speaker. */
        int icon;
        boolean on;
    }

    private final class CallView extends View {
        private final List<Button> buttons = new ArrayList<Button>();

        private final Paint bg = TelcoTheme.fill(TelcoTheme.BG);
        private final Paint panel = TelcoTheme.fill(TelcoTheme.SURFACE);
        private final Paint divider = TelcoTheme.fill(TelcoTheme.DIVIDER);
        private final Paint work = TelcoTheme.fill(TelcoTheme.TEXT);
        private final Paint surface = TelcoTheme.fill(TelcoTheme.SURFACE);
        private final Paint namePaint =
                TelcoTheme.text(TelcoTheme.TEXT, 22f, Paint.Align.CENTER, false);
        private final Paint statePaint =
                TelcoTheme.text(TelcoTheme.TEXT_DIM, 11f, Paint.Align.CENTER, false);
        private final Paint timerPaint =
                TelcoTheme.text(TelcoTheme.CALL_HI, 16f, Paint.Align.CENTER, false);
        private final Paint footerPaint =
                TelcoTheme.text(TelcoTheme.TEXT_DIM, 8f, Paint.Align.CENTER, false);
        private final Paint buttonTextPaint =
                TelcoTheme.text(TelcoTheme.TEXT, 9f, Paint.Align.CENTER, false);

        private final RectF header = new RectF();
        private final RectF controls = new RectF();
        private final RectF footer = new RectF();
        private final RectF scratch = new RectF();
        private final RectF iconRect = new RectF();

        private int latched = -1;

        CallView(Context context) {
            super(context);
            setFocusable(true);
            setBackgroundColor(TelcoTheme.BG);
        }

        protected void onSizeChanged(int w, int h, int ow, int oh) {
            header.set(0, 0, w, h * 0.46f);
            controls.set(0, header.bottom, w, h * 0.90f);
            footer.set(0, controls.bottom, w, h);
            namePaint.setTextSize(h * 0.11f);
            statePaint.setTextSize(h * 0.055f);
            timerPaint.setTextSize(h * 0.075f);
            footerPaint.setTextSize(Math.max(7f, h * 0.036f));
            buttonTextPaint.setTextSize(Math.max(7f, h * 0.042f));
        }

        protected void onDraw(Canvas canvas) {
            rebuildButtons();
            canvas.drawRect(0, 0, getWidth(), getHeight(), bg);

            canvas.drawRect(header, panel);
            canvas.drawRect(header.left, header.bottom - 1, header.right,
                    header.bottom, divider);

            // N3DS_TELCO_CONTACT_NAMES: a saved contact shows by name, with
            // the number beside the phase; TelcoNames caches the lookup.
            String name = TelcoNames.lookup(peer);
            String title = (peer == null || peer.length() == 0) ? "3DSTelco"
                    : (name != null ? name : TelcoNames.formatNumber(peer));
            canvas.drawText(title, header.centerX(),
                    header.top + header.height() * 0.42f, namePaint);
            String label = name != null ? phaseLabel() + "  -  " + TelcoNames.formatNumber(peer)
                    : phaseLabel();
            canvas.drawText(label, header.centerX(),
                    header.top + header.height() * 0.62f, statePaint);
            if (phase == PHASE_CONNECTED) {
                long seconds = (SystemClock.elapsedRealtime() - connectedAtMs) / 1000L;
                canvas.drawText(TelcoTheme.duration(seconds), header.centerX(),
                        header.top + header.height() * 0.85f, timerPaint);
            } else if (caption != null && caption.length() > 0) {
                canvas.drawText(caption, header.centerX(),
                        header.top + header.height() * 0.85f, statePaint);
            }

            for (int i = 0; i < buttons.size(); i++) {
                drawButton(canvas, buttons.get(i), i == latched);
            }

            canvas.drawText("3DSTelco over Wi-Fi. No cellular radio.",
                    footer.centerX(),
                    TelcoTheme.centeredBaseline(footerPaint, footer.top,
                            footer.centerY()),
                    footerPaint);
            canvas.drawText("The 3DS has no earpiece: audio is on the speakers.",
                    footer.centerX(),
                    TelcoTheme.centeredBaseline(footerPaint, footer.centerY(),
                            footer.bottom),
                    footerPaint);
        }

        private String phaseLabel() {
            switch (phase) {
                case PHASE_RINGING_IN: return "Incoming call";
                case PHASE_CONNECTED: return muted ? "Connected  -  muted" : "Connected";
                case PHASE_FINISHED: return "Call ended";
                default: return "Dialing";
            }
        }

        private void drawButton(Canvas canvas, Button b, boolean pressed) {
            scratch.set(b.bounds);
            float radius = scratch.height() * 0.22f;
            surface.setColor(pressed ? b.pressedColor : b.color);
            TelcoTheme.roundRect(canvas, scratch, radius, surface);

            float iconSize = scratch.height() * 0.34f;
            float labelY = scratch.bottom - scratch.height() * 0.14f;
            if (b.icon != 0) {
                iconRect.set(scratch.centerX() - iconSize / 2,
                        scratch.top + scratch.height() * 0.20f,
                        scratch.centerX() + iconSize / 2,
                        scratch.top + scratch.height() * 0.20f + iconSize);
                switch (b.icon) {
                    case 1: TelcoTheme.handset(canvas, iconRect, b.textColor, false, work); break;
                    case 2: TelcoTheme.handset(canvas, iconRect, b.textColor, true, work); break;
                    case 3: TelcoTheme.microphone(canvas, iconRect, b.textColor, b.on, work); break;
                    case 4: TelcoTheme.speaker(canvas, iconRect, b.textColor, b.on, work); break;
                    default: break;
                }
            } else {
                labelY = TelcoTheme.centeredBaseline(buttonTextPaint,
                        scratch.top, scratch.bottom);
            }
            buttonTextPaint.setColor(b.textColor);
            canvas.drawText(b.label, scratch.centerX(), labelY, buttonTextPaint);
            buttonTextPaint.setColor(TelcoTheme.TEXT);
        }

        /*
         * Rebuilt on every draw rather than cached: the control set is a pure
         * function of the phase, and rebuilding a handful of objects is far
         * cheaper than the bugs that come from a stale cached layout after a
         * phase change arrives from a broadcast.
         */
        private void rebuildButtons() {
            buttons.clear();
            switch (phase) {
                case PHASE_RINGING_IN:
                    add(BTN_DECLINE, "DECLINE", TelcoTheme.DANGER, TelcoTheme.DANGER_HI, 2, false);
                    add(BTN_ANSWER, "ANSWER", TelcoTheme.CALL, TelcoTheme.CALL_HI, 1, false);
                    break;
                case PHASE_CONNECTED:
                    add(BTN_MUTE, muted ? "UNMUTE" : "MUTE",
                            muted ? TelcoTheme.SURFACE_HI : TelcoTheme.SURFACE,
                            TelcoTheme.SURFACE_HI, 3, muted);
                    add(BTN_END, "END", TelcoTheme.DANGER, TelcoTheme.DANGER_HI, 2, false);
                    break;
                case PHASE_FINISHED:
                    add(BTN_CLOSE, "CLOSE", TelcoTheme.SURFACE, TelcoTheme.SURFACE_HI, 0, false);
                    break;
                default:
                    // Dialing out: the callee may not pick up, so offer the
                    // mailbox alongside hanging up.
                    add(BTN_VOICEMAIL, "VOICEMAIL", TelcoTheme.SURFACE,
                            TelcoTheme.SURFACE_HI, 0, false);
                    add(BTN_END, "END", TelcoTheme.DANGER, TelcoTheme.DANGER_HI, 2, false);
                    break;
            }
            layoutButtons();
        }

        private void add(int id, String label, int color, int pressedColor, int icon,
                boolean on) {
            Button b = new Button();
            b.id = id;
            b.label = label;
            b.color = color;
            b.pressedColor = pressedColor;
            b.textColor = TelcoTheme.TEXT;
            b.icon = icon;
            b.on = on;
            buttons.add(b);
        }

        private void layoutButtons() {
            int n = buttons.size();
            if (n == 0) return;
            float gap = Math.max(3f, controls.height() * 0.08f);
            float width = (controls.width() - gap * (n + 1)) / n;
            float top = controls.top + gap;
            float bottom = controls.bottom - gap;
            for (int i = 0; i < n; i++) {
                float left = controls.left + gap + i * (width + gap);
                buttons.get(i).bounds.set(left, top, left + width, bottom);
            }
        }

        public boolean onTouchEvent(MotionEvent event) {
            float x = event.getX();
            float y = event.getY();
            switch (event.getAction()) {
                case MotionEvent.ACTION_DOWN:
                    latched = indexAt(x, y);
                    invalidate();
                    return true;
                case MotionEvent.ACTION_UP: {
                    int index = latched;
                    latched = -1;
                    invalidate();
                    // Unlike the dialpad, a press here is NOT allowed to fire
                    // from anywhere on the surface: ANSWER and END sit side by
                    // side and firing the wrong one cannot be undone. The
                    // target must still be the one that was latched, with a
                    // small allowance for the digitizer's drift.
                    if (index >= 0 && index < buttons.size()) {
                        RectF b = buttons.get(index).bounds;
                        float slopX = b.width() * 0.12f;
                        float slopY = b.height() * 0.12f;
                        if (x >= b.left - slopX && x <= b.right + slopX
                                && y >= b.top - slopY && y <= b.bottom + slopY) {
                            onButton(buttons.get(index).id);
                        }
                    }
                    return true;
                }
                case MotionEvent.ACTION_CANCEL:
                    latched = -1;
                    invalidate();
                    return true;
                default:
                    return true;
            }
        }

        private int indexAt(float x, float y) {
            for (int i = 0; i < buttons.size(); i++) {
                if (buttons.get(i).bounds.contains(x, y)) return i;
            }
            return -1;
        }
    }
}
