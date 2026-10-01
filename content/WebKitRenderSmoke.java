package android3ds;

import android.content.BroadcastReceiver;
import android.content.ContentResolver;
import android.content.Context;
import android.content.IContentProvider;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.res.AssetManager;
import android.content.res.Resources;
import android.database.sqlite.SQLiteDatabase;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Picture;
import android.os.Handler;
import android.os.Looper;
import android.util.AttributeSet;
import android.view.LayoutInflater;
import android.view.View;
import android.view.WindowManagerImpl;
import android.webkit.WebSettings;
import android.webkit.WebView;

import java.io.File;

/**
 * Host-side (qemu-user) render test for the WebKit engine linked into
 * app_process.
 *
 * #321 and #322 both showed real pages as blank on hardware, and #322's fix
 * (WebViewCore SetSize float ABI) was only checked by reading disassembly.
 * This drives the same Java WebView -> WebViewCore -> WebCore path the
 * Browser uses, with no system_server, then rasterises the recorded content
 * and looks at the pixels: a red box, a green page background and black
 * text must all be there.  Two passes: plain settings, and the Browser's own
 * (wide viewport, overview mode, narrow columns, JavaScript), which is what
 * actually runs on the device.
 *
 * A system Context cannot be used here: ActivityThread.getSystemContext()
 * asks SurfaceFlinger for the display and loops forever without it.  So this
 * supplies a minimal Context over Resources.getSystem().
 */
public class WebKitRenderSmoke {
    private static final int W = 320;
    private static final int H = 240;
    private static final int SENTINEL = 0xFFFF00FF;   /* magenta: "nothing drew here" */

    private static final String HTML =
        "<html><head><title>n3ds</title></head>"
        + "<body style=\"margin:0;padding:0;background-color:#00ff00\">"
        + "<div style=\"width:120px;height:80px;margin:0;background-color:#ff0000\"></div>"
        + "<p style=\"margin:0;font-size:32px;color:#000000\">Hello 3DS</p>"
        + "<p style=\"margin:0\">The quick brown fox jumps over the lazy dog.</p>"
        + "</body></html>";

    private static int sPictures;
    private static int sFailures;

    public static void main(String[] args) throws Exception {
        Looper.prepareMainLooper();
        final Context ctx = new TestContext();
        final Handler handler = new Handler();

        Thread watchdog = new Thread() {
            public void run() {
                try { Thread.sleep(150 * 1000); } catch (InterruptedException e) { return; }
                System.out.println("FAIL: webkit render smoke timed out");
                die();
            }
        };
        watchdog.setDaemon(true);
        watchdog.start();

        handler.post(new Runnable() {
            public void run() {
                try {
                    new Pass(ctx, handler, "plain", false, new Runnable() {
                        public void run() {
                            new Pass(ctx, handler, "browser", true, new Runnable() {
                                public void run() { finish(); }
                            }).start();
                        }
                    }).start();
                } catch (Throwable t) {
                    t.printStackTrace();
                    System.out.println("FAIL: webkit render smoke threw " + t);
                    die();
                }
            }
        });
        Looper.loop();
    }

    static void finish() {
        if (sFailures == 0) {
            System.out.println("PASS: webkit render");
        } else {
            System.out.println("FAIL: webkit render (" + sFailures + " checks failed)");
        }
        die();
    }

    /* exit() runs static destructors that wait on WebKit's threads and can
     * stall for minutes under qemu; the harness reads the PASS line, not the
     * exit status. */
    static void die() {
        System.out.flush();
        android.os.Process.killProcess(android.os.Process.myPid());
    }

    static void check(String what, boolean ok) {
        System.out.println((ok ? "  ok   " : "  FAIL ") + what);
        if (!ok) sFailures++;
    }

    /** One WebView, one page load, two rasterisations. */
    static final class Pass implements WebView.PictureListener {
        final Context mCtx;
        final Handler mHandler;
        final String mName;
        final boolean mBrowserSettings;
        final Runnable mNext;
        WebView mView;
        int mPolls;
        int mPictures;

        Pass(Context ctx, Handler h, String name, boolean browser, Runnable next) {
            mCtx = ctx; mHandler = h; mName = name; mBrowserSettings = browser; mNext = next;
        }

        void start() {
            System.out.println("== pass " + mName);
            mView = new WebView(mCtx);
            WebSettings s = mView.getSettings();
            if (mBrowserSettings) {
                /* BrowserSettings.java's defaults for this device. */
                s.setUseWideViewPort(true);
                s.setLoadWithOverviewMode(true);
                s.setLayoutAlgorithm(WebSettings.LayoutAlgorithm.NARROW_COLUMNS);
                s.setJavaScriptEnabled(true);
            }
            mView.setPictureListener(this);
            mView.measure(View.MeasureSpec.makeMeasureSpec(W, View.MeasureSpec.EXACTLY),
                          View.MeasureSpec.makeMeasureSpec(H, View.MeasureSpec.EXACTLY));
            mView.layout(0, 0, W, H);
            mView.loadDataWithBaseURL("http://n3ds.test/", HTML, "text/html", "utf-8", null);
            mHandler.postDelayed(new Runnable() { public void run() { poll(); } }, 500);
        }

        public void onNewPicture(WebView view, Picture picture) {
            mPictures++;
            sPictures++;
        }

        void poll() {
            mPolls++;
            int cw = mView.getContentWidth();
            int ch = mView.getContentHeight();
            if ((mPictures == 0 || cw == 0 || ch == 0) && mPolls < 120) {
                if (mPolls % 10 == 0) {
                    System.out.println("  waiting: pictures=" + mPictures + " content=" + cw + "x" + ch);
                }
                mHandler.postDelayed(new Runnable() { public void run() { poll(); } }, 500);
                return;
            }
            /* One more beat so a second layout pass can land. */
            mHandler.postDelayed(new Runnable() { public void run() { verify(); } }, 1500);
        }

        void verify() {
            int cw = mView.getContentWidth();
            int ch = mView.getContentHeight();
            float scale = mView.getScale();
            System.out.println("  pictures=" + mPictures + " content=" + cw + "x" + ch + " scale=" + scale);
            check(mName + ": a content picture was recorded", mPictures > 0);
            check(mName + ": content has a size", cw > 0 && ch > 0);

            Picture p = mView.capturePicture();
            Bitmap a = Bitmap.createBitmap(W, H, Bitmap.Config.ARGB_8888);
            a.eraseColor(SENTINEL);
            if (p != null) {
                new Canvas(a).drawPicture(p);
            }
            System.out.println("  capturePicture " + (p == null ? "null" : p.getWidth() + "x" + p.getHeight())
                    + ": " + histogram(a));
            /* capturePicture() is unscaled content coordinates. */
            check(mName + ": capturePicture red box at (60,40)", isRed(a.getPixel(60, 40)));
            check(mName + ": capturePicture green background at (300,40)", isGreen(a.getPixel(300, 40)));
            check(mName + ": capturePicture has dark text pixels", countDark(a, 0, 80, W, 160) > 30);

            /* What the screen gets: WebView.onDraw -> drawContentPicture. */
            Bitmap b = Bitmap.createBitmap(W, H, Bitmap.Config.ARGB_8888);
            b.eraseColor(SENTINEL);
            mView.draw(new Canvas(b));
            System.out.println("  WebView.draw: " + histogram(b));
            save(a, mName + "_capture.png");
            save(b, mName + "_draw.png");
            int red = count(b, 0xFFFF0000), green = count(b, 0xFF00FF00);
            check(mName + ": WebView.draw shows the red box", red > 200);
            check(mName + ": WebView.draw shows the green background", green > 2000);
            check(mName + ": WebView.draw shows dark text pixels", countDark(b, 0, 0, W, H) > 30);

            mView.destroy();
            mNext.run();
        }
    }

    /** Kept for a human to look at: the harness copies them out of the fakeroot. */
    static void save(Bitmap b, String name) {
        try {
            java.io.FileOutputStream o = new java.io.FileOutputStream("/data/webkitsmoke/" + name);
            b.compress(Bitmap.CompressFormat.PNG, 100, o);
            o.close();
        } catch (java.io.IOException e) {
            System.out.println("  (could not save " + name + ": " + e + ")");
        }
    }

    static boolean isRed(int c)   { return (c & 0xFFFFFF) == 0xFF0000; }
    static boolean isGreen(int c) { return (c & 0xFFFFFF) == 0x00FF00; }

    static int count(Bitmap b, int argb) {
        int n = 0;
        for (int y = 0; y < b.getHeight(); y++)
            for (int x = 0; x < b.getWidth(); x++)
                if (b.getPixel(x, y) == argb) n++;
        return n;
    }

    static int countDark(Bitmap b, int x0, int y0, int x1, int y1) {
        int n = 0;
        for (int y = y0; y < Math.min(y1, b.getHeight()); y++) {
            for (int x = x0; x < Math.min(x1, b.getWidth()); x++) {
                int c = b.getPixel(x, y);
                int r = (c >> 16) & 0xFF, g = (c >> 8) & 0xFF, bl = c & 0xFF;
                if (r < 80 && g < 80 && bl < 80) n++;
            }
        }
        return n;
    }

    static String histogram(Bitmap b) {
        return "red=" + count(b, 0xFFFF0000) + " green=" + count(b, 0xFF00FF00)
                + " white=" + count(b, 0xFFFFFFFF) + " untouched=" + count(b, SENTINEL)
                + " dark=" + countDark(b, 0, 0, b.getWidth(), b.getHeight());
    }

    /** PhoneLayoutInflater's lookup order, without android.policy.jar. */
    static final class TestInflater extends LayoutInflater {
        private static final String[] PREFIXES = { "android.widget.", "android.webkit." };
        TestInflater(Context c) { super(c); }
        TestInflater(LayoutInflater o, Context c) { super(o, c); }
        public LayoutInflater cloneInContext(Context c) { return new TestInflater(this, c); }
        protected View onCreateView(String name, AttributeSet attrs) throws ClassNotFoundException {
            for (int i = 0; i < PREFIXES.length; i++) {
                try {
                    View v = createView(name, PREFIXES[i], attrs);
                    if (v != null) return v;
                } catch (ClassNotFoundException e) {
                    /* try the next package */
                }
            }
            return super.onCreateView(name, attrs);
        }
    }

    /** WebSettings reads one counter from its preference file. */
    static final class MemoryPrefs implements SharedPreferences {
        final java.util.HashMap<String, Object> mMap = new java.util.HashMap<String, Object>();
        public java.util.Map<String, ?> getAll() { return mMap; }
        public String getString(String k, String d) { Object v = mMap.get(k); return v == null ? d : (String) v; }
        public int getInt(String k, int d) { Object v = mMap.get(k); return v == null ? d : (Integer) v; }
        public long getLong(String k, long d) { Object v = mMap.get(k); return v == null ? d : (Long) v; }
        public float getFloat(String k, float d) { Object v = mMap.get(k); return v == null ? d : (Float) v; }
        public boolean getBoolean(String k, boolean d) { Object v = mMap.get(k); return v == null ? d : (Boolean) v; }
        public boolean contains(String k) { return mMap.containsKey(k); }
        public void registerOnSharedPreferenceChangeListener(OnSharedPreferenceChangeListener l) { }
        public void unregisterOnSharedPreferenceChangeListener(OnSharedPreferenceChangeListener l) { }
        public Editor edit() {
            return new Editor() {
                public Editor putString(String k, String v) { mMap.put(k, v); return this; }
                public Editor putInt(String k, int v) { mMap.put(k, v); return this; }
                public Editor putLong(String k, long v) { mMap.put(k, v); return this; }
                public Editor putFloat(String k, float v) { mMap.put(k, v); return this; }
                public Editor putBoolean(String k, boolean v) { mMap.put(k, v); return this; }
                public Editor remove(String k) { mMap.remove(k); return this; }
                public Editor clear() { mMap.clear(); return this; }
                public boolean commit() { return true; }
            };
        }
    }

    /** Just enough Context for WebView, WebViewCore and BrowserFrame. */
    static final class TestContext extends Context {
        private static final String PKG = "android3ds.webkitsmoke";
        private static final File DATA = new File("/data/webkitsmoke");
        private final Resources mRes = Resources.getSystem();
        private Resources.Theme mTheme;
        private LayoutInflater mInflater;
        private ContentResolver mResolver;
        private android.app.ActivityManager mActivityManager;
        private SharedPreferences mPrefs;

        private static File dir(String name) {
            File f = new File(DATA, name);
            f.mkdirs();
            return f;
        }

        public AssetManager getAssets() { return mRes.getAssets(); }
        public Resources getResources() { return mRes; }
        public PackageManager getPackageManager() { return null; }
        public synchronized ContentResolver getContentResolver() {
            if (mResolver == null) {
                mResolver = new ContentResolver(this) {
                    protected IContentProvider acquireProvider(Context c, String name) { return null; }
                    public boolean releaseProvider(IContentProvider p) { return false; }
                };
            }
            return mResolver;
        }
        public Looper getMainLooper() { return Looper.getMainLooper(); }
        public Context getApplicationContext() { return this; }
        public void setTheme(int resid) { getTheme().applyStyle(resid, true); }
        public synchronized Resources.Theme getTheme() {
            if (mTheme == null) {
                mTheme = mRes.newTheme();
                mTheme.applyStyle(android.R.style.Theme, true);
            }
            return mTheme;
        }
        public ClassLoader getClassLoader() { return WebKitRenderSmoke.class.getClassLoader(); }
        public String getPackageName() { return PKG; }
        public ApplicationInfo getApplicationInfo() {
            ApplicationInfo ai = new ApplicationInfo();
            ai.packageName = PKG;
            ai.dataDir = DATA.getPath();
            ai.targetSdkVersion = 7;
            return ai;
        }
        public String getPackageResourcePath() { return "/system/framework/framework-res.apk"; }
        public String getPackageCodePath() { return "/system/app/WebKitRenderSmoke.apk"; }
        public synchronized SharedPreferences getSharedPreferences(String name, int mode) {
            if (mPrefs == null) mPrefs = new MemoryPrefs();
            return mPrefs;
        }
        public File getFilesDir() { return dir("files"); }
        public File getCacheDir() { return dir("cache"); }
        public File getDir(String name, int mode) { return dir("app_" + name); }
        public File getDatabasePath(String name) { return new File(dir("databases"), name); }
        public SQLiteDatabase openOrCreateDatabase(String name, int mode,
                SQLiteDatabase.CursorFactory factory) {
            return SQLiteDatabase.openOrCreateDatabase(getDatabasePath(name), factory);
        }
        public synchronized Object getSystemService(String name) {
            if (LAYOUT_INFLATER_SERVICE.equals(name)) {
                if (mInflater == null) mInflater = new TestInflater(this);
                return mInflater;
            }
            if (WINDOW_SERVICE.equals(name)) return WindowManagerImpl.getDefault();
            if (ACTIVITY_SERVICE.equals(name)) {
                /* BrowserFrame sizes WebCore's cache from getMemoryClass(),
                 * which only reads dalvik.vm.heapsize.  The constructor is
                 * package-private. */
                if (mActivityManager == null) {
                    try {
                        java.lang.reflect.Constructor<android.app.ActivityManager> c =
                                android.app.ActivityManager.class.getDeclaredConstructor(
                                        Context.class, Handler.class);
                        c.setAccessible(true);
                        mActivityManager = c.newInstance(this, new Handler(Looper.getMainLooper()));
                    } catch (Exception e) {
                        throw new RuntimeException(e);
                    }
                }
                return mActivityManager;
            }
            return null;
        }
        public Intent registerReceiver(BroadcastReceiver r, IntentFilter f) { return null; }
        public Intent registerReceiver(BroadcastReceiver r, IntentFilter f, String p, Handler h) { return null; }
        public int checkPermission(String permission, int pid, int uid) { return PackageManager.PERMISSION_GRANTED; }
        public int checkCallingPermission(String permission) { return PackageManager.PERMISSION_GRANTED; }
        public int checkCallingOrSelfPermission(String permission) { return PackageManager.PERMISSION_GRANTED; }

        /* Everything below: generated stubs (scratch gen_stub_context.py). */
        public java.io.File getSharedPrefsFile(java.lang.String a0) { return null; }
        public java.io.FileInputStream openFileInput(java.lang.String a0) throws java.io.FileNotFoundException { throw new java.io.FileNotFoundException(a0); }
        public java.io.FileOutputStream openFileOutput(java.lang.String a0, int a1) throws java.io.FileNotFoundException { return new java.io.FileOutputStream(new File(getFilesDir(), a0)); }
        public boolean deleteFile(java.lang.String a0) { return new File(getFilesDir(), a0).delete(); }
        public java.io.File getFileStreamPath(java.lang.String a0) { return new File(getFilesDir(), a0); }
        public java.lang.String[] fileList() { return getFilesDir().list(); }
        public boolean deleteDatabase(java.lang.String a0) { return getDatabasePath(a0).delete(); }
        public java.lang.String[] databaseList() { return dir("databases").list(); }
        public android.graphics.drawable.Drawable getWallpaper() { return null; }
        public android.graphics.drawable.Drawable peekWallpaper() { return null; }
        public int getWallpaperDesiredMinimumWidth() { return 0; }
        public int getWallpaperDesiredMinimumHeight() { return 0; }
        public void setWallpaper(android.graphics.Bitmap a0) throws java.io.IOException { }
        public void setWallpaper(java.io.InputStream a0) throws java.io.IOException { }
        public void clearWallpaper() throws java.io.IOException { }
        public void startActivity(android.content.Intent a0) { }
        public void startIntentSender(android.content.IntentSender a0, android.content.Intent a1, int a2, int a3, int a4) throws android.content.IntentSender.SendIntentException { }
        public void sendBroadcast(android.content.Intent a0) { }
        public void sendBroadcast(android.content.Intent a0, java.lang.String a1) { }
        public void sendOrderedBroadcast(android.content.Intent a0, java.lang.String a1) { }
        public void sendOrderedBroadcast(android.content.Intent a0, java.lang.String a1, android.content.BroadcastReceiver a2, android.os.Handler a3, int a4, java.lang.String a5, android.os.Bundle a6) { }
        public void sendStickyBroadcast(android.content.Intent a0) { }
        public void sendStickyOrderedBroadcast(android.content.Intent a0, android.content.BroadcastReceiver a1, android.os.Handler a2, int a3, java.lang.String a4, android.os.Bundle a5) { }
        public void removeStickyBroadcast(android.content.Intent a0) { }
        public void unregisterReceiver(android.content.BroadcastReceiver a0) { }
        public android.content.ComponentName startService(android.content.Intent a0) { return null; }
        public boolean stopService(android.content.Intent a0) { return false; }
        public boolean bindService(android.content.Intent a0, android.content.ServiceConnection a1, int a2) { return false; }
        public void unbindService(android.content.ServiceConnection a0) { }
        public boolean startInstrumentation(android.content.ComponentName a0, java.lang.String a1, android.os.Bundle a2) { return false; }
        public void enforcePermission(java.lang.String a0, int a1, int a2, java.lang.String a3) { }
        public void enforceCallingPermission(java.lang.String a0, java.lang.String a1) { }
        public void enforceCallingOrSelfPermission(java.lang.String a0, java.lang.String a1) { }
        public void grantUriPermission(java.lang.String a0, android.net.Uri a1, int a2) { }
        public void revokeUriPermission(android.net.Uri a0, int a1) { }
        public int checkUriPermission(android.net.Uri a0, int a1, int a2, int a3) { return 0; }
        public int checkCallingUriPermission(android.net.Uri a0, int a1) { return 0; }
        public int checkCallingOrSelfUriPermission(android.net.Uri a0, int a1) { return 0; }
        public int checkUriPermission(android.net.Uri a0, java.lang.String a1, java.lang.String a2, int a3, int a4, int a5) { return 0; }
        public void enforceUriPermission(android.net.Uri a0, int a1, int a2, int a3, java.lang.String a4) { }
        public void enforceCallingUriPermission(android.net.Uri a0, int a1, java.lang.String a2) { }
        public void enforceCallingOrSelfUriPermission(android.net.Uri a0, int a1, java.lang.String a2) { }
        public void enforceUriPermission(android.net.Uri a0, java.lang.String a1, java.lang.String a2, int a3, int a4, int a5, java.lang.String a6) { }
        public android.content.Context createPackageContext(java.lang.String a0, int a1) throws android.content.pm.PackageManager.NameNotFoundException { throw new android.content.pm.PackageManager.NameNotFoundException(a0); }
    }
}
