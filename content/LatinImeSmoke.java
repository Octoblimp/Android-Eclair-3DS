package android3ds;

import android.content.Context;
import android.content.res.AssetManager;
import dalvik.system.PathClassLoader;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Arrays;

/**
 * test_latinime_qemu.sh: drive LatinIME's dictionary natives the way the IME
 * process does on the device.
 *
 * #321 died on hardware in BinaryDictionary.<clinit> because
 * java.library.path was "" (nothing exports LD_LIBRARY_PATH), so
 * PathClassLoader.findLibrary() never looked in /system/lib, Native.c's
 * built-in table (N3DS_STATIC_JNI_LIBS) was never reached, and every static
 * check passed.  This loads the class through an APK PathClassLoader with
 * LD_LIBRARY_PATH unset, then opens the real res/raw/main.dict.
 */
public class LatinImeSmoke {
    private static final int MAX_WORD_LENGTH = 48;
    private static final int MAX_ALTERNATIVES = 16;
    private static final int MAX_WORDS = 16;

    private static void fail(String why) {
        System.out.println("FAIL: " + why);
        System.exit(1);
    }

    public static void main(String[] args) throws Exception {
        String lp = System.getProperty("java.library.path");
        System.out.println("java.library.path=[" + lp + "] (N3DS_JAVA_LIBRARY_PATH)");
        if (lp == null || lp.indexOf("/system/lib") < 0) {
            fail("java.library.path does not contain /system/lib");
        }

        PathClassLoader cl = new PathClassLoader("/system/app/LatinIME.apk",
                "/data/data/com.android.inputmethod.latin/lib",
                ClassLoader.getSystemClassLoader());
        Class<?> c = Class.forName("com.android.inputmethod.latin.BinaryDictionary", true, cl);
        Field avail = c.getDeclaredField("sNativeAvailable");
        avail.setAccessible(true);
        if (!avail.getBoolean(null)) {
            fail("System.loadLibrary(\"jni_latinime\") failed (sNativeAvailable == false)");
        }
        System.out.println("loadLibrary(jni_latinime): OK");

        // resId 0 skips loadDictionary(), which needs a real Context.
        Object dict = c.getConstructor(Context.class, int.class).newInstance(null, 0);

        AssetManager am = new AssetManager();
        if (am.addAssetPath("/system/app/LatinIME.apk") == 0) {
            fail("AssetManager.addAssetPath(LatinIME.apk) returned 0");
        }
        Method open = c.getDeclaredMethod("openNative",
                AssetManager.class, String.class, int.class, int.class);
        open.setAccessible(true);
        int nd = ((Integer) open.invoke(dict, am, "res/raw/main.dict", 2, 2)).intValue();
        if (nd == 0) fail("openNative(res/raw/main.dict) returned 0");
        System.out.println("openNative: OK");

        Method valid = c.getDeclaredMethod("isValidWordNative", int.class, char[].class, int.class);
        valid.setAccessible(true);
        String[] good = { "the", "keyboard", "android", "hello" };
        for (int i = 0; i < good.length; i++) {
            char[] w = good[i].toCharArray();
            if (!((Boolean) valid.invoke(dict, nd, w, w.length)).booleanValue()) {
                fail("isValidWord(\"" + good[i] + "\") == false");
            }
        }
        char[] junk = "qzxvkj".toCharArray();
        if (((Boolean) valid.invoke(dict, nd, junk, junk.length)).booleanValue()) {
            fail("isValidWord(\"qzxvkj\") == true");
        }
        System.out.println("isValidWord: OK");

        Method sugg = c.getDeclaredMethod("getSuggestionsNative", int.class, int[].class,
                int.class, char[].class, int[].class, int.class, int.class, int.class, int.class);
        sugg.setAccessible(true);
        int[] codes = new int[MAX_WORD_LENGTH * MAX_ALTERNATIVES];
        Arrays.fill(codes, -1);
        String typed = "hel";
        for (int i = 0; i < typed.length(); i++) codes[i * MAX_ALTERNATIVES] = typed.charAt(i);
        char[] out = new char[MAX_WORD_LENGTH * MAX_WORDS];
        int[] freq = new int[MAX_WORDS];
        int n = ((Integer) sugg.invoke(dict, nd, codes, typed.length(), out, freq,
                MAX_WORD_LENGTH, MAX_WORDS, MAX_ALTERNATIVES, -1)).intValue();
        StringBuilder sb = new StringBuilder();
        boolean sawHello = false;
        for (int j = 0; j < n; j++) {
            int start = j * MAX_WORD_LENGTH;
            int len = 0;
            while (out[start + len] != 0) len++;
            String w = new String(out, start, len);
            if (w.equals("hello")) sawHello = true;
            sb.append(w).append('(').append(freq[j]).append(") ");
        }
        System.out.println("suggestions for \"" + typed + "\": " + n + ": " + sb);
        if (n < 3 || !sawHello) fail("getSuggestions(\"hel\") did not offer \"hello\"");

        Method close = c.getDeclaredMethod("closeNative", int.class);
        close.setAccessible(true);
        close.invoke(dict, nd);
        System.out.println("PASS: latinime native dictionary");
    }
}
