/*
 * Copyright (C) 2008 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.android.internal.policy.impl;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.StatusBarManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.IntentFilter;
import android.media.AudioManager;
import android.os.Handler;
import android.os.Power;
import android.os.Message;
import android.os.SystemProperties;
import android.provider.Settings;
import android.telephony.PhoneStateListener;
import android.telephony.ServiceState;
import android.telephony.TelephonyManager;
import android.util.Log;
import android.view.KeyEvent;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.BaseAdapter;
import android.widget.ImageView;
import android.widget.TextView;
import com.android.internal.R;
import com.android.internal.app.ShutdownThread;
import com.android.internal.telephony.TelephonyIntents;
import com.android.internal.telephony.TelephonyProperties;
import com.google.android.collect.Lists;

import java.util.ArrayList;

/**
 * Helper to show the global actions dialog.  Each item is an {@link Action} that
 * may show depending on whether the keyguard is showing, and whether the device
 * is provisioned.
 */
class GlobalActions implements DialogInterface.OnDismissListener, DialogInterface.OnClickListener  {

    private static final String TAG = "GlobalActions";

    private StatusBarManager mStatusBar;

    private final Context mContext;
    private final AudioManager mAudioManager;

    private ArrayList<Action> mItems;
    private AlertDialog mDialog;

    private ToggleAction mSilentModeToggle;
    private ToggleAction mAirplaneModeOn;

    private MyAdapter mAdapter;

    private boolean mKeyguardShowing = false;
    private boolean mDeviceProvisioned = false;
    private ToggleAction.State mAirplaneState = ToggleAction.State.Off;
    private boolean mIsWaitingForEcmExit = false;

    /**
     * @param context everything needs a context :(
     */
    public GlobalActions(Context context) {
        mContext = context;
        mAudioManager = (AudioManager) mContext.getSystemService(Context.AUDIO_SERVICE);

        // receive broadcasts
        IntentFilter filter = new IntentFilter();
        filter.addAction(Intent.ACTION_CLOSE_SYSTEM_DIALOGS);
        filter.addAction(Intent.ACTION_SCREEN_OFF);
        filter.addAction(TelephonyIntents.ACTION_EMERGENCY_CALLBACK_MODE_CHANGED);
        context.registerReceiver(mBroadcastReceiver, filter);

        // get notified of phone state changes
        TelephonyManager telephonyManager =
                (TelephonyManager) context.getSystemService(Context.TELEPHONY_SERVICE);
        telephonyManager.listen(mPhoneStateListener, PhoneStateListener.LISTEN_SERVICE_STATE);
    }

    /**
     * N3DS_GLOBAL_ACTIONS_PREWARM (#327): build the dialog and inflate its
     * content once, after boot, so the first SELECT hold only has to add a
     * window. Eclair has no public Dialog.create(); restoring an empty saved
     * hierarchy is the public route to Dialog.dispatchOnCreate() without
     * showing anything.
     */
    public void prewarm() {
        if (mDialog != null) return;
        mStatusBar = (StatusBarManager)mContext.getSystemService(Context.STATUS_BAR_SERVICE);
        mDialog = createDialog();
        android.os.Bundle state = new android.os.Bundle();
        state.putBundle("android:dialogHierarchy", new android.os.Bundle());
        state.putBoolean("android:dialogShowing", false);
        mDialog.onRestoreInstanceState(state);
    }

    /**
     * Show the global actions dialog (creating if necessary)
     * @param keyguardShowing True if keyguard is showing
     */
    public void showDialog(boolean keyguardShowing, boolean isDeviceProvisioned) {
        mKeyguardShowing = keyguardShowing;
        mDeviceProvisioned = isDeviceProvisioned;
        if (mDialog == null) {
            mStatusBar = (StatusBarManager)mContext.getSystemService(Context.STATUS_BAR_SERVICE);
            mDialog = createDialog();
        }
        prepareDialog();

        mStatusBar.disable(StatusBarManager.DISABLE_EXPAND);
        mDialog.show();
    }

    /**
     * Create the global actions dialog.
     * @return A new dialog.
     */
    private AlertDialog createDialog() {

        mSilentModeToggle = new ToggleAction(
                R.drawable.ic_lock_silent_mode,
                R.drawable.ic_lock_silent_mode_off,
                R.string.global_action_toggle_silent_mode,
                R.string.global_action_silent_mode_on_status,
                R.string.global_action_silent_mode_off_status) {

            void onToggle(boolean on) {
                mAudioManager.setRingerMode(on ? AudioManager.RINGER_MODE_SILENT
                        : AudioManager.RINGER_MODE_NORMAL);
            }

            public boolean showDuringKeyguard() {
                return true;
            }

            public boolean showBeforeProvisioning() {
                return false;
            }
        };

        mAirplaneModeOn = new ToggleAction(
                R.drawable.ic_lock_airplane_mode,
                R.drawable.ic_lock_airplane_mode_off,
                R.string.global_actions_toggle_airplane_mode,
                R.string.global_actions_airplane_mode_on_status,
                R.string.global_actions_airplane_mode_off_status) {

            void onToggle(boolean on) {
                if (Boolean.parseBoolean(
                        SystemProperties.get(TelephonyProperties.PROPERTY_INECM_MODE))) {
                    mIsWaitingForEcmExit = true;
                    // Launch ECM exit dialog
                    Intent ecmDialogIntent =
                            new Intent(TelephonyIntents.ACTION_SHOW_NOTICE_ECM_BLOCK_OTHERS, null);
                    ecmDialogIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    mContext.startActivity(ecmDialogIntent);
                } else {
                    changeAirplaneModeSystemSetting(on);
                }
            }

            @Override
            protected void changeStateFromPress(boolean buttonOn) {
                // In ECM mode airplane state cannot be changed
                if (!(Boolean.parseBoolean(
                        SystemProperties.get(TelephonyProperties.PROPERTY_INECM_MODE)))) {
                    mState = buttonOn ? State.TurningOn : State.TurningOff;
                    mAirplaneState = mState;
                }
            }

            public boolean showDuringKeyguard() {
                return true;
            }

            public boolean showBeforeProvisioning() {
                return false;
            }
        };

        mItems = Lists.newArrayList(
                // silent mode
                mSilentModeToggle,
                // next: airplane mode
                mAirplaneModeOn,
                // last: power off
                new SinglePressAction(
                        com.android.internal.R.drawable.ic_lock_power_off,
                        R.string.global_action_power_off) {

                    public void onPress() {
                        /* N3DS_POWER_OFF_CONFIRM: restore the stock
                         * "Your phone will shut down." confirmation step that
                         * ShutdownThread.shutdown(context, true) normally
                         * provides. ShutdownThread itself cannot be used here:
                         * it ends in Power.shutdown(), which halts this board
                         * without flushing the SD card. Show the same dialog
                         * and hand the real shutdown to init instead. */
                        confirmPowerOff();
                    }

                    public boolean showDuringKeyguard() {
                        return true;
                    }

                    public boolean showBeforeProvisioning() {
                        return true;
                    }
                });

        // N3DS_POWER_MENU_WITHOUT_AUDIO_SERVICE: this image does not
        // start AudioService. Omit the silent action so displaying or
        // pressing it cannot dereference a null AudioManager.
        if (android.os.ServiceManager.checkService(Context.AUDIO_SERVICE) == null) {
            mItems.remove(mSilentModeToggle);
        }

        // N3DS_POWER_OFF_FIRST: the menu opens with item 0 selected as soon
        // as A leaves touch mode, so A clicks item 0.  Once AudioService
        // existed (#321) that was Silent mode, and on #322 hold-SELECT, A
        // silenced the console instead of offering to power it off.
        mItems.add(0, mItems.remove(mItems.size() - 1));

        mAdapter = new MyAdapter();

        final AlertDialog.Builder ab = new AlertDialog.Builder(mContext);

        ab.setAdapter(mAdapter, this)
                .setInverseBackgroundForced(true)
                .setTitle(R.string.global_actions);

        final AlertDialog dialog = ab.create();
        dialog.getWindow().setType(WindowManager.LayoutParams.TYPE_SYSTEM_DIALOG);
        if (!mContext.getResources().getBoolean(
                com.android.internal.R.bool.config_sf_slowBlur)) {
            dialog.getWindow().setFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND,
                    WindowManager.LayoutParams.FLAG_BLUR_BEHIND);
        }

        dialog.setOnDismissListener(this);

        return dialog;
    }

    /**
     * N3DS_POWER_OFF_CONFIRM: second-step confirmation for the power-off item,
     * matching stock Android's ShutdownThread confirmation.  Only a positive
     * answer raises sys.n3ds.poweroff, which init turns into the root-owned
     * ctr_poweroff oneshot (service stop + SD flush barrier + MCU power cut).
     */
    private void confirmPowerOff() {
        final AlertDialog confirm = new AlertDialog.Builder(mContext)
                .setIcon(com.android.internal.R.drawable.ic_dialog_alert)
                .setTitle(com.android.internal.R.string.power_off)
                .setMessage(com.android.internal.R.string.shutdown_confirm)
                .setPositiveButton(com.android.internal.R.string.yes,
                        new DialogInterface.OnClickListener() {
                            public void onClick(DialogInterface dialog, int which) {
                                /* N3DS_POWER_OFF_LOG_FINALIZER: SELECT must use
                                 * the same root, fail-closed log flush and real
                                 * SD unmount barrier as START. init owns the
                                 * privileged service. */
                                Log.i(TAG, "N3DS finalized poweroff requested");
                                SystemProperties.set("sys.n3ds.poweroff", "1");
                            }
                        })
                .setNegativeButton(com.android.internal.R.string.no, null)
                /* N3DS_POWER_OFF_A_CONFIRMS: Eclair's dialog buttons are
                 * not focusable in touch mode, so A (DPAD_CENTER) on this
                 * dialog did nothing.  A fresh press of A or ENTER answers
                 * Yes; B/back still cancels. */
                .setOnKeyListener(new DialogInterface.OnKeyListener() {
                    public boolean onKey(DialogInterface dialog, int keyCode,
                            KeyEvent event) {
                        if ((keyCode == KeyEvent.KEYCODE_DPAD_CENTER
                                || keyCode == KeyEvent.KEYCODE_ENTER)
                                && event.getAction() == KeyEvent.ACTION_DOWN
                                && event.getRepeatCount() == 0) {
                            Log.i(TAG, "N3DS finalized poweroff requested (A)");
                            SystemProperties.set("sys.n3ds.poweroff", "1");
                            dialog.dismiss();
                            return true;
                        }
                        return false;
                    }
                })
                .create();
        confirm.getWindow().setType(mKeyguardShowing
                ? WindowManager.LayoutParams.TYPE_KEYGUARD_DIALOG
                : WindowManager.LayoutParams.TYPE_SYSTEM_DIALOG);
        confirm.getWindow().addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
        confirm.setCancelable(true);
        confirm.show();
    }

    private void prepareDialog() {
        if (mAudioManager != null && android.os.ServiceManager.checkService(Context.AUDIO_SERVICE) != null) {
            final boolean silentModeOn = mAudioManager.getRingerMode()
                    != AudioManager.RINGER_MODE_NORMAL;
            mSilentModeToggle.updateState(silentModeOn
                    ? ToggleAction.State.On : ToggleAction.State.Off);
        }
        mAirplaneModeOn.updateState(mAirplaneState);
        mAdapter.notifyDataSetChanged();
        if (mKeyguardShowing) {
            mDialog.getWindow().setType(WindowManager.LayoutParams.TYPE_KEYGUARD_DIALOG);
        } else {
            mDialog.getWindow().setType(WindowManager.LayoutParams.TYPE_SYSTEM_DIALOG);
        }
    }


    /** {@inheritDoc} */
    public void onDismiss(DialogInterface dialog) {
        mStatusBar.disable(StatusBarManager.DISABLE_NONE);
    }

    /** {@inheritDoc} */
    public void onClick(DialogInterface dialog, int which) {
        dialog.dismiss();
        mAdapter.getItem(which).onPress();
    }


    /**
     * The adapter used for the list within the global actions dialog, taking
     * into account whether the keyguard is showing via
     * {@link GlobalActions#mKeyguardShowing} and whether the device is provisioned
     * via {@link GlobalActions#mDeviceProvisioned}.
     */
    private class MyAdapter extends BaseAdapter {

        public int getCount() {
            int count = 0;

            for (int i = 0; i < mItems.size(); i++) {
                final Action action = mItems.get(i);

                if (mKeyguardShowing && !action.showDuringKeyguard()) {
                    continue;
                }
                if (!mDeviceProvisioned && !action.showBeforeProvisioning()) {
                    continue;
                }
                count++;
            }
            return count;
        }

        @Override
        public boolean isEnabled(int position) {
            return getItem(position).isEnabled();
        }

        @Override
        public boolean areAllItemsEnabled() {
            return false;
        }

        public Action getItem(int position) {

            int filteredPos = 0;
            for (int i = 0; i < mItems.size(); i++) {
                final Action action = mItems.get(i);
                if (mKeyguardShowing && !action.showDuringKeyguard()) {
                    continue;
                }
                if (!mDeviceProvisioned && !action.showBeforeProvisioning()) {
                    continue;
                }
                if (filteredPos == position) {
                    return action;
                }
                filteredPos++;
            }

            throw new IllegalArgumentException("position " + position + " out of "
                    + "range of showable actions, filtered count = "
                    + "= " + getCount() + ", keyguardshowing=" + mKeyguardShowing
                    + ", provisioned=" + mDeviceProvisioned);
        }


        public long getItemId(int position) {
            return position;
        }

        public View getView(int position, View convertView, ViewGroup parent) {
            Action action = getItem(position);
            return action.create(mContext, convertView, parent, LayoutInflater.from(mContext));
        }
    }

    // note: the scheme below made more sense when we were planning on having
    // 8 different things in the global actions dialog.  seems overkill with
    // only 3 items now, but may as well keep this flexible approach so it will
    // be easy should someone decide at the last minute to include something
    // else, such as 'enable wifi', or 'enable bluetooth'

    /**
     * What each item in the global actions dialog must be able to support.
     */
    private interface Action {
        View create(Context context, View convertView, ViewGroup parent, LayoutInflater inflater);

        void onPress();

        /**
         * @return whether this action should appear in the dialog when the keygaurd
         *    is showing.
         */
        boolean showDuringKeyguard();

        /**
         * @return whether this action should appear in the dialog before the
         *   device is provisioned.
         */
        boolean showBeforeProvisioning();

        boolean isEnabled();
    }

    /**
     * A single press action maintains no state, just responds to a press
     * and takes an action.
     */
    private static abstract class SinglePressAction implements Action {
        private final int mIconResId;
        private final int mMessageResId;

        protected SinglePressAction(int iconResId, int messageResId) {
            mIconResId = iconResId;
            mMessageResId = messageResId;
        }

        public boolean isEnabled() {
            return true;
        }

        abstract public void onPress();

        public View create(
                Context context, View convertView, ViewGroup parent, LayoutInflater inflater) {
            View v = (convertView != null) ?
                    convertView :
                    inflater.inflate(R.layout.global_actions_item, parent, false);

            ImageView icon = (ImageView) v.findViewById(R.id.icon);
            TextView messageView = (TextView) v.findViewById(R.id.message);

            v.findViewById(R.id.status).setVisibility(View.GONE);

            icon.setImageDrawable(context.getResources().getDrawable(mIconResId));
            messageView.setText(mMessageResId);

            return v;
        }
    }

    /**
     * A toggle action knows whether it is on or off, and displays an icon
     * and status message accordingly.
     */
    private static abstract class ToggleAction implements Action {

        enum State {
            Off(false),
            TurningOn(true),
            TurningOff(true),
            On(false);

            private final boolean inTransition;

            State(boolean intermediate) {
                inTransition = intermediate;
            }

            public boolean inTransition() {
                return inTransition;
            }
        }

        protected State mState = State.Off;

        // prefs
        private final int mEnabledIconResId;
        private final int mDisabledIconResid;
        private final int mMessageResId;
        private final int mEnabledStatusMessageResId;
        private final int mDisabledStatusMessageResId;

        /**
         * @param enabledIconResId The icon for when this action is on.
         * @param disabledIconResid The icon for when this action is off.
         * @param essage The general information message, e.g 'Silent Mode'
         * @param enabledStatusMessageResId The on status message, e.g 'sound disabled'
         * @param disabledStatusMessageResId The off status message, e.g. 'sound enabled'
         */
        public ToggleAction(int enabledIconResId,
                int disabledIconResid,
                int essage,
                int enabledStatusMessageResId,
                int disabledStatusMessageResId) {
            mEnabledIconResId = enabledIconResId;
            mDisabledIconResid = disabledIconResid;
            mMessageResId = essage;
            mEnabledStatusMessageResId = enabledStatusMessageResId;
            mDisabledStatusMessageResId = disabledStatusMessageResId;
        }

        public View create(Context context, View convertView, ViewGroup parent,
                LayoutInflater inflater) {
            View v = (convertView != null) ?
                    convertView :
                    inflater.inflate(R
                            .layout.global_actions_item, parent, false);

            ImageView icon = (ImageView) v.findViewById(R.id.icon);
            TextView messageView = (TextView) v.findViewById(R.id.message);
            TextView statusView = (TextView) v.findViewById(R.id.status);

            messageView.setText(mMessageResId);

            boolean on = ((mState == State.On) || (mState == State.TurningOn));
            icon.setImageDrawable(context.getResources().getDrawable(
                    (on ? mEnabledIconResId : mDisabledIconResid)));
            statusView.setText(on ? mEnabledStatusMessageResId : mDisabledStatusMessageResId);
            statusView.setVisibility(View.VISIBLE);

            final boolean enabled = isEnabled();
            messageView.setEnabled(enabled);
            statusView.setEnabled(enabled);
            icon.setEnabled(enabled);
            v.setEnabled(enabled);

            return v;
        }

        public final void onPress() {
            if (mState.inTransition()) {
                Log.w(TAG, "shouldn't be able to toggle when in transition");
                return;
            }

            final boolean nowOn = !(mState == State.On);
            onToggle(nowOn);
            changeStateFromPress(nowOn);
        }

        public boolean isEnabled() {
            return !mState.inTransition();
        }

        /**
         * Implementations may override this if their state can be in on of the intermediate
         * states until some notification is received (e.g airplane mode is 'turning off' until
         * we know the wireless connections are back online
         * @param buttonOn Whether the button was turned on or off
         */
        protected void changeStateFromPress(boolean buttonOn) {
            mState = buttonOn ? State.On : State.Off;
        }

        abstract void onToggle(boolean on);

        public void updateState(State state) {
            mState = state;
        }
    }

    private BroadcastReceiver mBroadcastReceiver = new BroadcastReceiver() {
        public void onReceive(Context context, Intent intent) {
            String action = intent.getAction();
            if (Intent.ACTION_CLOSE_SYSTEM_DIALOGS.equals(action)
                    || Intent.ACTION_SCREEN_OFF.equals(action)) {
                String reason = intent.getStringExtra(PhoneWindowManager.SYSTEM_DIALOG_REASON_KEY);
                if (!PhoneWindowManager.SYSTEM_DIALOG_REASON_GLOBAL_ACTIONS.equals(reason)) {
                    mHandler.sendEmptyMessage(MESSAGE_DISMISS);
                }
            } else if (TelephonyIntents.ACTION_EMERGENCY_CALLBACK_MODE_CHANGED.equals(action)) {
                // Airplane mode can be changed after ECM exits if airplane toggle button
                // is pressed during ECM mode
                if (!(intent.getBooleanExtra("PHONE_IN_ECM_STATE", false)) &&
                        mIsWaitingForEcmExit) {
                    mIsWaitingForEcmExit = false;
                    changeAirplaneModeSystemSetting(true);
                }
            }
        }
    };

    PhoneStateListener mPhoneStateListener = new PhoneStateListener() {
        @Override
        public void onServiceStateChanged(ServiceState serviceState) {
            final boolean inAirplaneMode = serviceState.getState() == ServiceState.STATE_POWER_OFF;
            mAirplaneState = inAirplaneMode ? ToggleAction.State.On : ToggleAction.State.Off;
            mAirplaneModeOn.updateState(mAirplaneState);
            mAdapter.notifyDataSetChanged();
        }
    };

    private static final int MESSAGE_DISMISS = 0;
    private Handler mHandler = new Handler() {
        public void handleMessage(Message msg) {
            if (msg.what == MESSAGE_DISMISS) {
                if (mDialog != null) {
                    mDialog.dismiss();
                }
            }
        }
    };

    /**
     * Change the airplane mode system setting
     */
    private void changeAirplaneModeSystemSetting(boolean on) {
        Settings.System.putInt(
                mContext.getContentResolver(),
                Settings.System.AIRPLANE_MODE_ON,
                on ? 1 : 0);
        Intent intent = new Intent(Intent.ACTION_AIRPLANE_MODE_CHANGED);
        intent.putExtra("state", on);
        mContext.sendBroadcast(intent);
    }
}
