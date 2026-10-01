/*
 * "New contact" editor for N3dsDialer.
 *
 * Reached via an explicit Intent from N3dsDialerActivity, and via
 * INSERT_OR_EDIT from Mms "Add to contacts" now that the stock Contacts app is
 * retired (#317). Never through the launcher, so per project convention it
 * needs no PNG icon of its own.
 *
 * N3DS_DIALER_TABS (2026-09-11): this screen used to be the whole contacts +
 * call-history UI. Both lists now live in N3dsDialerActivity as Canvas panes,
 * so switching to them is a repaint rather than an Activity launch. What is
 * left here is the one thing a list pane cannot do -- text entry -- so this is
 * now a single-purpose editor.
 *
 * It stays on framework widgets rather than Canvas because an EditText is what
 * brings up the IME; a hand-drawn field would have nothing behind it. The
 * number field is pre-seeded with whatever was on the dialpad (EXTRA_SEED_NUMBER)
 * so the common path -- type digits on the pad, then save them under a name --
 * needs the keyboard only for the name.
 *
 * On save it returns RESULT_OK with EXTRA_NUMBER, so the caller can drop the
 * new number straight into the dialpad.
 *
 * N3DS_CONTACTS_EDIT (#326): with EXTRA_CONTACT_ID it edits an existing
 * contact instead, and shows DELETE (tap twice). Saving a new contact under
 * a number that is already saved updates that contact rather than adding a
 * duplicate, so the name a call shows is never ambiguous.
 */
package com.android.n3dsdialer;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

public final class N3dsContactsActivity extends Activity {
    private static final String TAG = "N3dsDialerContacts";
    static final String EXTRA_NUMBER = "com.android.n3dsdialer.extra.NUMBER";
    static final String EXTRA_SEED_NUMBER = "com.android.n3dsdialer.extra.SEED_NUMBER";
    static final String EXTRA_CONTACT_ID = "com.android.n3dsdialer.extra.CONTACT_ID";
    static final String EXTRA_NAME = "com.android.n3dsdialer.extra.NAME";

    private ContactsStore mStore;
    private EditText mNameField;
    private EditText mNumberField;
    private long mContactId = -1;
    private Button mDelete;
    private boolean mDeleteArmed;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN);
        mStore = ContactsStore.get(this);
        Intent in = getIntent();
        if (in != null) mContactId = in.getLongExtra(EXTRA_CONTACT_ID, -1);
        setContentView(buildLayout());

        String seed = in == null ? null : in.getStringExtra(EXTRA_SEED_NUMBER);
        // N3DS_CONTACTS_INSERT_OR_EDIT: Mms "Add to contacts" sends the
        // standard ContactsContract.Intents.Insert extras ("phone", "name").
        if ((seed == null || seed.length() == 0) && in != null) {
            seed = in.getStringExtra("phone");
        }
        if (seed != null && seed.length() > 0) {
            mNumberField.setText(seed);
        }
        String name = in == null ? null : in.getStringExtra(EXTRA_NAME);
        if ((name == null || name.length() == 0) && in != null) {
            name = in.getStringExtra("name");
        }
        if (name != null && name.length() > 0) {
            mNameField.setText(name);
        }
        Log.i(TAG, "N3DS_CONTACTS_EDITOR_READY edit=" + (mContactId >= 0));
    }

    private View buildLayout() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(DialerTheme.BG);
        root.setPadding(8, 6, 8, 6);

        root.addView(label(mContactId >= 0 ? "Edit contact" : "New contact", 18,
                        DialerTheme.TEXT, Gravity.CENTER),
                wrap(ViewGroup.LayoutParams.FILL_PARENT));
        root.addView(label("3-4 digit 3DS numbers or 10 digit web numbers.", 11,
                        DialerTheme.TEXT_DIM, Gravity.CENTER),
                wrap(ViewGroup.LayoutParams.FILL_PARENT));

        root.addView(label("NAME", 10, DialerTheme.TEXT_DIM, Gravity.LEFT),
                wrap(ViewGroup.LayoutParams.FILL_PARENT));
        mNameField = new EditText(this);
        mNameField.setSingleLine(true);
        mNameField.setTextColor(DialerTheme.TEXT);
        root.addView(mNameField, wrap(ViewGroup.LayoutParams.FILL_PARENT));

        root.addView(label("NUMBER", 10, DialerTheme.TEXT_DIM, Gravity.LEFT),
                wrap(ViewGroup.LayoutParams.FILL_PARENT));
        mNumberField = new EditText(this);
        mNumberField.setSingleLine(true);
        mNumberField.setInputType(InputType.TYPE_CLASS_PHONE);
        mNumberField.setTextColor(DialerTheme.TEXT);
        root.addView(mNumberField, wrap(ViewGroup.LayoutParams.FILL_PARENT));

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        Button cancel = new Button(this);
        cancel.setText("CANCEL");
        cancel.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                setResult(RESULT_CANCELED);
                finish();
            }
        });
        buttons.addView(cancel, weighted(1f));
        if (mContactId >= 0) {
            mDelete = new Button(this);
            mDelete.setText("DELETE");
            mDelete.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) {
                    onDeleteContact();
                }
            });
            buttons.addView(mDelete, weighted(1f));
        }
        Button save = new Button(this);
        save.setText("SAVE");
        save.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                onSaveContact();
            }
        });
        buttons.addView(save, weighted(1f));
        root.addView(buttons, wrap(ViewGroup.LayoutParams.FILL_PARENT));

        return root;
    }

    private TextView label(String text, float size, int color, int gravity) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextColor(color);
        tv.setTextSize(size);
        tv.setGravity(gravity);
        tv.setPadding(0, 4, 0, 2);
        return tv;
    }

    private static LinearLayout.LayoutParams wrap(int width) {
        return new LinearLayout.LayoutParams(width, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    private static LinearLayout.LayoutParams weighted(float weight) {
        LinearLayout.LayoutParams lp =
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.weight = weight;
        return lp;
    }

    private void onSaveContact() {
        String name = mNameField.getText().toString().trim();
        String number = mNumberField.getText().toString().trim();
        if (number.length() == 0) {
            Toast.makeText(this, "Enter a number to save.", Toast.LENGTH_SHORT).show();
            return;
        }
        // Warn rather than refuse: the store is also used to label numbers seen
        // in the call log, and rejecting an odd one would just lose the name.
        if (!number.matches("(?:[1-9][0-9]{2,3}|[2-9][0-9]{9})")) {
            Toast.makeText(this, "Saved, but that is not a dialable 3DSTelco number.",
                    Toast.LENGTH_SHORT).show();
        }
        if (name.length() == 0) {
            name = number;
        }
        try {
            long existing = mContactId >= 0 ? mContactId : mStore.idForNumber(number);
            if (existing >= 0) {
                mStore.updateContact(existing, name, number);
                Log.i(TAG, "N3DS_CONTACTS_UPDATED id=" + existing);
            } else {
                mStore.addContact(name, number);
                Log.i(TAG, "N3DS_CONTACTS_ADDED");
            }
            Toast.makeText(this, "Saved " + name + ".", Toast.LENGTH_SHORT).show();
        } catch (Throwable t) {
            Log.w(TAG, "N3DS_CONTACTS_SAVE_FAILED: " + t);
            Toast.makeText(this, "Could not save contact.", Toast.LENGTH_SHORT).show();
            return;
        }
        Intent result = new Intent();
        result.putExtra(EXTRA_NUMBER, number);
        setResult(RESULT_OK, result);
        finish();
    }

    private void onDeleteContact() {
        // Two taps: the button sits beside SAVE on a resistive screen.
        if (!mDeleteArmed) {
            mDeleteArmed = true;
            mDelete.setText("SURE?");
            return;
        }
        try {
            mStore.deleteContact(mContactId);
            Log.i(TAG, "N3DS_CONTACTS_DELETED id=" + mContactId);
            Toast.makeText(this, "Contact deleted.", Toast.LENGTH_SHORT).show();
        } catch (Throwable t) {
            Log.w(TAG, "N3DS_CONTACTS_DELETE_FAILED: " + t);
            Toast.makeText(this, "Could not delete contact.", Toast.LENGTH_SHORT).show();
            return;
        }
        setResult(RESULT_OK);
        finish();
    }
}
