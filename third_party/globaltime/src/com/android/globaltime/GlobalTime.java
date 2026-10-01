/*
 * Copyright (C) 2007 The Android Open Source Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.android.globaltime;

import java.io.ByteArrayInputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
/* N3DS_GLOBALTIME_FIXED_POINT_PROXY imports */
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
/* N3DS_GLOBALTIME_READBACK_IMPORTS */
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

import javax.microedition.khronos.egl.*;
import javax.microedition.khronos.opengles.*;

import android.app.Activity;
import android.content.Context;
import android.content.res.AssetManager;
import android.graphics.Canvas;
/* N3DS_GLOBALTIME_PIXEL_FORMAT_IMPORT */
import android.graphics.PixelFormat;
import android.opengl.Object3D;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Message;
import android.os.MessageQueue;
import android.util.Log;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.animation.AccelerateDecelerateInterpolator;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.Interpolator;

/**
 * The main View of the GlobalTime Activity.
 */
class GTView extends SurfaceView implements SurfaceHolder.Callback {

    /* N3DS_GLOBALTIME_LOG_TAG */
    private static final String TAG = "GlobalTime";

    /**
     * A TimeZone object used to compute the current UTC time.
     */
    private static final TimeZone UTC_TIME_ZONE = TimeZone.getTimeZone("utc");

    /**
     * The Sun's color is close to that of a 5780K blackbody.
     */
    private static final float[] SUNLIGHT_COLOR = {
        1.0f, 0.9375f, 0.91015625f, 1.0f
    };

    /**
     * The inclination of the earth relative to the plane of the ecliptic
     * is 23.45 degrees.
     */
    private static final float EARTH_INCLINATION = 23.45f * Shape.PI / 180.0f;

    /** Seconds in a day */
    private static final int SECONDS_PER_DAY = 24 * 60 * 60;

    /** Flag for the depth test */
    private static final boolean PERFORM_DEPTH_TEST= false;

    /** Use raw time zone offsets, disregarding "summer time."  If false,
     * current offsets will be used, which requires a much longer startup time
     * in order to sort the city database.
     */
    private static final boolean USE_RAW_OFFSETS = true;

    /**
     * The earth's atmosphere.
     */
    private static final Annulus ATMOSPHERE =
        new Annulus(0.0f, 0.0f, 1.75f, 0.9f, 1.08f, 0.4f, 0.4f, 0.8f, 0.0f,
            0.0f, 0.0f, 0.0f, 1.0f, 50);

    /**
     * The tesselation of the earth by latitude.
     */
    private static final int SPHERE_LATITUDES = 25;

    /**
     * The tesselation of the earth by longitude.
     */
    private static int SPHERE_LONGITUDES = 25;

    /**
     * A flattened version of the earth.  The normals are computed identically
     * to those of the round earth, allowing the day/night lighting to be
     * applied to the flattened surface.
     */
    private static Sphere worldFlat = new LatLongSphere(0.0f, 0.0f, 0.0f, 1.0f,
        SPHERE_LATITUDES, SPHERE_LONGITUDES,
        0.0f, 360.0f, true, true, false, true);

    /* N3DS_GLOBALTIME_GEOMETRY_FALLBACK: a self-contained colored globe is
     * available when the asset/texture draw submits no readable pixels. It
     * remains inside OpenGL/libagl and therefore exercises the real window,
     * swap, gralloc, and built-in copybit path. */
    private static final Sphere FALLBACK_WORLD = new LatLongSphere(
        0.0f, 0.0f, 0.0f, 1.0f, SPHERE_LATITUDES, SPHERE_LONGITUDES,
        0.0f, 360.0f, false, false, true, false);

    /**
     * The earth.
     */
    private Object3D mWorld;

    /**
     * Geometry of the city lights
     */
    private PointCloud mLights;

    /**
     * True if the activiy has been initialized.
     */
    boolean mInitialized = false;

    /**
     * True if we're in alphabetic entry mode.
     */
    private boolean mAlphaKeySet = false;

    private EGLContext mEGLContext;
    private EGLSurface mEGLSurface;
    private EGLDisplay mEGLDisplay;
    private EGLConfig  mEGLConfig;
    GLView  mGLView;

    // Rotation and tilt of the Earth
    private float mRotAngle = 0.0f;
    private float mTiltAngle = 0.0f;

    // Rotational velocity of the orbiting viewer
    private float mRotVelocity = 1.0f;

    // Rotation of the flat view
    private float mWrapX =  0.0f;
    private float  mWrapVelocity =  0.0f;
    private float mWrapVelocityFactor =  0.01f;

    // Toggle switches
    private boolean mDisplayAtmosphere = true;
    private boolean mDisplayClock = false;
    private boolean mClockShowing = false;
    private boolean mDisplayLights = false;
    private boolean mDisplayWorld = true;
    private boolean mDisplayWorldFlat = false;
    private boolean mSmoothShading = true;

    // City search string
    private String mCityName = "";

    // List of all cities
    private List<City> mClockCities;

    // List of cities matching a user-supplied prefix
    private List<City> mCityNameMatches = new ArrayList<City>();

    private List<City> mCities;

    // Start time for clock fade animation
    private long mClockFadeTime;

    // Interpolator for clock fade animation
    private Interpolator mClockSizeInterpolator =
        new DecelerateInterpolator(1.0f);

    // Index of current clock
    private int mCityIndex;

    // Current clock
    private Clock mClock;

    // City-to-city flight animation parameters
    private boolean mFlyToCity = false;
    private long mCityFlyStartTime;
    private float mCityFlightTime;
    private float mRotAngleStart, mRotAngleDest;
    private float mTiltAngleStart, mTiltAngleDest;

    // Interpolator for flight motion animation
    private Interpolator mFlyToCityInterpolator =
        new AccelerateDecelerateInterpolator();

    private static int sNumLights;
    private static int[] sLightCoords;

    //     static Map<Float,int[]> cityCoords = new HashMap<Float,int[]>();

    // Arrays for GL calls
    private float[] mClipPlaneEquation = new float[4];
    private float[] mLightDir = new float[4];

    // Calendar for computing the Sun's position
    Calendar mSunCal = Calendar.getInstance(UTC_TIME_ZONE);

    // Triangles drawn per frame
    private int mNumTriangles;
    /* N3DS_GLOBALTIME_FRAME_STATE */
    private boolean mFirstFrameLogged;
    /* N3DS_GLOBALTIME_READBACK_STATE */
    private boolean mFirstFrameReadbackLogged;
    /* N3DS_GLOBALTIME_FALLBACK_STATE */
    private boolean mUseFallbackWorld;
    /* N3DS_GLOBALTIME_GL_ERROR: first GL error seen by the per-stage
     * first-frame checks, so the readback line still reports it after the
     * stage check has consumed it with glGetError(). */
    private int mFirstFrameGlError;
    /* N3DS_GLOBALTIME_FIXED_POINT_PROXY: the GL object handed to
     * android.opengl.Object3D, and the context GL it wraps. */
    private GL10 mWorldGL;
    private GL10 mWorldGLSource;

    private long startTime;

    private static final int MOTION_NONE = 0;
    private static final int MOTION_X = 1;
    private static final int MOTION_Y = 2;

    private static final int MIN_MANHATTAN_DISTANCE = 20;
    private static final float ROTATION_FACTOR = 1.0f / 30.0f;
    private static final float TILT_FACTOR = 0.35f;

    // Touchscreen support
    private float mMotionStartX;
    private float mMotionStartY;
    private float mMotionStartRotVelocity;
    private float mMotionStartTiltAngle;
    private int mMotionDirection;
    
    private boolean mPaused = true;
    private boolean mHaveSurface = false;
    private boolean mStartAnimating = false;
    
    public void surfaceCreated(SurfaceHolder holder) {
        mHaveSurface = true;
        startEGL();
    }

    public void surfaceDestroyed(SurfaceHolder holder) {
        mHaveSurface = false;
        stopEGL();
    }

    public void surfaceChanged(SurfaceHolder holder, int format, int w, int h) {
        /* N3DS_SURFACE_CHANGED_ASPECT: never leave the projection at its
         * constructor-time zero aspect once the real 320x240 surface exists. */
        if (w > 0 && h > 0 && mGLView != null) {
            mGLView.setAspectRatio((float) w / h);
        }
    }

    /**
     * Set up the view.
     *
     * @param context the Context
     * @param am an AssetManager to retrieve the city database from
     */
    public GTView(Context context) {
        super(context);

        getHolder().addCallback(this);
        /* N3DS_SURFACE_TYPE_NORMAL: Eclair's GPU SurfaceHolder path expects a
         * hardware gralloc buffer queue. Android3DS still presents libagl
         * through the proven normal framebuffer surface. */
        getHolder().setType(SurfaceHolder.SURFACE_TYPE_NORMAL);
        /* N3DS_GLOBALTIME_RGB565_WINDOW: the 3DS primary display and gralloc
         * scanout are RGB565. Do not let EGL select a translucent 32-bit
         * child buffer that this PixelFlinger composition path cannot show. */
        getHolder().setFormat(PixelFormat.RGB_565);

        startTime = System.currentTimeMillis();

        mClock = new Clock();

        startEGL();
        
        setFocusable(true);
        setFocusableInTouchMode(true);
        requestFocus();
    }

    /**
     * Creates an egl context. If the state of the activity is right, also
     * creates the egl surface. Otherwise the surface will be created in a
     * future call to createEGLSurface().
     */
    private void startEGL() {
        EGL10 egl = (EGL10)EGLContext.getEGL();

        if (mEGLContext == null) {
            EGLDisplay dpy = egl.eglGetDisplay(EGL10.EGL_DEFAULT_DISPLAY);
            int[] version = new int[2];
            egl.eglInitialize(dpy, version);
            /* N3DS_GLOBALTIME_RGB565_CONFIG */
            int[] configSpec = {
                    EGL10.EGL_SURFACE_TYPE, EGL10.EGL_WINDOW_BIT,
                    EGL10.EGL_RED_SIZE,     5,
                    EGL10.EGL_GREEN_SIZE,   6,
                    EGL10.EGL_BLUE_SIZE,    5,
                    EGL10.EGL_ALPHA_SIZE,   0,
                    EGL10.EGL_DEPTH_SIZE,   16,
                    EGL10.EGL_NONE
            };
            EGLConfig[] configs = new EGLConfig[1];
            int[] num_config = new int[1];
            boolean choseConfig = egl.eglChooseConfig(dpy, configSpec,
                    configs, 1, num_config);
            if (!choseConfig || num_config[0] < 1 || configs[0] == null) {
                throw new RuntimeException("No RGB565 EGL window config");
            }
            mEGLConfig = configs[0];

            mEGLContext = egl.eglCreateContext(dpy, mEGLConfig, 
                    EGL10.EGL_NO_CONTEXT, null);
            mEGLDisplay = dpy;
            
            AssetManager am = mContext.getAssets();
            try {
                loadAssets(am);
            } catch (IOException ioe) {
                ioe.printStackTrace();
                throw new RuntimeException(ioe);
            } catch (ArrayIndexOutOfBoundsException aioobe) {
                aioobe.printStackTrace();
                throw new RuntimeException(aioobe);
            }
        }
        
        if (mEGLSurface == null && !mPaused && mHaveSurface) {
            mEGLSurface = egl.eglCreateWindowSurface(mEGLDisplay, mEGLConfig,
                    this, null);
            boolean madeCurrent = egl.eglMakeCurrent(mEGLDisplay, mEGLSurface,
                    mEGLSurface, mEGLContext);
            int surfaceError = egl.eglGetError();
            /* N3DS_GLOBALTIME_EGL_SURFACE_READY: distinguish a compositor-side
             * black frame from failure to create or bind the libagl surface. */
            if (mEGLSurface == EGL10.EGL_NO_SURFACE || !madeCurrent ||
                    surfaceError != EGL10.EGL_SUCCESS) {
                Log.e(TAG, "N3DS_GLOBALTIME_EGL_FAILURE madeCurrent=" +
                        madeCurrent + " error=0x" +
                        Integer.toHexString(surfaceError));
                throw new RuntimeException("Unable to bind Global Time EGL surface");
            }
            Log.i(TAG, "N3DS_GLOBALTIME_EGL_SURFACE_READY");
            mInitialized = false;
            mFirstFrameLogged = false;
            mFirstFrameReadbackLogged = false;
            mFirstFrameGlError = GL10.GL_NO_ERROR;
            mWorldGL = null;
            mWorldGLSource = null;
            /* N3DS_GLOBALTIME_FALLBACK_RESET */
            /* N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT: the old forced colored-sphere
             * default (N3DS_GLOBALTIME_FALLBACK_DEFAULT, #235) only hid the
             * real bug.  The black frame came from scalar-float GL calls
             * crossing a hard-float/base-AAPCS JNI mismatch, and the fallback
             * sphere used the same broken projection, so it was black too.
             * With the GLfixed entry points (N3DS_GLOBALTIME_FIXED_POINT_GL)
             * the textured world.gles globe is the default again.  The
             * first-frame readback still switches to the fallback if the real
             * globe reads back black or raises a GL error. */
            mUseFallbackWorld = false;
            Log.i(TAG, "N3DS_GLOBALTIME_REAL_GLOBE_DEFAULT fallback=false");
            if (mStartAnimating) {
                startAnimating();
                mStartAnimating = false;
            }
        }
    }
    
    /**
     * Destroys the egl context. If an egl surface has been created, it is
     * destroyed as well.
     */
    private void stopEGL() {
        EGL10 egl = (EGL10)EGLContext.getEGL();
        if (mEGLSurface != null) {
            egl.eglMakeCurrent(mEGLDisplay, 
                    egl.EGL_NO_SURFACE, egl.EGL_NO_SURFACE, egl.EGL_NO_CONTEXT);
            egl.eglDestroySurface(mEGLDisplay, mEGLSurface);
            mEGLSurface = null;
        }

        if (mEGLContext != null) {
            egl.eglDestroyContext(mEGLDisplay, mEGLContext);
            egl.eglTerminate(mEGLDisplay);
            mEGLContext = null;
            mEGLDisplay = null;
            mEGLConfig = null;
        }
    }
    
    public void onPause() {
        mPaused = true;
        stopAnimating();
        stopEGL();
    }
    
    public void onResume() {
        mPaused = false;
        startEGL();
    }
    
    public void destroy() {
        stopAnimating();
        stopEGL();
    }

    /**
     * Begin animation.
     */
    public void startAnimating() {
        if (mEGLSurface == null) {
            mStartAnimating = true; // will start when egl surface is created
        } else {
            mHandler.sendEmptyMessage(INVALIDATE);
        }
    }

    /**
     * Quit animation.
     */
    public void stopAnimating() {
        mHandler.removeMessages(INVALIDATE);
    }

    /**
     * Read a two-byte integer from the input stream.
     */
    private int readInt16(InputStream is) throws IOException {
        int lo = is.read();
        int hi = is.read();
        return (hi << 8) | lo;
    }

    /**
     * Returns the offset from UTC for the given city.  If USE_RAW_OFFSETS
     * is true, summer/daylight savings is ignored.
     */
    private static float getOffset(City c) {
        return USE_RAW_OFFSETS ? c.getRawOffset() : c.getOffset();
    }

    private InputStream cache(InputStream is) throws IOException {
        int nbytes = is.available();
        byte[] data = new byte[nbytes];
        int nread = 0;
        while (nread < nbytes) {
            nread += is.read(data, nread, nbytes - nread);
        }
        return new ByteArrayInputStream(data);
    }

    /**
     * Load the city and lights databases.
     *
     * @param am the AssetManager to load from.
     */
    private void loadAssets(final AssetManager am) throws IOException {
        Locale locale = Locale.getDefault();
        String language = locale.getLanguage();
        String country = locale.getCountry();

        InputStream cis = null;
        try {
            // Look for (e.g.) cities_fr_FR.dat or cities_fr_CA.dat
            cis = am.open("cities_" + language + "_" + country + ".dat");
        } catch (FileNotFoundException e1) {
            try {
                // Look for (e.g.) cities_fr.dat or cities_fr.dat
                cis = am.open("cities_" + language + ".dat");
            } catch (FileNotFoundException e2) {
                try {
                    // Use English city names by default
                    cis = am.open("cities_en.dat");
                } catch (FileNotFoundException e3) {
                    throw e3;
                }
            }
        }

        cis = cache(cis);
        City.loadCities(cis);
        City[] cities;
        if (USE_RAW_OFFSETS) {
            cities = City.getCitiesByRawOffset();
        } else {
            cities = City.getCitiesByOffset();
        }

        mClockCities = new ArrayList<City>(cities.length);
        for (int i = 0; i < cities.length; i++) {
            mClockCities.add(cities[i]);
        }
        mCities = mClockCities;
        mCityIndex = 0;

        this.mWorld = new Object3D() {
                @Override
                public InputStream readFile(String filename)
                    throws IOException {
                    return cache(am.open(filename));
                }
            };

        mWorld.load("world.gles");

        // lights.dat has the following format.  All integers
        // are 16 bits, low byte first.
        //
        // width
        // height
        // N [# of lights]
        // light 0 X [in the range 0 to (width - 1)]
        // light 0 Y ]in the range 0 to (height - 1)]
        // light 1 X [in the range 0 to (width - 1)]
        // light 1 Y ]in the range 0 to (height - 1)]
        // ...
        // light (N - 1) X [in the range 0 to (width - 1)]
        // light (N - 1) Y ]in the range 0 to (height - 1)]
        //
        // For a larger number of lights, it could make more
        // sense to store the light positions in a bitmap
        // and extract them manually
        InputStream lis = am.open("lights.dat");
        lis = cache(lis);

        int lightWidth = readInt16(lis);
        int lightHeight = readInt16(lis);
        sNumLights = readInt16(lis);
        sLightCoords = new int[3 * sNumLights];

        int lidx = 0;
        float lightRadius = 1.009f;
        float lightScale = 65536.0f * lightRadius;

        float[] cosTheta = new float[lightWidth];
        float[] sinTheta = new float[lightWidth];
        float twoPi = (float) (2.0 * Math.PI);
        float scaleW = twoPi / lightWidth;
        for (int i = 0; i < lightWidth; i++) {
            float theta = twoPi - i * scaleW;
            cosTheta[i] = (float)Math.cos(theta);
            sinTheta[i] = (float)Math.sin(theta);
        }

        float[] cosPhi = new float[lightHeight];
        float[] sinPhi = new float[lightHeight];
        float scaleH = (float) (Math.PI / lightHeight);
        for (int j = 0; j < lightHeight; j++) {
            float phi = j * scaleH;
            cosPhi[j] = (float)Math.cos(phi);
            sinPhi[j] = (float)Math.sin(phi);
        }

        int nbytes = 4 * sNumLights;
        byte[] ilights = new byte[nbytes];
        int nread = 0;
        while (nread < nbytes) {
            nread += lis.read(ilights, nread, nbytes - nread);
        }

        int idx = 0;
        for (int i = 0; i < sNumLights; i++) {
            int lx = (((ilights[idx + 1] & 0xff) << 8) |
                       (ilights[idx    ] & 0xff));
            int ly = (((ilights[idx + 3] & 0xff) << 8) |
                       (ilights[idx + 2] & 0xff));
            idx += 4;

            float sin = sinPhi[ly];
            float x = cosTheta[lx]*sin;
            float y = cosPhi[ly];
            float z = sinTheta[lx]*sin;

            sLightCoords[lidx++] = (int) (x * lightScale);
            sLightCoords[lidx++] = (int) (y * lightScale);
            sLightCoords[lidx++] = (int) (z * lightScale);
        }
        mLights = new PointCloud(sLightCoords);
    }

    /**
     * Returns true if two time zone offsets are equal.  We assume distinct
     * time zone offsets will differ by at least a few minutes.
     */
    private boolean tzEqual(float o1, float o2) {
        return Math.abs(o1 - o2) < 0.001;
    }

    /**
     * Move to a different time zone.
     *
     * @param incr The increment between the current and future time zones.
     */
    private void shiftTimeZone(int incr) {
        // If only 1 city in the current set, there's nowhere to go
        if (mCities.size() <= 1) {
            return;
        }

        float offset = getOffset(mCities.get(mCityIndex));
        do {
            mCityIndex = (mCityIndex + mCities.size() + incr) % mCities.size();
        } while (tzEqual(getOffset(mCities.get(mCityIndex)), offset));

        offset = getOffset(mCities.get(mCityIndex));
        locateCity(true, offset);
        goToCity();
    }

    /**
     * Returns true if there is another city within the current time zone
     * that is the given increment away from the current city.
     *
     * @param incr the increment, +1 or -1
     * @return
     */
    private boolean atEndOfTimeZone(int incr) {
        if (mCities.size() <= 1) {
            return true;
        }

        float offset = getOffset(mCities.get(mCityIndex));
        int nindex = (mCityIndex + mCities.size() + incr) % mCities.size();
        if (tzEqual(getOffset(mCities.get(nindex)), offset)) {
            return false;
        }
        return true;
    }

    /**
     * Shifts cities within the current time zone.
     *
     * @param incr the increment, +1 or -1
     */
    private void shiftWithinTimeZone(int incr) {
        float offset = getOffset(mCities.get(mCityIndex));
        int nindex = (mCityIndex + mCities.size() + incr) % mCities.size();
        if (tzEqual(getOffset(mCities.get(nindex)), offset)) {
            mCityIndex = nindex;
            goToCity();
        }
    }

    /**
     * Returns true if the city name matches the given prefix, ignoring spaces.
     */
    private boolean nameMatches(City city, String prefix) {
        String cityName = city.getName().replaceAll("[ ]", "");
        return prefix.regionMatches(true, 0,
                                    cityName, 0,
                                    prefix.length());
    }

    /**
     * Returns true if there are cities matching the given name prefix.
     */
    private boolean hasMatches(String prefix) {
        for (int i = 0; i < mClockCities.size(); i++) {
            City city = mClockCities.get(i);
            if (nameMatches(city, prefix)) {
                return true;
            }
        }

        return false;
    }

    /**
     * Shifts to the nearest city that matches the new prefix.
     */
    private void shiftByName() {
        // Attempt to keep current city if it matches
        City finalCity = null;
        City currCity = mCities.get(mCityIndex);
        if (nameMatches(currCity, mCityName)) {
            finalCity = currCity;
        }

        mCityNameMatches.clear();
        for (int i = 0; i < mClockCities.size(); i++) {
            City city = mClockCities.get(i);
            if (nameMatches(city, mCityName)) {
                mCityNameMatches.add(city);
            }
        }

        mCities = mCityNameMatches;

        if (finalCity != null) {
            for (int i = 0; i < mCityNameMatches.size(); i++) {
                if (mCityNameMatches.get(i) == finalCity) {
                    mCityIndex = i;
                    break;
                }
            }
        } else {
            // Find the closest matching city
            locateCity(false, 0.0f);
        }
        goToCity();
    }

    /**
     * Increases or decreases the rotational speed of the earth.
     */
    private void incrementRotationalVelocity(float incr) {
        if (mDisplayWorldFlat) {
            mWrapVelocity -= incr;
        } else {
            mRotVelocity -= incr;
        }
    }

    /**
     * Clears the current matching prefix, while keeping the focus on
     * the current city.
     */
    private void clearCityMatches() {
        // Determine the global city index that matches the current city
        if (mCityNameMatches.size() > 0) {
            City city = mCityNameMatches.get(mCityIndex);
            for (int i = 0; i < mClockCities.size(); i++) {
                City ncity = mClockCities.get(i);
                if (city.equals(ncity)) {
                    mCityIndex = i;
                    break;
                }
            }
        }

        mCityName = "";
        mCityNameMatches.clear();
        mCities = mClockCities;
        goToCity();
    }

    /**
     * Fade the clock in or out.
     */
    private void enableClock(boolean enabled) {
        mClockFadeTime = System.currentTimeMillis();
        mDisplayClock = enabled;
        mClockShowing = true;
        mAlphaKeySet = enabled;
        if (enabled) {
            // Find the closest matching city
            locateCity(false, 0.0f);
        }
        clearCityMatches();
    }

    /**
     * Use the touchscreen to alter the rotational velocity or the
     * tilt of the earth.
     */
    @Override public boolean onTouchEvent(MotionEvent event) {
        switch (event.getAction()) {
            case MotionEvent.ACTION_DOWN:
                mMotionStartX = event.getX();
                mMotionStartY = event.getY();
                mMotionStartRotVelocity = mDisplayWorldFlat ?
                    mWrapVelocity : mRotVelocity;
                mMotionStartTiltAngle = mTiltAngle;

                // Stop the rotation
                if (mDisplayWorldFlat) {
                    mWrapVelocity = 0.0f;
                } else {
                    mRotVelocity = 0.0f;
                }
                mMotionDirection = MOTION_NONE;
                break;

            case MotionEvent.ACTION_MOVE:
                // Disregard motion events when the clock is displayed
                float dx = event.getX() - mMotionStartX;
                float dy = event.getY() - mMotionStartY;
                float delx = Math.abs(dx);
                float dely = Math.abs(dy);

                // Determine the direction of motion (major axis)
                // Once if has been determined, it's locked in until
                // we receive ACTION_UP or ACTION_CANCEL
                if ((mMotionDirection == MOTION_NONE) &&
                    (delx + dely > MIN_MANHATTAN_DISTANCE)) {
                    if (delx > dely) {
                        mMotionDirection = MOTION_X;
                    } else {
                        mMotionDirection = MOTION_Y;
                    }
                }

                // If the clock is displayed, don't actually rotate or tilt;
                // just use mMotionDirection to record whether motion occurred
                if (!mDisplayClock) {
                    if (mMotionDirection == MOTION_X) {
                        if (mDisplayWorldFlat) {
                            mWrapVelocity = mMotionStartRotVelocity +
                                dx * ROTATION_FACTOR;
                        } else {
                            mRotVelocity = mMotionStartRotVelocity +
                                dx * ROTATION_FACTOR;
                        }
                        mClock.setCity(null);
                    } else if (mMotionDirection == MOTION_Y &&
                        !mDisplayWorldFlat) {
                        mTiltAngle = mMotionStartTiltAngle + dy * TILT_FACTOR;
                        if (mTiltAngle < -90.0f) {
                            mTiltAngle = -90.0f;
                        }
                        if (mTiltAngle > 90.0f) {
                            mTiltAngle = 90.0f;
                        }
                        mClock.setCity(null);
                    }
                }
                break;

            case MotionEvent.ACTION_UP:
                mMotionDirection = MOTION_NONE;
                break;

            case MotionEvent.ACTION_CANCEL:
                mTiltAngle = mMotionStartTiltAngle;
                if (mDisplayWorldFlat) {
                    mWrapVelocity = mMotionStartRotVelocity;
                } else {
                    mRotVelocity = mMotionStartRotVelocity;
                }
                mMotionDirection = MOTION_NONE;
                break;
        }
        return true;
    }

    @Override public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (mInitialized && mGLView.processKey(keyCode)) {
            boolean drawing = (mClockShowing || mGLView.hasMessages());
            this.setWillNotDraw(!drawing);
            return true;
        }

        boolean handled = false;

        // If we're not in alphabetical entry mode, convert letters
        // to their digit equivalents
        if (!mAlphaKeySet) {
            char numChar = event.getNumber();
            if (numChar >= '0' && numChar <= '9') {
                keyCode = KeyEvent.KEYCODE_0 + (numChar - '0');
            }
        }

        switch (keyCode) {
        // The 'space' key toggles the clock
        case KeyEvent.KEYCODE_SPACE:
            mAlphaKeySet = !mAlphaKeySet;
            enableClock(mAlphaKeySet);
            handled = true;
            break;

        // The 'left' and 'right' buttons shift time zones if the clock is
        // displayed, otherwise they alters the rotational speed of the earthh
        case KeyEvent.KEYCODE_DPAD_LEFT:
            if (mDisplayClock) {
                shiftTimeZone(-1);
            } else {
                mClock.setCity(null);
                incrementRotationalVelocity(1.0f);
            }
            handled = true;
            break;

        case KeyEvent.KEYCODE_DPAD_RIGHT:
            if (mDisplayClock) {
                shiftTimeZone(1);
            } else {
                mClock.setCity(null);
                incrementRotationalVelocity(-1.0f);
            }
            handled = true;
            break;

        // The 'up' and 'down' buttons shift cities within a time zone if the
        // clock is displayed, otherwise they tilt the earth
        case KeyEvent.KEYCODE_DPAD_UP:
            if (mDisplayClock) {
                shiftWithinTimeZone(-1);
            } else {
                mClock.setCity(null);
                if (!mDisplayWorldFlat) {
                    mTiltAngle += 360.0f / 48.0f;
                }
            }
            handled = true;
            break;

        case KeyEvent.KEYCODE_DPAD_DOWN:
            if (mDisplayClock) {
                shiftWithinTimeZone(1);
            } else {
                mClock.setCity(null);
                if (!mDisplayWorldFlat) {
                    mTiltAngle -= 360.0f / 48.0f;
                }
            }
            handled = true;
            break;

        // The center key stops the earth's rotation, then toggles between the
        // round and flat views of the earth
        case KeyEvent.KEYCODE_DPAD_CENTER:
            if ((!mDisplayWorldFlat && mRotVelocity == 0.0f) ||
                (mDisplayWorldFlat && mWrapVelocity == 0.0f)) {
                mDisplayWorldFlat = !mDisplayWorldFlat;
            } else {
                if (mDisplayWorldFlat) {
                    mWrapVelocity = 0.0f;
                } else {
                    mRotVelocity = 0.0f;
                }
            }
            handled = true;
            break;

        // The 'L' key toggles the city lights
        case KeyEvent.KEYCODE_L:
            if (!mAlphaKeySet && !mDisplayWorldFlat) {
                mDisplayLights = !mDisplayLights;
                handled = true;
            }
            break;


        // The 'W' key toggles the earth (just for fun)
        case KeyEvent.KEYCODE_W:
            if (!mAlphaKeySet && !mDisplayWorldFlat) {
                mDisplayWorld = !mDisplayWorld;
                handled = true;
            }
            break;

        // The 'A' key toggles the atmosphere
        case KeyEvent.KEYCODE_A:
            if (!mAlphaKeySet && !mDisplayWorldFlat) {
                mDisplayAtmosphere = !mDisplayAtmosphere;
                handled = true;
            }
            break;

        // The '2' key zooms out
        case KeyEvent.KEYCODE_2:
            if (!mAlphaKeySet && !mDisplayWorldFlat) {
                mGLView.zoom(-2);
                handled = true;
            }
            break;

        // The '8' key zooms in
        case KeyEvent.KEYCODE_8:
            if (!mAlphaKeySet && !mDisplayWorldFlat) {
                mGLView.zoom(2);
                handled = true;
            }
            break;
        }

        // Handle letters in city names
        if (!handled && mAlphaKeySet) {
            switch (keyCode) {
            // Add a letter to the city name prefix
            case KeyEvent.KEYCODE_A:
            case KeyEvent.KEYCODE_B:
            case KeyEvent.KEYCODE_C:
            case KeyEvent.KEYCODE_D:
            case KeyEvent.KEYCODE_E:
            case KeyEvent.KEYCODE_F:
            case KeyEvent.KEYCODE_G:
            case KeyEvent.KEYCODE_H:
            case KeyEvent.KEYCODE_I:
            case KeyEvent.KEYCODE_J:
            case KeyEvent.KEYCODE_K:
            case KeyEvent.KEYCODE_L:
            case KeyEvent.KEYCODE_M:
            case KeyEvent.KEYCODE_N:
            case KeyEvent.KEYCODE_O:
            case KeyEvent.KEYCODE_P:
            case KeyEvent.KEYCODE_Q:
            case KeyEvent.KEYCODE_R:
            case KeyEvent.KEYCODE_S:
            case KeyEvent.KEYCODE_T:
            case KeyEvent.KEYCODE_U:
            case KeyEvent.KEYCODE_V:
            case KeyEvent.KEYCODE_W:
            case KeyEvent.KEYCODE_X:
            case KeyEvent.KEYCODE_Y:
            case KeyEvent.KEYCODE_Z:
                char c = (char)(keyCode - KeyEvent.KEYCODE_A + 'A');
                if (hasMatches(mCityName + c)) {
                    mCityName += c;
                    shiftByName();
                }
                handled = true;
                break;

            // Remove a letter from the city name prefix
            case KeyEvent.KEYCODE_DEL:
                if (mCityName.length() > 0) {
                    mCityName = mCityName.substring(0, mCityName.length() - 1);
                    shiftByName();
                } else {
                    clearCityMatches();
                }
                handled = true;
                break;

            // Clear the city name prefix
            case KeyEvent.KEYCODE_ENTER:
                clearCityMatches();
                handled = true;
                break;
            }
        }

        boolean drawing = (mClockShowing ||
            ((mGLView != null) && (mGLView.hasMessages())));
        this.setWillNotDraw(!drawing);

        // Let the system handle other keypresses
        if (!handled) {
            return super.onKeyDown(keyCode, event);
        }
        return true;
    }

    /**
     * Initialize OpenGL ES drawing.
     */
    private synchronized void init(GL10 gl) {
        mGLView = new GLView();
        mGLView.setNearFrustum(5.0f);
        mGLView.setFarFrustum(50.0f);
        mGLView.setLightModelAmbientIntensity(0.225f);
        mGLView.setAmbientIntensity(0.0f);
        mGLView.setDiffuseIntensity(1.5f);
        mGLView.setDiffuseColor(SUNLIGHT_COLOR);
        mGLView.setSpecularIntensity(0.0f);
        mGLView.setSpecularColor(SUNLIGHT_COLOR);

        if (PERFORM_DEPTH_TEST) {
            gl.glEnable(GL10.GL_DEPTH_TEST);
        }
        gl.glDisable(GL10.GL_SCISSOR_TEST);
        /* N3DS_GLOBALTIME_FIXED_POINT_GL: opaque black, GLfixed 1.0 alpha. */
        gl.glClearColorx(0, 0, 0, GLView.FIXED_ONE);
        gl.glHint(GL10.GL_POINT_SMOOTH_HINT, GL10.GL_NICEST);
        probeFloatJniAbi(gl);

        mInitialized = true;
    }

    /* N3DS_GLOBALTIME_FLOAT_ABI_PROBE: one deliberate scalar-float GL call
     * per GL context, so logcat says whether the running app_process has
     * the libandroid_runtime float JNI fix.  GL_LINEAR is a valid
     * GL_TEXTURE_MAG_FILTER, so a correct float ABI raises no error.  With
     * the hard-float mismatch libagl reads an unloaded VFP register and
     * raises GL_INVALID_ENUM, which is the 0x500 build #314 logged.  The
     * probe targets the default texture object and restores its GL_LINEAR
     * default through the fixed entry point, so drawing never depends on
     * the probe's outcome. */
    private void probeFloatJniAbi(GL10 gl) {
        for (int i = 0; i < 8 && gl.glGetError() != GL10.GL_NO_ERROR; i++) {
            // drain errors raised before the probe
        }
        gl.glBindTexture(GL10.GL_TEXTURE_2D, 0);
        gl.glTexParameterf(GL10.GL_TEXTURE_2D, GL10.GL_TEXTURE_MAG_FILTER, GL10.GL_LINEAR); // N3DS_GLOBALTIME_FLOAT_ABI_PROBE_CALL
        int probeError = gl.glGetError();
        gl.glTexParameterx(GL10.GL_TEXTURE_2D, GL10.GL_TEXTURE_MAG_FILTER,
                GL10.GL_LINEAR);
        int restoreError = gl.glGetError();
        if (probeError == GL10.GL_NO_ERROR) {
            Log.i(TAG, "N3DS_GLOBALTIME_FLOAT_ABI_PROBE glTexParameterf error=0x0" +
                    " restore=0x" + Integer.toHexString(restoreError) +
                    " float JNI ABI ok");
        } else {
            Log.w(TAG, "N3DS_GLOBALTIME_FLOAT_ABI_PROBE glTexParameterf error=0x" +
                    Integer.toHexString(probeError) +
                    " restore=0x" + Integer.toHexString(restoreError) +
                    " float JNI ABI BROKEN: app_process predates the" +
                    " pcs(aapcs) GLImpl bindings; Global Time uses GLfixed");
        }
    }

    /* N3DS_GLOBALTIME_GL_ERROR: per-stage glGetError on the first frame
     * only, so a black frame names the stage that raised the error. */
    private void checkFirstFrameGlError(GL10 gl, String stage) {
        if (mFirstFrameReadbackLogged) {
            return;
        }
        int error = gl.glGetError();
        if (error != GL10.GL_NO_ERROR &&
                mFirstFrameGlError == GL10.GL_NO_ERROR) {
            mFirstFrameGlError = error;
        }
        Log.i(TAG, "N3DS_GLOBALTIME_GL_ERROR stage=" + stage + " error=0x" +
                Integer.toHexString(error));
    }

    /* N3DS_GLOBALTIME_FIXED_POINT_PROXY: android.opengl.Object3D (in
     * framework.jar, not this APK) draws world.gles with glMaterialf,
     * glTexParameterf and glTexEnvf.  Hand it a GL whose scalar-float
     * calls are routed to the GLfixed entry points; every other call is
     * forwarded unchanged to the real context GL. */
    private GL10 worldGL(GL10 gl) {
        if (mWorldGL != null && mWorldGLSource == gl) {
            return mWorldGL;
        }
        mWorldGLSource = gl;
        mWorldGL = gl;
        try {
            Class<?>[] interfaces = gl.getClass().getInterfaces();
            boolean hasGL10 = false;
            for (int i = 0; i < interfaces.length; i++) {
                if (interfaces[i] == GL10.class) {
                    hasGL10 = true;
                }
            }
            if (!hasGL10) {
                Class<?>[] widened = new Class<?>[interfaces.length + 1];
                System.arraycopy(interfaces, 0, widened, 0, interfaces.length);
                widened[interfaces.length] = GL10.class;
                interfaces = widened;
            }
            mWorldGL = (GL10) Proxy.newProxyInstance(
                    GTView.class.getClassLoader(), interfaces,
                    new FixedPointGL(gl));
            Log.i(TAG, "N3DS_GLOBALTIME_FIXED_POINT_PROXY ready interfaces=" +
                    interfaces.length);
        } catch (Throwable t) {
            mWorldGL = gl;
            Log.w(TAG, "N3DS_GLOBALTIME_FIXED_POINT_PROXY unavailable: " + t);
        }
        return mWorldGL;
    }

    private static final class FixedPointGL implements InvocationHandler {
        private final GL10 mGl;

        FixedPointGL(GL10 gl) {
            mGl = gl;
        }

        public Object invoke(Object proxy, Method method, Object[] args)
                throws Throwable {
            if (args != null && args.length == 3 &&
                    args[0] instanceof Integer && args[1] instanceof Integer &&
                    args[2] instanceof Float) {
                String name = method.getName();
                int a0 = ((Integer) args[0]).intValue();
                int a1 = ((Integer) args[1]).intValue();
                float value = ((Float) args[2]).floatValue();
                // Enum-valued texture parameters are passed unscaled, as
                // libagl's own glTexParameterf/glTexEnvf convert them.
                if ("glTexParameterf".equals(name)) {
                    mGl.glTexParameterx(a0, a1, (int) value);
                    return null;
                }
                if ("glTexEnvf".equals(name)) {
                    mGl.glTexEnvx(a0, a1, (int) value);
                    return null;
                }
                if ("glMaterialf".equals(name)) {
                    mGl.glMaterialx(a0, a1, GLView.toFixed(value));
                    return null;
                }
                if ("glLightf".equals(name)) {
                    mGl.glLightx(a0, a1, GLView.toFixed(value));
                    return null;
                }
            }
            try {
                return method.invoke(mGl, args);
            } catch (InvocationTargetException e) {
                Throwable cause = e.getCause();
                throw cause != null ? cause : e;
            }
        }
    }

    /**
     * Computes the vector from the center of the earth to the sun for a
     * particular moment in time.
     */
    private void computeSunDirection() {
        mSunCal.setTimeInMillis(System.currentTimeMillis());
        int day = mSunCal.get(Calendar.DAY_OF_YEAR);
        int seconds = 3600 * mSunCal.get(Calendar.HOUR_OF_DAY) +
            60 * mSunCal.get(Calendar.MINUTE) + mSunCal.get(Calendar.SECOND);
        day += (float) seconds / SECONDS_PER_DAY;

        // Approximate declination of the sun, changes sinusoidally
        // during the year.  The winter solstice occurs 10 days before
        // the start of the year.
        float decl = (float) (EARTH_INCLINATION *
            Math.cos(Shape.TWO_PI * (day + 10) / 365.0));

        // Subsolar latitude, convert from (-PI/2, PI/2) -> (0, PI) form
        float phi = decl + Shape.PI_OVER_TWO;
        // Subsolar longitude
        float theta = Shape.TWO_PI * seconds / SECONDS_PER_DAY;

        float sinPhi = (float) Math.sin(phi);
        float cosPhi = (float) Math.cos(phi);
        float sinTheta = (float) Math.sin(theta);
        float cosTheta = (float) Math.cos(theta);

        // Convert from polar to rectangular coordinates
        float x = cosTheta * sinPhi;
        float y = cosPhi;
        float z = sinTheta * sinPhi;

        // Directional light -> w == 0
        mLightDir[0] = x;
        mLightDir[1] = y;
        mLightDir[2] = z;
        mLightDir[3] = 0.0f;
    }

    /**
     * Computes the approximate spherical distance between two
     * (latitude, longitude) coordinates.
     */
    private float distance(float lat1, float lon1,
                           float lat2, float lon2) {
        lat1 *= Shape.DEGREES_TO_RADIANS;
        lat2 *= Shape.DEGREES_TO_RADIANS;
        lon1 *= Shape.DEGREES_TO_RADIANS;
        lon2 *= Shape.DEGREES_TO_RADIANS;

        float r = 6371.0f; // Earth's radius in km
        float dlat = lat2 - lat1;
        float dlon = lon2 - lon1;
        double sinlat2 = Math.sin(dlat / 2.0f);
        sinlat2 *= sinlat2;
        double sinlon2 = Math.sin(dlon / 2.0f);
        sinlon2 *= sinlon2;

        double a = sinlat2 + Math.cos(lat1) * Math.cos(lat2) * sinlon2;
        double c = 2.0 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return (float) (r * c);
    }

    /**
     * Locates the closest city to the currently displayed center point,
     * optionally restricting the search to cities within a given time zone.
     */
    private void locateCity(boolean useOffset, float offset) {
        float mindist = Float.MAX_VALUE;
        int minidx = -1;
        for (int i = 0; i < mCities.size(); i++) {
            City city = mCities.get(i);
            if (useOffset && !tzEqual(getOffset(city), offset)) {
                continue;
            }
            float dist = distance(city.getLatitude(), city.getLongitude(),
                mTiltAngle, mRotAngle - 90.0f);
            if (dist < mindist) {
                mindist = dist;
                minidx = i;
            }
        }

        mCityIndex = minidx;
    }

    /**
     * Animates the earth to be centered at the current city.
     */
    private void goToCity() {
        City city = mCities.get(mCityIndex);
        float dist = distance(city.getLatitude(), city.getLongitude(),
            mTiltAngle, mRotAngle - 90.0f);

        mFlyToCity = true;
        mCityFlyStartTime = System.currentTimeMillis();
        mCityFlightTime = dist / 5.0f; // 5000 km/sec
        mRotAngleStart = mRotAngle;
        mRotAngleDest = city.getLongitude() + 90;

        if (mRotAngleDest - mRotAngleStart > 180.0f) {
            mRotAngleDest -= 360.0f;
        } else if (mRotAngleStart - mRotAngleDest > 180.0f) {
            mRotAngleDest += 360.0f;
        }

        mTiltAngleStart = mTiltAngle;
        mTiltAngleDest = city.getLatitude();
        mRotVelocity = 0.0f;
    }

    /**
     * Returns a linearly interpolated value between two values.
     */
    private float lerp(float a, float b, float lerp) {
        return a + (b - a)*lerp;
    }

    /**
     * Draws the city lights, using a clip plane to restrict the lights
     * to the night side of the earth.
     */
    private void drawCityLights(GL10 gl, float brightness) {
        gl.glEnable(GL10.GL_POINT_SMOOTH);
        gl.glDisable(GL10.GL_DEPTH_TEST);
        gl.glDisable(GL10.GL_LIGHTING);
        gl.glDisable(GL10.GL_DITHER);
        gl.glShadeModel(GL10.GL_FLAT);
        gl.glEnable(GL10.GL_BLEND);
        gl.glBlendFunc(GL10.GL_SRC_ALPHA, GL10.GL_ONE_MINUS_SRC_ALPHA);
        /* N3DS_GLOBALTIME_FIXED_POINT_GL */
        gl.glPointSizex(GLView.FIXED_ONE);

        float ls = lerp(0.8f, 0.3f, brightness);
        gl.glColor4x(GLView.toFixed(ls * 1.0f), GLView.toFixed(ls * 1.0f),
                GLView.toFixed(ls * 0.8f), GLView.FIXED_ONE);

        if (mDisplayWorld) {
            mClipPlaneEquation[0] = -mLightDir[0];
            mClipPlaneEquation[1] = -mLightDir[1];
            mClipPlaneEquation[2] = -mLightDir[2];
            mClipPlaneEquation[3] = 0.0f;
            // Assume we have glClipPlanef() from OpenGL ES 1.1
            ((GL11) gl).glClipPlanef(GL11.GL_CLIP_PLANE0,
                mClipPlaneEquation, 0);
            gl.glEnable(GL11.GL_CLIP_PLANE0);
        }
        mLights.draw(gl);
        if (mDisplayWorld) {
            gl.glDisable(GL11.GL_CLIP_PLANE0);
        }

        mNumTriangles += mLights.getNumTriangles()*2;
    }

    /**
     * Draws the atmosphere.
     */
    private void drawAtmosphere(GL10 gl) {
        gl.glDisable(GL10.GL_LIGHTING);
        gl.glDisable(GL10.GL_CULL_FACE);
        gl.glDisable(GL10.GL_DITHER);
        gl.glDisable(GL10.GL_DEPTH_TEST);
        gl.glShadeModel(mSmoothShading ? GL10.GL_SMOOTH : GL10.GL_FLAT);

        // Draw the atmospheric layer
        float tx = mGLView.getTranslateX();
        float ty = mGLView.getTranslateY();
        float tz = mGLView.getTranslateZ();

        gl.glMatrixMode(GL10.GL_MODELVIEW);
        gl.glLoadIdentity();
        gl.glTranslatex(GLView.toFixed(tx), GLView.toFixed(ty),
                GLView.toFixed(tz));

        // Blend in the atmosphere a bit
        gl.glEnable(GL10.GL_BLEND);
        gl.glBlendFunc(GL10.GL_SRC_ALPHA, GL10.GL_ONE_MINUS_SRC_ALPHA);
        ATMOSPHERE.draw(gl);

        mNumTriangles += ATMOSPHERE.getNumTriangles();
    }

    /**
     * Draws the world in a 2D map view.
     */
    private void drawWorldFlat(GL10 gl) {
        gl.glDisable(GL10.GL_BLEND);
        gl.glEnable(GL10.GL_DITHER);
        gl.glShadeModel(mSmoothShading ? GL10.GL_SMOOTH : GL10.GL_FLAT);

        gl.glTranslatex(GLView.toFixed(mWrapX - 2), 0, 0);
        worldFlat.draw(gl);
        gl.glTranslatex(2 * GLView.FIXED_ONE, 0, 0);
        worldFlat.draw(gl);
        mNumTriangles += worldFlat.getNumTriangles() * 2;

        mWrapX += mWrapVelocity * mWrapVelocityFactor;
        while (mWrapX < 0.0f) {
            mWrapX += 2.0f;
        }
        while (mWrapX > 2.0f) {
            mWrapX -= 2.0f;
        }
    }

    /**
     * Draws the world in a 2D round view.
     */
    private void drawWorldRound(GL10 gl) {
        /* N3DS_CLIP_PLANE_CLEANUP: the night-light pass can leave clip plane
         * zero enabled, which culls the following globe on PixelFlinger. */
        if (gl instanceof GL11) {
            ((GL11) gl).glDisable(GL11.GL_CLIP_PLANE0);
        }
        gl.glDisable(GL10.GL_BLEND);
        gl.glEnable(GL10.GL_DITHER);
        gl.glShadeModel(mSmoothShading ? GL10.GL_SMOOTH : GL10.GL_FLAT);

        /* N3DS_GLOBALTIME_FIXED_POINT_PROXY */
        mWorld.draw(worldGL(gl));
        mNumTriangles += mWorld.getNumTriangles();
    }

    /* N3DS_GLOBALTIME_FALLBACK_DRAW */
    private void drawFallbackWorld(GL10 gl) {
        gl.glDisable(GL10.GL_LIGHTING);
        gl.glDisable(GL10.GL_CULL_FACE);
        gl.glDisable(GL10.GL_BLEND);
        gl.glDisable(GL10.GL_DEPTH_TEST);
        gl.glShadeModel(GL10.GL_SMOOTH);
        FALLBACK_WORLD.draw(gl);
        mNumTriangles += FALLBACK_WORLD.getNumTriangles();
    }

    /* N3DS_GLOBALTIME_RGBA_READBACK helper: reads the centre 16x16 of the
     * back buffer and returns {nonBlack, firstPixelRGB, readError, total}. */
    private int[] readCenterSample(GL10 gl, int w, int h) {
        final int sampleWidth = Math.min(16, w);
        final int sampleHeight = Math.min(16, h);
        ByteBuffer bytes = ByteBuffer.allocateDirect(
                sampleWidth * sampleHeight * 4);
        gl.glReadPixels(Math.max(0, (w - sampleWidth) / 2),
                Math.max(0, (h - sampleHeight) / 2),
                sampleWidth, sampleHeight, GL10.GL_RGBA,
                GL10.GL_UNSIGNED_BYTE, bytes);
        int readbackError = gl.glGetError();
        int nonBlack = 0;
        int firstPixel = 0;
        for (int i = 0; i < sampleWidth * sampleHeight; i++) {
            int offset = i * 4;
            int red = bytes.get(offset) & 0xff;
            int green = bytes.get(offset + 1) & 0xff;
            int blue = bytes.get(offset + 2) & 0xff;
            if (i == 0) firstPixel = (red << 16) | (green << 8) | blue;
            if (red != 0 || green != 0 || blue != 0) nonBlack++;
        }
        return new int[] {
            nonBlack, firstPixel, readbackError, sampleWidth * sampleHeight
        };
    }

    /**
     * Draws the clock.
     *
     * @param canvas the Canvas to draw to
     * @param now the current time
     * @param w the width of the screen
     * @param h the height of the screen
     * @param lerp controls the animation, between 0.0 and 1.0
     */
    private void drawClock(Canvas canvas,
                           long now,
                           int w, int h,
                           float lerp) {
        float clockAlpha = lerp(0.0f, 0.8f, lerp);
        mClockShowing = clockAlpha > 0.0f;
        if (clockAlpha > 0.0f) {
            City city = mCities.get(mCityIndex);
            mClock.setCity(city);
            mClock.setTime(now);

            float cx = w / 2.0f;
            float cy = h / 2.0f;
            float smallRadius = 18.0f;
            float bigRadius = 0.75f * 0.5f * Math.min(w, h);
            float radius = lerp(smallRadius, bigRadius, lerp);

            // Only display left/right arrows if we are in a name search
            boolean scrollingByName =
                (mCityName.length() > 0) && (mCities.size() > 1);
            mClock.drawClock(canvas, cx, cy, radius,
                             clockAlpha,
                             1.0f,
                             lerp == 1.0f, lerp == 1.0f,
                             !atEndOfTimeZone(-1),
                             !atEndOfTimeZone(1),
                             scrollingByName,
                             mCityName.length());
        }
    }

    /**
     * Draws the 2D layer.
     */
    @Override protected void onDraw(Canvas canvas) {
        long now = System.currentTimeMillis();
        if (startTime != -1) {
            startTime = -1;
        }

        int w = getWidth();
        int h = getHeight();

        // Interpolator for clock size, clock alpha, night lights intensity
        float lerp = Math.min((now - mClockFadeTime)/1000.0f, 1.0f);
        if (!mDisplayClock) {
            // Clock is receding
            lerp = 1.0f - lerp;
        }
        lerp = mClockSizeInterpolator.getInterpolation(lerp);

        // we don't need to make sure OpenGL rendering is done because
        // we're drawing in to a different surface

        drawClock(canvas, now, w, h, lerp);

        mGLView.showMessages(canvas);
        mGLView.showStatistics(canvas, w);
    }

    /**
     * Draws the 3D layer.
     */
    protected void drawOpenGLScene() {
        long now = System.currentTimeMillis();
        mNumTriangles = 0;

        EGL10 egl = (EGL10)EGLContext.getEGL();
        GL10 gl = (GL10)mEGLContext.getGL();

        if (!mInitialized) {
            init(gl);
        }

        /* N3DS_VIEWPORT_SAFE_BOUNDS: SurfaceView can report zero dimensions
         * during its first animation turn. Never submit an empty viewport or
         * divide by zero while establishing the projection. */
        int w = getWidth();
        int h = getHeight();
        if (w <= 0) w = 320;
        if (h <= 0) h = 240;
        gl.glViewport(0, 0, w, h);

        gl.glEnable(GL10.GL_LIGHTING);
        gl.glEnable(GL10.GL_LIGHT0);
        gl.glEnable(GL10.GL_CULL_FACE);
        gl.glFrontFace(GL10.GL_CCW);

        float ratio = (float) w / h;
        mGLView.setAspectRatio(ratio);

        mGLView.setTextureParameters(gl);

        if (PERFORM_DEPTH_TEST) {
            gl.glClear(GL10.GL_COLOR_BUFFER_BIT | GL10.GL_DEPTH_BUFFER_BIT);
        } else {
            gl.glClear(GL10.GL_COLOR_BUFFER_BIT);
        }

        if (mDisplayWorldFlat) {
            gl.glMatrixMode(GL10.GL_PROJECTION);
            gl.glLoadIdentity();
            /* N3DS_GLOBALTIME_FIXED_POINT_GL */
            gl.glFrustumx(-GLView.FIXED_ONE, GLView.FIXED_ONE,
                    GLView.toFixed(-1.0f / ratio), GLView.toFixed(1.0f / ratio),
                    GLView.FIXED_ONE, 2 * GLView.FIXED_ONE);
            gl.glMatrixMode(GL10.GL_MODELVIEW);
            gl.glLoadIdentity();
            gl.glTranslatex(0, 0, -GLView.FIXED_ONE);
        } else {
            mGLView.setProjection(gl);
            mGLView.setView(gl);
        }

        if (!mDisplayWorldFlat) {
            if (mFlyToCity) {
                float lerp = (now - mCityFlyStartTime)/mCityFlightTime;
                if (lerp >= 1.0f) {
                    mFlyToCity = false;
                }
                lerp = Math.min(lerp, 1.0f);
                lerp = mFlyToCityInterpolator.getInterpolation(lerp);
                mRotAngle = lerp(mRotAngleStart, mRotAngleDest, lerp);
                mTiltAngle = lerp(mTiltAngleStart, mTiltAngleDest, lerp);
            }

            // Rotate the viewpoint around the earth
            gl.glMatrixMode(GL10.GL_MODELVIEW);
            gl.glRotatex(GLView.toFixed(mTiltAngle), GLView.FIXED_ONE, 0, 0);
            gl.glRotatex(GLView.toFixed(mRotAngle), 0, GLView.FIXED_ONE, 0);

            // Increment the rotation angle
            mRotAngle += mRotVelocity;
            if (mRotAngle < 0.0f) {
                mRotAngle += 360.0f;
            }
            if (mRotAngle > 360.0f) {
                mRotAngle -= 360.0f;
            }
        }

        // Draw the world with lighting
        gl.glLightfv(GL10.GL_LIGHT0, GL10.GL_POSITION, mLightDir, 0);
        mGLView.setLights(gl, GL10.GL_LIGHT0);
        checkFirstFrameGlError(gl, "setup");

        if (mDisplayWorldFlat) {
            drawWorldFlat(gl);
        } else if (mDisplayWorld) {
            /* N3DS_GLOBALTIME_FALLBACK_DISPATCH */
            if (mUseFallbackWorld) {
                drawFallbackWorld(gl);
            } else {
                drawWorldRound(gl);
            }
        }
        checkFirstFrameGlError(gl, mUseFallbackWorld ? "fallback-world" : "world");

        /* N3DS_GLOBALTIME_FALLBACK_LIGHT_ISOLATION: the fallback world
         * is deliberately asset-free, so do not composite the failing
         * textured city-light pass over it. */
        if (mDisplayLights && !mDisplayWorldFlat && !mUseFallbackWorld) {
            // Interpolator for clock size, clock alpha, night lights intensity
            float lerp = Math.min((now - mClockFadeTime)/1000.0f, 1.0f);
            if (!mDisplayClock) {
                // Clock is receding
                lerp = 1.0f - lerp;
            }
            lerp = mClockSizeInterpolator.getInterpolation(lerp);
            drawCityLights(gl, lerp);
            checkFirstFrameGlError(gl, "lights");
        }

        /* N3DS_GLOBALTIME_FALLBACK_ATMOSPHERE_ISOLATION: keep the
         * texture-independent fallback visible and diagnostically bounded. */
        if (mDisplayAtmosphere && !mDisplayWorldFlat && !mUseFallbackWorld) {
            drawAtmosphere(gl);
            checkFirstFrameGlError(gl, "atmosphere");
        }
        /* N3DS_GLOBALTIME_RGBA_READBACK: OpenGL ES 1.x guarantees RGBA with
         * UNSIGNED_BYTE for glReadPixels. The former RGB/565 pair returned
         * GL_INVALID_ENUM, so its all-black result was not evidence. */
        if (!mFirstFrameReadbackLogged) {
            gl.glFinish();
            int drawError = gl.glGetError();
            int stageError = mFirstFrameGlError;
            int[] sample = readCenterSample(gl, w, h);
            Log.i(TAG, "N3DS_GLOBALTIME_READBACK drawError=0x" +
                    Integer.toHexString(drawError) + " stageError=0x" +
                    Integer.toHexString(stageError) + " readError=0x" +
                    Integer.toHexString(sample[2]) + " nonBlack=" +
                    sample[0] + "/" + sample[3] + " first=0x" +
                    Integer.toHexString(sample[1]) + " world=" +
                    (mUseFallbackWorld ? "fallback" : "textured"));
            if (drawError != GL10.GL_NO_ERROR ||
                    stageError != GL10.GL_NO_ERROR ||
                    sample[2] != GL10.GL_NO_ERROR || sample[0] == 0) {
                mUseFallbackWorld = true;
                drawFallbackWorld(gl);
                gl.glFinish();
                int fallbackError = gl.glGetError();
                int[] fallbackSample = readCenterSample(gl, w, h);
                Log.w(TAG, "N3DS_GLOBALTIME_GEOMETRY_FALLBACK enabled error=0x" +
                        Integer.toHexString(fallbackError) + " readError=0x" +
                        Integer.toHexString(fallbackSample[2]) + " nonBlack=" +
                        fallbackSample[0] + "/" + fallbackSample[3] +
                        " first=0x" + Integer.toHexString(fallbackSample[1]));
            }
            mFirstFrameReadbackLogged = true;
        }
        mGLView.setNumTriangles(mNumTriangles);
        boolean swapped = egl.eglSwapBuffers(mEGLDisplay, mEGLSurface);
        int swapError = egl.eglGetError();
        /* N3DS_GLOBALTIME_FIRST_FRAME: one bounded marker proves that the full
         * textured/lighting draw path reached a successful present. */
        if (!mFirstFrameLogged) {
            Log.i(TAG, "N3DS_GLOBALTIME_FIRST_FRAME swapped=" + swapped +
                    " error=0x" + Integer.toHexString(swapError) +
                    " size=" + w + "x" + h +
                    " triangles=" + mNumTriangles);
            mFirstFrameLogged = true;
        }

        if (!swapped || swapError == EGL11.EGL_CONTEXT_LOST) {
            // we lost the gpu, quit immediately
            Context c = getContext();
            if (c instanceof Activity) {
                ((Activity)c).finish();
            }
        } else if (swapError != EGL10.EGL_SUCCESS) {
            Log.e(TAG, "N3DS_GLOBALTIME_SWAP_FAILURE error=0x" +
                    Integer.toHexString(swapError));
        }
    }


    private static final int INVALIDATE = 1;
    private static final int ONE_MINUTE = 60000;

    /**
     * Controls the animation using the message queue.  Every time we receive
     * an INVALIDATE message, we redraw and place another message in the queue.
     */
    private final Handler mHandler = new Handler() {
        private long mLastSunPositionTime = 0;

        @Override public void handleMessage(Message msg) {
            if (msg.what == INVALIDATE) {

                // Use the message's time, it's good enough and
                // allows us to avoid a system call.
                if ((msg.getWhen() - mLastSunPositionTime) >= ONE_MINUTE) {
                    // Recompute the sun's position once per minute
                    // Place the light at the Sun's direction
                    computeSunDirection();
                    mLastSunPositionTime = msg.getWhen();
                }

                // Draw the GL scene
                drawOpenGLScene();

                // Send an update for the 2D overlay if needed
                if (mInitialized &&
                                (mClockShowing || mGLView.hasMessages())) {
                    invalidate();
                }

                // Just send another message immediately. This works because
                // drawOpenGLScene() does the timing for us -- it will
                // block until the last frame has been processed.
                // The invalidate message we're posting here will be
                // interleaved properly with motion/key events which
                // guarantee a prompt reaction to the user input.
                sendEmptyMessage(INVALIDATE);
            }
        }
    };
}

/**
 * The main activity class for GlobalTime.
 */
public class GlobalTime extends Activity {

    GTView gtView = null;

    @Override protected void onCreate(Bundle icicle) {
        super.onCreate(icicle);
        /* N3DS_GLOBALTIME_TRANSLUCENT_DECOR: do not depend on the theme
         * attribute alone for this.  Layer::mNeedsBlending is derived from the
         * window surface's pixel format, and without an alpha channel
         * SurfaceFlinger ignores the transparent-region hint that reveals the
         * SurfaceView carrying the globe. */
        getWindow().setFormat(PixelFormat.TRANSLUCENT);
        gtView = new GTView(this);
        setContentView(gtView);
    }

    @Override protected void onResume() {
        super.onResume();
        gtView.onResume();
        Looper.myQueue().addIdleHandler(new Idler());
    }

    @Override protected void onPause() {
        super.onPause();
        gtView.onPause();
    }

    @Override protected void onStop() {
        super.onStop();
        gtView.destroy();
        gtView = null;
    }

    // Allow the activity to go idle before its animation starts
    class Idler implements MessageQueue.IdleHandler {
        public Idler() {
            super();
        }

        public final boolean queueIdle() {
            if (gtView != null) {
                gtView.startAnimating();
            }
            return false;
        }
    }
}
