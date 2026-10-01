package com.android.mictest;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.View;

/**
 * A horizontal level meter with a decaying peak-hold marker.
 *
 * The peak hold is the point of it.  A bar that only shows the current chunk
 * makes a single loud syllable in a quiet second look like nothing happened,
 * and on a device where the honest question is "did any non-zero sample
 * arrive at all" that is exactly the wrong thing to hide.  The marker holds
 * the loudest recent chunk and slides back down, so a brief peak stays
 * visible long enough to be read.
 */
final class LevelView extends View {
    /** How much of the remaining distance the peak falls back per frame. */
    private static final float DECAY = 0.08f;

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private float level;
    private float peak;

    LevelView(Context context) {
        super(context);
    }

    /** @param value 0..1; anything outside that is clamped, not trusted. */
    void setLevel(float value) {
        float clamped = value < 0 ? 0 : (value > 1 ? 1 : value);
        level = clamped;
        peak = (clamped > peak) ? clamped : peak - (peak - clamped) * DECAY;
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int width = getWidth();
        int height = getHeight();

        paint.setColor(0xff1c2430);
        canvas.drawRect(0, 0, width, height, paint);

        int filled = (int) (width * level);
        // Green until it is loud, amber near the top: a recording that is
        // clipping is as much a failure as one that is silent.
        paint.setColor(level > 0.9f ? 0xffffb300 : 0xff00e5ff);
        canvas.drawRect(0, 0, filled, height, paint);

        if (peak > 0.01f) {
            int x = (int) (width * peak);
            paint.setColor(0xffe0f7fa);
            canvas.drawRect(Math.max(0, x - 2), 0, Math.min(width, x), height, paint);
        }

        paint.setColor(0xff33404f);
        canvas.drawRect(0, height - 1, width, height, paint);
    }
}
