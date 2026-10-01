package com.android.settings;

import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.SystemProperties;
import android.preference.CheckBoxPreference;
import android.preference.Preference;
import android.preference.PreferenceActivity;
import android.preference.PreferenceScreen;

/** Manual, disabled-by-default TCP ADB control for hardware without USB. */
public final class WirelessAdbSettings extends PreferenceActivity implements
        Preference.OnPreferenceChangeListener {
    private static final int ADB_PORT = 5555;
    private CheckBoxPreference mEnabled;
    private Preference mAddress;
    private Preference mInstructions;
    private final Handler mHandler = new Handler();
    private final Runnable mRefresh = new Runnable() {
        public void run() {
            refreshState();
            mHandler.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setTitle("Wireless ADB");

        PreferenceScreen screen = getPreferenceManager().createPreferenceScreen(this);
        setPreferenceScreen(screen);

        Preference warning = new Preference(this);
        warning.setTitle("Security warning");
        warning.setSummary("Anyone on the same network can obtain a root shell while "
                + "wireless ADB is enabled. Enable it only on a trusted network and "
                + "turn it off when finished.");
        warning.setSelectable(false);
        screen.addPreference(warning);

        mEnabled = new CheckBoxPreference(this);
        mEnabled.setKey("n3ds_wireless_adb_enabled");
        mEnabled.setPersistent(false);
        mEnabled.setTitle("Enable wireless ADB");
        mEnabled.setOnPreferenceChangeListener(this);
        screen.addPreference(mEnabled);

        mAddress = new Preference(this);
        mAddress.setTitle("Connection address");
        mAddress.setSelectable(false);
        screen.addPreference(mAddress);

        mInstructions = new Preference(this);
        mInstructions.setTitle("Connect from Windows");
        mInstructions.setSelectable(false);
        screen.addPreference(mInstructions);
    }

    @Override
    protected void onResume() {
        super.onResume();
        mHandler.removeCallbacks(mRefresh);
        mHandler.post(mRefresh);
    }

    @Override
    protected void onPause() {
        mHandler.removeCallbacks(mRefresh);
        super.onPause();
    }

    public boolean onPreferenceChange(Preference preference, Object newValue) {
        if (preference != mEnabled) return false;
        boolean enabled = Boolean.TRUE.equals(newValue);
        /* N3DS_WIRELESS_ADB_PROPERTY_CONTROL: init owns process lifetime;
         * Settings only publishes the requested TCP port. */
        SystemProperties.set("service.adb.tcp.port", enabled ?
                Integer.toString(ADB_PORT) : "0");
        refreshState();
        return true;
    }

    private void refreshState() {
        boolean enabled = SystemProperties.getInt("service.adb.tcp.port", 0) == ADB_PORT;
        /* N3DS_WIRELESS_ADB_VERIFIED_READY: a request is not a listener.
         * init reports lifetime; adbd reports readiness only after bind/listen. */
        boolean running = "running".equals(SystemProperties.get("init.svc.adbd", ""));
        boolean ready = running &&
                SystemProperties.getInt("sys.adb.tcp.ready", 0) == ADB_PORT;
        String ip = getWifiAddress();
        mEnabled.setChecked(enabled);
        mEnabled.setSummary(!enabled ? "Off (recommended when not actively debugging)" :
                ready ? "Listening on TCP port 5555" :
                running ? "Starting; waiting for TCP listener" :
                "Requested, but daemon is not running; check adbd logs");
        mAddress.setSummary(ip == null ? "Connect to Wi-Fi to obtain an IP address" :
                ip + ":" + ADB_PORT);
        String target = ip == null ? "<3DS-IP>" : ip;
        mInstructions.setSummary(
                "1. Install Android SDK Platform Tools on Windows.\n"
                + "2. Put the PC and 3DS on the same trusted Wi-Fi network.\n"
                + "3. Open PowerShell in the platform-tools folder.\n"
                + "4. Run: .\\adb.exe connect " + target + ":" + ADB_PORT + "\n"
                + "5. Run: .\\adb.exe devices\n"
                + "6. When finished: .\\adb.exe disconnect " + target + ":" + ADB_PORT);
    }

    private String getWifiAddress() {
        try {
            WifiManager wifi = (WifiManager) getSystemService(WIFI_SERVICE);
            WifiInfo info = wifi == null ? null : wifi.getConnectionInfo();
            int address = info == null ? 0 : info.getIpAddress();
            if (address == 0) return null;
            return (address & 0xff) + "." + ((address >> 8) & 0xff) + "."
                    + ((address >> 16) & 0xff) + "." + ((address >> 24) & 0xff);
        } catch (RuntimeException e) {
            return null;
        }
    }
}
