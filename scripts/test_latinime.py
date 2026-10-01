#!/usr/bin/env python3
"""Static checks for the AOSP LatinIME system keyboard (replaced N3DSKeyboard).

Run from rebuild_everything.sh before anything is built: every piece that
makes LatinIME work on this port lives in a different tree, and each one
fails silently on the device (no suggestions, a crash in onCreate, or the old
keyboard coming back from the SD card).
"""
from a3ds_paths import A3DS_ROOT
import importlib.util
import os
import re
import sys
import tempfile

ROOT = A3DS_ROOT
TP = ROOT + "/third_party"
LATIN = TP + "/latinime"
J = LATIN + "/src/com/android/inputmethod/latin/"
SCRIPTS = ROOT + "/scripts"


def read(p):
    with open(p) as f:
        return f.read()


def need(path, *markers):
    text = read(path)
    for m in markers:
        assert m in text, "%s: missing %r" % (path, m)
    return text


# --- LatinIME source patches -------------------------------------------------
latin = need(J + "LatinIME.java", "N3DS_LATINIME_NO_EXTRACT", "N3DS_LATINIME_NO_CONTACTS",
             "public boolean onEvaluateFullscreenMode() {\n        return false;")
assert "mContactsDictionary = new ContactsDictionary" not in latin
assert "if (mContactsDictionary != null) mContactsDictionary.close();" in latin
need(J + "UserDictionary.java", "N3DS_LATINIME_NO_USERDICT_PROVIDER", "if (cursor == null) return;")
ks = need(J + "KeyboardSwitcher.java", "N3DS_LATINIME_NO_KEY_PREVIEW")
assert "setPreviewEnabled(true)" not in ks, "key preview popup re-enabled"
for d in ("res/values/dimens.xml", "res/values-land/dimens.xml"):
    t = need(LATIN + "/" + d, "N3DS_LATINIME_240P")
    assert '<dimen name="key_height">40dip</dimen>' in t, d
    assert '<dimen name="candidate_strip_height">28dip</dimen>' in t, d
man = need(LATIN + "/AndroidManifest.xml", "N3DS_LATINIME_OWN_UID",
           'package="com.android.inputmethod.latin"', "android.permission.BIND_INPUT_METHOD")
assert "sharedUserId" not in re.sub(r"<!--.*?-->", "", man, flags=re.S)
assert os.path.getsize(LATIN + "/dictionaries/en_us_wordlist.xml.gz") > 500000

# --- native dictionary: Dalvik built-in table + app_process link -------------
native = need(TP + "/dalvik/vm/Native.c", "N3DS_STATIC_JNI_LIBS",
              'extern int JNI_OnLoad_jni_latinime(JavaVM*, void*) __attribute__((weak));',
              '{ "libjni_latinime.so", JNI_OnLoad_jni_latinime }',
              "if (pLib->handle == &gBuiltinJniHandle)")
need(SCRIPTS + "/build_app_process.sh", "N3DS_STATIC_JNI_LIBS",
     "-DJNI_OnLoad=JNI_OnLoad_jni_latinime",
     '"$OUT/obj/latinime_BinaryDictionary.o"', '"$OUT/obj/latinime_dictionary.o"',
     "T JNI_OnLoad_jni_latinime$")
# #321 hardware: java.library.path was "" (init.rc never exports LD_LIBRARY_PATH),
# so findLibrary() never reached /system/lib, the built-in table above was never
# consulted, and LatinIME died in BinaryDictionary.<clinit>.
props = need(TP + "/dalvik/vm/Properties.c", "N3DS_JAVA_LIBRARY_PATH",
             'libraryPath = "/system/lib";')
assert "\x00" not in props, "Properties.c contains a NUL byte"
bd = need(J + "BinaryDictionary.java", "N3DS_LATINIME_NATIVE_OPTIONAL",
          "sNativeAvailable", "if (mNativeDict == 0) return;")
need(SCRIPTS + "/patch_latinime_n3ds.py", "N3DS_LATINIME_NATIVE_OPTIONAL")
need(SCRIPTS + "/build_latinime.sh", "-0 .dict", "libjni_latinime.so", "N3DS_LATINIME_REAL_DICT")
need(SCRIPTS + "/prebake_latinime_odex.sh", "APK_NAME=LatinIME")
need(SCRIPTS + "/patch_latinime_n3ds.py", "N3DS_LATINIME_NO_EXTRACT", "N3DS_LATINIME_OWN_UID")

# --- default IME -------------------------------------------------------------
db = need(TP + "/frameworks/base/packages/SettingsProvider/src/com/android/providers/settings/DatabaseHelper.java",
          "N3DS_DEFAULT_TOUCH_IME", "N3DS_DEFAULT_LATINIME")
assert db.count("com.android.inputmethod.latin/.LatinIME") == 6, db.count("com.android.inputmethod.latin/.LatinIME")
assert "inputmethod.n3ds" not in db

# --- N3DSKeyboard is gone and stays gone -------------------------------------
prune = read(TP + "/buildroot/board/nintendo3ds/rootfs_overlay/etc/prune_retired_apps.sh")
m = re.search(r'^RETIRED="([^"]*)"', prune, re.M)
assert m and "N3DSKeyboard" in m.group(1).split(), "prune_retired_apps.sh does not retire N3DSKeyboard"
dexdep = read(SCRIPTS + "/jar_dexdep.py")
assert '("LatinIME.odex", "LatinIME.apk")' in dexdep
assert '"N3DSKeyboard.apk"' in dexdep and '"N3DSKeyboard.odex"' in dexdep  # RETIRED_APPS
for s in ("prebake_all_app_odex.sh", "rebuild_everything.sh", "resume_release_after_framework.sh"):
    t = read(SCRIPTS + "/" + s)
    assert "n3ds_ime" not in t, "%s still runs the retired N3DS keyboard" % s
    assert "latinime" in t, "%s does not build/prebake LatinIME" % s
for gone in ("build_n3ds_ime.sh", "prebake_n3ds_ime_odex.sh"):
    assert not os.path.exists(SCRIPTS + "/" + gone), gone

# --- the dictionary compiler round-trips the format dictionary.cpp reads -----
spec = importlib.util.spec_from_file_location("mkdict", SCRIPTS + "/make_latinime_dict.py")
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)
sample = {"the": 222, "then": 150, "they": 160, "I": 196, "don't": 120,
          "café": 60, "naïve": 50, "Āx": 40, "ÿy": 35,
          "a" * 40: 31, "Android": 90}
order, total = mk.layout(mk.build_trie(sample))
data = mk.serialise(order, total)
assert dict(mk.walk(data)) == sample, "trie round-trip failed"
for w, f in sample.items():
    assert mk.lookup(data, w) == f, w
assert mk.lookup(data, "th") is None and mk.lookup(data, "xyz") is None
with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as t:
    t.write('<wordlist>\n <w f="200" flags="">keep</w>\n <w f="10" flags="">rare</w>\n'
            ' <w f="200" flags="offensive">drop</w>\n <w f="0" flags="">zero</w>\n</wordlist>\n')
try:
    got = mk.read_words(t.name, 30)
finally:
    os.unlink(t.name)
assert got == {"keep": 200}, got

print("latinime: PASS")
