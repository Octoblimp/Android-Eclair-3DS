package com.android.gpuz;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.view.SurfaceHolder;
import android.view.SurfaceView;

/**
 * Canvas-based benchmark view for GPU-Z.
 *
 * N3DS_GPUZ_CANVAS_BENCHMARK: Uses SurfaceView + lockCanvas/unlockCanvasAndPost
 * running on a dedicated render thread.  This path is safe with PixelFlinger/
 * libagl because it never touches EGL window surfaces or GLSurfaceView — the
 * two paths that crash with PC=0x0 on this device when the PICA200 probe has
 * not yet completed.
 *
 * Four test modes are supported:
 *   0 - Rotating lit cube simulation (multi-polygon vector, depth illusion)
 *   1 - Textured mesh simulation (grid fill + gradient)
 *   2 - Alpha-blended particle stress (many small translucent circles)
 *   3 - 2D canvas fillrate (full-frame gradient sweep)
 */
public class BenchmarkView extends SurfaceView implements SurfaceHolder.Callback {

    private final int mTestId;
    private volatile boolean mRunning = false;

    private float mAngle = 0.0f;
    private int   mFrames = 0;
    private long  mLastTime = 0;
    private float mFps = 0.0f;
    private float mFrameTimeMs = 0.0f;

    private final Paint mPaint    = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mTextPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mFillPaint = new Paint();   /* no AA for fillrate test */

    private Thread mRenderThread = null;

    public BenchmarkView(Context context) {
        this(context, 0);
    }

    public BenchmarkView(Context context, int testId) {
        super(context);
        mTestId = testId;
        mTextPaint.setColor(Color.WHITE);
        mTextPaint.setTextSize(11.0f);
        mTextPaint.setTypeface(android.graphics.Typeface.MONOSPACE);
        mTextPaint.setTextAlign(Paint.Align.CENTER);
        mLastTime = System.currentTimeMillis();
        getHolder().addCallback(this);
    }

    public float getFps()        { return mFps; }
    public float getFrameTimeMs(){ return mFrameTimeMs; }

    public void stopRendering() {
        mRunning = false;
        if (mRenderThread != null) {
            try { mRenderThread.join(500); } catch (InterruptedException ignored) {}
            mRenderThread = null;
        }
    }

    /* SurfaceHolder.Callback ------------------------------------------------*/

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        mRunning = true;
        mRenderThread = new Thread(new Runnable() {
            public void run() { renderLoop(getHolder()); }
        }, "BenchmarkRender");
        mRenderThread.start();
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        stopRendering();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int w, int h) {
        /* nothing needed */
    }

    /* Render loop -----------------------------------------------------------*/

    private void renderLoop(SurfaceHolder holder) {
        while (mRunning) {
            Canvas canvas = null;
            try {
                canvas = holder.lockCanvas();
                if (canvas != null) {
                    long start = System.currentTimeMillis();
                    drawFrame(canvas);
                    long end = System.currentTimeMillis();
                    mFrameTimeMs = (float)(end - start);
                    mFrames++;
                    if (end - mLastTime >= 1000) {
                        mFps = (float)mFrames * 1000.0f / (float)(end - mLastTime);
                        mFrames = 0;
                        mLastTime = end;
                    }
                }
            } catch (Throwable t) {
                /* Never crash the benchmark; just skip the frame. */
            } finally {
                if (canvas != null) {
                    try { holder.unlockCanvasAndPost(canvas); }
                    catch (Throwable ignored) {}
                }
            }
            /* Throttle to ~30fps when rendering is faster than the bus */
            try { Thread.sleep(8); } catch (InterruptedException ignored) {}
        }
    }

    private void drawFrame(Canvas canvas) {
        switch (mTestId) {
            case 0:  drawCube(canvas);      break;
            case 1:  drawMesh(canvas);      break;
            case 2:  drawParticles(canvas); break;
            case 3:  drawFillrate(canvas);  break;
            default: drawCube(canvas);      break;
        }
    }

    /* Test 0: rotating lit cube (vector polygon simulation) */
    private void drawCube(Canvas canvas) {
        int w = canvas.getWidth();
        int h = canvas.getHeight();
        if (w <= 0) w = 320; if (h <= 0) h = 200;
        float cx = w / 2.0f, cy = h / 2.0f;

        canvas.drawColor(Color.rgb(10, 14, 20));

        double rad = Math.toRadians(mAngle);
        float cos = (float)Math.cos(rad);
        float sin = (float)Math.sin(rad);
        float sz = Math.min(w, h) * 0.30f;

        /* Project 8 cube vertices with a simple rotation + perspective */
        float[][] v3 = {
            {-1,-1,-1},{1,-1,-1},{1,1,-1},{-1,1,-1},
            {-1,-1, 1},{1,-1, 1},{1,1, 1},{-1,1, 1}
        };
        float[][] p = new float[8][2];
        for (int i = 0; i < 8; i++) {
            float x = v3[i][0] * cos - v3[i][2] * sin;
            float z = v3[i][0] * sin + v3[i][2] * cos;
            float y = v3[i][1];
            float pers = 1.0f / (z + 3.5f);
            p[i][0] = cx + x * sz * pers;
            p[i][1] = cy + y * sz * pers * 0.85f;
        }

        int[][] faces = {{0,1,2,3},{4,5,6,7},{0,4,5,1},{2,6,7,3},{0,3,7,4},{1,5,6,2}};
        int[] baseColors = {
            Color.rgb(60,100,180), Color.rgb(40,80,140),
            Color.rgb(80,130,210), Color.rgb(50,90,160),
            Color.rgb(30,70,120),  Color.rgb(70,110,190)
        };

        for (int f = 0; f < 6; f++) {
            Path path = new Path();
            int[] idx = faces[f];
            path.moveTo(p[idx[0]][0], p[idx[0]][1]);
            for (int k = 1; k < 4; k++) path.lineTo(p[idx[k]][0], p[idx[k]][1]);
            path.close();
            mPaint.setColor(baseColors[f]);
            mPaint.setStyle(Paint.Style.FILL);
            canvas.drawPath(path, mPaint);
            mPaint.setColor(Color.argb(180, 150, 200, 255));
            mPaint.setStyle(Paint.Style.STROKE);
            mPaint.setStrokeWidth(1.0f);
            canvas.drawPath(path, mPaint);
        }

        mPaint.setStyle(Paint.Style.FILL);
        mPaint.setColor(Color.argb(200, 20, 30, 50));
        canvas.drawRect(cx - 75, cy + sz * 0.7f, cx + 75, cy + sz * 0.7f + 18, mPaint);
        mTextPaint.setColor(Color.CYAN);
        canvas.drawText("3D Cube Bench", cx, cy + sz * 0.7f + 13, mTextPaint);

        mAngle += 2.5f;
        if (mAngle >= 360.0f) mAngle -= 360.0f;
    }

    /* Test 1: textured mesh simulation (grid + per-cell gradient) */
    private void drawMesh(Canvas canvas) {
        int w = canvas.getWidth();
        int h = canvas.getHeight();
        if (w <= 0) w = 320; if (h <= 0) h = 200;

        canvas.drawColor(Color.rgb(5, 10, 18));
        int cols = 16, rows = 12;
        float cw = (float)w / cols, ch = (float)h / rows;
        int phase = (int)mAngle;

        for (int r = 0; r < rows; r++) {
            for (int c = 0; c < cols; c++) {
                float t = (float)Math.sin(Math.toRadians((r + c) * 22 + phase));
                int rv = (int)(80 + t * 60);
                int gv = (int)(120 + t * 80);
                int bv = (int)(200 + t * 55);
                mPaint.setColor(Color.rgb(
                    Math.max(0, Math.min(255, rv)),
                    Math.max(0, Math.min(255, gv)),
                    Math.max(0, Math.min(255, bv))));
                mPaint.setStyle(Paint.Style.FILL);
                canvas.drawRect(c * cw + 1, r * ch + 1,
                                c * cw + cw - 1, r * ch + ch - 1, mPaint);
            }
        }
        float cx = w / 2.0f, cy = h / 2.0f;
        mPaint.setColor(Color.argb(210, 10, 20, 40));
        canvas.drawRect(cx - 70, cy - 10, cx + 70, cy + 16, mPaint);
        mTextPaint.setColor(Color.WHITE);
        canvas.drawText("Mesh Fill Test", cx, cy + 11, mTextPaint);

        mAngle += 4.0f;
        if (mAngle >= 360.0f) mAngle -= 360.0f;
    }

    /* Test 2: alpha-blended particle stress */
    private void drawParticles(Canvas canvas) {
        int w = canvas.getWidth();
        int h = canvas.getHeight();
        if (w <= 0) w = 320; if (h <= 0) h = 200;

        canvas.drawColor(Color.rgb(4, 4, 12));
        int count = 60;
        for (int i = 0; i < count; i++) {
            double a = Math.toRadians(mAngle + i * (360.0 / count));
            double orb = 30.0 + 25.0 * Math.sin(a * 3);
            float x = w / 2.0f + (float)(orb * Math.cos(a));
            float y = h / 2.0f + (float)(orb * Math.sin(a) * 0.7);
            int r = (int)(128 + 127 * Math.sin(a));
            int g = (int)(128 + 127 * Math.cos(a * 1.3));
            int b = (int)(200 + 55 * Math.sin(a * 0.7));
            mPaint.setColor(Color.argb(140,
                Math.max(0,Math.min(255,r)),
                Math.max(0,Math.min(255,g)),
                Math.max(0,Math.min(255,b))));
            mPaint.setStyle(Paint.Style.FILL);
            canvas.drawCircle(x, y, 7.0f, mPaint);
        }
        float cx = w / 2.0f, cy = h / 2.0f;
        mPaint.setColor(Color.argb(220, 8, 8, 30));
        canvas.drawCircle(cx, cy, 22.0f, mPaint);
        mTextPaint.setColor(Color.YELLOW);
        canvas.drawText("Particles", cx, cy + 5, mTextPaint);

        mAngle += 3.0f;
        if (mAngle >= 360.0f) mAngle -= 360.0f;
    }

    /* Test 3: 2D fillrate (full-frame sweep, no AA) */
    private void drawFillrate(Canvas canvas) {
        int w = canvas.getWidth();
        int h = canvas.getHeight();
        if (w <= 0) w = 320; if (h <= 0) h = 200;

        int band = (int)mAngle & 0xff;
        mFillPaint.setColor(Color.rgb(band, 255 - band, (band * 2) & 0xff));
        canvas.drawRect(0, 0, w, h, mFillPaint);
        mFillPaint.setColor(Color.rgb(255 - band, band, (band * 3) & 0xff));
        canvas.drawRect(0, h / 2, w, h, mFillPaint);

        float cx = w / 2.0f, cy = h / 2.0f;
        mPaint.setColor(Color.argb(200, 10, 10, 10));
        mPaint.setStyle(Paint.Style.FILL);
        canvas.drawRect(cx - 75, cy - 12, cx + 75, cy + 16, mPaint);
        mTextPaint.setColor(Color.WHITE);
        canvas.drawText("2D Fillrate Test", cx, cy + 11, mTextPaint);

        mAngle += 5.0f;
        if (mAngle >= 512.0f) mAngle -= 512.0f;
    }
}
