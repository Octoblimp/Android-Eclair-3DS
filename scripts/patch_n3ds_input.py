#!/usr/bin/env python3
"""Patch the 3DS touch sampler and Eclair's physical-button policy.

The TSC FIFO contains five samples for each axis.  The historical virtual
keyboard driver used only sample zero; on current N3DS hardware that sample
can be the just-consumed/stale slot, yielding a stream of (0, 0) touches.
Median-filter all five hardware samples and expose a real pressure axis.

Eclair also treats HOME as an asynchronous "app switch" before policy gets
to consume it.  A hardware HOME key handled by PhoneWindowManager therefore
leaves KeyWaiter armed forever and every later touch/key is discarded.  The
3DS has explicit HOME/BACK/RECENTS buttons, so it must bypass that obsolete
timeout gate while retaining normal PhoneWindowManager handling.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
TOUCH = ROOT / "third_party/linux/drivers/platform/nintendo3ds/tsc/touch.c"
POLICY = ROOT / ("third_party/frameworks/policies/base/phone/com/android/"
                 "internal/policy/impl/PhoneWindowManager.java")
HID_KEYLAYOUT = ROOT / ("third_party/buildroot/board/nintendo3ds/"
                        "rootfs_overlay/system/usr/keylayout/hid_buttons.kl")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


touch = TOUCH.read_text()
if "N3DS_MEDIAN_TOUCH_SAMPLES" not in touch:
    touch = replace_once(
        touch,
        "#define TOUCH_MAX_Y\t\t\t240\n",
        "#define TOUCH_MAX_Y\t\t\t240\n"
        "#define N3DS_MEDIAN_TOUCH_SAMPLES\t5\n",
        "touch sample count",
    )
    touch = replace_once(
        touch,
        "static void touch_input_poll(struct input_dev *input)\n{\n",
        "/* Sort five 12-bit ADC readings in place and return the median. */\n"
        "static u16 touch_median(u16 *sample)\n"
        "{\n"
        "\tint i, j;\n"
        "\n"
        "\tfor (i = 1; i < N3DS_MEDIAN_TOUCH_SAMPLES; i++) {\n"
        "\t\tu16 value = sample[i];\n"
        "\t\tfor (j = i; j > 0 && sample[j - 1] > value; j--)\n"
        "\t\t\tsample[j] = sample[j - 1];\n"
        "\t\tsample[j] = value;\n"
        "\t}\n"
        "\treturn sample[N3DS_MEDIAN_TOUCH_SAMPLES / 2];\n"
        "}\n"
        "\n"
        "static void touch_input_poll(struct input_dev *input)\n{\n",
        "median helper",
    )
    touch = replace_once(
        touch,
        "\tu16 screen_touch_y;\n",
        "\tu16 screen_touch_y;\n"
        "\tu16 x_samples[N3DS_MEDIAN_TOUCH_SAMPLES];\n"
        "\tu16 y_samples[N3DS_MEDIAN_TOUCH_SAMPLES];\n"
        "\tint touch_down_samples;\n"
        "\tint i;\n",
        "sample locals",
    )
    touch = replace_once(
        touch,
        "\tpendown = !(raw_data[0] & BIT(4));\n\n"
        "\tif (pendown) {\n"
        "\t\t/* The sample is 12 bits; the upper nibble of byte 0 carries\n"
        "\t\t * status flags (BIT(4) is pen-up), so mask it off. */\n"
        "\t\traw_touch_x = le16_to_cpu((raw_data[0]  << 8) | raw_data[1]) & MAX_12BIT;\n"
        "\t\traw_touch_y = le16_to_cpu((raw_data[10] << 8) | raw_data[11]) & MAX_12BIT;\n",
        "\t/* The FIFO is five big-endian 16-bit samples for X followed by\n"
        "\t * five for Y.  Its upper nibble contains status; ADC data is the\n"
        "\t * low 12 bits.  Majority-vote pen state and median-filter the ADC\n"
        "\t * values so a stale first FIFO slot cannot pin Android at (0,0). */\n"
        "\ttouch_down_samples = 0;\n"
        "\tfor (i = 0; i < N3DS_MEDIAN_TOUCH_SAMPLES; i++) {\n"
        "\t\tu16 xword = ((u16)raw_data[i * 2] << 8) | raw_data[i * 2 + 1];\n"
        "\t\tu16 yword = ((u16)raw_data[10 + i * 2] << 8) | raw_data[11 + i * 2];\n"
        "\t\tif (!(xword & BIT(12)))\n"
        "\t\t\ttouch_down_samples++;\n"
        "\t\tx_samples[i] = xword & MAX_12BIT;\n"
        "\t\ty_samples[i] = yword & MAX_12BIT;\n"
        "\t}\n"
        "\tpendown = touch_down_samples >= 3;\n"
        "\n"
        "\tif (pendown) {\n"
        "\t\traw_touch_x = touch_median(x_samples);\n"
        "\t\traw_touch_y = touch_median(y_samples);\n",
        "touch FIFO decode",
    )
    touch = replace_once(
        touch,
        "\t\tinput_report_abs(input, ABS_Y, screen_touch_y);\n\n"
        "\t\tif (!touch_hid->pendown) {\n",
        "\t\tinput_report_abs(input, ABS_Y, screen_touch_y);\n"
        "\t\tinput_report_abs(input, ABS_PRESSURE, 1);\n\n"
        "\t\tif (!touch_hid->pendown) {\n",
        "touch pressure down",
    )
    touch = replace_once(
        touch,
        "\t\ttouch_hid->pendown = false;\n"
        "\t\tinput_report_key(input, BTN_TOUCH, 0);\n",
        "\t\ttouch_hid->pendown = false;\n"
        "\t\tinput_report_abs(input, ABS_PRESSURE, 0);\n"
        "\t\tinput_report_key(input, BTN_TOUCH, 0);\n",
        "touch pressure up",
    )
    touch = replace_once(
        touch,
        "\tinput_set_abs_params(input, ABS_Y, 0, TOUCH_MAX_Y - 1, 0, 0);\n",
        "\tinput_set_abs_params(input, ABS_Y, 0, TOUCH_MAX_Y - 1, 0, 0);\n"
        "\tinput_set_abs_params(input, ABS_PRESSURE, 0, 1, 0, 0);\n",
        "pressure axis",
    )
TOUCH.write_text(touch)


policy = POLICY.read_text()
if "N3DS_NO_LEGACY_APP_SWITCH_GATE" not in policy:
    policy = replace_once(
        policy,
        "    public boolean isAppSwitchKeyTqTiLwLi(int keycode) {\n"
        "        return keycode == KeyEvent.KEYCODE_HOME\n"
        "                || keycode == KeyEvent.KEYCODE_ENDCALL;\n"
        "    }\n",
        "    public boolean isAppSwitchKeyTqTiLwLi(int keycode) {\n"
        "        // N3DS_NO_LEGACY_APP_SWITCH_GATE: HOME is consumed globally\n"
        "        // by this policy.  Arming Eclair's KeyWaiter before that would\n"
        "        // never receive the later dispatch that clears it, permanently\n"
        "        // dropping BACK, RECENTS, and all touchscreen events.\n"
        "        if (\"n3ds\".equals(SystemProperties.get(\"ro.product.device\"))) {\n"
        "            return false;\n"
        "        }\n"
        "        return keycode == KeyEvent.KEYCODE_HOME\n"
        "                || keycode == KeyEvent.KEYCODE_ENDCALL;\n"
        "    }\n",
        "legacy app-switch policy",
    )

if "N3DS_GLOBAL_NAVIGATION_KEYS" not in policy:
    policy = replace_once(
        policy,
        "    /** {@inheritDoc} */\n"
        "    public boolean interceptKeyTi(WindowState win, int code, int metaKeys, boolean down, \n"
        "            int repeatCount, int flags) {\n"
        "        boolean keyguardOn = keyguardOn();\n\n"
        "        // BTN_B is the 3DS running-apps button. Consume it globally so the\n"
        "        // focused application cannot turn it into text, and reuse Eclair's\n"
        "        // existing recent-applications dialog.\n"
        "        if (\"n3ds\".equals(SystemProperties.get(\"ro.product.device\"))\n"
        "                && code == KeyEvent.KEYCODE_B) {\n"
        "            if (!down && repeatCount == 0 && !keyguardOn) {\n"
        "                Log.i(TAG, \"n3ds B: showing recent applications\");\n"
        "                sendCloseSystemWindows(SYSTEM_DIALOG_REASON_RECENT_APPS);\n"
        "                showRecentAppsDialog();\n"
        "            }\n"
        "            return true;\n"
        "        }\n",
        "    // N3DS_GLOBAL_NAVIGATION_KEYS: the expanded notification dialog is a\n"
        "    // system-alert window, and stock Eclair intentionally disables HOME\n"
        "    // while such a window has focus.  Route the dedicated hardware keys\n"
        "    // before that rule and always ask the shade to collapse first.\n"
        "    private void n3dsCollapseStatusBar() {\n"
        "        IStatusBar status = IStatusBar.Stub.asInterface(\n"
        "                ServiceManager.getService(\"statusbar\"));\n"
        "        if (status != null) {\n"
        "            try {\n"
        "                status.deactivate();\n"
        "            } catch (RemoteException ignored) {\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "\n"
        "    /** {@inheritDoc} */\n"
        "    public boolean interceptKeyTi(WindowState win, int code, int metaKeys, boolean down, \n"
        "            int repeatCount, int flags) {\n"
        "        boolean keyguardOn = keyguardOn();\n"
        "\n"
        "        if (\"n3ds\".equals(SystemProperties.get(\"ro.product.device\"))\n"
        "                && (code == KeyEvent.KEYCODE_HOME\n"
        "                        || code == KeyEvent.KEYCODE_BACK\n"
        "                        || code == KeyEvent.KEYCODE_B)) {\n"
        "            Log.i(TAG, \"n3ds nav key code=\" + code + \" down=\" + down);\n"
        "            if (down && repeatCount == 0) {\n"
        "                n3dsCollapseStatusBar();\n"
        "            }\n"
        "            if (code == KeyEvent.KEYCODE_BACK) {\n"
        "                return false;\n"
        "            }\n"
        "            if (code == KeyEvent.KEYCODE_HOME) {\n"
        "                if (!down && repeatCount == 0 && !keyguardOn\n"
        "                        && (flags & KeyEvent.FLAG_CANCELED) == 0) {\n"
        "                    Log.i(TAG, \"n3ds MCU HOME: launching home\");\n"
        "                    launchHomeFromHotKey();\n"
        "                }\n"
        "                return true;\n"
        "            }\n"
        "            if (!down && repeatCount == 0 && !keyguardOn) {\n"
        "                Log.i(TAG, \"n3ds B: showing recent applications\");\n"
        "                sendCloseSystemWindows(SYSTEM_DIALOG_REASON_RECENT_APPS);\n"
        "                showRecentAppsDialog();\n"
        "            }\n"
        "            return true;\n"
        "        }\n",
        "global n3ds navigation",
    )
POLICY.write_text(policy)


# A is no longer an Android navigation key.  The dedicated 3DS HOME button is
# exposed separately by mcu_buttons as Linux KEY_HOME (scancode 102).
keylayout = HID_KEYLAYOUT.read_text()
keylayout = keylayout.replace("key 304   HOME\n", "# BTN_A (304) intentionally unmapped\n", 1)
HID_KEYLAYOUT.write_text(keylayout)

print("patch_n3ds_input: median touch; Y=BACK B=recents MCU-HOME=HOME; A unmapped")
