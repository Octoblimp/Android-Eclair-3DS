#!/usr/bin/env python3
"""Keep optional late services from suppressing HOME; finalize logs on poweroff."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
SYSTEM_SERVER = ROOT / "third_party/frameworks/base/services/java/com/android/server/SystemServer.java"
AMS = ROOT / "third_party/frameworks/base/services/java/com/android/server/am/ActivityManagerService.java"
GLOBAL_ACTIONS = ROOT / "third_party/frameworks/policies/base/phone/com/android/internal/policy/impl/GlobalActions.java"
SERVER_MARKER = "N3DS_BOOT_COMPLETION_ISOLATION"
HOME_MARKER = "N3DS_BUNDLED_HOME_FALLBACK"
POWER_MARKER = "N3DS_DIRECT_GLOBAL_POWER_OFF"
POWER_FINALIZER_MARKER = "N3DS_POWER_OFF_LOG_FINALIZER"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_server(text: str) -> str:
    if SERVER_MARKER in text:
        for token in ("Failure synchronizing ADB setting",
                      "Failure making Notification ready",
                      "Failure making Status Bar ready",
                      "Failure making Window Manager ready",
                      "Failure making Power Manager ready",
                      "Failure making Package Manager ready"):
            if token not in text:
                raise RuntimeError("marked SystemServer missing " + token)
        return text

    adb_old = '''        // make sure the ADB_ENABLED setting value matches the secure property value
        Settings.Secure.putInt(mContentResolver, Settings.Secure.ADB_ENABLED,
                "1".equals(SystemProperties.get("persist.service.adb.enable")) ? 1 : 0);

        // register observer to listen for settings changes
        mContentResolver.registerContentObserver(Settings.Secure.getUriFor(Settings.Secure.ADB_ENABLED),
                false, new AdbSettingsObserver());
'''
    adb_new = '''        /* N3DS_BOOT_COMPLETION_ISOLATION: wireless-ADB preference sync is
         * optional.  A provider/FAT failure here must not prevent the later
         * ActivityManager.systemReady() call that launches HOME. */
        try {
            Settings.Secure.putInt(mContentResolver, Settings.Secure.ADB_ENABLED,
                    "1".equals(SystemProperties.get("persist.service.adb.enable")) ? 1 : 0);
            mContentResolver.registerContentObserver(
                    Settings.Secure.getUriFor(Settings.Secure.ADB_ENABLED),
                    false, new AdbSettingsObserver());
        } catch (Throwable e) {
            Log.e(TAG, "Failure synchronizing ADB setting; continuing boot", e);
        }
'''
    text = replace_once(text, adb_old, adb_new, "ADB boot isolation")

    ready_old = '''        if (notification != null) {
            notification.systemReady();
        }

        if (statusBar != null) {
            statusBar.systemReady();
        }
        if (wm != null) {
            wm.systemReady();
        }
        power.systemReady();
        try {
            pm.systemReady();
        } catch (RemoteException e) {
        }
'''
    ready_new = '''        try {
            if (notification != null) notification.systemReady();
        } catch (Throwable e) {
            Log.e(TAG, "Failure making Notification ready; continuing boot", e);
        }
        try {
            if (statusBar != null) statusBar.systemReady();
        } catch (Throwable e) {
            Log.e(TAG, "Failure making Status Bar ready; continuing boot", e);
        }
        try {
            if (wm != null) wm.systemReady();
        } catch (Throwable e) {
            Log.e(TAG, "Failure making Window Manager ready; continuing boot", e);
        }
        try {
            power.systemReady();
        } catch (Throwable e) {
            Log.e(TAG, "Failure making Power Manager ready; continuing boot", e);
        }
        try {
            pm.systemReady();
        } catch (Throwable e) {
            Log.e(TAG, "Failure making Package Manager ready; continuing boot", e);
        }
'''
    return replace_once(text, ready_old, ready_new, "late service readiness isolation")


def patch_ams(text: str) -> str:
    if HOME_MARKER in text:
        if '"com.android.launcher2.Launcher"' not in text:
            raise RuntimeError("marked ActivityManager lacks bundled HOME component")
        return text
    old = '''        ActivityInfo aInfo =
            intent.resolveActivityInfo(mContext.getPackageManager(),
                    STOCK_PM_FLAGS);
        if (aInfo != null) {
'''
    new = '''        ActivityInfo aInfo =
            intent.resolveActivityInfo(mContext.getPackageManager(),
                    STOCK_PM_FLAGS);
        /* N3DS_BUNDLED_HOME_FALLBACK: the HOME intent table can be absent on
         * a first boot whose package settings are being reconstructed.  The
         * bundled, verified system Launcher is still addressable directly. */
        if (aInfo == null && mTopComponent == null &&
                "n3ds".equals(SystemProperties.get("ro.product.device"))) {
            ComponentName fallback = new ComponentName(
                    "com.android.launcher2", "com.android.launcher2.Launcher");
            try {
                aInfo = mContext.getPackageManager().getActivityInfo(
                        fallback, STOCK_PM_FLAGS);
                intent.setComponent(fallback);
                Log.w(TAG, "N3DS HOME resolver empty; using bundled Launcher");
            } catch (PackageManager.NameNotFoundException e) {
                Log.e(TAG, "N3DS bundled Launcher missing; HOME not started", e);
            }
        }
        if (aInfo != null) {
'''
    return replace_once(text, old, new, "bundled HOME fallback")


def patch_global_actions(text: str) -> str:
    old = '''                    public void onPress() {
                        /* N3DS_DIRECT_GLOBAL_POWER_OFF: this device has no
                         * telephony/Bluetooth shutdown work.  Eclair's generic
                         * path adds confirmation plus waits of up to 18 seconds;
                         * go directly through sync() and the kernel poweroff
                         * handler. START remains the independent emergency cut. */
                        Log.i(TAG, "N3DS direct poweroff requested");
                        Power.shutdown();
                    }
'''
    new = '''                    public void onPress() {
                        /* N3DS_DIRECT_GLOBAL_POWER_OFF: SELECT must use the
                         * same shutdown finalizer as START. It stops every
                         * SD-backed logger, waits for init to reap them, calls
                         * sync(), and only then unmounts the card. */
                        Log.i(TAG, "N3DS finalized poweroff requested");
                        try {
                            /* N3DS_POWER_OFF_LOG_FINALIZER: never call
                             * Power.shutdown() directly: system_server is uid
                             * system, while the finalizer needs root for init
                             * controls, unmount, and the poweroff syscall.
                             * Ask init to start its root oneshot instead. */
                            SystemProperties.set("sys.n3ds.poweroff", "1");
                        } catch (RuntimeException e) {
                            /* Fail closed. A direct reboot here could cut the
                             * SD card while a logger still owns an fd. */
                            Log.e(TAG, "N3DS poweroff request failed; refusing cutoff", e);
                        }
                    }
'''
    if POWER_FINALIZER_MARKER in text:
        if 'SystemProperties.set("sys.n3ds.poweroff", "1");' not in text:
            raise RuntimeError("marked GlobalActions lacks root log finalizer request")
        if "import android.os.SystemProperties;" not in text:
            text = replace_once(text, "import android.os.Handler;\n",
                                "import android.os.Handler;\nimport android.os.SystemProperties;\n",
                                "SystemProperties import")
        return text
    if POWER_MARKER in text:
        if "Power.shutdown();" not in text:
            raise RuntimeError("marked GlobalActions lacks migratable direct shutdown")
        text = replace_once(text, old, new, "log-finalizing GlobalActions poweroff")
    else:
        stock = '''                    public void onPress() {
                        // shutdown by making sure radio and power are handled accordingly.
                        ShutdownThread.shutdown(mContext, true);
                    }
'''
        text = replace_once(text, stock, new,
                            "log-finalizing GlobalActions poweroff")
    if "import android.os.SystemProperties;" not in text:
        text = replace_once(text, "import android.os.Handler;\n",
                            "import android.os.Handler;\nimport android.os.SystemProperties;\n",
                            "SystemProperties import")
    return text


def update(path: Path, patcher) -> None:
    if not path.is_file():
        raise SystemExit("missing canonical source: " + str(path))
    original = path.read_text(encoding="utf-8")
    updated = patcher(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")


def main() -> None:
    update(SYSTEM_SERVER, patch_server)
    update(AMS, patch_ams)
    update(GLOBAL_ACTIONS, patch_global_actions)
    print("patch_n3ds_boot_completion: HOME and root-finalized poweroff repair installed")


if __name__ == "__main__":
    main()
