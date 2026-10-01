#!/usr/bin/env python3
"""Finalize CTR SMP, responsive touch, and the software Launcher UI."""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

from pathlib import Path
import re


ROOT = Path(A3DS_ROOT)
PROJECT = Path(A3DS_WIN)
LINUX = ROOT / "third_party/linux"
CTR = LINUX / "arch/arm/boot/dts/nintendo3ds_ctr.dts"
TOUCH = LINUX / "drivers/platform/nintendo3ds/tsc/touch.c"
DEFCONFIG = LINUX / "arch/arm/configs/nintendo3ds_defconfig"
ACTIVE_CONFIG = LINUX / ".config"
WMS = (ROOT / "third_party/frameworks/base/services/java/com/android/server/"
       "WindowManagerService.java")
POLICY = (ROOT / "third_party/frameworks/policies/base/phone/com/android/"
          "internal/policy/impl/PhoneWindowManager.java")
LAUNCHER_PROVIDER = (ROOT / "third_party/launcher2/src/com/android/launcher2/"
                     "LauncherProvider.java")
WORKSPACE = ROOT / "third_party/launcher2/res/xml/default_workspace.xml"


# Old 3DS has two ARM11 MPCore application CPUs.  The ARM946 is a separate
# security/I/O processor and cannot be described as Linux CPU2.  CPU1 uses the
# same loader wake path repaired by patch_n3ds_touch_launcher_smp.py.
ctr = CTR.read_text()
if "N3DS_CTR_DUAL_CORE" not in ctr:
    old_note = '''\t\t * maxcpus=1 is the supported boot configuration for this
\t\t * port, not a test -- see nintendo3ds_ktr.dts for the full
\t\t * note. Short version: ARM11 MPCore routes every user TLB
\t\t * flush through a synchronous cross-CPU IPI, one core stops
\t\t * answering, and the boot wedges with three repeating
\t\t * backtraces. Booting single-core removes that path
\t\t * entirely. Do not remove without a hardware-confirmed SMP
\t\t * fix.
'''
    new_note = '''\t\t * N3DS_CTR_DUAL_CORE: Old 3DS exposes exactly two ARM11
\t\t * MPCore application CPUs (cpu@0 and cpu@1). The separate ARM946
\t\t * remains owned by firm_linux_loader/arm9linuxfw and is not a Linux
\t\t * SMP CPU. CPU1 now uses the repaired boot-ROM SGI EOI path shared
\t\t * with KTR, so the former maxcpus=1 safety limit is removed.
'''
    if ctr.count(old_note) != 1:
        raise SystemExit("CTR maxcpus history hunk not found exactly once")
    ctr = ctr.replace(old_note, new_note, 1)
ctr = ctr.replace(" consoleblank=0 maxcpus=1\";", " consoleblank=0\";", 1)
bootargs = next(line for line in ctr.splitlines() if "bootargs = " in line)
cpu_nodes = re.findall(r"^\s*cpu@(\d+)\s*\{", ctr, re.MULTILINE)
if "maxcpus=" in bootargs or cpu_nodes != ["0", "1"]:
    raise SystemExit("CTR must expose exactly ARM11 CPU0/CPU1 with no maxcpus limit")
CTR.write_text(ctr)


# Eclair preprocesses every raw event independently.  During boot/wake its
# generic power policy discards EV_ABS X/Y/pressure while the display is still
# reported off.  BTN_TOUCH then arrives as EV_KEY, wakes the display, and
# KeyInputQueue constructs a MotionEvent using untouched initial coordinates
# (0,0).  Preserve ABS events for the one direct touchscreen device while
# retaining the standard wake/bright flags.
wms = WMS.read_text()
if "N3DS_TOUCH_ABS_WAKE_PRESERVE" not in wms:
    old = '''                case RawInputEvent.EV_ABS: {
                    boolean screenIsOff = !mPowerManager.screenIsOn();
                    boolean screenIsDim = !mPowerManager.screenIsBright();
                    if (screenIsOff) {
'''
    new = '''                case RawInputEvent.EV_ABS: {
                    boolean screenIsOff = !mPowerManager.screenIsOn();
                    boolean screenIsDim = !mPowerManager.screenIsBright();

                    // N3DS_TOUCH_ABS_WAKE_PRESERVE: the direct panel emits
                    // ABS_X/ABS_Y before BTN_TOUCH. Dropping those independent
                    // raw events during wake turns every real contact into
                    // MotionEvent(0,0), even though the kernel coordinates are
                    // valid. Keep coordinates and annotate the wake transition.
                    if (device != null &&
                            "Android3DS Direct Touchscreen".equals(device.name)) {
                        if (screenIsOff) {
                            event.flags |= WindowManagerPolicy.FLAG_WOKE_HERE;
                        }
                        if (screenIsDim) {
                            event.flags |= WindowManagerPolicy.FLAG_BRIGHT_HERE;
                        }
                        return true;
                    }
                    if (screenIsOff) {
'''
    if wms.count(old) != 1:
        raise SystemExit("WindowManagerService EV_ABS hunk not found exactly once")
    wms = wms.replace(old, new, 1)
if wms.count("N3DS_TOUCH_ABS_WAKE_PRESERVE") != 1:
    raise SystemExit("touch ABS wake preservation marker count is not one")
WMS.write_text(wms)


# Linux's generic input poller schedules in jiffies. At the old CONFIG_HZ=250,
# asking for 1 ms silently rounded back to a 4 ms tick. Run this kernel at
# 1000 Hz and request a 1 ms interval so the configured cadence is genuine.
touch = TOUCH.read_text()
touch = touch.replace("#define POLL_INTERVAL_MS 16",
                      "#define POLL_INTERVAL_MS 1", 1)
touch = touch.replace("#define POLL_INTERVAL_MS 4",
                      "#define POLL_INTERVAL_MS 1", 1)
if "DIAGNOSTIC_INTERVAL_POLLS" not in touch:
    touch = touch.replace("#define POLL_INTERVAL_MS 1\n#define SAMPLE_COUNT 5",
                          "#define POLL_INTERVAL_MS 1\n"
                          "#define DIAGNOSTIC_INTERVAL_POLLS "
                          "(5000 / POLL_INTERVAL_MS)\n"
                          "#define SAMPLE_COUNT 5", 1)
touch = touch.replace("ts->polls++ % 300",
                      "ts->polls++ % DIAGNOSTIC_INTERVAL_POLLS", 1)
if "#define POLL_INTERVAL_MS 1" not in touch:
    raise SystemExit("touch poll interval was not reduced to 1 ms")
if "ts->polls++ % DIAGNOSTIC_INTERVAL_POLLS" not in touch:
    raise SystemExit("touch diagnostic log cadence was not preserved")
TOUCH.write_text(touch)

for config_path in (DEFCONFIG, ACTIVE_CONFIG):
    config = config_path.read_text()
    config = config.replace("CONFIG_HZ_250=y", "# CONFIG_HZ_250 is not set")
    if "# CONFIG_HZ_1000 is not set" in config:
        config = config.replace("# CONFIG_HZ_1000 is not set",
                                "CONFIG_HZ_1000=y")
    elif "CONFIG_HZ_1000=y" not in config:
        config += "\nCONFIG_HZ_1000=y\n"
    config = config.replace("CONFIG_HZ=250", "CONFIG_HZ=1000")
    if "CONFIG_HZ_1000=y" not in config:
        raise SystemExit("1000 Hz kernel timer was not installed in "
                         + str(config_path))
    config_path.write_text(config)


# The prior SEARCH policy hook is retained only as compatibility for already
# deployed kernels. Current ctr_navkey performs a debounced/timed synthetic
# POWER hold because hardware proved Eclair filters SEARCH before policy.
policy = POLICY.read_text()
if "N3DS_SELECT_GLOBAL_ACTIONS" not in policy:
    policy = policy.replace(
        "    Runnable mPowerLongPress = new Runnable() {\n",
        "    // N3DS_SELECT_GLOBAL_ACTIONS: SELECT is KEYCODE_SEARCH only on\n"
        "    // the dedicated n3ds_navigation device. A short press does\n"
        "    // nothing; holding it opens Android's native power dialog.\n"
        "    Runnable mSelectLongPress = new Runnable() {\n"
        "        public void run() {\n"
        "            performHapticFeedbackLw(null,\n"
        "                    HapticFeedbackConstants.LONG_PRESS, false);\n"
        "            sendCloseSystemWindows(SYSTEM_DIALOG_REASON_GLOBAL_ACTIONS);\n"
        "            showGlobalActionsDialog();\n"
        "        }\n"
        "    };\n\n"
        "    Runnable mPowerLongPress = new Runnable() {\n",
        1)
    policy = policy.replace(
        "        // BTN_B is the 3DS running-apps button. Consume it globally so the\n",
        "        if (\"n3ds\".equals(SystemProperties.get(\"ro.product.device\"))\n"
        "                && code == KeyEvent.KEYCODE_SEARCH) {\n"
        "            mHandler.removeCallbacks(mSelectLongPress);\n"
        "            if (down && repeatCount == 0) {\n"
        "                mHandler.postDelayed(mSelectLongPress,\n"
        "                        ViewConfiguration.getGlobalActionKeyTimeout());\n"
        "            }\n"
        "            return true;\n"
        "        }\n\n"
        "        // BTN_B is the 3DS running-apps button. Consume it globally so the\n",
        1)
if policy.count("N3DS_SELECT_GLOBAL_ACTIONS") != 1:
    raise SystemExit("SELECT GlobalActions policy marker count is not one")
POLICY.write_text(policy)


# The launcher database already exists on deployed cards, so changing only
# default_workspace.xml would not update an existing card. The checked-in
# public Launcher sources are canonical for these n3ds-specific UI changes;
# sync only those four files into the WSL build tree after earlier idempotent
# patches have prepared it.
launcher_files = (
    "src/com/android/launcher2/AllAppsView.java",
    "src/com/android/launcher2/Launcher.java",
    "src/com/android/launcher2/LauncherProvider.java",
    "res/xml/default_workspace.xml",
)
for rel in launcher_files:
    source = PROJECT / "third_party/launcher2" / rel
    target = ROOT / "third_party/launcher2" / rel
    if not source.is_file():
        raise SystemExit("missing public Launcher source: " + str(source))
    target.write_bytes(source.read_bytes())

provider = LAUNCHER_PROVIDER.read_text()
workspace = WORKSPACE.read_text()
all_apps = (ROOT / "third_party/launcher2/src/com/android/launcher2/"
            "AllAppsView.java").read_text()
launcher = (ROOT / "third_party/launcher2/src/com/android/launcher2/"
            "Launcher.java").read_text()
version_match = re.search(
    r"private static final int DATABASE_VERSION = (\d+);", provider
)
if version_match is None or int(version_match.group(1)) < 9:
    raise SystemExit("Launcher database migration baseline 9 was not installed")
if "N3DS_GLOBAL_TIME_EXISTING_WORKSPACE" not in provider:
    raise SystemExit("Global Time existing-workspace migration is absent")
if "N3DS_SPACED_THREE_APP_WORKSPACE" not in provider:
    raise SystemExit("three-app workspace spacing migration is absent")
if 'launcher:x="2"' not in workspace:
    raise SystemExit("Touch Diagnostic does not have a full-cell desktop gap")
if ('launcher:className="com.android.globaltime.GlobalTime"' not in workspace
        or 'launcher:y="1"' not in workspace):
    raise SystemExit("Global Time was not moved to the second desktop row")
if "N3DS_NATIVE_ALL_APPS_DRAWER" not in all_apps:
    raise SystemExit("native Android All Apps drawer is absent")
if "N3DS_HOME_CLOSES_SOFTWARE_DRAWER" not in launcher:
    raise SystemExit("physical HOME drawer exit repair is absent")

print("patch_n3ds_touch_cpu_diag: CTR=2; touch=1ms; native drawer; SELECT power menu")
