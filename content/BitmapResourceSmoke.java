package android3ds;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.graphics.RectF;

public final class BitmapResourceSmoke {
    public static void main(String[] args) {
        if (args.length != 1) {
            throw new IllegalArgumentException("expected PNG path");
        }
        Bitmap source = BitmapFactory.decodeFile(args[0]);
        if (source == null) {
            throw new AssertionError("BitmapFactory returned null");
        }
        int width = source.getWidth();
        int height = source.getHeight();
        if (width <= 0 || height <= 0) {
            throw new AssertionError("decoded dimensions " + width + "x" + height);
        }
        int scaledWidth = Math.max(1, (width * 2) / 3);
        int scaledHeight = Math.max(1, (height * 2) / 3);
        Bitmap allocation = Bitmap.createBitmap(
                scaledWidth, scaledHeight, Bitmap.Config.ARGB_8888);
        if (allocation.getWidth() != scaledWidth
                || allocation.getHeight() != scaledHeight) {
            throw new AssertionError("direct bitmap allocation dimensions");
        }
        float scaleX = scaledWidth / (float) width;
        float scaleY = scaledHeight / (float) height;
        if (Math.round(width * scaleX) != scaledWidth
                || Math.round(height * scaleY) != scaledHeight) {
            throw new AssertionError("float/double Math JNI ABI");
        }
        Matrix matrix = new Matrix();
        matrix.setScale(scaleX, scaleY);
        float[] matrixValues = new float[9];
        matrix.getValues(matrixValues);
        if (Math.abs(matrixValues[0] - scaleX) > 0.0001f
                || Math.abs(matrixValues[4] - scaleY) > 0.0001f) {
            throw new AssertionError("Matrix scalar JNI ABI");
        }
        Matrix rotation = new Matrix();
        rotation.postRotate(180.0f);
        rotation.getValues(matrixValues);
        if (Math.abs(matrixValues[0] + 1.0f) > 0.0001f
                || Math.abs(matrixValues[1]) > 0.0001f
                || Math.abs(matrixValues[3]) > 0.0001f
                || Math.abs(matrixValues[4] + 1.0f) > 0.0001f) {
            throw new AssertionError("Matrix rotation/sincosf ABI");
        }
        RectF mapped = new RectF(0, 0, width, height);
        matrix.mapRect(mapped);
        if (Math.round(mapped.left) != 0 || Math.round(mapped.top) != 0
                || Math.round(mapped.right) != scaledWidth
                || Math.round(mapped.bottom) != scaledHeight) {
            throw new AssertionError("mapped rectangle dimensions");
        }
        Bitmap scaled = Bitmap.createScaledBitmap(
                source, scaledWidth, scaledHeight, true);
        if (scaled.getWidth() != scaledWidth || scaled.getHeight() != scaledHeight) {
            throw new AssertionError("scaled bitmap dimensions are incorrect");
        }
        System.out.println("PASS: bitmap decode/width/height/scale/rotation "
                + width + "x" + height + " -> " + scaledWidth + "x" + scaledHeight);
    }
}
