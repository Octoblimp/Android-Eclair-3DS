package android3ds;

import android.view.KeyCharacterMap;
import android.view.KeyEvent;

public final class KeyCharacterMapSmoke {
    public static void main(String[] args) {
        KeyCharacterMap map = KeyCharacterMap.load(0);
        int lower = map.get(KeyEvent.KEYCODE_X, 0);
        int upper = map.get(KeyEvent.KEYCODE_X, KeyEvent.META_SHIFT_ON);
        if (lower != 'x' || upper != 'X') {
            throw new AssertionError("unexpected X mapping: " + lower + "/" + upper);
        }
        System.out.println("PASS: KeyCharacterMap JNI/native map x/X");
    }
}
