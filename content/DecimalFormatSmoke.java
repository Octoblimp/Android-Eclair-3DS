package android3ds;

import java.text.DecimalFormat;
import java.text.DecimalFormatSymbols;
import java.util.Locale;

/** Exercises the scalar-double plus object-argument ICU JNI boundary. */
public final class DecimalFormatSmoke {
    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }

    public static void main(String[] args) {
        String stats = String.format(
                Locale.US,
                "FPS: %.1f | Frame: %.1f ms | 320x240",
                new Object[] { Float.valueOf(12.25f), Float.valueOf(0.5f) });
        require(stats != null, "String.format returned null");
        require(stats.startsWith("FPS: "), "bad String.format prefix: " + stats);
        require(stats.indexOf(" | Frame: ") > 0, "bad String.format body: " + stats);

        DecimalFormat direct = new DecimalFormat(
                "0.000", new DecimalFormatSymbols(Locale.US));
        String number = direct.format(1234.5d);
        require(number != null && number.length() > 0,
                "DecimalFormat.format returned no text");

        System.out.println("stats=" + stats);
        System.out.println("direct=" + number);
        System.out.println("PASS: DecimalFormat mixed double/object JNI ABI");
    }
}
