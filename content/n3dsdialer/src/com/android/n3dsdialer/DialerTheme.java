/*
 * N3DS_DIALER_THEME: the one place that decides what this app looks like.
 *
 * Everything in N3dsDialer is drawn with Canvas/Paint rather than XML layouts.
 * That is a deliberate choice, not a shortcut: the 3DS resistive digitizer is
 * imprecise, and the hand-rolled touch model in N3dsDialpad (latch on DOWN,
 * fire on UP anywhere inside the pad) is what makes it usable. Framework
 * widgets would give back stock hit-testing and lose that.
 *
 * The cost of Canvas is that visual consistency has to be maintained by hand,
 * which is what this class is for. Nothing else in the app should contain a
 * literal colour or a magic pixel size.
 *
 * Sizing: every metric is derived from the view's own height rather than from
 * DisplayMetrics.density. The bottom screen is a fixed 320x240 panel and the
 * framework's reported density has been wrong on this port before; deriving
 * from real pixel bounds cannot be wrong.
 */
package com.android.n3dsdialer;

import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;

final class DialerTheme {
    private DialerTheme() {}

    // ---- palette ------------------------------------------------------
    // Deliberately not the stock Eclair grey-on-black: this is a distinct
    // app, and the user asked for something that reads as professional
    // without imitating the stock dialer.
    static final int BG = Color.rgb(0x10, 0x12, 0x14);
    static final int SURFACE = Color.rgb(0x1E, 0x22, 0x27);
    static final int SURFACE_HI = Color.rgb(0x2A, 0x30, 0x37);
    static final int DIVIDER = Color.rgb(0x26, 0x2A, 0x30);
    static final int TEXT = Color.rgb(0xF2, 0xF4, 0xF7);
    static final int TEXT_DIM = Color.rgb(0x8A, 0x93, 0x9B);
    static final int ACCENT = Color.rgb(0x2F, 0x6F, 0xEB);
    static final int CALL = Color.rgb(0x2F, 0xA8, 0x4F);
    static final int CALL_HI = Color.rgb(0x3C, 0xC4, 0x61);
    static final int DANGER = Color.rgb(0xE5, 0x48, 0x4D);

    // ---- letter subtitles ---------------------------------------------
    // Purely decorative here: 3DSTelco numbers are 3-4 digit device IDs, so
    // there is no alphanumeric dialling. They are drawn because a keypad
    // without them does not read as a phone keypad.
    static final String[] KEY_LETTERS = {
        "", "", "ABC", "DEF", "GHI", "JKL", "MNO", "PQRS", "TUV", "WXYZ"
    };

    static Paint fill(int color) {
        Paint p = new Paint();
        p.setAntiAlias(true);
        p.setColor(color);
        p.setStyle(Paint.Style.FILL);
        return p;
    }

    static Paint stroke(int color, float width) {
        Paint p = new Paint();
        p.setAntiAlias(true);
        p.setColor(color);
        p.setStyle(Paint.Style.STROKE);
        p.setStrokeWidth(width);
        return p;
    }

    static Paint text(int color, float size, Paint.Align align, boolean bold) {
        Paint p = new Paint();
        p.setAntiAlias(true);
        p.setColor(color);
        p.setTextSize(size);
        p.setTextAlign(align);
        p.setFakeBoldText(bold);
        return p;
    }

    /** Baseline that vertically centres text of this Paint inside [top,bottom]. */
    static float centeredBaseline(Paint paint, float top, float bottom) {
        Paint.FontMetrics fm = paint.getFontMetrics();
        return (top + bottom) / 2.0f - (fm.ascent + fm.descent) / 2.0f;
    }

    static void roundRect(Canvas canvas, RectF r, float radius, Paint paint) {
        canvas.drawRoundRect(r, radius, radius, paint);
    }

    /**
     * Call-log direction indicator, drawn as geometry rather than as a glyph.
     *
     * N3DS_DIALER_NO_GLYPH_FONT_DEPENDENCY: the arrow characters a stock
     * dialer would use are not guaranteed to exist in this build's bundled
     * DroidSans, and a missing glyph renders as an empty box. Lines always
     * render.
     *
     * dx/dy point the arrow: outgoing is up-right, incoming is down-left,
     * missed is down-left in the danger colour with a cross-bar.
     */
    static void directionArrow(Canvas canvas, float cx, float cy, float size,
            int callType, Paint work) {
        boolean outgoing = callType == ContactsStore.TYPE_OUTGOING;
        int color = callType == ContactsStore.TYPE_MISSED ? DANGER
                : callType == ContactsStore.TYPE_REJECTED ? TEXT_DIM
                : (outgoing ? CALL : ACCENT);
        work.setColor(color);
        work.setStyle(Paint.Style.STROKE);
        work.setStrokeWidth(Math.max(1.0f, size * 0.14f));
        work.setAntiAlias(true);

        float h = size / 2.0f;
        if (callType == ContactsStore.TYPE_VOICEMAIL) {
            // The tape-reel voicemail mark: two rings joined along the bottom.
            float r = size * 0.24f;
            canvas.drawCircle(cx - h + r, cy, r, work);
            canvas.drawCircle(cx + h - r, cy, r, work);
            canvas.drawLine(cx - h + r, cy + r, cx + h - r, cy + r, work);
            work.setStyle(Paint.Style.FILL);
            return;
        }
        // Shaft runs bottom-left to top-right for outgoing, the reverse for
        // incoming and missed.
        float x0 = cx - h, y0 = cy + h, x1 = cx + h, y1 = cy - h;
        if (!outgoing) { float t; t = x0; x0 = x1; x1 = t; t = y0; y0 = y1; y1 = t; }
        canvas.drawLine(x0, y0, x1, y1, work);

        // Head: two short strokes at the tip (x1,y1).
        float head = size * 0.45f;
        Path path = new Path();
        path.moveTo(x1, y1);
        if (outgoing) {
            path.lineTo(x1 - head, y1);
            path.moveTo(x1, y1);
            path.lineTo(x1, y1 + head);
        } else {
            path.lineTo(x1 + head, y1);
            path.moveTo(x1, y1);
            path.lineTo(x1, y1 - head);
        }
        canvas.drawPath(path, work);
        work.setStyle(Paint.Style.FILL);
    }

    /** Backspace affordance: an arrow-tailed box with an x in it. */
    static void backspaceIcon(Canvas canvas, RectF r, int color, Paint work) {
        work.setColor(color);
        work.setStyle(Paint.Style.STROKE);
        work.setStrokeWidth(Math.max(1.0f, r.height() * 0.09f));
        float midY = r.centerY();
        float tipX = r.left;
        float bodyLeft = r.left + r.width() * 0.32f;
        Path path = new Path();
        path.moveTo(tipX, midY);
        path.lineTo(bodyLeft, r.top);
        path.lineTo(r.right, r.top);
        path.lineTo(r.right, r.bottom);
        path.lineTo(bodyLeft, r.bottom);
        path.close();
        canvas.drawPath(path, work);
        float inset = r.width() * 0.16f;
        canvas.drawLine(bodyLeft + inset, r.top + inset, r.right - inset, r.bottom - inset, work);
        canvas.drawLine(r.right - inset, r.top + inset, bodyLeft + inset, r.bottom - inset, work);
        work.setStyle(Paint.Style.FILL);
    }

    /** Handset silhouette used on the call / end-call keys. */
    static void handset(Canvas canvas, RectF r, int color, boolean hangUp, Paint work) {
        work.setColor(color);
        work.setStyle(Paint.Style.STROKE);
        work.setStrokeWidth(Math.max(1.5f, r.height() * 0.20f));
        work.setStrokeCap(Paint.Cap.ROUND);
        // A simple diagonal bar with two end lugs reads as a handset at this
        // size; a full receiver outline turns to mush below ~14 px.
        float x0 = r.left, y0 = hangUp ? r.top : r.bottom;
        float x1 = r.right, y1 = hangUp ? r.bottom : r.top;
        canvas.drawLine(x0, y0, x1, y1, work);
        float lug = r.width() * 0.28f;
        canvas.drawLine(x0, y0, x0 + lug, y0 + (hangUp ? lug : -lug), work);
        canvas.drawLine(x1, y1, x1 - lug, y1 + (hangUp ? -lug : lug), work);
        work.setStyle(Paint.Style.FILL);
        work.setStrokeCap(Paint.Cap.BUTT);
    }

    /**
     * "5 min ago" / "Yesterday 14:02" / "09/03 14:02" -- relative for the
     * recent past, absolute once relative stops being informative.
     */
    static String relativeTime(long whenMs, long nowMs) {
        long delta = nowMs - whenMs;
        if (delta < 0) delta = 0;
        long minutes = delta / 60000L;
        if (minutes < 1) return "Just now";
        if (minutes < 60) return minutes + " min ago";
        long hours = minutes / 60;
        if (hours < 24) return hours + (hours == 1 ? " hr ago" : " hrs ago");
        long days = hours / 24;
        if (days < 7) return days + (days == 1 ? " day ago" : " days ago");
        return android.text.format.DateFormat.format("MM/dd HH:mm", whenMs).toString();
    }

    /** "0:00" / "12:34" / "1:02:03". */
    static String duration(long seconds) {
        if (seconds < 0) seconds = 0;
        long h = seconds / 3600;
        long m = (seconds % 3600) / 60;
        long s = seconds % 60;
        StringBuilder sb = new StringBuilder();
        if (h > 0) {
            sb.append(h).append(':');
            if (m < 10) sb.append('0');
        }
        sb.append(m).append(':');
        if (s < 10) sb.append('0');
        sb.append(s);
        return sb.toString();
    }

    /**
     * Display formatting for a 3DSTelco device number. These are 3-4 digits,
     * so there is no grouping to do -- but the entry field still needs
     * letter-spacing to be legible at a glance on a 320x240 panel, which is
     * done by drawing with a wide typeface size rather than by inserting
     * separators that would then have to be stripped before dialling.
     */
    static String forDisplay(String digits) {
        if (digits == null) return "";
        // Web account numbers read as (678) 009-3808; 3DS numbers stay bare.
        if (digits.length() == 10) {
            return "(" + digits.substring(0, 3) + ") " + digits.substring(3, 6) + "-" + digits.substring(6);
        }
        return digits;
    }
}
