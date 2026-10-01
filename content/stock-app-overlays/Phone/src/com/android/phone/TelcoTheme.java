/*
 * N3DS_TELCO_THEME: palette, metrics and vector icons for the 3DSTelco
 * in-call and voicemail screens.
 *
 * This deliberately mirrors com.android.n3dsdialer.DialerTheme so the dialer
 * and the in-call screen read as one product. It is a copy rather than a
 * shared library because these are two separately built, separately signed
 * APKs with no common library in this build -- a third jar to keep them in
 * sync would cost more than the duplication does. If one palette changes,
 * change both; the constants are the only thing that has to match.
 *
 * Metrics derive from the view's own pixel bounds, never from
 * DisplayMetrics.density: the reported density has been wrong on this port.
 */
package com.android.phone;

import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;

final class TelcoTheme {
    private TelcoTheme() {}

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
    static final int DANGER_HI = Color.rgb(0xF0, 0x62, 0x67);

    static Paint fill(int color) {
        Paint p = new Paint();
        p.setAntiAlias(true);
        p.setColor(color);
        p.setStyle(Paint.Style.FILL);
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
     * Handset silhouette, drawn as geometry.
     *
     * N3DS_TELCO_NO_GLYPH_FONT_DEPENDENCY: the telephone characters a stock
     * in-call screen would use are not guaranteed to be in this build's
     * bundled DroidSans, and a missing glyph renders as an empty box. Lines
     * always render. hangUp flips the handset to the "down" orientation.
     */
    static void handset(Canvas canvas, RectF r, int color, boolean hangUp, Paint work) {
        work.setColor(color);
        work.setStyle(Paint.Style.STROKE);
        work.setStrokeWidth(Math.max(1.5f, r.height() * 0.20f));
        work.setStrokeCap(Paint.Cap.ROUND);
        float x0 = r.left, y0 = hangUp ? r.top : r.bottom;
        float x1 = r.right, y1 = hangUp ? r.bottom : r.top;
        canvas.drawLine(x0, y0, x1, y1, work);
        float lug = r.width() * 0.28f;
        canvas.drawLine(x0, y0, x0 + lug, y0 + (hangUp ? lug : -lug), work);
        canvas.drawLine(x1, y1, x1 - lug, y1 + (hangUp ? -lug : lug), work);
        work.setStyle(Paint.Style.FILL);
        work.setStrokeCap(Paint.Cap.BUTT);
    }

    /** Microphone glyph; struck through when muted. */
    static void microphone(Canvas canvas, RectF r, int color, boolean muted, Paint work) {
        work.setColor(color);
        work.setStyle(Paint.Style.STROKE);
        work.setStrokeWidth(Math.max(1.0f, r.height() * 0.11f));
        float capsuleW = r.width() * 0.42f;
        RectF capsule = new RectF(r.centerX() - capsuleW / 2, r.top,
                r.centerX() + capsuleW / 2, r.top + r.height() * 0.58f);
        canvas.drawRoundRect(capsule, capsuleW / 2, capsuleW / 2, work);
        Path arc = new Path();
        arc.addArc(new RectF(r.left, r.top + r.height() * 0.22f,
                r.right, r.top + r.height() * 0.80f), 20, 140);
        canvas.drawPath(arc, work);
        canvas.drawLine(r.centerX(), r.top + r.height() * 0.80f,
                r.centerX(), r.bottom, work);
        if (muted) {
            work.setColor(DANGER);
            canvas.drawLine(r.left, r.top, r.right, r.bottom, work);
        }
        work.setStyle(Paint.Style.FILL);
    }

    /** Speaker glyph: a cone plus two sound arcs (one arc when quiet). */
    static void speaker(Canvas canvas, RectF r, int color, boolean loud, Paint work) {
        work.setColor(color);
        work.setStyle(Paint.Style.STROKE);
        work.setStrokeWidth(Math.max(1.0f, r.height() * 0.11f));
        float boxRight = r.left + r.width() * 0.30f;
        Path cone = new Path();
        cone.moveTo(r.left, r.top + r.height() * 0.33f);
        cone.lineTo(boxRight, r.top + r.height() * 0.33f);
        cone.lineTo(boxRight + r.width() * 0.22f, r.top);
        cone.lineTo(boxRight + r.width() * 0.22f, r.bottom);
        cone.lineTo(boxRight, r.bottom - r.height() * 0.33f);
        cone.lineTo(r.left, r.bottom - r.height() * 0.33f);
        cone.close();
        canvas.drawPath(cone, work);
        float ax = r.left + r.width() * 0.62f;
        canvas.drawArc(new RectF(ax - r.width() * 0.10f, r.top + r.height() * 0.28f,
                ax + r.width() * 0.20f, r.bottom - r.height() * 0.28f), -60, 120, false, work);
        if (loud) {
            canvas.drawArc(new RectF(ax - r.width() * 0.04f, r.top + r.height() * 0.08f,
                    ax + r.width() * 0.38f, r.bottom - r.height() * 0.08f),
                    -60, 120, false, work);
        }
        work.setStyle(Paint.Style.FILL);
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
}
