/*
 * A from-scratch keypad for N3dsDialerActivity: a 3x4 key grid plus a
 * full-width call bar, all drawn with Canvas/Paint so it needs nothing beyond
 * the minimal Eclair framework surface this build has.
 *
 * Touch UX (unchanged, and deliberately so): the cell under ACTION_DOWN is
 * latched immediately (and highlighted); the latched cell's action fires on
 * ACTION_UP as long as the finger is still somewhere inside the pad, not only
 * if it is still over the same cell. The 3DS touchscreen digitizer is
 * imprecise enough that a strict same-cell-on-UP check drops taps near cell
 * borders. Do not "fix" this into a conventional hit test.
 *
 * N3DS_DIALER_RESTYLE (2026-09-11): the keys are now rounded surfaces with
 * letter subtitles, a pressed state, and a real type scale; DEL moved to the
 * header (where the entry field is) and the old flat DEL/CLR + VMAIL/CALL
 * rows became a single call bar. The touch model above is untouched.
 *
 * Long-press-1 is the stock voicemail shortcut and is honoured here. It is
 * implemented as hold-then-release rather than fire-on-timeout: this pad has
 * no Handler of its own, and on a resistive panel a press that has to be held
 * still for 500 ms without moving is less reliable than one that is simply
 * held and then lifted.
 */
package com.android.n3dsdialer;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.SystemClock;
import android.view.MotionEvent;

final class N3dsDialpad {
    interface Listener {
        void onDigit(char digit);
        void onDelete();
        void onClear();
        void onVoicemail();
        void onCall();
    }

    private static final int TYPE_DIGIT = 0;
    private static final int TYPE_CLEAR = 2;
    private static final int TYPE_VOICEMAIL = 3;
    private static final int TYPE_CALL = 4;

    private static final long LONG_PRESS_MS = 550;

    private static final class Cell {
        final RectF bounds = new RectF();
        int type;
        char digit;
        String label;
        String sublabel;
    }

    // 12 grid keys + the call bar.
    private final Cell[] mCells = new Cell[13];
    private static final int CALL_INDEX = 12;

    private final Paint mKeyPaint = DialerTheme.fill(DialerTheme.SURFACE);
    private final Paint mKeyPressedPaint = DialerTheme.fill(DialerTheme.SURFACE_HI);
    private final Paint mCallPaint = DialerTheme.fill(DialerTheme.CALL);
    private final Paint mCallPressedPaint = DialerTheme.fill(DialerTheme.CALL_HI);
    private final Paint mLabelPaint =
            DialerTheme.text(DialerTheme.TEXT, 10f, Paint.Align.CENTER, false);
    private final Paint mSubPaint =
            DialerTheme.text(DialerTheme.TEXT_DIM, 8f, Paint.Align.CENTER, false);
    private final Paint mIconPaint = DialerTheme.fill(DialerTheme.TEXT);
    private final RectF mPadBounds = new RectF();
    private final RectF mIconRect = new RectF();

    private Listener mListener;
    private int mLatchedIndex = -1;
    private long mLatchedAtMs;
    private float mKeyRadius = 4f;
    private float mGap = 3f;

    N3dsDialpad() {
        for (int i = 0; i < mCells.length; i++) {
            mCells[i] = new Cell();
        }
        final char[] digits = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
        for (int i = 0; i < digits.length; i++) {
            mCells[i].type = TYPE_DIGIT;
            mCells[i].digit = digits[i];
            mCells[i].label = String.valueOf(digits[i]);
            mCells[i].sublabel = DialerTheme.KEY_LETTERS[digits[i] - '0'];
        }
        mCells[0].sublabel = "VOICEMAIL";
        mCells[9].type = TYPE_VOICEMAIL;
        mCells[9].label = "VM";
        mCells[9].sublabel = "MAILBOX";
        mCells[10].type = TYPE_DIGIT;
        mCells[10].digit = '0';
        mCells[10].label = "0";
        mCells[10].sublabel = "";
        mCells[11].type = TYPE_CLEAR;
        mCells[11].label = "CLR";
        mCells[11].sublabel = "HOLD ALL";
        mCells[CALL_INDEX].type = TYPE_CALL;
        mCells[CALL_INDEX].label = "CALL";
        mCells[CALL_INDEX].sublabel = "";
    }

    void setListener(Listener listener) {
        mListener = listener;
    }

    void layout(float left, float top, float right, float bottom) {
        mPadBounds.set(left, top, right, bottom);
        float width = right - left;
        float height = bottom - top;

        mGap = Math.max(2f, height * 0.018f);
        mKeyRadius = Math.max(3f, height * 0.035f);

        // The call bar gets a fixed slice of the pad; the 4 key rows share
        // the rest. 22% reads as a deliberate primary action without eating
        // the grid on a 240 px-tall panel.
        float callHeight = height * 0.22f;
        float gridHeight = height - callHeight;

        float cellW = width / 3.0f;
        float cellH = gridHeight / 4.0f;
        int col = 0;
        int row = 0;
        for (int i = 0; i < 12; i++) {
            float cellLeft = left + col * cellW;
            float cellTop = top + row * cellH;
            mCells[i].bounds.set(cellLeft, cellTop, cellLeft + cellW, cellTop + cellH);
            col++;
            if (col == 3) {
                col = 0;
                row++;
            }
        }
        mCells[CALL_INDEX].bounds.set(left, top + gridHeight, right, bottom);

        float keyH = cellH - 2 * mGap;
        mLabelPaint.setTextSize(keyH * 0.46f);
        mSubPaint.setTextSize(Math.max(6f, keyH * 0.19f));
    }

    void draw(Canvas canvas) {
        for (int i = 0; i < mCells.length; i++) {
            Cell cell = mCells[i];
            boolean pressed = (i == mLatchedIndex);
            RectF b = cell.bounds;
            RectF inner = new RectF(b.left + mGap, b.top + mGap,
                    b.right - mGap, b.bottom - mGap);

            if (cell.type == TYPE_CALL) {
                DialerTheme.roundRect(canvas, inner, mKeyRadius,
                        pressed ? mCallPressedPaint : mCallPaint);
                float iconSize = inner.height() * 0.42f;
                float textWidth = mLabelPaint.measureText(cell.label);
                float blockLeft = inner.centerX() - (iconSize + mGap * 2 + textWidth) / 2.0f;
                mIconRect.set(blockLeft, inner.centerY() - iconSize / 2.0f,
                        blockLeft + iconSize, inner.centerY() + iconSize / 2.0f);
                DialerTheme.handset(canvas, mIconRect, DialerTheme.TEXT, false, mIconPaint);
                mLabelPaint.setTextAlign(Paint.Align.LEFT);
                canvas.drawText(cell.label, mIconRect.right + mGap * 2,
                        DialerTheme.centeredBaseline(mLabelPaint, inner.top, inner.bottom),
                        mLabelPaint);
                mLabelPaint.setTextAlign(Paint.Align.CENTER);
                continue;
            }

            DialerTheme.roundRect(canvas, inner, mKeyRadius,
                    pressed ? mKeyPressedPaint : mKeyPaint);

            boolean hasSub = cell.sublabel != null && cell.sublabel.length() > 0;
            float labelBaseline = hasSub
                    ? DialerTheme.centeredBaseline(mLabelPaint, inner.top,
                            inner.bottom - inner.height() * 0.20f)
                    : DialerTheme.centeredBaseline(mLabelPaint, inner.top, inner.bottom);
            mLabelPaint.setColor(cell.type == TYPE_CLEAR
                    ? DialerTheme.TEXT_DIM : DialerTheme.TEXT);
            canvas.drawText(cell.label, inner.centerX(), labelBaseline, mLabelPaint);
            if (hasSub) {
                canvas.drawText(cell.sublabel, inner.centerX(),
                        inner.bottom - inner.height() * 0.10f, mSubPaint);
            }
        }
        mLabelPaint.setColor(DialerTheme.TEXT);
    }

    boolean onTouchEvent(MotionEvent event) {
        float x = event.getX();
        float y = event.getY();
        switch (event.getAction()) {
            case MotionEvent.ACTION_DOWN:
                mLatchedIndex = indexAt(x, y);
                mLatchedAtMs = SystemClock.uptimeMillis();
                return mLatchedIndex >= 0;
            case MotionEvent.ACTION_MOVE:
                return mLatchedIndex >= 0;
            case MotionEvent.ACTION_UP: {
                int latched = mLatchedIndex;
                boolean held = SystemClock.uptimeMillis() - mLatchedAtMs >= LONG_PRESS_MS;
                mLatchedIndex = -1;
                if (latched >= 0 && mPadBounds.contains(x, y)) {
                    dispatch(mCells[latched], held);
                    return true;
                }
                return latched >= 0;
            }
            case MotionEvent.ACTION_CANCEL:
                mLatchedIndex = -1;
                return true;
            default:
                return false;
        }
    }

    private int indexAt(float x, float y) {
        for (int i = 0; i < mCells.length; i++) {
            if (mCells[i].bounds.contains(x, y)) {
                return i;
            }
        }
        return -1;
    }

    private void dispatch(Cell cell, boolean held) {
        if (mListener == null) return;
        switch (cell.type) {
            case TYPE_DIGIT:
                // Stock long-press-1 voicemail shortcut.
                if (held && cell.digit == '1') mListener.onVoicemail();
                else mListener.onDigit(cell.digit);
                break;
            case TYPE_CLEAR:
                // A tap clears one digit, a hold clears the whole field.
                if (held) mListener.onClear(); else mListener.onDelete();
                break;
            case TYPE_VOICEMAIL: mListener.onVoicemail(); break;
            case TYPE_CALL: mListener.onCall(); break;
            default: break;
        }
    }
}
