#!/usr/bin/env python3
# N3DS patches to AOSP LatinIME (android-2.0_r1) for the 320x240 bottom screen.
# Idempotent: every hunk is guarded by its N3DS_LATINIME_* marker, and
# scripts/test_latinime.py asserts the result.  Applied to the shallow clone
# third_party/latinime (android-2.0 tip 8850bdc), a nested repo.
from a3ds_paths import A3DS_ROOT
import re
import sys

L = f"{A3DS_ROOT}/third_party/latinime/"
J = L + "src/com/android/inputmethod/latin/"


def patch(path, marker, pairs):
    s = open(path).read()
    if marker in s:
        print("already", path)
        return
    for old, new in pairs:
        assert s.count(old) == 1, "%s: anchor not found:\n%s" % (path, old)
        s = s.replace(old, new)
    assert marker in s, marker
    open(path, "w").write(s)
    print("patched", path)


# ------------------------------------------------------------- LatinIME.java
patch(J + "LatinIME.java", "N3DS_LATINIME_NO_EXTRACT", [
    ('''        mUserDictionary = new UserDictionary(this);
        mContactsDictionary = new ContactsDictionary(this);
''', '''        mUserDictionary = new UserDictionary(this);
        // N3DS_LATINIME_NO_CONTACTS: the contacts dictionary queries
        // ContactsProvider every time the IME process starts, which spins up
        // the whole android.process.acore Dalvik process on this 128 MB
        // console just to learn a few names -- and the N3DS dialer keeps its
        // contacts in its own database, not there.  Suggest treats a null
        // contacts dictionary as absent.
        mContactsDictionary = null;
'''),
    ('''        mUserDictionary.close();
        mContactsDictionary.close();
''', '''        mUserDictionary.close();
        if (mContactsDictionary != null) mContactsDictionary.close();
'''),
    ('''    @Override
    public View onCreateInputView() {
''', '''    /**
     * N3DS_LATINIME_NO_EXTRACT: the 320x240 screen always reports landscape,
     * where InputMethodService would switch to a full-screen extract editor
     * and mirror every keystroke into it over IPC.  Keep the app's own field
     * visible above the keyboard instead, as the old N3DS keyboard did; the
     * keyboard is sized (dimens.xml in values and values-land,
     * N3DS_LATINIME_240P) to
     * leave room for it.
     */
    @Override
    public boolean onEvaluateFullscreenMode() {
        return false;
    }

    @Override
    public View onCreateInputView() {
'''),
])

# ------------------------------------------------------------ UserDictionary
# The UserDictionary provider is not installed on this build: query() returns
# null and insert() throws "Unknown URL".  Keep the in-memory dictionary.
patch(J + "UserDictionary.java", "N3DS_LATINIME_NO_USERDICT_PROVIDER", [
    ('''        super.addWord(word, frequency);

        Words.addWord(getContext(), word, frequency, Words.LOCALE_TYPE_CURRENT);
''', '''        super.addWord(word, frequency);

        // N3DS_LATINIME_NO_USERDICT_PROVIDER: there is no UserDictionary
        // provider on this build, so the insert throws "Unknown URL".  The
        // word stays in this in-memory dictionary for the session.
        try {
            Words.addWord(getContext(), word, frequency, Words.LOCALE_TYPE_CURRENT);
        } catch (RuntimeException e) {
            // No provider: nothing to persist to.
        }
'''),
    ('''    private void addWords(Cursor cursor) {
        clearDictionary();

''', '''    private void addWords(Cursor cursor) {
        clearDictionary();
        // N3DS_LATINIME_NO_USERDICT_PROVIDER: query() returns null when the
        // provider is not installed.
        if (cursor == null) return;

'''),
])

# ---------------------------------------------------------- KeyboardSwitcher
patch(J + "KeyboardSwitcher.java", "N3DS_LATINIME_NO_KEY_PREVIEW", [
    ('''        mIsSymbols = isSymbols;
        mInputView.setPreviewEnabled(true);
''', '''        mIsSymbols = isSymbols;
        // N3DS_LATINIME_NO_KEY_PREVIEW: the key-press preview is a separate
        // popup window that is shown, moved and dismissed on every key, i.e.
        // a window-manager relayout and an extra SurfaceFlinger layer per
        // tap.  The candidate strip already echoes what was typed.
        mInputView.setPreviewEnabled(false);
'''),
])

# ------------------------------------------------------------------ dimens
DIMENS = '''<?xml version="1.0" encoding="utf-8"?>
<!--
/*
**
** Copyright 2008, The Android Open Source Project
**
** Licensed under the Apache License, Version 2.0 (the "License");
** you may not use this file except in compliance with the License.
** You may obtain a copy of the License at
**
**     http://www.apache.org/licenses/LICENSE-2.0
**
** Unless required by applicable law or agreed to in writing, software
** distributed under the License is distributed on an "AS IS" BASIS,
** WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
** See the License for the specific language governing permissions and
** limitations under the License.
*/
-->
<!-- N3DS_LATINIME_240P: the bottom screen is 320x240 at 160 dpi (1 dip =
     1 px) and always landscape.  Stock rows (47-54 dip) plus the 38-42 dip
     strip filled 226 of its 240 px; 4 x 40 + 28 = 188 px leaves the edited
     field visible above the keyboard (N3DS_LATINIME_NO_EXTRACT). -->
<resources>
    <dimen name="key_height">40dip</dimen>
    <dimen name="bubble_pointer_offset">22dip</dimen>
    <dimen name="candidate_strip_height">28dip</dimen>
    <dimen name="spacebar_vertical_correction">2dip</dimen>
</resources>
'''
for p in (L + "res/values/dimens.xml", L + "res/values-land/dimens.xml"):
    s = open(p).read()
    if "N3DS_LATINIME_240P" in s:
        print("already", p)
        continue
    open(p, "w").write(DIMENS)
    print("patched", p)

p = L + "res/layout/candidate_preview.xml"
s = open(p).read()
if 'android:textSize="18sp"' in s:
    s = s.replace('android:textSize="18sp"', 'android:textSize="16sp"')
    s = s.replace("<TextView", "<!-- N3DS_LATINIME_240P: 16sp fits the 28 dip strip -->\n<TextView", 1)
    open(p, "w").write(s)
    print("patched", p)

# ------------------------------------------------------------- manifest
# N3DS_LATINIME_OWN_UID: android.uid.shared only existed so the contacts
# dictionary could read contacts with ContactsProvider's permissions; with that
# off (N3DS_LATINIME_NO_CONTACTS) it would only tie this APK's install to
# ContactsProvider's signature.
p = L + "AndroidManifest.xml"
s = open(p).read()
if "N3DS_LATINIME_OWN_UID" not in s:
    old = '''        package="com.android.inputmethod.latin"
        android:sharedUserId="android.uid.shared">
'''
    new = '''        package="com.android.inputmethod.latin">
    <!-- N3DS_LATINIME_OWN_UID: no android.uid.shared; it only existed so the
         contacts dictionary could read contacts, which this build turns off
         (N3DS_LATINIME_NO_CONTACTS). -->
    <uses-sdk android:minSdkVersion="5" />
'''
    assert s.count(old) == 1
    s = s.replace(old, new)
    open(p, "w").write(s)
    print("patched", p)

# ---------------------------------------------------------- BinaryDictionary
# N3DS_LATINIME_NATIVE_OPTIONAL: build #321 shipped with the dictionary natives
# unreachable (Dalvik's java.library.path was empty, so loadLibrary never got
# to the built-in JNI table) and LatinIME died in onCreate on the first
# native call -- no keyboard at all.  A keyboard without suggestions is still
# a keyboard: without the natives the dictionary is simply empty.
patch(J + "BinaryDictionary.java", "N3DS_LATINIME_NATIVE_OPTIONAL", [
    ('''    static {
        try {
            System.loadLibrary("jni_latinime");
        } catch (UnsatisfiedLinkError ule) {
            Log.e("BinaryDictionary", "Could not load native library jni_latinime");
        }
    }
''', '''    // N3DS_LATINIME_NATIVE_OPTIONAL: false when the natives could not be
    // bound; every native call below is then skipped and the dictionary is
    // empty, instead of an UnsatisfiedLinkError killing the IME process.
    private static boolean sNativeAvailable;

    static {
        try {
            System.loadLibrary("jni_latinime");
            sNativeAvailable = true;
        } catch (UnsatisfiedLinkError ule) {
            Log.e("BinaryDictionary", "Could not load native library jni_latinime: "
                    + ule.getMessage() + " (N3DS_LATINIME_NATIVE_OPTIONAL)");
        }
    }
'''),
    ('''        String assetName = context.getResources().getString(resId);
        mNativeDict = openNative(am, assetName, TYPED_LETTER_MULTIPLIER, FULL_WORD_FREQ_MULTIPLIER);
    }
''', '''        String assetName = context.getResources().getString(resId);
        if (!sNativeAvailable) return;
        try {
            mNativeDict = openNative(am, assetName, TYPED_LETTER_MULTIPLIER,
                    FULL_WORD_FREQ_MULTIPLIER);
        } catch (UnsatisfiedLinkError ule) {
            Log.e("BinaryDictionary", "openNative is not bound: " + ule.getMessage()
                    + " (N3DS_LATINIME_NATIVE_OPTIONAL)");
            sNativeAvailable = false;
            mNativeDict = 0;
        }
    }
'''),
    ('''        mWordCallback = callback;
        final int codesSize = codes.size();
''', '''        mWordCallback = callback;
        if (mNativeDict == 0) return;
        final int codesSize = codes.size();
'''),
    ('''        if (word == null) return false;
        char[] chars''', '''        if (word == null || mNativeDict == 0) return false;
        char[] chars'''),
])
