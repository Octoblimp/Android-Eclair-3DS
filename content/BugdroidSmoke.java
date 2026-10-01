package android3ds;

import android.graphics.Bitmap;
import android.graphics.Canvas;

import java.io.FileOutputStream;
import java.io.IOException;

import com.android.settings.PlatLogoActivity;

/**
 * #328: the Firmware-version easter egg's drawing code, run for real under
 * qemu-arm. Renders the bugdroid at the bottom screen's size with
 * PlatLogoActivity.drawFrame() and checks the pixels: green body, black
 * eyes and background, a blink that closes the eyes, and a hop that lifts
 * the robot and swings its arms out past its sides.
 */
public final class BugdroidSmoke {
    private static final int W = 320;
    private static final int H = 240;

    public static void main(String[] args) {
        final float scale = PlatLogoActivity.scaleFor(W, H);
        final float left = (W - PlatLogoActivity.GRID_W * scale) / 2f;
        final float top = (H - PlatLogoActivity.GRID_H * scale) / 2f;
        final float hop = PlatLogoActivity.HOP_HEIGHT;

        // 800 ms in: the bob is at zero and the eyes are open.
        int[] rest = render(800L, -1L);
        // 3200 ms in: the bob is at zero again and the eyes are shut.
        int[] blink = render(3200L, -1L);
        // Half way through a hop: as high as it goes, arms fully up.
        int[] air = render(800L, PlatLogoActivity.HOP_MS / 2);
        // Just after landing: back to the resting pose.
        int[] landed = render(800L, PlatLogoActivity.HOP_MS + 10L);

        expect(rest, 0, 0, PlatLogoActivity.BACKGROUND, "rest corner");
        expect(rest, W - 1, H - 1, PlatLogoActivity.BACKGROUND, "rest far corner");
        expect(rest, gx(left, scale, 80f), gy(top, scale, hop, 0f, 120f),
                PlatLogoActivity.GREEN, "rest body");
        expect(rest, gx(left, scale, 80f), gy(top, scale, hop, 0f, 40f),
                PlatLogoActivity.GREEN, "rest head");
        expect(rest, gx(left, scale, 58f), gy(top, scale, hop, 0f, 47f),
                PlatLogoActivity.BACKGROUND, "rest left eye");
        expect(rest, gx(left, scale, 102f), gy(top, scale, hop, 0f, 47f),
                PlatLogoActivity.BACKGROUND, "rest right eye");
        expect(rest, gx(left, scale, 15f), gy(top, scale, hop, 0f, 120f),
                PlatLogoActivity.GREEN, "rest left arm");
        expect(rest, gx(left, scale, 61f), gy(top, scale, hop, 0f, 185f),
                PlatLogoActivity.GREEN, "rest left leg");

        expect(blink, gx(left, scale, 58f), gy(top, scale, hop, 0f, 47f),
                PlatLogoActivity.GREEN, "blink left eye");
        expect(blink, gx(left, scale, 80f), gy(top, scale, hop, 0f, 120f),
                PlatLogoActivity.GREEN, "blink body");

        expect(air, gx(left, scale, 80f), gy(top, scale, hop, hop, 120f),
                PlatLogoActivity.GREEN, "hop body");
        // Where the bottom of the body sits at rest is empty floor mid-hop.
        expect(rest, gx(left, scale, 80f), gy(top, scale, hop, 0f, 160f),
                PlatLogoActivity.GREEN, "rest lower body");
        expect(air, gx(left, scale, 80f), gy(top, scale, hop, 0f, 160f),
                PlatLogoActivity.BACKGROUND, "hop gap under the robot");

        final int restTop = topGreenRow(rest);
        final int airTop = topGreenRow(air);
        final int rise = restTop - airTop;
        if (rise < (int) (0.8f * hop * scale)) {
            throw new AssertionError("hop only rose " + rise + " px (rest top " + restTop
                    + ", air top " + airTop + ")");
        }
        final int sideX = (int) left;
        if (countGreen(rest, 0, sideX) != 0) {
            throw new AssertionError("green left of the robot at rest");
        }
        final int armsOut = countGreen(air, 0, sideX);
        if (armsOut == 0) {
            throw new AssertionError("arms did not swing out during the hop");
        }
        int changed = 0;
        for (int i = 0; i < rest.length; i++) {
            if (rest[i] != landed[i]) changed++;
        }
        if (changed != 0) {
            throw new AssertionError(changed + " pixels differ between rest and landed");
        }
        if (args.length > 0) {
            save(rest, args[0] + "/bugdroid_rest.png");
            save(blink, args[0] + "/bugdroid_blink.png");
            save(air, args[0] + "/bugdroid_hop.png");
        }
        final int green = countGreen(rest, 0, W);
        System.out.println("PASS: bugdroid " + W + "x" + H + " scale " + scale + ", "
                + green + " green px at rest, blink closes the eyes, hop rises "
                + rise + " px with " + armsOut + " arm px out past its sides, lands clean");
    }

    /** Writes one frame as a PNG, for looking at by eye. */
    private static void save(int[] px, String path) {
        Bitmap bitmap = Bitmap.createBitmap(px, W, H, Bitmap.Config.ARGB_8888);
        FileOutputStream out = null;
        try {
            out = new FileOutputStream(path);
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, out);
        } catch (IOException e) {
            throw new AssertionError("could not write " + path + ": " + e);
        } finally {
            if (out != null) {
                try {
                    out.close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private static int gx(float left, float scale, float x) {
        return (int) (left + x * scale);
    }

    private static int gy(float top, float scale, float hop, float lift, float y) {
        return (int) (top + (y + hop - lift) * scale);
    }

    private static void expect(int[] px, int x, int y, int want, String what) {
        final int got = px[y * W + x];
        if ((got & 0xffffff) != (want & 0xffffff)) {
            throw new AssertionError(what + " at " + x + "," + y + ": got "
                    + Integer.toHexString(got) + " want " + Integer.toHexString(want));
        }
    }

    private static int topGreenRow(int[] px) {
        for (int y = 0; y < H; y++) {
            for (int x = 0; x < W; x++) {
                if ((px[y * W + x] & 0xffffff) == (PlatLogoActivity.GREEN & 0xffffff)) {
                    return y;
                }
            }
        }
        throw new AssertionError("no green pixels at all");
    }

    private static int countGreen(int[] px, int x0, int x1) {
        int n = 0;
        for (int y = 0; y < H; y++) {
            for (int x = x0; x < x1; x++) {
                if ((px[y * W + x] & 0xffffff) == (PlatLogoActivity.GREEN & 0xffffff)) {
                    n++;
                }
            }
        }
        return n;
    }

    private static int[] render(long elapsedMs, long sinceTapMs) {
        Bitmap out = Bitmap.createBitmap(W, H, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(out);
        PlatLogoActivity.drawFrame(canvas, W, H, elapsedMs, sinceTapMs,
                new PlatLogoActivity.Paints());
        int[] pixels = new int[W * H];
        out.getPixels(pixels, 0, W, 0, 0, W, H);
        return pixels;
    }
}
