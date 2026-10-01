#!/usr/bin/env python3
"""Use the 3DS panel's real single-touch protocol and restore requested logs.

The 3DS digitizer is a single-contact resistive panel.  Advertising synthetic
multitouch made Eclair select CLASS_TOUCHSCREEN_MT and ignore the stable
BTN_TOUCH/ABS_X/ABS_Y state machine.  Protocol A also requires a complete
contact record in every frame, while Linux may coalesce unchanged ABS values;
that combination can turn a held contact into an immediate empty MT frame.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
TOUCH = ROOT / "third_party/linux/drivers/platform/nintendo3ds/tsc/touch.c"
EVENT_HUB = ROOT / "third_party/frameworks/base/libs/ui/EventHub.cpp"
KEY_QUEUE = ROOT / "third_party/frameworks/base/services/java/com/android/server/KeyInputQueue.java"
INIT_RC = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/init.rc"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


touch = TOUCH.read_text()

# The canonical pipeline first rewrites touch.c from the direct-touch template,
# so these removals primarily make this patch safe to apply to the currently
# deployed Protocol-A tree without requiring a clean checkout.
touch = touch.replace(" * N3DS_ANDROID_PROTOCOL_A_MT\n", "")
touch = touch.replace("#include <linux/input/mt.h>\n", "")
touch = touch.replace(
    """\t\t/* Android Eclair's EventHub prefers the old Protocol-A MT
\t\t * interface whenever these axes exist. Keep the legacy fields above
\t\t * for evdev diagnostics and newer compatibility, but make the MT
\t\t * frame the authoritative Android contact. */
\t\tinput_report_abs(input, ABS_PRESSURE, 1);
\t\tinput_report_key(input, BTN_TOUCH, 1);
\t\tinput_report_abs(input, ABS_MT_TOUCH_MAJOR, 1);
\t\tinput_report_abs(input, ABS_MT_POSITION_X, x);
\t\tinput_report_abs(input, ABS_MT_POSITION_Y, y);
\t\tinput_mt_sync(input);
\t\tinput_sync(input);""",
    """\t\t/* N3DS_HARDWARE_SINGLE_TOUCH: the resistive panel can report one
\t\t * contact.  Keep it on Eclair's persistent BTN_TOUCH state machine;
\t\t * do not advertise synthetic ABS_MT axes on this device. */
\t\tinput_report_abs(input, ABS_PRESSURE, 1);
\t\tinput_report_key(input, BTN_TOUCH, 1);
\t\tinput_sync(input);""",
)
touch = touch.replace(
    """\t\tinput_report_abs(input, ABS_PRESSURE, 0);
\t\tinput_report_key(input, BTN_TOUCH, 0);
\t\tinput_report_abs(input, ABS_MT_TOUCH_MAJOR, 0);
\t\tinput_mt_sync(input);
\t\tinput_sync(input);""",
    """\t\tinput_report_abs(input, ABS_PRESSURE, 0);
\t\tinput_report_key(input, BTN_TOUCH, 0);
\t\tinput_sync(input);""",
)
touch = touch.replace(
    """\t/* N3DS_ANDROID_PROTOCOL_A_MT: Eclair recognizes this exact triplet
\t * before considering the legacy BTN_TOUCH/ABS_X/ABS_Y path. */
\tinput_set_abs_params(input, ABS_MT_TOUCH_MAJOR, 0, 1, 0, 0);
\tinput_set_abs_params(input, ABS_MT_POSITION_X, 0, SCREEN_WIDTH - 1, 0, 0);
\tinput_set_abs_params(input, ABS_MT_POSITION_Y, 0, SCREEN_HEIGHT - 1, 0, 0);
""",
    "",
)
if "N3DS_HARDWARE_SINGLE_TOUCH" not in touch:
    touch = replace_once(
        touch,
        """\t\tinput_report_abs(input, ABS_PRESSURE, 1);
\t\tinput_report_key(input, BTN_TOUCH, 1);
\t\tinput_sync(input);""",
        """\t\t/* N3DS_HARDWARE_SINGLE_TOUCH: the resistive panel can report one
\t\t * contact.  Keep it on Eclair's persistent BTN_TOUCH state machine;
\t\t * do not advertise synthetic ABS_MT axes on this device. */
\t\tinput_report_abs(input, ABS_PRESSURE, 1);
\t\tinput_report_key(input, BTN_TOUCH, 1);
\t\tinput_sync(input);""",
        "single-touch marker",
    )

if "ABS_MT_" in touch or "input_mt_sync" in touch:
    raise SystemExit("touch: synthetic multitouch interface survived")
TOUCH.write_text(touch)


event_hub = EVENT_HUB.read_text()
if "N3DS_TOUCH_ABS_PRESSURE_FALLBACK" not in event_hub:
    event_hub = replace_once(
        event_hub,
        """    } else if (test_bit(BTN_TOUCH, key_bitmask)
            && test_bit(ABS_X, abs_bitmask) && test_bit(ABS_Y, abs_bitmask)) {
        device->classes |= CLASS_TOUCHSCREEN;
    }""",
        """    } else if ((test_bit(BTN_TOUCH, key_bitmask)
                || test_bit(ABS_PRESSURE, abs_bitmask))
            && test_bit(ABS_X, abs_bitmask) && test_bit(ABS_Y, abs_bitmask)) {
        // N3DS_TOUCH_ABS_PRESSURE_FALLBACK: accept resistive controllers
        // whose contact state is carried by pressure even if BTN_TOUCH is
        // lost or reordered by an older evdev bridge.
        device->classes |= CLASS_TOUCHSCREEN;
    }""",
        "EventHub pressure classification fallback",
    )
EVENT_HUB.write_text(event_hub)


key_queue = KEY_QUEUE.read_text()
if "N3DS_TOUCH_PRESSURE_SETS_DOWN" not in key_queue:
    key_queue = replace_once(
        key_queue,
        """                            } else if (ev.scancode == RawInputEvent.ABS_PRESSURE) {
                                di.mAbs.changed = true;
                                di.curTouchVals[MotionEvent.SAMPLE_PRESSURE] = ev.value;""",
        """                            } else if (ev.scancode == RawInputEvent.ABS_PRESSURE) {
                                di.mAbs.changed = true;
                                // N3DS_TOUCH_PRESSURE_SETS_DOWN: the direct
                                // resistive panel reports pressure in the
                                // same SYN frame as position. Treat it as an
                                // independent single-touch contact signal.
                                di.mAbs.mDown[0] = ev.value > 0;
                                di.curTouchVals[MotionEvent.SAMPLE_PRESSURE] = ev.value;""",
        "KeyInputQueue pressure contact fallback",
    )
if "N3DS_SINGLE_TOUCH_DISPATCH_TRACE" not in key_queue:
    key_queue = replace_once(
        key_queue,
        """                                di.mAbs.changed = true;
                                di.mAbs.mDown[0] = ev.value != 0;
                            
                            // Trackball (mouse) protocol:""",
        """                                di.mAbs.changed = true;
                                di.mAbs.mDown[0] = ev.value != 0;
                                // N3DS_SINGLE_TOUCH_DISPATCH_TRACE: one bounded
                                // line per physical transition proves the raw
                                // event reached Eclair's single-touch parser.
                                if ("Android3DS Direct Touchscreen".equals(di.name)) {
                                    Log.i(TAG, "N3DS touch "
                                            + (ev.value != 0 ? "DOWN" : "UP")
                                            + " raw=(" + di.curTouchVals[MotionEvent.SAMPLE_X]
                                            + "," + di.curTouchVals[MotionEvent.SAMPLE_Y] + ")");
                                }
                            
                            // Trackball (mouse) protocol:""",
        "single-touch dispatch trace",
    )
KEY_QUEUE.write_text(key_queue)


initrc = INIT_RC.read_text()
for service in ("logcat", "bootprogress"):
    start = initrc.index(f"service {service} ")
    end = initrc.find("\nservice ", start + 1)
    if end < 0:
        end = len(initrc)
    block = initrc[start:end]
    if "\n    disabled" in block:
        block = block.replace("\n    disabled", "", 1)
        initrc = initrc[:start] + block + initrc[end:]

if "N3DS_REQUESTED_EARLY_LOGS" not in initrc:
    initrc += """

# N3DS_REQUESTED_EARLY_LOGS: hardware now reaches HOME with the bounded ARM9
# storage service. Preserve early-boot forensics requested by the user while
# leaving the duplicate bootlog and lockupwatch FAT writers disabled.
"""
INIT_RC.write_text(initrc)


checks = (
    (TOUCH, "N3DS_HARDWARE_SINGLE_TOUCH"),
    (EVENT_HUB, "N3DS_TOUCH_ABS_PRESSURE_FALLBACK"),
    (KEY_QUEUE, "N3DS_TOUCH_PRESSURE_SETS_DOWN"),
    (KEY_QUEUE, "N3DS_SINGLE_TOUCH_DISPATCH_TRACE"),
    (INIT_RC, "N3DS_REQUESTED_EARLY_LOGS"),
)
for path, marker in checks:
    if marker not in path.read_text():
        raise SystemExit(f"missing {marker} in {path}")

for service in ("logcat", "bootprogress"):
    text = INIT_RC.read_text()
    start = text.index(f"service {service} ")
    end = text.find("\nservice ", start + 1)
    if end < 0:
        end = len(text)
    if "\n    disabled" in text[start:end]:
        raise SystemExit(f"{service} unexpectedly remains disabled")

print("patch_n3ds_touch_mt_restore_logs: hardware single-touch and requested logs enabled")
