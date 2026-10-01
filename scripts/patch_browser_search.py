#!/usr/bin/env python3
# N3DS_BROWSER_JS_FREE_SEARCH: search and home page that a 2009 WebKit can use.
# Idempotent (guarded by the marker); the release gate checks the dex string.
from a3ds_paths import A3DS_ROOT
B = f"{A3DS_ROOT}/third_party/browser/"
p = B + "src/com/android/browser/BrowserActivity.java"
s = open(p).read()
if "N3DS_BROWSER_JS_FREE_SEARCH" not in s:
    old = '    final static String QuickSearch_G = "http://www.google.com/m?q=%s";\n'
    new = ('    // N3DS_BROWSER_JS_FREE_SEARCH: Google search needs modern JavaScript\n'
           '    // (this 2009 JavaScriptCore stops at "SyntaxError: Parse error" on its\n'
           '    // xjs bundle) and redirects to HTTPS.  Wiby is plain HTTP and no script,\n'
           '    // so typed searches return a page this engine can render.\n'
           '    final static String QuickSearch_G = "http://wiby.me/?q=%s";\n')
    assert s.count(old) == 1
    s = s.replace(old, new)
    open(p, "w").write(s)
    print("patched", p)
p = B + "res/values/strings.xml"
s = open(p).read()
if "N3DS_BROWSER_JS_FREE_SEARCH" not in s:
    old = ('    <string name="homepage_base" translatable="false">\n'
           '        http://www.google.com/m?client=ms-{CID}&amp;source=android-home</string>\n')
    new = ('    <!-- N3DS_BROWSER_JS_FREE_SEARCH: google.com/m is a JavaScript page this\n'
           '         2009 engine cannot run; Wiby is plain HTTP and no script. -->\n'
           '    <string name="homepage_base" translatable="false">http://wiby.me/</string>\n')
    assert s.count(old) == 1
    s = s.replace(old, new)
    open(p, "w").write(s)
    print("patched", p)
