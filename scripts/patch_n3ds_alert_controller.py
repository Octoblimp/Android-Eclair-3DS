#!/usr/bin/env python3
"""
Fix AlertController title text rendering to prevent subpixel fringing on 3DS LCD.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ALERT_CONTROLLER_JAVA = Path(f"{A3DS_ROOT}/third_party/frameworks/base/core/java/com/android/internal/app/AlertController.java")

text = ALERT_CONTROLLER_JAVA.read_text()

if "N3DS_NO_SUBPIXEL" not in text:
    old_code = """                mTitleView = (TextView) mWindow.findViewById(R.id.alertTitle);

                mTitleView.setText(mTitle);"""
    
    new_code = """                mTitleView = (TextView) mWindow.findViewById(R.id.alertTitle);
                
                /* N3DS_NO_SUBPIXEL: 3DS LCD has unique subpixel arrangement, 
                 * disable subpixel text flag to avoid red/cyan fringing */
                mTitleView.getPaint().setFlags(mTitleView.getPaint().getFlags() & ~android.graphics.Paint.SUBPIXEL_TEXT_FLAG);

                mTitleView.setText(mTitle);"""
    
    if old_code in text:
        text = text.replace(old_code, new_code, 1)
        ALERT_CONTROLLER_JAVA.write_text(text)
        print("AlertController.java patched: N3DS_NO_SUBPIXEL added")
    else:
        print("Failed to find injection point in AlertController.java")
else:
    print("AlertController.java already patched")
