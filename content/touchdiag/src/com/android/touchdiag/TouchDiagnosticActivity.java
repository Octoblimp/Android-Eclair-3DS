package com.android.touchdiag;

import android.app.Activity;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.os.Bundle;
import android.util.Log;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;

/** Full-panel single-touch tester for the Nintendo 3DS resistive digitizer. */
public final class TouchDiagnosticActivity extends Activity {
    private static final String TAG = "TouchDiag";

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        setContentView(new TouchView());
        Log.i(TAG, "N3DS_TOUCH_DIAG_READY single-touch 320x240 target test");
    }

    /**
     * N3DS_TOUCH_CALIBRATION_SYSFS producer/consumer counterpart: locates the
     * kernel driver's raw_x/raw_y/raw_down attributes by matching the
     * world-readable sibling "name" file under /sys/class/input, exactly the
     * way the driver comment documents, rather than hardcoding a devicetree
     * node path that could change.
     */
    private static final class RawTouchNode {
        private static final String DEVICE_NAME = "Android3DS Direct Touchscreen";
        private static final String CLASS_INPUT = "/sys/class/input";

        private File dir;

        boolean resolve() {
            if (dir != null) return true;
            File base = new File(CLASS_INPUT);
            File[] kids = base.listFiles();
            if (kids == null) return false;
            for (int i = 0; i < kids.length; i++) {
                File nameFile = new File(kids[i], "name");
                String name = readLine(nameFile);
                if (name != null && name.trim().equals(DEVICE_NAME)) {
                    dir = kids[i];
                    return true;
                }
            }
            return false;
        }

        int readRawX() { return readInt("raw_x"); }
        int readRawY() { return readInt("raw_y"); }

        private int readInt(String attr) {
            if (!resolve()) return -1;
            String line = readLine(new File(dir, attr));
            if (line == null) return -1;
            try {
                return Integer.parseInt(line.trim());
            } catch (NumberFormatException e) {
                return -1;
            }
        }

        private static String readLine(File f) {
            BufferedReader r = null;
            try {
                r = new BufferedReader(new FileReader(f));
                return r.readLine();
            } catch (IOException e) {
                return null;
            } finally {
                if (r != null) {
                    try { r.close(); } catch (IOException ignored) { }
                }
            }
        }
    }

    private final class TouchView extends View {
        private static final int TARGET_COUNT = 5;
        private static final String CAL_CONF_PATH = "/data/misc/touchcalibration.conf";
        private static final int CAL_INSET = 32;

        private final Paint paint = new Paint();
        private final Path path = new Path();
        private final boolean[] hit = new boolean[TARGET_COUNT];
        private final float[] tx = new float[TARGET_COUNT];
        private final float[] ty = new float[TARGET_COUNT];
        private float lastX;
        private float lastY;
        private float lastPressure;
        private int lastAction = -1;
        private int events;
        private int downs;
        private int moves;
        private int ups;
        private int pointerCount;
        private boolean havePoint;

        // Calibrate-mode state, entered/left with the MENU key.
        private final RawTouchNode rawNode = new RawTouchNode();
        private boolean calibrating;
        private int calStep;
        private float calTargetX0, calTargetY0;
        private float calTargetX1, calTargetY1;
        private int calRawX0, calRawY0;
        private String calStatus;

        TouchView() {
            super(TouchDiagnosticActivity.this);
            paint.setAntiAlias(false);
            setFocusable(true);
            setClickable(true);
            setBackgroundColor(Color.rgb(8, 14, 18));
        }

        @Override
        protected void onSizeChanged(int w, int h, int oldw, int oldh) {
            tx[0] = 22;       ty[0] = 48;
            tx[1] = w - 22;   ty[1] = 48;
            tx[2] = w / 2;    ty[2] = h / 2;
            tx[3] = 22;       ty[3] = h - 22;
            tx[4] = w - 22;   ty[4] = h - 22;

            calTargetX0 = CAL_INSET;
            calTargetY0 = CAL_INSET;
            calTargetX1 = w - CAL_INSET;
            calTargetY1 = h - CAL_INSET;
        }

        @Override
        protected void onDraw(Canvas c) {
            super.onDraw(c);
            if (calibrating) {
                drawCalibrate(c);
            } else {
                drawDiagnostic(c);
            }
        }

        private void drawDiagnostic(Canvas c) {
            int w = getWidth();
            int h = getHeight();

            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(1);
            paint.setColor(Color.rgb(40, 65, 72));
            for (int x = 0; x < w; x += 32) c.drawLine(x, 0, x, h, paint);
            for (int y = 0; y < h; y += 24) c.drawLine(0, y, w, y, paint);

            for (int i = 0; i < TARGET_COUNT; i++) {
                paint.setColor(hit[i] ? Color.GREEN : Color.YELLOW);
                paint.setStrokeWidth(hit[i] ? 4 : 2);
                c.drawCircle(tx[i], ty[i], 13, paint);
                c.drawLine(tx[i] - 18, ty[i], tx[i] + 18, ty[i], paint);
                c.drawLine(tx[i], ty[i] - 18, tx[i], ty[i] + 18, paint);
            }

            paint.setColor(Color.CYAN);
            paint.setStrokeWidth(2);
            c.drawPath(path, paint);
            if (havePoint) {
                paint.setColor(Color.MAGENTA);
                c.drawCircle(lastX, lastY, 6, paint);
            }

            paint.setStyle(Paint.Style.FILL);
            paint.setTextSize(12);
            paint.setColor(Color.WHITE);
            c.drawText("Touch each target; drag across the grid", 5, 13, paint);
            c.drawText("x=" + (int) lastX + " y=" + (int) lastY
                    + " p=" + lastPressure + " ptr=" + pointerCount, 5, 27, paint);
            c.drawText("events=" + events + " down=" + downs + " move=" + moves
                    + " up=" + ups + " targets=" + hits() + "/5", 5, 40, paint);
            if (hits() == TARGET_COUNT) {
                paint.setTextSize(24);
                paint.setColor(Color.GREEN);
                c.drawText("PASS", w / 2 - 29, h / 2 - 20, paint);
            } else if (lastAction < 0) {
                paint.setColor(Color.LTGRAY);
                c.drawText("Waiting for ACTION_DOWN...", 5, h - 5, paint);
            }
            paint.setColor(Color.LTGRAY);
            c.drawText("MENU: calibrate", w - 90, h - 5, paint);
        }

        private void drawCalibrate(Canvas c) {
            int w = getWidth();
            int h = getHeight();

            paint.setStyle(Paint.Style.FILL);
            paint.setTextSize(12);
            paint.setColor(Color.WHITE);
            c.drawText("Touch calibration -- MENU to cancel", 5, 13, paint);

            if (calStatus != null) {
                paint.setColor(Color.GREEN);
                c.drawText(calStatus, 5, 30, paint);
                paint.setColor(Color.LTGRAY);
                c.drawText("MENU: back to diagnostic", 5, h - 5, paint);
                return;
            }

            float targetX = calStep == 0 ? calTargetX0 : calTargetX1;
            float targetY = calStep == 0 ? calTargetY0 : calTargetY1;

            paint.setColor(Color.YELLOW);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(2);
            c.drawCircle(targetX, targetY, 13, paint);
            c.drawLine(targetX - 18, targetY, targetX + 18, targetY, paint);
            c.drawLine(targetX, targetY - 18, targetX, targetY + 18, paint);

            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.WHITE);
            c.drawText("Touch target " + (calStep + 1) + " of 2 precisely", 5, h / 2, paint);
        }

        @Override
        public boolean onKeyDown(int keyCode, KeyEvent event) {
            if (keyCode == KeyEvent.KEYCODE_MENU) {
                calibrating = !calibrating;
                calStep = 0;
                calStatus = null;
                invalidate();
                return true;
            }
            return super.onKeyDown(keyCode, event);
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            if (calibrating) {
                return onCalibrateTouch(e);
            }
            return onDiagnosticTouch(e);
        }

        private boolean onCalibrateTouch(MotionEvent e) {
            if (e.getAction() != MotionEvent.ACTION_DOWN || calStatus != null) {
                return true;
            }
            float x = e.getX();
            float y = e.getY();
            float targetX = calStep == 0 ? calTargetX0 : calTargetX1;
            float targetY = calStep == 0 ? calTargetY0 : calTargetY1;
            float dx = x - targetX;
            float dy = y - targetY;
            if (dx * dx + dy * dy > 28 * 28) {
                return true;
            }

            int rawX = rawNode.readRawX();
            int rawY = rawNode.readRawY();
            if (rawX < 0 || rawY < 0) {
                calStatus = "Raw touch sysfs unavailable; calibration aborted";
                invalidate();
                return true;
            }

            if (calStep == 0) {
                calRawX0 = rawX;
                calRawY0 = rawY;
                calStep = 1;
                Log.i(TAG, "calibrate point0 raw=(" + rawX + "," + rawY + ")");
            } else {
                calStatus = saveCalibration(calRawX0, rawX, calRawY0, rawY);
                Log.i(TAG, "calibrate point1 raw=(" + rawX + "," + rawY + ") -> " + calStatus);
            }
            invalidate();
            return true;
        }

        /**
         * Writes the two-point-per-axis cal_* config that
         * android_prefs_init.sh imports into /data/misc/touchcalibration.conf
         * at boot and applies to the kernel's sysfs module params. Takes
         * effect on the next boot, the same "calibrate once, keep it" model
         * GodMode9 uses for its own HWCAL -- this app has no path to poke
         * root-owned 0644 sysfs files live.
         */
        private String saveCalibration(int rawX0, int rawX1, int rawY0, int rawY1) {
            FileWriter w = null;
            try {
                w = new FileWriter(CAL_CONF_PATH, false);
                w.write("cal_x0_raw=" + rawX0 + "\n");
                w.write("cal_x0_px=" + (int) calTargetX0 + "\n");
                w.write("cal_x1_raw=" + rawX1 + "\n");
                w.write("cal_x1_px=" + (int) calTargetX1 + "\n");
                w.write("cal_y0_raw=" + rawY0 + "\n");
                w.write("cal_y0_px=" + (int) calTargetY0 + "\n");
                w.write("cal_y1_raw=" + rawY1 + "\n");
                w.write("cal_y1_px=" + (int) calTargetY1 + "\n");
                return "Saved. Reboot to apply new calibration.";
            } catch (IOException e) {
                Log.e(TAG, "failed to write " + CAL_CONF_PATH, e);
                return "Write failed: " + e.getMessage();
            } finally {
                if (w != null) {
                    try { w.close(); } catch (IOException ignored) { }
                }
            }
        }

        private boolean onDiagnosticTouch(MotionEvent e) {
            int action = e.getAction() & MotionEvent.ACTION_MASK;
            lastX = e.getX();
            lastY = e.getY();
            lastPressure = e.getPressure();
            pointerCount = e.getPointerCount();
            lastAction = action;
            events++;
            havePoint = true;

            if (action == MotionEvent.ACTION_DOWN) {
                downs++;
                path.moveTo(lastX, lastY);
            } else if (action == MotionEvent.ACTION_MOVE) {
                moves++;
                path.lineTo(lastX, lastY);
            } else if (action == MotionEvent.ACTION_UP
                    || action == MotionEvent.ACTION_CANCEL) {
                ups++;
                path.lineTo(lastX, lastY);
            }

            for (int i = 0; i < TARGET_COUNT; i++) {
                float dx = lastX - tx[i];
                float dy = lastY - ty[i];
                if (dx * dx + dy * dy <= 24 * 24) hit[i] = true;
            }

            if (action != MotionEvent.ACTION_MOVE || (events & 7) == 0) {
                Log.i(TAG, "event action=" + action + " x=" + lastX + " y="
                        + lastY + " pressure=" + lastPressure + " pointers="
                        + pointerCount + " targets=" + hits());
            }
            invalidate();
            return true;
        }

        private int hits() {
            int count = 0;
            for (int i = 0; i < TARGET_COUNT; i++) if (hit[i]) count++;
            return count;
        }
    }
}
