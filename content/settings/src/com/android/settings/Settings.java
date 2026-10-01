package com.android.settings;

import android.os.Bundle;
import android.preference.PreferenceActivity;
import android.util.Log;

/** Hardware-appropriate entry screen built from the stock Eclair panels. */
public class Settings extends PreferenceActivity {
    private static final String TAG = "N3DS-TelcoSettings";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Log.i(TAG, "N3DS_TELCO_SETTINGS_V2: configurable HTTPS endpoint UI active");
        addPreferencesFromResource(R.xml.settings);
    }
}
