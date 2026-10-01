/*
 * N3DS_DIALER_LIST_PANE: the Recents and Contacts tabs, drawn on the same
 * Canvas as the keypad instead of hosting a ListView.
 *
 * Why not ListView: the three tabs live inside one View so that switching
 * tabs is a repaint rather than an Activity transition, which on this device
 * costs hundreds of milliseconds and (until the AMS process-trim fix) risked
 * the whole process being reaped between screens. Mixing a child ViewGroup
 * into a custom-drawn View to get one scrolling list back would give up that
 * property for very little.
 *
 * Touch model matches N3dsDialpad's: press latches on DOWN, fires on UP. A
 * drag past the slop converts the gesture into a scroll and cancels the tap.
 * A press held past LONG_PRESS_MS and then released fires onRowHold instead
 * of onRowTap -- hold-then-release rather than fire-on-timeout, for the same
 * resistive-digitizer reason documented in N3dsDialpad.
 *
 * There is no fling. Recents and Contacts on a 3-4 digit device network are
 * short lists, and inertial scrolling would need a Handler-driven animation
 * loop repainting the whole 320x240 surface through libagl.
 */
package com.android.n3dsdialer;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.SystemClock;
import android.view.MotionEvent;

import java.util.ArrayList;
import java.util.List;

final class ListPane {
    interface Listener {
        void onRowTap(Row row);
        void onRowHold(Row row);
        /** The pane's single header action (CLEAR ALL / NEW CONTACT). */
        void onHeaderAction();
    }

    static final class Row {
        long id;
        String title;
        String subtitle;
        String meta;
        /** One of ContactsStore.TYPE_*, or 0 for no direction indicator. */
        int callType;
        /** Payload handed back to the listener; the dialable number. */
        String number;
    }

    private static final long LONG_PRESS_MS = 550;

    private final List<Row> mRows = new ArrayList<Row>();
    private final RectF mBounds = new RectF();
    private final RectF mHeaderBounds = new RectF();
    private final RectF mActionBounds = new RectF();
    private final RectF mScratch = new RectF();

    private final Paint mBgPaint = DialerTheme.fill(DialerTheme.BG);
    private final Paint mRowPaint = DialerTheme.fill(DialerTheme.SURFACE);
    private final Paint mRowPressedPaint = DialerTheme.fill(DialerTheme.SURFACE_HI);
    private final Paint mDividerPaint = DialerTheme.fill(DialerTheme.DIVIDER);
    private final Paint mActionPaint = DialerTheme.fill(DialerTheme.SURFACE);
    private final Paint mTitlePaint =
            DialerTheme.text(DialerTheme.TEXT, 12f, Paint.Align.LEFT, false);
    private final Paint mSubPaint =
            DialerTheme.text(DialerTheme.TEXT_DIM, 9f, Paint.Align.LEFT, false);
    private final Paint mMetaPaint =
            DialerTheme.text(DialerTheme.TEXT_DIM, 9f, Paint.Align.RIGHT, false);
    private final Paint mEmptyPaint =
            DialerTheme.text(DialerTheme.TEXT_DIM, 11f, Paint.Align.CENTER, false);
    private final Paint mActionTextPaint =
            DialerTheme.text(DialerTheme.ACCENT, 10f, Paint.Align.CENTER, false);
    private final Paint mIconPaint = DialerTheme.fill(DialerTheme.TEXT);
    private final Paint mHintPaint =
            DialerTheme.text(DialerTheme.TEXT_DIM, 8f, Paint.Align.LEFT, false);

    private Listener mListener;
    private String mHeaderAction;
    /** N3DS_CONTACTS_MANAGE: says what holding a row does, left of the action. */
    private String mHeaderHint;
    private String mEmptyText = "Nothing here yet.";

    private float mRowHeight = 34f;
    private float mHeaderHeight = 22f;
    private float mScroll;
    private float mMaxScroll;

    private int mPressedIndex = -1;
    private boolean mPressedAction;
    private boolean mScrolling;
    private float mDownY;
    private float mDownScroll;
    private long mDownAtMs;

    void setListener(Listener listener) { mListener = listener; }

    void setHeaderAction(String label) { mHeaderAction = label; }

    void setEmptyText(String text) { mEmptyText = text; }

    void setHeaderHint(String hint) { mHeaderHint = hint; }

    void setRows(List<Row> rows) {
        mRows.clear();
        if (rows != null) mRows.addAll(rows);
        mScroll = 0;
        recomputeScrollRange();
    }

    void layout(float left, float top, float right, float bottom) {
        mBounds.set(left, top, right, bottom);
        float height = bottom - top;
        mHeaderHeight = mHeaderAction == null ? 0 : Math.max(18f, height * 0.16f);
        mRowHeight = Math.max(22f, height * 0.26f);
        mHeaderBounds.set(left, top, right, top + mHeaderHeight);
        mActionBounds.set(right - (right - left) * 0.42f, top + 2, right - 4,
                top + mHeaderHeight - 2);
        mTitlePaint.setTextSize(mRowHeight * 0.36f);
        mSubPaint.setTextSize(mRowHeight * 0.26f);
        mMetaPaint.setTextSize(mRowHeight * 0.26f);
        mEmptyPaint.setTextSize(Math.max(9f, height * 0.11f));
        mActionTextPaint.setTextSize(Math.max(8f, mHeaderHeight * 0.44f));
        mHintPaint.setTextSize(Math.max(7f, mHeaderHeight * 0.40f));
        recomputeScrollRange();
    }

    private void recomputeScrollRange() {
        float visible = mBounds.height() - mHeaderHeight;
        float content = mRows.size() * mRowHeight;
        mMaxScroll = Math.max(0, content - visible);
        if (mScroll > mMaxScroll) mScroll = mMaxScroll;
        if (mScroll < 0) mScroll = 0;
    }

    void draw(Canvas canvas) {
        canvas.drawRect(mBounds, mBgPaint);

        if (mHeaderAction != null) {
            DialerTheme.roundRect(canvas, mActionBounds, mHeaderHeight * 0.25f,
                    mPressedAction ? mRowPressedPaint : mActionPaint);
            canvas.drawText(mHeaderAction, mActionBounds.centerX(),
                    DialerTheme.centeredBaseline(mActionTextPaint,
                            mActionBounds.top, mActionBounds.bottom),
                    mActionTextPaint);
            if (mHeaderHint != null && mRows.size() > 0) {
                canvas.drawText(mHeaderHint, mBounds.left + 6,
                        DialerTheme.centeredBaseline(mHintPaint,
                                mActionBounds.top, mActionBounds.bottom),
                        mHintPaint);
            }
        }

        float listTop = mBounds.top + mHeaderHeight;
        if (mRows.isEmpty()) {
            canvas.drawText(mEmptyText, mBounds.centerX(),
                    DialerTheme.centeredBaseline(mEmptyPaint, listTop, mBounds.bottom),
                    mEmptyPaint);
            return;
        }

        canvas.save();
        canvas.clipRect(mBounds.left, listTop, mBounds.right, mBounds.bottom);
        float pad = mRowHeight * 0.16f;
        for (int i = 0; i < mRows.size(); i++) {
            float rowTop = listTop + i * mRowHeight - mScroll;
            float rowBottom = rowTop + mRowHeight;
            if (rowBottom < listTop || rowTop > mBounds.bottom) continue;
            Row row = mRows.get(i);

            mScratch.set(mBounds.left + 2, rowTop + 1, mBounds.right - 2, rowBottom - 1);
            DialerTheme.roundRect(canvas, mScratch, mRowHeight * 0.12f,
                    i == mPressedIndex ? mRowPressedPaint : mRowPaint);

            float textLeft = mScratch.left + pad;
            if (row.callType != 0) {
                float icon = mRowHeight * 0.30f;
                DialerTheme.directionArrow(canvas, mScratch.left + pad + icon / 2.0f,
                        mScratch.centerY(), icon, row.callType, mIconPaint);
                textLeft = mScratch.left + pad * 2 + icon;
            }

            boolean hasSub = row.subtitle != null && row.subtitle.length() > 0;
            mTitlePaint.setColor(row.callType == ContactsStore.TYPE_MISSED
                    ? DialerTheme.DANGER : DialerTheme.TEXT);
            if (hasSub) {
                canvas.drawText(row.title, textLeft,
                        DialerTheme.centeredBaseline(mTitlePaint, mScratch.top,
                                mScratch.centerY() + mRowHeight * 0.06f),
                        mTitlePaint);
                canvas.drawText(row.subtitle, textLeft,
                        mScratch.bottom - pad, mSubPaint);
            } else {
                canvas.drawText(row.title, textLeft,
                        DialerTheme.centeredBaseline(mTitlePaint, mScratch.top, mScratch.bottom),
                        mTitlePaint);
            }
            if (row.meta != null && row.meta.length() > 0) {
                canvas.drawText(row.meta, mScratch.right - pad,
                        DialerTheme.centeredBaseline(mMetaPaint, mScratch.top, mScratch.bottom),
                        mMetaPaint);
            }
        }
        mTitlePaint.setColor(DialerTheme.TEXT);
        canvas.restore();

        // Scroll indicator: a thin rail on the right, only while scrollable.
        if (mMaxScroll > 0) {
            float trackTop = listTop;
            float trackHeight = mBounds.bottom - listTop;
            float thumb = Math.max(trackHeight * 0.12f,
                    trackHeight * (trackHeight / (mRows.size() * mRowHeight)));
            float y = trackTop + (trackHeight - thumb) * (mScroll / mMaxScroll);
            mScratch.set(mBounds.right - 3, y, mBounds.right - 1, y + thumb);
            canvas.drawRect(mScratch, mDividerPaint);
        }
    }

    boolean onTouchEvent(MotionEvent event) {
        float x = event.getX();
        float y = event.getY();
        switch (event.getAction()) {
            case MotionEvent.ACTION_DOWN:
                mDownY = y;
                mDownScroll = mScroll;
                mDownAtMs = SystemClock.uptimeMillis();
                mScrolling = false;
                mPressedAction = mHeaderAction != null && mActionBounds.contains(x, y);
                mPressedIndex = mPressedAction ? -1 : indexAt(x, y);
                return true;
            case MotionEvent.ACTION_MOVE: {
                float dy = y - mDownY;
                if (!mScrolling && Math.abs(dy) > mRowHeight * 0.35f) {
                    mScrolling = true;
                    mPressedIndex = -1;
                    mPressedAction = false;
                }
                if (mScrolling) {
                    mScroll = mDownScroll - dy;
                    if (mScroll < 0) mScroll = 0;
                    if (mScroll > mMaxScroll) mScroll = mMaxScroll;
                }
                return true;
            }
            case MotionEvent.ACTION_UP: {
                boolean held = SystemClock.uptimeMillis() - mDownAtMs >= LONG_PRESS_MS;
                int pressed = mPressedIndex;
                boolean action = mPressedAction;
                mPressedIndex = -1;
                mPressedAction = false;
                if (mScrolling) return true;
                if (action && mListener != null) {
                    mListener.onHeaderAction();
                    return true;
                }
                if (pressed >= 0 && pressed < mRows.size() && mListener != null) {
                    if (held) mListener.onRowHold(mRows.get(pressed));
                    else mListener.onRowTap(mRows.get(pressed));
                }
                return true;
            }
            case MotionEvent.ACTION_CANCEL:
                mPressedIndex = -1;
                mPressedAction = false;
                mScrolling = false;
                return true;
            default:
                return false;
        }
    }

    private int indexAt(float x, float y) {
        float listTop = mBounds.top + mHeaderHeight;
        if (y < listTop || y > mBounds.bottom) return -1;
        int index = (int) ((y - listTop + mScroll) / mRowHeight);
        return (index >= 0 && index < mRows.size()) ? index : -1;
    }
}
