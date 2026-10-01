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

import android.app.ActivityManager;
import android.app.Dialog;
import android.app.StatusBarManager;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.res.Resources;
import android.content.pm.ActivityInfo;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.os.Process;
import android.provider.Settings;
import android.util.Log;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.view.View.OnClickListener;
import android.view.View.OnLongClickListener;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/**
 * N3DS_RECENTS_CLOSE (#324): the recent-apps switcher lists the apps that are
 * running (tasks that still have activities), like a modern Android overview.
 * Tap an app to switch to it; hold it (touch, or hold A) to close it; the tile
 * after the last app is "Close all".  The layout is the stock two rows of
 * three, so the dialog is no taller on the 240-pixel bottom screen.
 *
 * Closing goes through ActivityManager.restartPackage(), which in Eclair is a
 * force-stop that does NOT spare persistent processes: it kills every process
 * of the package's uid (unless that uid is system) and every process named
 * after the package.  n3dsCanClose() is what keeps it away from the system,
 * the launcher, the keyboard, persistent apps and the shared low uids (closing
 * a phone-uid package would take telephony down with it).
 */
public class RecentApplicationsDialog extends Dialog
        implements OnClickListener, OnLongClickListener {
    // Elements for debugging support
    private static final String LOG_TAG = "RecentApplicationsDialog";
    private static final boolean DBG_FORCE_EMPTY_LIST = false;

    static private StatusBarManager sStatusBar;

    private static final int NUM_BUTTONS = 6;
    private static final int MAX_RECENT_TASKS = 20;    // running tasks are a subset

    final View[] mButtons = new View[NUM_BUTTONS];
    View mNoAppsText;
    View mCloseAllButton;
    IntentFilter mBroadcastIntentFilter = new IntentFilter(Intent.ACTION_CLOSE_SYSTEM_DIALOGS);


    private int mIconSize;

    public RecentApplicationsDialog(Context context) {
        super(context, com.android.internal.R.style.Theme_Dialog_RecentApplications);

        final Resources resources = context.getResources();
        mIconSize = (int) resources.getDimension(android.R.dimen.app_icon_size);
    }

    /**
     * We create the recent applications dialog just once, and it stays around (hidden)
     * until activated by the user.
     *
     * @see PhoneWindowManager#showRecentAppsDialog
     */
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Context context = getContext();

        if (sStatusBar == null) {
            sStatusBar = (StatusBarManager)context.getSystemService(Context.STATUS_BAR_SERVICE);
        }

        Window theWindow = getWindow();
        theWindow.requestFeature(Window.FEATURE_NO_TITLE);
        theWindow.setType(WindowManager.LayoutParams.TYPE_SYSTEM_DIALOG);
        theWindow.setFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND,
                WindowManager.LayoutParams.FLAG_DIM_BEHIND);
        theWindow.setFlags(WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM,
                WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM);
        theWindow.setTitle("Recents");

        setContentView(com.android.internal.R.layout.recent_apps_dialog);

        mButtons[0] = findViewById(com.android.internal.R.id.button1);
        mButtons[1] = findViewById(com.android.internal.R.id.button2);
        mButtons[2] = findViewById(com.android.internal.R.id.button3);
        mButtons[3] = findViewById(com.android.internal.R.id.button4);
        mButtons[4] = findViewById(com.android.internal.R.id.button5);
        mButtons[5] = findViewById(com.android.internal.R.id.button6);
        mNoAppsText = findViewById(com.android.internal.R.id.no_applications_message);

        for (View b : mButtons) {
            b.setOnClickListener(this);
            b.setOnLongClickListener(this);
        }
    }

    /**
     * Handler for user clicks.  If a button was clicked, launch the corresponding activity.
     */
    public void onClick(View v) {
        if (v != null && v == mCloseAllButton) {
            closeAll();
            dismiss();
            return;
        }

        for (View b : mButtons) {
            if (b == v && b.getTag() instanceof Intent) {
                // prepare a launch intent and send it
                Intent intent = (Intent)b.getTag();
                intent.addFlags(Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY);
                getContext().startActivity(intent);
            }
        }
        dismiss();
    }

    /**
     * Holding an app closes it.  The list reloads at once (Eclair finishes the
     * task's activities synchronously), so its tile disappears.
     */
    public boolean onLongClick(View v) {
        if (v == null || v == mCloseAllButton || !(v.getTag() instanceof Intent)) {
            return false;   // the Close all tile: a long press is just a press
        }
        Intent intent = (Intent) v.getTag();
        ComponentName cn = intent.getComponent();
        CharSequence title = ((TextView) v).getText();
        if (cn == null || !n3dsCanClose(cn.getPackageName())) {
            Toast.makeText(getContext(), title + " can't be closed",
                    Toast.LENGTH_SHORT).show();
            return true;
        }
        closePackage(cn.getPackageName());
        Toast.makeText(getContext(), "Closed " + title, Toast.LENGTH_SHORT).show();
        reloadButtons();
        return true;
    }

    /**
     * Set up and show the recent activities dialog.
     */
    @Override
    public void onStart() {
        super.onStart();
        reloadButtons();
        if (sStatusBar != null) {
            sStatusBar.disable(StatusBarManager.DISABLE_EXPAND);
        }

        // receive broadcasts
        getContext().registerReceiver(mBroadcastReceiver, mBroadcastIntentFilter);
    }

    /**
     * Dismiss the recent activities dialog.
     */
    @Override
    public void onStop() {
        super.onStop();

        // dump extra memory we're hanging on to
        for (View b : mButtons) {
            setButtonAppearance(b, null, null);
            b.setTag(null);
        }
        mCloseAllButton = null;

        if (sStatusBar != null) {
            sStatusBar.disable(StatusBarManager.DISABLE_NONE);
        }

        // stop receiving broadcasts
        getContext().unregisterReceiver(mBroadcastReceiver);
     }

    /** The running tasks' launch intents, newest first, home excluded. */
    private List<Intent> runningTaskIntents(PackageManager pm, ActivityManager am) {
        final List<ActivityManager.RecentTaskInfo> recentTasks =
                                        am.getRecentTasks(MAX_RECENT_TASKS, 0);
        final ArrayList<Intent> result = new ArrayList<Intent>();

        ResolveInfo homeInfo = pm.resolveActivity(
                new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME),
                0);

        int numTasks = recentTasks.size();
        for (int i = 0; i < numTasks; ++i) {
            final ActivityManager.RecentTaskInfo info = recentTasks.get(i);

            // for debug purposes only, disallow first result to create empty lists
            if (DBG_FORCE_EMPTY_LIST && (i == 0)) continue;

            // A task with no activities left is history, not a running app.
            if (info.id < 0) continue;

            Intent intent = new Intent(info.baseIntent);
            if (info.origActivity != null) {
                intent.setComponent(info.origActivity);
            }
            if (intent.getComponent() == null) continue;

            // Skip the current home activity.
            if (homeInfo != null) {
                if (homeInfo.activityInfo.packageName.equals(
                        intent.getComponent().getPackageName())
                        && homeInfo.activityInfo.name.equals(
                                intent.getComponent().getClassName())) {
                    continue;
                }
            }

            intent.setFlags((intent.getFlags()&~Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
                    | Intent.FLAG_ACTIVITY_NEW_TASK);
            result.add(intent);
        }
        return result;
    }

    /**
     * Reload the buttons with the running apps, and the Close all tile after them.
     */
    private void reloadButtons() {

        final Context context = getContext();
        final PackageManager pm = context.getPackageManager();
        final ActivityManager am = (ActivityManager)
                                        context.getSystemService(Context.ACTIVITY_SERVICE);
        final List<Intent> running = runningTaskIntents(pm, am);

        // One tile is kept for Close all.
        int button = 0;
        mCloseAllButton = null;
        for (int i = 0; i < running.size() && (button < NUM_BUTTONS - 1); ++i) {
            final Intent intent = running.get(i);
            final ResolveInfo resolveInfo = pm.resolveActivity(intent, 0);
            if (resolveInfo != null) {
                final ActivityInfo activityInfo = resolveInfo.activityInfo;
                final String title = activityInfo.loadLabel(pm).toString();
                final Drawable icon = activityInfo.loadIcon(pm);

                if (title != null && title.length() > 0 && icon != null) {
                    final View b = mButtons[button];
                    setButtonAppearance(b, title, icon);
                    b.setTag(intent);
                    b.setVisibility(View.VISIBLE);
                    b.setPressed(false);
                    b.clearFocus();
                    ++button;
                }
            }
        }

        if (button > 0) {
            final View b = mButtons[button];
            setButtonAppearance(b, "Close all", context.getResources().getDrawable(
                    android.R.drawable.ic_menu_close_clear_cancel));
            b.setTag(null);
            b.setVisibility(View.VISIBLE);
            b.setPressed(false);
            b.clearFocus();
            mCloseAllButton = b;
            ++button;
        }

        // handle the case of "no icons to show"
        mNoAppsText.setVisibility((button == 0) ? View.VISIBLE : View.GONE);

        // hide the rest
        for ( ; button < NUM_BUTTONS; ++button) {
            mButtons[button].setVisibility(View.GONE);
        }

        // Keep the D-pad on a tile after a close removed the focused one.
        if (mButtons[0].getVisibility() == View.VISIBLE) {
            mButtons[0].requestFocus();
        }
    }

    /** Close every running app that may be closed, not only the five shown. */
    private void closeAll() {
        final Context context = getContext();
        final PackageManager pm = context.getPackageManager();
        final ActivityManager am = (ActivityManager)
                                        context.getSystemService(Context.ACTIVITY_SERVICE);
        final ArrayList<String> done = new ArrayList<String>();
        for (Intent intent : runningTaskIntents(pm, am)) {
            String pkg = intent.getComponent().getPackageName();
            if (done.contains(pkg)) continue;
            done.add(pkg);
            if (n3dsCanClose(pkg)) {
                closePackage(pkg);
            } else {
                Log.i(LOG_TAG, "N3DS_RECENTS_CLOSE: kept " + pkg);
            }
        }
    }

    private void closePackage(String pkg) {
        final ActivityManager am = (ActivityManager)
                getContext().getSystemService(Context.ACTIVITY_SERVICE);
        try {
            Log.i(LOG_TAG, "N3DS_RECENTS_CLOSE: closing " + pkg);
            am.restartPackage(pkg);
        } catch (RuntimeException e) {
            Log.w(LOG_TAG, "N3DS_RECENTS_CLOSE: could not close " + pkg, e);
        }
    }

    /**
     * Whether restartPackage(pkg) is safe -- see the class comment.  Anything
     * in doubt is kept.
     */
    private boolean n3dsCanClose(String pkg) {
        if (pkg == null || pkg.equals("android")
                || pkg.equals(getContext().getPackageName())) {
            return false;
        }
        final PackageManager pm = getContext().getPackageManager();

        ResolveInfo homeInfo = pm.resolveActivity(
                new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), 0);
        if (homeInfo != null && pkg.equals(homeInfo.activityInfo.packageName)) {
            return false;
        }

        String ime = Settings.Secure.getString(getContext().getContentResolver(),
                Settings.Secure.DEFAULT_INPUT_METHOD);
        if (ime != null) {
            ComponentName imeName = ComponentName.unflattenFromString(ime);
            if (imeName != null && pkg.equals(imeName.getPackageName())) {
                return false;
            }
        }

        ApplicationInfo ai;
        try {
            ai = pm.getApplicationInfo(pkg, 0);
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
        if ((ai.flags & ApplicationInfo.FLAG_PERSISTENT) != 0) {
            return false;
        }
        // The system uid is killed by process name only; other uids below the
        // application range are shared with system services (phone, ...).
        if (ai.uid == Process.SYSTEM_UID) {
            return true;
        }
        if (ai.uid < Process.FIRST_APPLICATION_UID) {
            return false;
        }
        // A shared application uid takes every package in it down too: keep
        // it if any of them is persistent.
        String[] sharing = pm.getPackagesForUid(ai.uid);
        if (sharing != null) {
            for (String other : sharing) {
                try {
                    if ((pm.getApplicationInfo(other, 0).flags
                            & ApplicationInfo.FLAG_PERSISTENT) != 0) {
                        return false;
                    }
                } catch (PackageManager.NameNotFoundException e) {
                    // gone already
                }
            }
        }
        return true;
    }

    /**
     * Adjust appearance of each icon-button
     */
    private void setButtonAppearance(View theButton, final String theTitle, final Drawable icon) {
        TextView tv = (TextView) theButton;
        tv.setText(theTitle);
        if (icon != null) {
            icon.setBounds(0, 0, mIconSize, mIconSize);
        }
        tv.setCompoundDrawables(null, icon, null, null);
    }

    /**
     * This is the listener for the ACTION_CLOSE_SYSTEM_DIALOGS intent.  It's an indication that
     * we should close ourselves immediately, in order to allow a higher-priority UI to take over
     * (e.g. phone call received).
     */
    private BroadcastReceiver mBroadcastReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String action = intent.getAction();
            if (Intent.ACTION_CLOSE_SYSTEM_DIALOGS.equals(action)) {
                String reason = intent.getStringExtra(PhoneWindowManager.SYSTEM_DIALOG_REASON_KEY);
                if (! PhoneWindowManager.SYSTEM_DIALOG_REASON_RECENT_APPS.equals(reason)) {
                    dismiss();
                }
            }
        }
    };
}
