package com.android.phone;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

public final class TelcoBootReceiver extends BroadcastReceiver {
    public void onReceive(Context context, Intent intent) {
        // Always let the service inspect the user-owned boot configuration.
        // Gating on the previous Settings value makes mobile_data_on_boot=1
        // unable to turn a previously disabled service on.
        // N3DS_TELCO_BOOT_RECEIVER_GUARD: a service-start or security denial
        // must never crash the whole Phone process again; log and move on.
        try {
            Intent service = new Intent(context, TelcoService.class);
            service.setAction(TelcoContract.ACTION_CONFIG_CHANGED);
            context.startService(service);
        } catch (RuntimeException error) {
            Log.w("TelcoBootReceiver",
                    "N3DS_TELCO_BOOT_RECEIVER_GUARD deferred 3DSTelco start: " + error.getMessage());
        }
    }
}
