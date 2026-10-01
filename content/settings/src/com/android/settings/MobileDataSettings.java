package com.android.settings;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.database.Cursor;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.net.Uri;
import android.os.Bundle;
import android.preference.CheckBoxPreference;
import android.preference.EditTextPreference;
import android.preference.Preference;
import android.preference.PreferenceActivity;
import android.preference.PreferenceScreen;
import android.provider.Settings;
import android.widget.Toast;

import java.net.URI;

/** Wi-Fi-backed 3DSTelco configuration for the original Phone and Mms apps. */
public final class MobileDataSettings extends PreferenceActivity implements
        Preference.OnPreferenceChangeListener {
    private static final String DEFAULT_ENDPOINT = "https://3dstelco.divergen.io";
    private static final String KEY_ENABLED = "n3ds_telco_enabled";
    private static final String KEY_ENDPOINT = "n3ds_telco_endpoint";
    private static final String KEY_STATUS = "n3ds_telco_status";
    private static final String KEY_NUMBER = "n3ds_telco_number";
    private static final String PHONE_PACKAGE = "com.android.phone";
    private static final String PHONE_SERVICE = "com.android.phone.TelcoService";
    private static final String ACCESS_PERMISSION = "io.divergen.telco.ACCESS";
    private static final String ACTION_CONFIG_CHANGED = "io.divergen.telco.action.CONFIG_CHANGED";
    private static final String ACTION_ENROLL = "io.divergen.telco.action.ENROLL";
    private static final String ACTION_POLL = "io.divergen.telco.action.POLL";
    private static final String ACTION_STATE = "io.divergen.telco.action.STATE";
    private static final Uri STATUS_URI = Uri.parse("content://io.divergen.telco/status");

    private CheckBoxPreference mEnabled;
    private EditTextPreference mEndpoint;
    private EditTextPreference mCode;
    private Preference mNumber;
    private Preference mStatus;
    private boolean mReceiverRegistered;

    private final BroadcastReceiver mStateReceiver = new BroadcastReceiver() {
        public void onReceive(Context context, Intent intent) { refreshStatus(); }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setTitle("3DSTelco Mobile Data");

        PreferenceScreen screen = getPreferenceManager().createPreferenceScreen(this);
        setPreferenceScreen(screen);

        Preference explanation = new Preference(this);
        explanation.setTitle("3DSTelco over Wi-Fi");
        explanation.setSummary("Texts and calls use the configured HTTPS service. Wi-Fi must be connected; this does not create an access point.");
        explanation.setSelectable(false);
        screen.addPreference(explanation);

        mEnabled = new CheckBoxPreference(this);
        mEnabled.setPersistent(false);
        mEnabled.setTitle("Enable Mobile Data");
        mEnabled.setOnPreferenceChangeListener(this);
        screen.addPreference(mEnabled);

        mEndpoint = new EditTextPreference(this);
        mEndpoint.setPersistent(false);
        mEndpoint.setTitle("3DSTelco HTTPS endpoint");
        mEndpoint.setDialogTitle("3DSTelco HTTPS endpoint");
        mEndpoint.getEditText().setSingleLine(true);
        mEndpoint.setOnPreferenceChangeListener(this);
        screen.addPreference(mEndpoint);

        mCode = new EditTextPreference(this);
        mCode.setPersistent(false);
        mCode.setTitle("Enroll this 3DS");
        mCode.setDialogTitle("One-time provisioning code");
        mCode.setSummary("Register this Wi-Fi MAC on the website, then enter its one-time code here. The code is never saved.");
        mCode.getEditText().setSingleLine(true);
        mCode.setOnPreferenceChangeListener(this);
        screen.addPreference(mCode);

        mNumber = new Preference(this);
        mNumber.setTitle("Phone number");
        mNumber.setSelectable(false);
        screen.addPreference(mNumber);

        mStatus = new Preference(this);
        mStatus.setTitle("Service status");
        mStatus.setSelectable(false);
        screen.addPreference(mStatus);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (!mReceiverRegistered) {
            registerReceiver(mStateReceiver, new IntentFilter(ACTION_STATE), ACCESS_PERMISSION, null);
            mReceiverRegistered = true;
        }
        refreshStatus();
        if (enabled()) startPhoneService(ACTION_POLL, null, false);
    }

    @Override
    protected void onPause() {
        if (mReceiverRegistered) {
            unregisterReceiver(mStateReceiver);
            mReceiverRegistered = false;
        }
        super.onPause();
    }

    public boolean onPreferenceChange(Preference preference, Object newValue) {
        if (preference == mEnabled) {
            boolean enable = Boolean.TRUE.equals(newValue);
            if (enable && !wifiConnected()) {
                toast("Connect Wi-Fi before enabling 3DSTelco Mobile Data.");
                return false;
            }
            Settings.System.putInt(getContentResolver(), KEY_ENABLED, enable ? 1 : 0);
            mEnabled.setSummary(enable ? "On — uses connected Wi-Fi" : "Off");
            Settings.System.putString(getContentResolver(), KEY_STATUS,
                    enable ? "Starting 3DSTelco…" : "Mobile Data is off");
            startPhoneService(ACTION_CONFIG_CHANGED, null, false, Boolean.valueOf(enable));
            refreshStatus();
            return true;
        }

        if (preference == mEndpoint) {
            String normalized = normalizeEndpoint(newValue == null ? "" : newValue.toString());
            if (normalized == null) {
                toast("Use an HTTPS URL with a host and no user info, query, or fragment.");
                return false;
            }
            String old = endpoint();
            Settings.System.putString(getContentResolver(), KEY_ENDPOINT, normalized);
            mEndpoint.setText(normalized);
            mEndpoint.setSummary(normalized);
            boolean changed = !normalized.equals(old);
            if (changed) {
                Settings.System.putString(getContentResolver(), KEY_NUMBER, null);
                Settings.System.putString(getContentResolver(), KEY_STATUS,
                        "Endpoint changed — enroll this 3DS again");
            }
            startPhoneService(ACTION_CONFIG_CHANGED, null, changed);
            refreshStatus();
            return false;
        }

        if (preference == mCode) {
            String code = normalizeProvisioningCode(newValue == null ? "" : newValue.toString());
            mCode.setText("");
            if (code == null || !code.matches("[A-Z0-9]{8,80}")) {
                toast("Enter the one-time code shown by the 3DSTelco website.");
                return false;
            }
            if (!enabled()) {
                toast("Enable Mobile Data before enrolling this 3DS.");
                return false;
            }
            if (!wifiConnected()) {
                toast("Connect Wi-Fi before enrolling this 3DS.");
                return false;
            }
            Settings.System.putString(getContentResolver(), KEY_STATUS, "Enrolling this 3DS…");
            startPhoneService(ACTION_ENROLL, code, false);
            refreshStatus();
            return false;
        }
        return false;
    }

    private void refreshStatus() {
        String endpoint = endpoint();
        boolean enabled = enabled();
        mEnabled.setChecked(enabled);
        mEnabled.setSummary(enabled ? (wifiConnected() ? "On — Wi-Fi connected" : "On — waiting for Wi-Fi") : "Off");
        mEndpoint.setText(endpoint);
        mEndpoint.setSummary(endpoint);

        String status = Settings.System.getString(getContentResolver(), KEY_STATUS);
        String number = Settings.System.getString(getContentResolver(), KEY_NUMBER);
        Cursor cursor = null;
        try {
            cursor = getContentResolver().query(STATUS_URI, null, null, null, null);
            if (cursor != null && cursor.moveToFirst()) {
                int numberColumn = cursor.getColumnIndex("number");
                int statusColumn = cursor.getColumnIndex("status");
                if (numberColumn >= 0 && !cursor.isNull(numberColumn)) number = cursor.getString(numberColumn);
                if (statusColumn >= 0 && !cursor.isNull(statusColumn)) status = cursor.getString(statusColumn);
            }
        } catch (RuntimeException ignored) {
            if (status == null) status = "Original Phone service is unavailable";
        } finally {
            if (cursor != null) cursor.close();
        }
        mNumber.setSummary(number == null || number.length() == 0 ? "Not assigned" : number);
        if (status != null && status.startsWith("Online")) {
            long latency = Settings.System.getLong(getContentResolver(),
                    "n3ds_telco_latency_ms", -1);
            if (latency >= 0) status += " (endpoint round trip " + latency + " ms)";
        }
        mStatus.setSummary(status == null || status.length() == 0 ? "Not registered" : status);
    }

    private boolean enabled() {
        return Settings.System.getInt(getContentResolver(), KEY_ENABLED, 0) == 1;
    }

    private String endpoint() {
        String value = Settings.System.getString(getContentResolver(), KEY_ENDPOINT);
        String normalized = normalizeEndpoint(value == null ? DEFAULT_ENDPOINT : value);
        return normalized == null ? DEFAULT_ENDPOINT : normalized;
    }

    private static String normalizeEndpoint(String value) {
        if (value == null) return null;
        value = value.trim();
        while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
        if (value.length() == 0 || value.length() > 512) return null;
        try {
            URI uri = new URI(value);
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null
                    || uri.getHost().length() == 0 || uri.getUserInfo() != null
                    || uri.getQuery() != null || uri.getFragment() != null) return null;
            return value;
        } catch (Exception ignored) { return null; }
    }

    private boolean wifiConnected() {
        ConnectivityManager manager = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        NetworkInfo wifi = manager == null ? null : manager.getNetworkInfo(ConnectivityManager.TYPE_WIFI);
        return wifi != null && wifi.isConnected();
    }

    private void startPhoneService(String action, String code, boolean endpointChanged) {
        startPhoneService(action, code, endpointChanged, null);
    }

    private void startPhoneService(String action, String code, boolean endpointChanged,
            Boolean mobileDataOnBoot) {
        Intent intent = new Intent(action);
        intent.setClassName(PHONE_PACKAGE, PHONE_SERVICE);
        if (code != null) intent.putExtra("provisioning_code", code);
        if (endpointChanged) intent.putExtra("endpoint_changed", true);
        if (mobileDataOnBoot != null) {
            intent.putExtra("mobile_data_on_boot_set", true);
            intent.putExtra("mobile_data_on_boot", mobileDataOnBoot.booleanValue());
        }
        try { startService(intent); }
        catch (RuntimeException error) { toast("Original Phone service is unavailable."); }
    }

    private static String normalizeProvisioningCode(String code) {
        if (code == null) return null;
        String value = code.trim();
        StringBuilder normalized = new StringBuilder(value.length());
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c != '-' && !Character.isWhitespace(c) && !Character.isSpaceChar(c)) normalized.append(c);
        }
        return normalized.toString().toUpperCase(java.util.Locale.US);
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show();
    }
}
