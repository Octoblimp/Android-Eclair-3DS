package com.android.gpuz;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.util.Random;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;
import android.opengl.GLSurfaceView;

public class ParticleRenderer implements GLSurfaceView.Renderer {
    private static final int NUM_PARTICLES = 120;

    private FloatBuffer mVertexBuffer;
    private FloatBuffer mColorBuffer;

    private float[] mCoords = new float[NUM_PARTICLES * 3];
    private float[] mVelocities = new float[NUM_PARTICLES * 3];
    private float[] mColors = new float[NUM_PARTICLES * 4];

    private long mLastTime = 0;
    private int mFrameCount = 0;
    private float mFps = 0.0f;
    private float mFrameTimeMs = 0.0f;
    private Random mRand = new Random(42);

    public ParticleRenderer() {
        for (int i = 0; i < NUM_PARTICLES; i++) {
            resetParticle(i);
        }

        ByteBuffer vbb = ByteBuffer.allocateDirect(mCoords.length * 4);
        vbb.order(ByteOrder.nativeOrder());
        mVertexBuffer = vbb.asFloatBuffer();

        ByteBuffer cbb = ByteBuffer.allocateDirect(mColors.length * 4);
        cbb.order(ByteOrder.nativeOrder());
        mColorBuffer = cbb.asFloatBuffer();
    }

    private void resetParticle(int i) {
        int vIdx = i * 3;
        int cIdx = i * 4;

        mCoords[vIdx]     = (mRand.nextFloat() - 0.5f) * 0.2f;
        mCoords[vIdx + 1] = -1.2f + (mRand.nextFloat() - 0.5f) * 0.2f;
        mCoords[vIdx + 2] = -3.0f + (mRand.nextFloat() - 0.5f) * 1.5f;

        mVelocities[vIdx]     = (mRand.nextFloat() - 0.5f) * 0.035f;
        mVelocities[vIdx + 1] = 0.03f + mRand.nextFloat() * 0.045f;
        mVelocities[vIdx + 2] = (mRand.nextFloat() - 0.5f) * 0.02f;

        mColors[cIdx]     = 0.2f + mRand.nextFloat() * 0.8f;
        mColors[cIdx + 1] = 0.6f + mRand.nextFloat() * 0.4f;
        mColors[cIdx + 2] = 1.0f;
        mColors[cIdx + 3] = 0.7f + mRand.nextFloat() * 0.3f;
    }

    public float getFps() { return mFps; }
    public float getFrameTimeMs() { return mFrameTimeMs; }

    @Override
    public void onSurfaceCreated(GL10 gl, EGLConfig config) {
        gl.glDisable(GL10.GL_DITHER);
        gl.glClearColor(0.02f, 0.04f, 0.08f, 1.0f);
        gl.glDisable(GL10.GL_DEPTH_TEST);
        gl.glEnable(GL10.GL_BLEND);
        gl.glBlendFunc(GL10.GL_SRC_ALPHA, GL10.GL_ONE);
        gl.glPointSize(4.0f);

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
        gl.glFrustumf(-ratio * 0.5f, ratio * 0.5f, -0.5f, 0.5f, 1.0f, 10.0f);
    }

    @Override
    public void onDrawFrame(GL10 gl) {
        long start = System.currentTimeMillis();

        gl.glClear(GL10.GL_COLOR_BUFFER_BIT);

        gl.glMatrixMode(GL10.GL_MODELVIEW);
        gl.glLoadIdentity();

        for (int i = 0; i < NUM_PARTICLES; i++) {
            int vIdx = i * 3;
            mCoords[vIdx]     += mVelocities[vIdx];
            mCoords[vIdx + 1] += mVelocities[vIdx + 1];
            mCoords[vIdx + 2] += mVelocities[vIdx + 2];

            if (mCoords[vIdx + 1] > 1.4f) {
                resetParticle(i);
            }
        }

        mVertexBuffer.position(0);
        mVertexBuffer.put(mCoords);
        mVertexBuffer.position(0);

        mColorBuffer.position(0);
        mColorBuffer.put(mColors);
        mColorBuffer.position(0);

        gl.glEnableClientState(GL10.GL_VERTEX_ARRAY);
        gl.glVertexPointer(3, GL10.GL_FLOAT, 0, mVertexBuffer);

        gl.glEnableClientState(GL10.GL_COLOR_ARRAY);
        gl.glColorPointer(4, GL10.GL_FLOAT, 0, mColorBuffer);

        gl.glDrawArrays(GL10.GL_POINTS, 0, NUM_PARTICLES);

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
