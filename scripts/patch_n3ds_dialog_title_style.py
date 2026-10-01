#!/usr/bin/env python3
"""Format Dialog and Alert Title styles cleanly for 320x240 Nintendo 3DS screen."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(f"{A3DS_ROOT}/third_party/frameworks/base")
ALERT_LAYOUT = ROOT / "core/res/res/layout/alert_dialog.xml"
DIALOG_TITLE = ROOT / "core/java/com/android/internal/widget/DialogTitle.java"

# 1. Update alert_dialog.xml
alert_text = ALERT_LAYOUT.read_text()
# Replace any DialogTitle in alert_dialog.xml with crisp standard TextView
if "<com.android.internal.widget.DialogTitle" in alert_text:
    old_block_1 = """            <!-- N3DS_CLEAN_DIALOG_TITLE: 16sp bold title fits 320x240 dialog headers
                 without subpixel text fringing or word truncation. -->
            <com.android.internal.widget.DialogTitle android:id="@+id/alertTitle" 
                style="?android:attr/textAppearanceMedium"
                android:textSize="16sp"
                android:textStyle="bold"
                android:singleLine="true"
                android:ellipsize="end"
                android:layout_width="fill_parent" 
                android:layout_height="wrap_content" />"""
    old_block_2 = """            <com.android.internal.widget.DialogTitle android:id="@+id/alertTitle" 
                style="?android:attr/textAppearanceLarge"
                android:singleLine="true"
                android:ellipsize="end"
                android:layout_width="fill_parent" 
                android:layout_height="wrap_content" />"""
    new_title = """            <!-- N3DS_CRISP_ALERT_TITLE: standard TextView prevents
                 DialogTitle from dynamically entering 2-line downscaling and ensures crisp text. -->
            <TextView android:id="@+id/alertTitle" 
                style="?android:attr/textAppearanceLarge"
                android:textSize="16sp"
                android:textStyle="bold"
                android:textColor="#FFFFFFFF"
                android:shadowRadius="0"
                android:shadowColor="#00000000"
                android:singleLine="true"
                android:ellipsize="end"
                android:layout_width="fill_parent" 
                android:layout_height="wrap_content" />"""
    if old_block_1 in alert_text:
        alert_text = alert_text.replace(old_block_1, new_title, 1)
    elif old_block_2 in alert_text:
        alert_text = alert_text.replace(old_block_2, new_title, 1)
    ALERT_LAYOUT.write_text(alert_text)
    print("alert_dialog.xml: replaced with crisp standard TextView")
else:
    print("alert_dialog.xml: already using standard TextView")

# 2. Update DialogTitle.java
dt_text = DIALOG_TITLE.read_text()
if "N3DS_DIALOG_TITLE_NOOP_SCALE" not in dt_text:
    old_measure = """    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec);

        final Layout layout = getLayout();
        if (layout != null) {
            final int lineCount = layout.getLineCount();
            if (lineCount > 0) {
                final int ellipsisCount = layout.getEllipsisCount(lineCount - 1);
                if (ellipsisCount > 0) {
                    setSingleLine(false);
                    
                    TypedArray a = mContext.obtainStyledAttributes(
                            android.R.style.TextAppearance_Medium,
                            android.R.styleable.TextAppearance);
                    final int textSize = a.getDimensionPixelSize(
                            android.R.styleable.TextAppearance_textSize,
                            /* N3DS_DIALOG_TITLE_COMPACT */
                            (int) (16 * getResources().getDisplayMetrics().density));

                    // textSize is already expressed in pixels
                    setTextSize(TypedValue.COMPLEX_UNIT_PX, textSize);
                    setMaxLines(2);
                    super.onMeasure(widthMeasureSpec, heightMeasureSpec);      
                }
            }
        }
    }"""
    new_measure = """    /* N3DS_DIALOG_TITLE_NOOP_SCALE: on 320x240 screen, preserve crisp single-line
     * rendering without dynamic 2-line downscaling or baseline distortion. */
    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec);
    }"""
    if old_measure in dt_text:
        dt_text = dt_text.replace(old_measure, new_measure, 1)
        DIALOG_TITLE.write_text(dt_text)
        print("DialogTitle.java: dynamic 2-line distortion disabled")
    else:
        print("DialogTitle.java: onMeasure anchor not found")
else:
    print("DialogTitle.java: already patched with N3DS_DIALOG_TITLE_NOOP_SCALE")

print("patch_n3ds_dialog_title_style: complete")
