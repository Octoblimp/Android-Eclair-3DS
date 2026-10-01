/*
 * Android3DS standalone Dialer.
 *
 * Replaces the stock Eclair TwelveKeyDialer tab (and the touch-cell dialpad
 * that used to be grafted into it) with a single self-contained app sized
 * for the 3DS's 320x240 bottom screen. It owns its own digit entry, its own
 * keypad, its own call log, and routes outgoing calls through the same
 * 3DSTelco scheme Phone/Contacts already use.
 *
 * N3DS_DIALER_TABS (2026-09-11): Dialpad, Recents and Contacts are now three
 * panes of one View rather than separate Activities. Switching is a repaint,
 * which on this device is the difference between instant and ~1 s -- and it
 * also means the app keeps a single window, so the process is a much less
 * attractive target for AMS's process trimming.
 *
 * HONEST FRAMING, deliberately surfaced in the UI: there is no cellular
 * radio and no RIL on this device. rild is never started; the 3DS has no
 * modem. Every "call" here is a UDP voice session to the io.divergen.telco
 * service over Wi-Fi, and "numbers" are 3-4 digit device IDs. The header
 * says "3DSTelco over Wi-Fi" rather than imitating a carrier label.
 */
package com.android.n3dsdialer;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.os.Vibrator;
import android.util.Log;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.SoundEffectConstants;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class N3dsDialerActivity extends Activity {
    private static final String TAG = "N3dsDialer";
    private static final String CALL_ACTION = "io.divergen.telco.action.CALL";
    private static final String VOICEMAIL_NUMBER = "100";
    /** N3DS_TELCO_WEB_NUMBERS: 10 digits fits a web account number. */
    private static final int MAX_DIGITS = 10;
    private static final int REQUEST_PICK_CONTACT = 1;
    private static final int REQUEST_EDIT_CONTACT = 2;

    private static final int TAB_DIALPAD = 0;
    private static final int TAB_RECENTS = 1;
    private static final int TAB_CONTACTS = 2;
    private static final String[] TAB_LABELS = { "DIALPAD", "RECENTS", "CONTACTS" };

    /*
     * N3DS_DIALER_RETURN_TO_CALL (#325): the call screen used to be reachable
     * only from the screen itself, so a call left mid-way was lost.  Phone's
     * TelcoService now publishes the live call id in this setting; opening
     * the dialer during a call goes back to it (once per call, so BACK from
     * the call screen lands here instead of bouncing), and so does pressing
     * Call while one is up.
     */
    private static final String SETTING_CALL_ACTIVE = "n3ds_telco_call_active";
    private static final String SHOW_CALL_ACTION = "io.divergen.telco.action.SHOW_CALL";
    private static final String ACTION_MISSED_SEEN = "io.divergen.telco.action.MISSED_SEEN";
    /** Phone's missed-call and voicemail notifications open the Recents tab. */
    static final String EXTRA_TAB = "n3ds_tab";

    private DialerView mView;
    private DialerTones mTones;
    private String mReturnedForCall;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN);
        mTones = new DialerTones(this);
        mView = new DialerView();
        setContentView(mView);

        Intent intent = getIntent();
        String seed = numberFromIntent(intent);
        if (seed != null) {
            mView.setDigits(seed);
        }
        if (wantsRecents(intent)) mView.setTab(TAB_RECENTS);
        Log.i(TAG, "N3DS_DIALER_READY");
    }

    private static boolean wantsRecents(Intent intent) {
        return intent != null && "recents".equals(intent.getStringExtra(EXTRA_TAB));
    }

    @Override
    protected void onResume() {
        super.onResume();
        mTones.refresh();
        mView.resumed();
        mView.reload();
        String live = activeCall();
        if (live != null && !live.equals(mReturnedForCall)) {
            mReturnedForCall = live;
            returnToCall();
        }
    }

    @Override
    protected void onPause() {
        // Hand the STREAM_DTMF output back. This device mixes everything
        // down to one CSND channel, so a backgrounded dialer sitting on an
        // AudioTrack is not free, and re-acquiring it is one binder call.
        mTones.release();
        super.onPause();
    }

    @Override
    public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String seed = numberFromIntent(intent);
        if (seed != null) {
            mView.setDigits(seed);
            mView.setTab(TAB_DIALPAD);
        } else if (wantsRecents(intent)) {
            mView.setTab(TAB_RECENTS);
        }
    }

    private static String numberFromIntent(Intent intent) {
        if (intent == null) return null;
        Uri data = intent.getData();
        if (data == null) return null;
        String scheme = data.getSchemeSpecificPart();
        if (scheme == null) return null;
        StringBuilder digits = new StringBuilder();
        for (int i = 0; i < scheme.length(); i++) {
            char c = scheme.charAt(i);
            if (c >= '0' && c <= '9') digits.append(c);
        }
        return digits.length() > 0 ? digits.toString() : null;
    }

    @Override
    public void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        // N3DS_CONTACTS_MANAGE (#326): a saved, edited or deleted contact
        // lands back on the Contacts list, where the change is visible,
        // instead of dropping the number onto the dialpad.
        if (resultCode == RESULT_OK && (requestCode == REQUEST_PICK_CONTACT
                || requestCode == REQUEST_EDIT_CONTACT)) {
            mView.setTab(TAB_CONTACTS);
        }
        mView.reload();
    }

    private void openContactEditor() {
        Intent intent = new Intent(this, N3dsContactsActivity.class);
        // Seed the editor with whatever is on the pad: saving the number you
        // just typed is the common path, and it is the one that otherwise
        // needs the IME for digits as well as for the name.
        intent.putExtra(N3dsContactsActivity.EXTRA_SEED_NUMBER, mView.digits());
        startActivityForResult(intent, REQUEST_PICK_CONTACT);
    }

    private void openContactEditor(long id, String name, String number) {
        Intent intent = new Intent(this, N3dsContactsActivity.class);
        if (id >= 0) intent.putExtra(N3dsContactsActivity.EXTRA_CONTACT_ID, id);
        if (name != null) intent.putExtra(N3dsContactsActivity.EXTRA_NAME, name);
        intent.putExtra(N3dsContactsActivity.EXTRA_SEED_NUMBER, number);
        startActivityForResult(intent, id >= 0 ? REQUEST_EDIT_CONTACT : REQUEST_PICK_CONTACT);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        char c = digitForKeyCode(keyCode);
        if (c != 0) {
            // The hardware keypad gets the same tone the touch keypad
            // does; from the user's side it is the same key.
            mTones.playDigit(c);
            mView.setTab(TAB_DIALPAD);
            mView.appendDigit(c);
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_DEL) {
            click();
            mView.deleteLast();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    private static char digitForKeyCode(int keyCode) {
        if (keyCode >= KeyEvent.KEYCODE_0 && keyCode <= KeyEvent.KEYCODE_9) {
            return (char) ('0' + (keyCode - KeyEvent.KEYCODE_0));
        }
        return 0;
    }

    /**
     * The shared UI tap sound -- Effect_Tick.wav via AudioService's
     * SoundPool, not a tone. Silently does nothing if the user has
     * Settings.System.SOUND_EFFECTS_ENABLED off, which is the whole point
     * of going through AudioManager rather than playing it ourselves.
     */
    private void click() {
        if (mView != null) {
            mView.playSoundEffect(SoundEffectConstants.CLICK);
        }
    }

    private void vibrate() {
        try {
            Vibrator vibrator = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (vibrator != null) {
                vibrator.vibrate(35);
            }
        } catch (RuntimeException e) {
            Log.w(TAG, "N3DS_DIALER_VIBRATOR_UNAVAILABLE: " + e);
        }
    }

    private String activeCall() {
        try {
            String id = android.provider.Settings.System.getString(getContentResolver(),
                    SETTING_CALL_ACTIVE);
            return id == null || id.length() == 0 ? null : id;
        } catch (RuntimeException e) {
            return null;
        }
    }

    private boolean returnToCall() {
        Intent intent = new Intent(SHOW_CALL_ACTION);
        intent.setClassName("com.android.phone", "com.android.phone.TelcoCallActivity");
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(intent);
            Log.i(TAG, "N3DS_DIALER_RETURN_TO_CALL");
            return true;
        } catch (RuntimeException e) {
            Log.w(TAG, "N3DS_DIALER_RETURN_TO_CALL failed: " + e);
            return false;
        }
    }

    private void placeCallTo(String number) {
        if (activeCall() != null && returnToCall()) {
            return;
        }
        if (!number.matches("(?:[1-9][0-9]{2,3}|[2-9][0-9]{9})")) {
            vibrate();
            Toast.makeText(this, "3DSTelco calls need a 3-4 digit 3DS or 10 digit web number.",
                    Toast.LENGTH_SHORT).show();
            return;
        }
        // Dial the number out loud before handing off, the way a handset
        // does when it seizes the line. Nothing receives these tones --
        // there is no line -- but the audible confirmation of what you
        // actually dialled is the useful half anyway.
        mTones.playNumber(number);
        Intent intent = new Intent(CALL_ACTION, Uri.fromParts("tel", number, null));
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(intent);
        // N3DS_CALL_LOG_RECEIVER (#327): no row is written here any more.
        // Phone's TelcoService logs the call itself, keyed by its call id --
        // including calls placed from Messaging or a Recents callback -- and
        // never logs "100", which opens the mailbox instead of dialling.
        mView.setDigits("");
    }

    /*
     * N3DS_MISSED_CALL_SEEN (#327): the missed-call notification belongs to
     * Phone, and only Phone can take it down. Looking at Recents is what
     * "seen" means, the way the stock call log clears its own notification.
     */
    private void tellPhoneMissedCallsSeen() {
        Intent intent = new Intent(ACTION_MISSED_SEEN);
        intent.setClassName("com.android.phone", "com.android.phone.TelcoService");
        try {
            startService(intent);
        } catch (RuntimeException e) {
            Log.w(TAG, "N3DS_MISSED_CALL_SEEN failed: " + e);
        }
    }

    private void openVoicemail() {
        Intent intent = new Intent();
        intent.setClassName("com.android.phone", "com.android.phone.VoicemailActivity");
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(intent);
        } catch (RuntimeException e) {
            Log.w(TAG, "N3DS_DIALER_OPEN_VOICEMAIL failed: " + e);
            placeCallTo(VOICEMAIL_NUMBER);
        }
    }

    private final class DialerView extends View
            implements N3dsDialpad.Listener, ListPane.Listener {
        private final StringBuilder mDigits = new StringBuilder();
        private final N3dsDialpad mPad = new N3dsDialpad();
        private final ListPane mRecents = new ListPane();
        private final ListPane mContacts = new ListPane();
        /** numberKey -> contact row, rebuilt on every reload(). */
        private final Map<String, ListPane.Row> mByNumber = new HashMap<String, ListPane.Row>();

        private final Paint mBgPaint = DialerTheme.fill(DialerTheme.BG);
        private final Paint mHeaderPaint = DialerTheme.fill(DialerTheme.SURFACE);
        private final Paint mSurfaceHiPaint = DialerTheme.fill(DialerTheme.SURFACE_HI);
        private final Paint mDividerPaint = DialerTheme.fill(DialerTheme.DIVIDER);
        private final Paint mAccentPaint = DialerTheme.fill(DialerTheme.ACCENT);
        private final Paint mBadgePaint = DialerTheme.fill(DialerTheme.DANGER);
        private final Paint mIconPaint = DialerTheme.fill(DialerTheme.TEXT);
        private final Paint mNumberPaint =
                DialerTheme.text(DialerTheme.TEXT, 22f, Paint.Align.CENTER, false);
        private final Paint mHintPaint =
                DialerTheme.text(DialerTheme.TEXT_DIM, 8f, Paint.Align.CENTER, false);
        private final Paint mTabPaint =
                DialerTheme.text(DialerTheme.TEXT_DIM, 9f, Paint.Align.CENTER, false);
        private final Paint mBadgeTextPaint =
                DialerTheme.text(DialerTheme.TEXT, 8f, Paint.Align.CENTER, false);

        private final RectF mHeaderBounds = new RectF();
        private final RectF mBackspaceBounds = new RectF();
        private final RectF mBackspaceIcon = new RectF();
        private final RectF mContentBounds = new RectF();
        private final RectF mTabBounds = new RectF();
        private final RectF mScratch = new RectF();

        private int mTab = TAB_DIALPAD;
        private boolean mBackspacePressed;
        private int mPressedTab = -1;
        private int mMissedCount;
        private boolean mClearArmed;
        private long mClearArmedAtMs;

        DialerView() {
            super(N3dsDialerActivity.this);
            setFocusable(true);
            setClickable(true);
            setBackgroundColor(DialerTheme.BG);
            mPad.setListener(this);

            mRecents.setEmptyText("No calls yet.");
            mRecents.setHeaderAction("CLEAR");
            mRecents.setHeaderHint("Hold an entry to save it");
            mRecents.setListener(new ListPane.Listener() {
                public void onRowTap(ListPane.Row row) { onRecentTap(row); }
                public void onRowHold(ListPane.Row row) { onRecentHold(row); }
                public void onHeaderAction() { onClearRecents(); }
            });

            mContacts.setEmptyText("No saved contacts yet.");
            mContacts.setHeaderAction("NEW");
            mContacts.setHeaderHint("Hold to edit or delete");
            mContacts.setListener(new ListPane.Listener() {
                public void onRowTap(ListPane.Row row) { onContactTap(row); }
                public void onRowHold(ListPane.Row row) { onContactHold(row); }
                public void onHeaderAction() { vibrate(); openContactEditor(); }
            });
        }

        void setTab(int tab) {
            if (mTab == tab) return;
            click();
            mTab = tab;
            mClearArmed = false;
            mRecents.setHeaderAction("CLEAR");
            if (tab == TAB_RECENTS) markRecentsSeen();
            reload();
            invalidate();
        }

        String digits() {
            return mDigits.toString();
        }

        void setDigits(String value) {
            mDigits.setLength(0);
            if (value != null && value.length() > 0) {
                mDigits.append(value.length() > MAX_DIGITS
                        ? value.substring(value.length() - MAX_DIGITS) : value);
            }
            invalidate();
        }

        void appendDigit(char c) {
            if (mDigits.length() < MAX_DIGITS) {
                mDigits.append(c);
            } else {
                // Silently dropping the keypress reads as a dead key. A short
                // buzz is the only feedback channel this panel has.
                vibrate();
            }
            invalidate();
        }

        void deleteLast() {
            if (mDigits.length() > 0) {
                mDigits.setLength(mDigits.length() - 1);
                invalidate();
            }
        }

        // ---- data ----------------------------------------------------

        void reload() {
            // Contacts first: Recents labels its rows from them.
            loadContacts();
            loadRecents();
            invalidate();
        }

        private void loadRecents() {
            List<ListPane.Row> rows = new ArrayList<ListPane.Row>();
            int missed = 0;
            Cursor c = null;
            try {
                ContactsStore store = ContactsStore.get(N3dsDialerActivity.this);
                c = store.queryCalls();
                long now = System.currentTimeMillis();
                while (c.moveToNext()) {
                    ListPane.Row row = new ListPane.Row();
                    row.id = c.getLong(c.getColumnIndexOrThrow("_id"));
                    row.number = c.getString(c.getColumnIndexOrThrow("number"));
                    // The name saved now, not the one at call time, so adding,
                    // renaming or deleting a contact relabels its old calls.
                    ListPane.Row contact = mByNumber.get(ContactsStore.numberKey(row.number));
                    String name = contact != null ? contact.title : null;
                    row.callType = c.getInt(c.getColumnIndexOrThrow("call_type"));
                    long date = c.getLong(c.getColumnIndexOrThrow("call_date"));
                    long duration = c.getLong(c.getColumnIndexOrThrow("duration"));
                    if (c.getInt(c.getColumnIndexOrThrow("new")) != 0) missed++;
                    row.title = (name != null && name.length() > 0) ? name : row.number;
                    String kind = row.callType == ContactsStore.TYPE_VOICEMAIL ? "Voicemail  -  "
                            : row.callType == ContactsStore.TYPE_MISSED ? "Missed  -  "
                            : row.callType == ContactsStore.TYPE_REJECTED ? "Declined  -  " : "";
                    row.subtitle = kind + DialerTheme.relativeTime(date, now)
                            + (duration > 0 ? "  -  " + DialerTheme.duration(duration) : "");
                    row.meta = (name != null && name.length() > 0) ? row.number : "";
                    rows.add(row);
                }
            } catch (Throwable t) {
                Log.w(TAG, "N3DS_CALLS_QUERY_FAILED: " + t);
            } finally {
                if (c != null) c.close();
            }
            mMissedCount = missed;
            mRecents.setRows(rows);
        }

        private void loadContacts() {
            List<ListPane.Row> rows = new ArrayList<ListPane.Row>();
            mByNumber.clear();
            Cursor c = null;
            try {
                c = ContactsStore.get(N3dsDialerActivity.this).queryContacts();
                while (c.moveToNext()) {
                    ListPane.Row row = new ListPane.Row();
                    row.id = c.getLong(c.getColumnIndexOrThrow("_id"));
                    row.title = c.getString(c.getColumnIndexOrThrow("name"));
                    row.number = c.getString(c.getColumnIndexOrThrow("number"));
                    row.meta = DialerTheme.forDisplay(row.number);
                    rows.add(row);
                    String key = ContactsStore.numberKey(row.number);
                    if (key.length() > 0 && !mByNumber.containsKey(key)) mByNumber.put(key, row);
                }
            } catch (Throwable t) {
                Log.w(TAG, "N3DS_CONTACTS_QUERY_FAILED: " + t);
            } finally {
                if (c != null) c.close();
            }
            mContacts.setRows(rows);
        }

        private void markRecentsSeen() {
            try {
                ContactsStore.get(N3dsDialerActivity.this).markAllCallsSeen();
            } catch (Throwable t) {
                Log.w(TAG, "N3DS_CALLS_MARK_SEEN_FAILED: " + t);
            }
            mMissedCount = 0;
            tellPhoneMissedCallsSeen();
        }

        /** Resuming on Recents is looking at it, too. */
        void resumed() {
            if (mTab == TAB_RECENTS) markRecentsSeen();
        }

        // ---- list actions --------------------------------------------

        private void onRecentTap(ListPane.Row row) {
            vibrate();
            // N3DS_RECENTS_VOICEMAIL_ROW (#327): a voicemail row opens the
            // message, which is saved on this 3DS; hold it to call back.
            if (row.callType == ContactsStore.TYPE_VOICEMAIL) {
                openVoicemail();
            } else if (row.number != null) {
                placeCallTo(row.number);
            }
        }

        private void onRecentHold(final ListPane.Row row) {
            vibrate();
            final ListPane.Row contact = row.number == null ? null
                    : mByNumber.get(ContactsStore.numberKey(row.number));
            final boolean voicemail = row.callType == ContactsStore.TYPE_VOICEMAIL;
            CharSequence[] items = {
                "Call " + DialerTheme.forDisplay(row.number),
                contact != null ? "Edit contact" : "Save as contact",
                "Delete from Recents",
                "Play voicemail",
            };
            if (!voicemail) {
                CharSequence[] shorter = new CharSequence[3];
                System.arraycopy(items, 0, shorter, 0, 3);
                items = shorter;
            }
            new AlertDialog.Builder(N3dsDialerActivity.this)
                    .setTitle(row.title)
                    .setItems(items, new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int which) {
                            if (which == 3) {
                                openVoicemail();
                            } else if (which == 0) {
                                if (row.number != null) placeCallTo(row.number);
                            } else if (which == 1) {
                                if (contact != null) {
                                    openContactEditor(contact.id, contact.title, contact.number);
                                } else {
                                    openContactEditor(-1, null, row.number);
                                }
                            } else {
                                deleteRecent(row);
                            }
                        }
                    })
                    .show();
        }

        private void deleteRecent(ListPane.Row row) {
            try {
                ContactsStore.get(N3dsDialerActivity.this).deleteCall(row.id);
                Toast.makeText(N3dsDialerActivity.this, "Entry deleted.",
                        Toast.LENGTH_SHORT).show();
            } catch (Throwable t) {
                Log.w(TAG, "N3DS_CALLS_DELETE_FAILED: " + t);
            }
            reload();
        }

        private void onClearRecents() {
            vibrate();
            // Two-step confirm: clearing the whole log is destructive and the
            // header button is small enough to hit by accident.
            long now = SystemClock.uptimeMillis();
            if (!mClearArmed || now - mClearArmedAtMs > 4000) {
                mClearArmed = true;
                mClearArmedAtMs = now;
                mRecents.setHeaderAction("SURE?");
                invalidate();
                return;
            }
            mClearArmed = false;
            mRecents.setHeaderAction("CLEAR");
            try {
                ContactsStore.get(N3dsDialerActivity.this).clearCalls();
            } catch (Throwable t) {
                Log.w(TAG, "N3DS_CALLS_CLEAR_FAILED: " + t);
            }
            reload();
        }

        private void onContactTap(ListPane.Row row) {
            vibrate();
            // Fill the pad rather than dialling: a contacts list tap is an
            // easy misfire, and an unwanted outgoing call cannot be undone.
            setDigits(row.number);
            setTab(TAB_DIALPAD);
        }

        /*
         * N3DS_CONTACTS_MANAGE (#326): holding a contact used to delete it on
         * the spot, with nothing on screen saying so -- a hidden, instant,
         * destructive gesture. It now offers Call / Edit / Delete, and Delete
         * asks first.
         */
        private void onContactHold(final ListPane.Row row) {
            vibrate();
            CharSequence[] items = { "Call", "Edit", "Delete" };
            new AlertDialog.Builder(N3dsDialerActivity.this)
                    .setTitle(row.title)
                    .setItems(items, new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int which) {
                            if (which == 0) {
                                placeCallTo(row.number);
                            } else if (which == 1) {
                                openContactEditor(row.id, row.title, row.number);
                            } else {
                                confirmDeleteContact(row);
                            }
                        }
                    })
                    .show();
        }

        private void confirmDeleteContact(final ListPane.Row row) {
            new AlertDialog.Builder(N3dsDialerActivity.this)
                    .setTitle("Delete " + row.title + "?")
                    .setMessage(DialerTheme.forDisplay(row.number))
                    .setPositiveButton("Delete", new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface dialog, int which) {
                            try {
                                ContactsStore.get(N3dsDialerActivity.this).deleteContact(row.id);
                                Log.i(TAG, "N3DS_CONTACTS_DELETED id=" + row.id);
                                Toast.makeText(N3dsDialerActivity.this, "Contact deleted.",
                                        Toast.LENGTH_SHORT).show();
                            } catch (Throwable t) {
                                Log.w(TAG, "N3DS_CONTACTS_DELETE_FAILED: " + t);
                            }
                            reload();
                        }
                    })
                    .setNegativeButton("Cancel", null)
                    .show();
        }

        // ---- layout / paint ------------------------------------------

        @Override
        protected void onSizeChanged(int w, int h, int oldw, int oldh) {
            float headerHeight = h * 0.19f;
            float tabHeight = h * 0.13f;
            mHeaderBounds.set(0, 0, w, headerHeight);
            float backWidth = Math.min(w * 0.17f, headerHeight * 0.9f);
            mBackspaceBounds.set(w - backWidth - 4, 2, w - 4, headerHeight - 2);
            float iconW = mBackspaceBounds.width() * 0.62f;
            float iconH = iconW * 0.62f;
            mBackspaceIcon.set(mBackspaceBounds.centerX() - iconW / 2,
                    mBackspaceBounds.centerY() - iconH / 2,
                    mBackspaceBounds.centerX() + iconW / 2,
                    mBackspaceBounds.centerY() + iconH / 2);
            mContentBounds.set(0, headerHeight, w, h - tabHeight);
            mTabBounds.set(0, h - tabHeight, w, h);

            mPad.layout(0, mContentBounds.top, w, mContentBounds.bottom);
            mRecents.layout(0, mContentBounds.top, w, mContentBounds.bottom);
            mContacts.layout(0, mContentBounds.top, w, mContentBounds.bottom);

            mNumberPaint.setTextSize(headerHeight * 0.56f);
            mHintPaint.setTextSize(Math.max(7f, headerHeight * 0.20f));
            mTabPaint.setTextSize(Math.max(7f, tabHeight * 0.36f));
            mBadgeTextPaint.setTextSize(Math.max(6f, tabHeight * 0.30f));
        }

        @Override
        protected void onDraw(Canvas canvas) {
            canvas.drawRect(0, 0, getWidth(), getHeight(), mBgPaint);
            drawHeader(canvas);
            switch (mTab) {
                case TAB_RECENTS: mRecents.draw(canvas); break;
                case TAB_CONTACTS: mContacts.draw(canvas); break;
                default: mPad.draw(canvas); break;
            }
            drawTabs(canvas);
        }

        private void drawHeader(Canvas canvas) {
            canvas.drawRect(mHeaderBounds, mHeaderPaint);
            canvas.drawRect(mHeaderBounds.left, mHeaderBounds.bottom - 1,
                    mHeaderBounds.right, mHeaderBounds.bottom, mDividerPaint);

            float textCenter = (mHeaderBounds.width() - mBackspaceBounds.width()) / 2.0f;
            if (mDigits.length() > 0) {
                // A ten digit web number is wider than the header at full
                // size: shrink to fit rather than clip.
                String shown = DialerTheme.forDisplay(mDigits.toString());
                float size = mNumberPaint.getTextSize();
                float room = (mHeaderBounds.width() - mBackspaceBounds.width()) * 0.92f;
                float width = mNumberPaint.measureText(shown);
                if (width > room && width > 0) mNumberPaint.setTextSize(size * room / width);
                canvas.drawText(shown, textCenter,
                        DialerTheme.centeredBaseline(mNumberPaint, mHeaderBounds.top,
                                mHeaderBounds.bottom - mHeaderBounds.height() * 0.18f),
                        mNumberPaint);
                mNumberPaint.setTextSize(size);
                // A typed number that is saved shows whose it is.
                ListPane.Row match = mByNumber.get(ContactsStore.numberKey(mDigits.toString()));
                canvas.drawText(match != null ? match.title : "3DSTelco over Wi-Fi", textCenter,
                        mHeaderBounds.bottom - mHeaderBounds.height() * 0.10f, mHintPaint);
                if (mTab == TAB_DIALPAD) {
                    DialerTheme.roundRect(canvas, mBackspaceBounds,
                            mBackspaceBounds.height() * 0.22f,
                            mBackspacePressed ? mSurfaceHiPaint
                                    : mHeaderPaint);
                    DialerTheme.backspaceIcon(canvas, mBackspaceIcon,
                            DialerTheme.TEXT_DIM, mIconPaint);
                }
            } else {
                canvas.drawText(TAB_LABELS[mTab], mHeaderBounds.centerX(),
                        DialerTheme.centeredBaseline(mNumberPaint, mHeaderBounds.top,
                                mHeaderBounds.bottom - mHeaderBounds.height() * 0.18f),
                        mNumberPaint);
                canvas.drawText("No cellular radio - calls run over Wi-Fi",
                        mHeaderBounds.centerX(),
                        mHeaderBounds.bottom - mHeaderBounds.height() * 0.10f, mHintPaint);
            }
        }

        private void drawTabs(Canvas canvas) {
            canvas.drawRect(mTabBounds, mHeaderPaint);
            canvas.drawRect(mTabBounds.left, mTabBounds.top,
                    mTabBounds.right, mTabBounds.top + 1, mDividerPaint);
            float tabWidth = mTabBounds.width() / TAB_LABELS.length;
            for (int i = 0; i < TAB_LABELS.length; i++) {
                float left = mTabBounds.left + i * tabWidth;
                boolean active = (i == mTab);
                mTabPaint.setColor(active ? DialerTheme.TEXT
                        : (i == mPressedTab ? DialerTheme.TEXT : DialerTheme.TEXT_DIM));
                float cx = left + tabWidth / 2.0f;
                canvas.drawText(TAB_LABELS[i], cx,
                        DialerTheme.centeredBaseline(mTabPaint, mTabBounds.top,
                                mTabBounds.bottom),
                        mTabPaint);
                if (active) {
                    mScratch.set(left + tabWidth * 0.22f, mTabBounds.top + 1,
                            left + tabWidth * 0.78f, mTabBounds.top + 3);
                    canvas.drawRect(mScratch, mAccentPaint);
                }
                if (i == TAB_RECENTS && mMissedCount > 0) {
                    float r = mTabBounds.height() * 0.20f;
                    float bx = cx + mTabPaint.measureText(TAB_LABELS[i]) / 2.0f + r + 2;
                    float by = mTabBounds.centerY() - mTabBounds.height() * 0.18f;
                    canvas.drawCircle(bx, by, r, mBadgePaint);
                    canvas.drawText(String.valueOf(Math.min(9, mMissedCount)), bx,
                            DialerTheme.centeredBaseline(mBadgeTextPaint, by - r, by + r),
                            mBadgeTextPaint);
                }
            }
            mTabPaint.setColor(DialerTheme.TEXT_DIM);
        }

        // ---- touch ----------------------------------------------------

        @Override
        public boolean onTouchEvent(MotionEvent event) {
            float x = event.getX();
            float y = event.getY();
            int action = event.getAction();

            if (mTabBounds.contains(x, y) || mPressedTab >= 0) {
                return handleTabTouch(action, x, y);
            }
            if (mTab == TAB_DIALPAD
                    && (mBackspacePressed || mBackspaceBounds.contains(x, y))) {
                return handleBackspaceTouch(action, x, y);
            }
            if (mContentBounds.contains(x, y) || action != MotionEvent.ACTION_DOWN) {
                boolean handled;
                switch (mTab) {
                    case TAB_RECENTS: handled = mRecents.onTouchEvent(event); break;
                    case TAB_CONTACTS: handled = mContacts.onTouchEvent(event); break;
                    default: handled = mPad.onTouchEvent(event); break;
                }
                if (handled) invalidate();
                if (handled) return true;
            }
            return super.onTouchEvent(event);
        }

        private boolean handleTabTouch(int action, float x, float y) {
            if (action == MotionEvent.ACTION_DOWN) {
                mPressedTab = tabAt(x);
                invalidate();
                return true;
            }
            if (action == MotionEvent.ACTION_UP) {
                int pressed = mPressedTab;
                mPressedTab = -1;
                if (pressed >= 0 && mTabBounds.contains(x, y)) {
                    vibrate();
                    setTab(pressed);
                }
                invalidate();
                return true;
            }
            if (action == MotionEvent.ACTION_CANCEL) {
                mPressedTab = -1;
                invalidate();
            }
            return true;
        }

        private boolean handleBackspaceTouch(int action, float x, float y) {
            if (action == MotionEvent.ACTION_DOWN) {
                mBackspacePressed = true;
                invalidate();
                return true;
            }
            if (action == MotionEvent.ACTION_UP) {
                boolean was = mBackspacePressed;
                mBackspacePressed = false;
                if (was && mBackspaceBounds.contains(x, y)) {
                    vibrate();
                    deleteLast();
                }
                invalidate();
                return true;
            }
            if (action == MotionEvent.ACTION_CANCEL) {
                mBackspacePressed = false;
                invalidate();
            }
            return true;
        }

        private int tabAt(float x) {
            float tabWidth = mTabBounds.width() / TAB_LABELS.length;
            int index = (int) ((x - mTabBounds.left) / tabWidth);
            return (index >= 0 && index < TAB_LABELS.length) ? index : -1;
        }

        // ---- N3dsDialpad.Listener -------------------------------------

        public void onDigit(char digit) {
            mTones.playDigit(digit);
            vibrate();
            appendDigit(digit);
        }

        public void onDelete() {
            click();
            vibrate();
            deleteLast();
        }

        public void onClear() {
            click();
            vibrate();
            setDigits("");
        }

        public void onVoicemail() {
            click();
            vibrate();
            placeCallTo(VOICEMAIL_NUMBER);
        }

        public void onCall() {
            click();
            vibrate();
            placeCallTo(mDigits.toString());
        }

        // ---- ListPane.Listener (unused on the View itself) ------------
        // The two panes each get their own adapter in the constructor; these
        // exist only because the View declares the interface for clarity.

        public void onRowTap(ListPane.Row row) {}
        public void onRowHold(ListPane.Row row) {}
        public void onHeaderAction() {}
    }
}
