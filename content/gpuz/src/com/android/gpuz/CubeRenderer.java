package com.android.gpuz;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.nio.ShortBuffer;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;
import android.opengl.GLSurfaceView;

public class CubeRenderer implements GLSurfaceView.Renderer {
    private FloatBuffer mVertexBuffer;
    private FloatBuffer mColorBuffer;
    private FloatBuffer mNormalBuffer;
    private ShortBuffer mIndexBuffer;

    private float mAngle = 0.0f;
    private boolean mLighting = true;
    private boolean mTextured = false;
    private int mTextureId = -1;

    private long mLastTime = 0;
    private int mFrameCount = 0;
    private float mFps = 0.0f;
    private float mFrameTimeMs = 0.0f;

    private final float[] mVertices = {
        // Front
        -1.0f, -1.0f,  1.0f,
         1.0f, -1.0f,  1.0f,
         1.0f,  1.0f,  1.0f,
        -1.0f,  1.0f,  1.0f,
        // Back
        -1.0f, -1.0f, -1.0f,
        -1.0f,  1.0f, -1.0f,
         1.0f,  1.0f, -1.0f,
         1.0f, -1.0f, -1.0f,
        // Top
        -1.0f,  1.0f, -1.0f,
        -1.0f,  1.0f,  1.0f,
         1.0f,  1.0f,  1.0f,
         1.0f,  1.0f, -1.0f,
        // Bottom
        -1.0f, -1.0f, -1.0f,
         1.0f, -1.0f, -1.0f,
         1.0f, -1.0f,  1.0f,
        -1.0f, -1.0f,  1.0f,
        // Right
         1.0f, -1.0f, -1.0f,
         1.0f,  1.0f, -1.0f,
         1.0f,  1.0f,  1.0f,
         1.0f, -1.0f,  1.0f,
        // Left
        -1.0f, -1.0f, -1.0f,
        -1.0f, -1.0f,  1.0f,
        -1.0f,  1.0f,  1.0f,
        -1.0f,  1.0f, -1.0f,
    };

    private final float[] mColors = {
        // Red
        1.0f, 0.2f, 0.2f, 1.0f,  1.0f, 0.2f, 0.2f, 1.0f,
        1.0f, 0.2f, 0.2f, 1.0f,  1.0f, 0.2f, 0.2f, 1.0f,
        // Green
        0.2f, 1.0f, 0.2f, 1.0f,  0.2f, 1.0f, 0.2f, 1.0f,
        0.2f, 1.0f, 0.2f, 1.0f,  0.2f, 1.0f, 0.2f, 1.0f,
        // Blue
        0.2f, 0.4f, 1.0f, 1.0f,  0.2f, 0.4f, 1.0f, 1.0f,
        0.2f, 0.4f, 1.0f, 1.0f,  0.2f, 0.4f, 1.0f, 1.0f,
        // Yellow
        1.0f, 1.0f, 0.2f, 1.0f,  1.0f, 1.0f, 0.2f, 1.0f,
        1.0f, 1.0f, 0.2f, 1.0f,  1.0f, 1.0f, 0.2f, 1.0f,
        // Cyan
        0.2f, 1.0f, 1.0f, 1.0f,  0.2f, 1.0f, 1.0f, 1.0f,
        0.2f, 1.0f, 1.0f, 1.0f,  0.2f, 1.0f, 1.0f, 1.0f,
        // Magenta
        1.0f, 0.2f, 1.0f, 1.0f,  1.0f, 0.2f, 1.0f, 1.0f,
        1.0f, 0.2f, 1.0f, 1.0f,  1.0f, 0.2f, 1.0f, 1.0f,
    };

    private final float[] mNormals = {
         0,  0,  1,   0,  0,  1,   0,  0,  1,   0,  0,  1, // Front
         0,  0, -1,   0,  0, -1,   0,  0, -1,   0,  0, -1, // Back
         0,  1,  0,   0,  1,  0,   0,  1,  0,   0,  1,  0, // Top
         0, -1,  0,   0, -1,  0,   0, -1,  0,   0, -1,  0, // Bottom
         1,  0,  0,   1,  0,  0,   1,  0,  0,   1,  0,  0, // Right
        -1,  0,  0,  -1,  0,  0,  -1,  0,  0,  -1,  0,  0  // Left
    };

    private final short[] mIndices = {
         0,  1,  2,   0,  2,  3, // Front
         4,  5,  6,   4,  6,  7, // Back
         8,  9, 10,   8, 10, 11, // Top
        12, 13, 14,  12, 14, 15, // Bottom
        16, 17, 18,  16, 18, 19, // Right
        20, 21, 22,  20, 22, 23  // Left
    };

    public CubeRenderer(boolean lighting, boolean textured) {
        mLighting = lighting;
        mTextured = textured;

        ByteBuffer vbb = ByteBuffer.allocateDirect(mVertices.length * 4);
        vbb.order(ByteOrder.nativeOrder());
        mVertexBuffer = vbb.asFloatBuffer();
        mVertexBuffer.put(mVertices);
        mVertexBuffer.position(0);

        ByteBuffer cbb = ByteBuffer.allocateDirect(mColors.length * 4);
        cbb.order(ByteOrder.nativeOrder());
        mColorBuffer = cbb.asFloatBuffer();
        mColorBuffer.put(mColors);
        mColorBuffer.position(0);

        ByteBuffer nbb = ByteBuffer.allocateDirect(mNormals.length * 4);
        nbb.order(ByteOrder.nativeOrder());
        mNormalBuffer = nbb.asFloatBuffer();
        mNormalBuffer.put(mNormals);
        mNormalBuffer.position(0);

        ByteBuffer ibb = ByteBuffer.allocateDirect(mIndices.length * 2);
        ibb.order(ByteOrder.nativeOrder());
        mIndexBuffer = ibb.asShortBuffer();
        mIndexBuffer.put(mIndices);
        mIndexBuffer.position(0);
    }

    public float getFps() { return mFps; }
    public float getFrameTimeMs() { return mFrameTimeMs; }

    @Override
    public void onSurfaceCreated(GL10 gl, EGLConfig config) {
        gl.glDisable(GL10.GL_DITHER);
        gl.glHint(GL10.GL_PERSPECTIVE_CORRECTION_HINT, GL10.GL_FASTEST);
        gl.glClearColor(0.05f, 0.07f, 0.10f, 1.0f);
        gl.glEnable(GL10.GL_CULL_FACE);
        gl.glShadeModel(GL10.GL_SMOOTH);
        gl.glEnable(GL10.GL_DEPTH_TEST);

        if (mLighting) {
            gl.glEnable(GL10.GL_LIGHTING);
            gl.glEnable(GL10.GL_LIGHT0);
            float[] lightPos = { 2.0f, 3.0f, 4.0f, 1.0f };
            float[] lightDiffuse = { 1.0f, 0.95f, 0.9f, 1.0f };
            float[] lightAmbient = { 0.25f, 0.25f, 0.3f, 1.0f };
            gl.glLightfv(GL10.GL_LIGHT0, GL10.GL_POSITION, lightPos, 0);
            gl.glLightfv(GL10.GL_LIGHT0, GL10.GL_DIFFUSE, lightDiffuse, 0);
            gl.glLightfv(GL10.GL_LIGHT0, GL10.GL_AMBIENT, lightAmbient, 0);
            gl.glEnable(GL10.GL_COLOR_MATERIAL);
        } else {
            gl.glDisable(GL10.GL_LIGHTING);
        }

        mLastTime = System.currentTimeMillis();
        mFrameCount = 0;
    }

    @Override
    public void onSurfaceChanged(GL10 gl, int width, int height) {
        if (width <= 0) width = 320;
        if (height <= 0) height = 240;
        gl.glViewport(0, 0, width, height);

        float ratio = (float) width / height;
        gl.glMatrixMode(GL10.GL_PROJECTION);
        gl.glLoadIdentity();
        gl.glFrustumf(-ratio * 0.7f, ratio * 0.7f, -0.7f, 0.7f, 1.0f, 20.0f);
    }

    @Override
    public void onDrawFrame(GL10 gl) {
        long start = System.currentTimeMillis();

        gl.glClear(GL10.GL_COLOR_BUFFER_BIT | GL10.GL_DEPTH_BUFFER_BIT);

        gl.glMatrixMode(GL10.GL_MODELVIEW);
        gl.glLoadIdentity();
        gl.glTranslatef(0.0f, 0.0f, -4.5f);
        gl.glRotatef(mAngle, 1.0f, 1.0f, 0.5f);

        gl.glEnableClientState(GL10.GL_VERTEX_ARRAY);
        gl.glVertexPointer(3, GL10.GL_FLOAT, 0, mVertexBuffer);

        gl.glEnableClientState(GL10.GL_COLOR_ARRAY);
        gl.glColorPointer(4, GL10.GL_FLOAT, 0, mColorBuffer);

        if (mLighting) {
            gl.glEnableClientState(GL10.GL_NORMAL_ARRAY);
            gl.glNormalPointer(GL10.GL_FLOAT, 0, mNormalBuffer);
        }

        gl.glDrawElements(GL10.GL_TRIANGLES, 36, GL10.GL_UNSIGNED_SHORT, mIndexBuffer);

        mAngle += 1.8f;
        if (mAngle >= 360.0f) mAngle -= 360.0f;

        long end = System.currentTimeMillis();
        mFrameTimeMs = (float)(end - start);
        mFrameCount++;
        if (end - mLastTime >= 1000) {
            mFps = (float)mFrameCount * 1000.0f / (float)(end - mLastTime);
            mFrameCount = 0;
            mLastTime = end;
        }
    }
}
