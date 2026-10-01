#!/usr/bin/env python3
"""Apply the low-cost Nintendo 3DS status-bar policy to the Eclair tree.

The Eclair status bar lives inside system_server and animates two translucent
overlay windows at 60 Hz.  On the 3DS that blocks the system UI thread for
seconds per frame.  Keep the stock path for every other target, but make a
3DS gesture toggle the panel directly and remove diagnostic stack crawls that
look like crashes whenever WindowManager normally destroys a surface.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/frameworks/base")
STATUS = ROOT / "services/java/com/android/server/status/StatusBarService.java"
WMS = ROOT / "services/java/com/android/server/WindowManagerService.java"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


status = STATUS.read_text()

if "N3DS_LOW_COST_UI" not in status:
    status = replace_once(
        status,
        "import android.os.SystemClock;\n",
        "import android.os.SystemClock;\nimport android.os.SystemProperties;\n",
        "SystemProperties import",
    )
    status = replace_once(
        status,
        "    static final boolean DBG = false;\n",
        "    static final boolean DBG = false;\n"
        "    // Eclair renders this service on system_server's UI thread.  The\n"
        "    // stock 60 Hz translucent-panel animation is too expensive on 3DS.\n"
        "    static final boolean N3DS_LOW_COST_UI =\n"
        "            \"n3ds\".equals(SystemProperties.get(\"ro.product.device\"));\n",
        "n3ds feature flag",
    )
    status = replace_once(
        status,
        "    public StatusBarService(Context context) {\n"
        "        mContext = context;\n",
        "    public StatusBarService(Context context) {\n"
        "        mContext = context;\n"
        "        if (N3DS_LOW_COST_UI) {\n"
        "            Log.i(TAG, \"n3ds low-cost notification shade enabled\");\n"
        "        }\n",
        "low-cost startup marker",
    )
    status = replace_once(
        status,
        "    void animateExpand() {\n"
        "        if (SPEW) Log.d(TAG, \"Animate expand: expanded=\" + mExpanded);\n",
        "    void animateExpand() {\n"
        "        if (N3DS_LOW_COST_UI) {\n"
        "            performExpand();\n"
        "            return;\n"
        "        }\n"
        "        if (SPEW) Log.d(TAG, \"Animate expand: expanded=\" + mExpanded);\n",
        "direct programmatic expand",
    )
    status = replace_once(
        status,
        "    void animateCollapse() {\n"
        "        if (SPEW) Log.d(TAG, \"Animate collapse: expanded=\" + mExpanded\n",
        "    void animateCollapse() {\n"
        "        if (N3DS_LOW_COST_UI) {\n"
        "            performCollapse();\n"
        "            return;\n"
        "        }\n"
        "        if (SPEW) Log.d(TAG, \"Animate collapse: expanded=\" + mExpanded\n",
        "direct programmatic collapse",
    )
    status = replace_once(
        status,
        "    boolean interceptTouchEvent(MotionEvent event) {\n"
        "        if (SPEW) Log.d(TAG, \"Touch: rawY=\" + event.getRawY() + \" event=\" + event);\n",
        "    boolean interceptTouchEvent(MotionEvent event) {\n"
        "        if (N3DS_LOW_COST_UI) {\n"
        "            final int action = event.getAction();\n"
        "            final int hitSize = mStatusBarView.getHeight() * 2;\n"
        "            if (action == MotionEvent.ACTION_DOWN) {\n"
        "                final int y = (int) event.getRawY();\n"
        "                mTracking = (!mExpanded && y < hitSize)\n"
        "                        || (mExpanded && y > mDisplay.getHeight() - hitSize);\n"
        "                return mTracking;\n"
        "            }\n"
        "            if (mTracking) {\n"
        "                if (action == MotionEvent.ACTION_UP) {\n"
        "                    mTracking = false;\n"
        "                    if (mExpanded) {\n"
        "                        performCollapse();\n"
        "                    } else {\n"
        "                        performExpand();\n"
        "                    }\n"
        "                } else if (action == MotionEvent.ACTION_CANCEL) {\n"
        "                    mTracking = false;\n"
        "                }\n"
        "                return true;\n"
        "            }\n"
        "            return false;\n"
        "        }\n"
        "        if (SPEW) Log.d(TAG, \"Touch: rawY=\" + event.getRawY() + \" event=\" + event);\n",
        "direct touch toggle",
    )
    status = replace_once(
        status,
        "        mDateView.startAnimation(loadAnim(anim, null));\n",
        "        if (!N3DS_LOW_COST_UI) {\n"
        "            mDateView.startAnimation(loadAnim(anim, null));\n"
        "        }\n",
        "date animation gate",
    )
    status = replace_once(
        status,
        "            mNotificationIcons.startAnimation(loadAnim(anim, null));\n",
        "            if (!N3DS_LOW_COST_UI) {\n"
        "                mNotificationIcons.startAnimation(loadAnim(anim, null));\n"
        "            }\n",
        "icon animation gate",
    )

if "N3DS_SHADE_SWIPE_CLOSE" not in status:
    status = replace_once(
        status,
        "    private class ExpandedDialog extends Dialog {\n"
        "        ExpandedDialog(Context context) {\n"
        "            super(context, com.android.internal.R.style.Theme_Light_NoTitleBar);\n"
        "        }\n\n"
        "        @Override\n"
        "        public boolean dispatchKeyEvent(KeyEvent event) {\n",
        "    private class ExpandedDialog extends Dialog {\n"
        "        // N3DS_SHADE_SWIPE_CLOSE: accept an upward swipe anywhere in\n"
        "        // the expanded panel, not only on Eclair's tiny bottom handle.\n"
        "        private float mN3dsDownY;\n"
        "\n"
        "        ExpandedDialog(Context context) {\n"
        "            super(context, com.android.internal.R.style.Theme_Light_NoTitleBar);\n"
        "        }\n"
        "\n"
        "        @Override\n"
        "        public boolean dispatchTouchEvent(MotionEvent event) {\n"
        "            if (N3DS_LOW_COST_UI) {\n"
        "                if (event.getAction() == MotionEvent.ACTION_DOWN) {\n"
        "                    mN3dsDownY = event.getRawY();\n"
        "                } else if (event.getAction() == MotionEvent.ACTION_UP\n"
        "                        && mN3dsDownY - event.getRawY()\n"
        "                                >= mStatusBarView.getHeight()) {\n"
        "                    StatusBarService.this.deactivate();\n"
        "                    return true;\n"
        "                }\n"
        "            }\n"
        "            return super.dispatchTouchEvent(event);\n"
        "        }\n"
        "\n"
        "        @Override\n"
        "        public boolean dispatchKeyEvent(KeyEvent event) {\n",
        "expanded shade swipe close",
    )

# Hardware showed a complete 234 -> 30 upward gesture, but the ACTION_UP-only
# dialog hook never collapsed. Child ScrollView gesture ownership may replace
# the terminal event with CANCEL. Collapse as soon as MOVE crosses the status-
# bar-height threshold; Dialog.dispatchTouchEvent sees it before any child.
old_swipe_close = """        // N3DS_SHADE_SWIPE_CLOSE: accept an upward swipe anywhere in
        // the expanded panel, not only on Eclair's tiny bottom handle.
        private float mN3dsDownY;

        ExpandedDialog(Context context) {
            super(context, com.android.internal.R.style.Theme_Light_NoTitleBar);
        }

        @Override
        public boolean dispatchTouchEvent(MotionEvent event) {
            if (N3DS_LOW_COST_UI) {
                if (event.getAction() == MotionEvent.ACTION_DOWN) {
                    mN3dsDownY = event.getRawY();
                } else if (event.getAction() == MotionEvent.ACTION_UP
                        && mN3dsDownY - event.getRawY()
                                >= mStatusBarView.getHeight()) {
                    StatusBarService.this.deactivate();
                    return true;
                }
            }
            return super.dispatchTouchEvent(event);
        }
"""
new_swipe_close = """        // N3DS_SHADE_SWIPE_CLOSE: accept an upward swipe anywhere in
        // the expanded panel, not only on Eclair's tiny bottom handle.
        // N3DS_SHADE_COLLAPSE_ON_MOVE: ScrollView may consume/cancel ACTION_UP,
        // so close immediately after a verified upward MOVE crosses threshold.
        private float mN3dsDownY;
        private boolean mN3dsTrackingSwipe;

        ExpandedDialog(Context context) {
            super(context, com.android.internal.R.style.Theme_Light_NoTitleBar);
        }

        @Override
        public boolean dispatchTouchEvent(MotionEvent event) {
            if (N3DS_LOW_COST_UI) {
                final int action = event.getAction();
                if (action == MotionEvent.ACTION_DOWN) {
                    mN3dsDownY = event.getRawY();
                    mN3dsTrackingSwipe = true;
                } else if (mN3dsTrackingSwipe
                        && (action == MotionEvent.ACTION_MOVE
                                || action == MotionEvent.ACTION_UP)
                        && mN3dsDownY - event.getRawY()
                                >= mStatusBarView.getHeight()) {
                    mN3dsTrackingSwipe = false;
                    Log.i(TAG, "n3ds upward shade swipe: collapsing");
                    StatusBarService.this.performCollapse();
                    return true;
                } else if (action == MotionEvent.ACTION_UP
                        || action == MotionEvent.ACTION_CANCEL) {
                    mN3dsTrackingSwipe = false;
                }
            }
            return super.dispatchTouchEvent(event);
        }
"""
if old_swipe_close in status:
    status = status.replace(old_swipe_close, new_swipe_close, 1)
if "N3DS_SHADE_COLLAPSE_ON_MOVE" not in status:
    raise SystemExit("status bar: MOVE-time upward collapse repair absent")

# This switch was enabled for bring-up photos.  It allocates/logs a synthetic
# RuntimeException on every normal surface destruction, which is the exact
# alarming stack seen in the latest hardware capture.
old_toggle = """        if (N3DS_LOW_COST_UI) {
            final int action = event.getAction();
            final int hitSize = mStatusBarView.getHeight() * 2;
            if (action == MotionEvent.ACTION_DOWN) {
                final int y = (int) event.getRawY();
                mTracking = (!mExpanded && y < hitSize)
                        || (mExpanded && y > mDisplay.getHeight() - hitSize);
                return mTracking;
            }
            if (mTracking) {
                if (action == MotionEvent.ACTION_UP) {
                    mTracking = false;
                    if (mExpanded) {
                        performCollapse();
                    } else {
                        performExpand();
                    }
                } else if (action == MotionEvent.ACTION_CANCEL) {
                    mTracking = false;
                }
                return true;
            }
            return false;
        }
"""
new_toggle = """        if (N3DS_LOW_COST_UI) {
            // N3DS_SHADE_REQUIRES_DRAG: never toggle on a tap. A deliberate
            // downward drag must begin in the real status bar, containing a
            // malformed or temporarily miscalibrated touchscreen at the edge.
            final int action = event.getAction();
            final int hitSize = mStatusBarView.getHeight();
            if (action == MotionEvent.ACTION_DOWN) {
                mN3dsShadeDownY = event.getRawY();
                mTracking = !mExpanded && mN3dsShadeDownY >= 0
                        && mN3dsShadeDownY < hitSize;
                return mTracking;
            }
            if (mTracking) {
                if (action == MotionEvent.ACTION_UP) {
                    final float distance = event.getRawY() - mN3dsShadeDownY;
                    mTracking = false;
                    if (distance >= hitSize) performExpand();
                } else if (action == MotionEvent.ACTION_CANCEL) {
                    mTracking = false;
                }
                return true;
            }
            return false;
        }
"""
if old_toggle in status:
    status = status.replace(old_toggle, new_toggle, 1)
if "N3DS_SHADE_REQUIRES_DRAG" in status and "mN3dsShadeDownY" not in status.split("boolean interceptTouchEvent", 1)[0]:
    status = status.replace("    static final boolean N3DS_LOW_COST_UI =\n",
                            "    private float mN3dsShadeDownY;\n"
                            "    static final boolean N3DS_LOW_COST_UI =\n", 1)
if "N3DS_SHADE_REQUIRES_DRAG" not in status:
    raise SystemExit("status bar: deliberate-drag marker absent")

status = status.replace("    static final boolean DEBUG = true;\n",
                        "    static final boolean DEBUG = false;\n", 1)
STATUS.write_text(status)

wms = WMS.read_text()
for name in (
    "DEBUG", "DEBUG_FOCUS", "DEBUG_ANIM", "DEBUG_LAYERS", "DEBUG_INPUT",
    "DEBUG_INPUT_METHOD", "DEBUG_VISIBILITY", "DEBUG_WINDOW_MOVEMENT",
    "DEBUG_ORIENTATION", "DEBUG_APP_TRANSITIONS", "DEBUG_STARTING_WINDOW",
    "DEBUG_REORDER", "DEBUG_WALLPAPER",
):
    wms = wms.replace(f"    static final boolean {name} = true;\n",
                      f"    static final boolean {name} = false;\n", 1)
WMS.write_text(wms)

print("patch_n3ds_statusbar: low-cost shade enabled; WindowManager debug stacks disabled")
