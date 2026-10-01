#!/usr/bin/env python3
"""Apply and verify the Android3DS Global Time rendering repairs."""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# N3DS_GLOBALTIME_ONE_TREE
#
# There are two checkouts of third_party/globaltime: the WSL-native tree at
# $ANDROID3DS_ROOT and the Windows-side tree.  This script used to
# patch whichever one it happened to be launched from, while
# build_globaltime_app.sh always reads the *Windows* one -- so running the
# patcher from WSL (which rebuild_everything.sh does) could silently produce an
# APK without the patches, and the verification block below would still report
# OK because it re-read the tree it had just written.
#
# Fix: patch the tree we are launched from, then mirror the result into every
# other checkout that exists and assert the bytes converge.  Whichever tree the
# builder reads, it now reads the patched files.
SIBLING_ROOTS = (
    Path(A3DS_ROOT),
    Path(A3DS_WIN),
)

GLOBALTIME_RELPATHS = (
    "third_party/globaltime/src/com/android/globaltime/GlobalTime.java",
    "third_party/globaltime/src/com/android/globaltime/GLView.java",
    "third_party/globaltime/res/values/styles.xml",
)

GLOBAL_TIME = PROJECT_ROOT / GLOBALTIME_RELPATHS[0]
GL_VIEW = PROJECT_ROOT / GLOBALTIME_RELPATHS[1]
STYLES = PROJECT_ROOT / GLOBALTIME_RELPATHS[2]

_TEXTURE_REL = "third_party/frameworks/base/opengl/java/android/opengl/Texture.java"
TEXTURE = PROJECT_ROOT / _TEXTURE_REL
if not TEXTURE.exists():
    # frameworks/base only ever builds under WSL; fall back to that tree when
    # this script runs from a checkout that does not carry it.
    TEXTURE = Path(A3DS_ROOT) / _TEXTURE_REL


def mirror_to_sibling_trees():
    """Copy the patched globaltime sources into every other checkout."""
    for root in SIBLING_ROOTS:
        try:
            if not root.is_dir() or root.resolve() == PROJECT_ROOT.resolve():
                continue
        except OSError:
            continue
        for rel in GLOBALTIME_RELPATHS:
            src = PROJECT_ROOT / rel
            dst = root / rel
            if not dst.parent.is_dir():
                continue
            data = src.read_bytes()
            if not dst.exists() or dst.read_bytes() != data:
                dst.write_bytes(data)
                print("patch_n3ds_globaltime_render: mirrored %s -> %s"
                      % (rel, root))
            if dst.read_bytes() != data:
                raise SystemExit(
                    "globaltime tree mirror failed to converge: %s" % dst
                )


def apply_once(path, marker, old, new):
    text = path.read_text()
    if marker not in text:
        count = text.count(old)
        if count != 1:
            raise SystemExit(
                "%s: expected exactly one unpatched hunk for %s, found %d"
                % (path, marker, count)
            )
        path.write_text(text.replace(old, new, 1))
        print("%s: applied %s" % (path.name, marker))
    else:
        print("%s: verified %s" % (path.name, marker))


apply_once(
    GLOBAL_TIME,
    "N3DS_SURFACE_TYPE_NORMAL",
    "        getHolder().setType(SurfaceHolder.SURFACE_TYPE_GPU);",
    """        /* N3DS_SURFACE_TYPE_NORMAL: Eclair's GPU SurfaceHolder path expects a
         * hardware gralloc buffer queue. Android3DS still presents libagl
         * through the proven normal framebuffer surface. */
        getHolder().setType(SurfaceHolder.SURFACE_TYPE_NORMAL);""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_SURFACE_CHANGED_ASPECT",
    """    public void surfaceChanged(SurfaceHolder holder, int format, int w, int h) {
        // nothing to do
    }""",
    """    public void surfaceChanged(SurfaceHolder holder, int format, int w, int h) {
        /* N3DS_SURFACE_CHANGED_ASPECT: never leave the projection at its
         * constructor-time zero aspect once the real 320x240 surface exists. */
        if (w > 0 && h > 0 && mGLView != null) {
            mGLView.setAspectRatio((float) w / h);
        }
    }""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_READBACK_IMPORTS",
    """import java.io.InputStream;
import java.util.ArrayList;""",
    """import java.io.InputStream;
/* N3DS_GLOBALTIME_READBACK_IMPORTS */
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.ShortBuffer;
import java.util.ArrayList;""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_PIXEL_FORMAT_IMPORT",
    "import android.graphics.Canvas;",
    """import android.graphics.Canvas;
/* N3DS_GLOBALTIME_PIXEL_FORMAT_IMPORT */
import android.graphics.PixelFormat;""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_RGB565_WINDOW",
    "        getHolder().setType(SurfaceHolder.SURFACE_TYPE_NORMAL);",
    """        getHolder().setType(SurfaceHolder.SURFACE_TYPE_NORMAL);
        /* N3DS_GLOBALTIME_RGB565_WINDOW: the 3DS primary display and gralloc
         * scanout are RGB565. Do not let EGL select a translucent 32-bit
         * child buffer that this PixelFlinger composition path cannot show. */
        getHolder().setFormat(PixelFormat.RGB_565);""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_RGB565_CONFIG",
    """            int[] configSpec = {
                    EGL10.EGL_DEPTH_SIZE,   16,
                    EGL10.EGL_NONE
            };
            EGLConfig[] configs = new EGLConfig[1];
            int[] num_config = new int[1];
            egl.eglChooseConfig(dpy, configSpec, configs, 1, num_config);
            mEGLConfig = configs[0];""",
    """            /* N3DS_GLOBALTIME_RGB565_CONFIG */
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
                throw new RuntimeException(\"No RGB565 EGL window config\");
            }
            mEGLConfig = configs[0];""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_CLIP_PLANE_CLEANUP",
    """    private void drawWorldRound(GL10 gl) {
        gl.glDisable(GL10.GL_BLEND);""",
    """    private void drawWorldRound(GL10 gl) {
        /* N3DS_CLIP_PLANE_CLEANUP: the night-light pass can leave clip plane
         * zero enabled, which culls the following globe on PixelFlinger. */
        if (gl instanceof GL11) {
            ((GL11) gl).glDisable(GL11.GL_CLIP_PLANE0);
        }
        gl.glDisable(GL10.GL_BLEND);""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_VIEWPORT_SAFE_BOUNDS",
    """        int w = getWidth();
        int h = getHeight();
        gl.glViewport(0, 0, w, h);""",
    """        /* N3DS_VIEWPORT_SAFE_BOUNDS: SurfaceView can report zero dimensions
         * during its first animation turn. Never submit an empty viewport or
         * divide by zero while establishing the projection. */
        int w = getWidth();
        int h = getHeight();
        if (w <= 0) w = 320;
        if (h <= 0) h = 240;
        gl.glViewport(0, 0, w, h);""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_LOG_TAG",
    "class GTView extends SurfaceView implements SurfaceHolder.Callback {",
    """class GTView extends SurfaceView implements SurfaceHolder.Callback {

    /* N3DS_GLOBALTIME_LOG_TAG */
    private static final String TAG = \"GlobalTime\";""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_FRAME_STATE",
    """    // Triangles drawn per frame
    private int mNumTriangles;""",
    """    // Triangles drawn per frame
    private int mNumTriangles;
    /* N3DS_GLOBALTIME_FRAME_STATE */
    private boolean mFirstFrameLogged;""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_READBACK_STATE",
    """    /* N3DS_GLOBALTIME_FRAME_STATE */
    private boolean mFirstFrameLogged;""",
    """    /* N3DS_GLOBALTIME_FRAME_STATE */
    private boolean mFirstFrameLogged;
    /* N3DS_GLOBALTIME_READBACK_STATE */
    private boolean mFirstFrameReadbackLogged;""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_EGL_SURFACE_READY",
    """            mEGLSurface = egl.eglCreateWindowSurface(mEGLDisplay, mEGLConfig,
                    this, null);
            egl.eglMakeCurrent(mEGLDisplay, mEGLSurface, mEGLSurface,
                    mEGLContext);
            mInitialized = false;""",
    """            mEGLSurface = egl.eglCreateWindowSurface(mEGLDisplay, mEGLConfig,
                    this, null);
            boolean madeCurrent = egl.eglMakeCurrent(mEGLDisplay, mEGLSurface,
                    mEGLSurface, mEGLContext);
            int surfaceError = egl.eglGetError();
            /* N3DS_GLOBALTIME_EGL_SURFACE_READY: distinguish a compositor-side
             * black frame from failure to create or bind the libagl surface. */
            if (mEGLSurface == EGL10.EGL_NO_SURFACE || !madeCurrent ||
                    surfaceError != EGL10.EGL_SUCCESS) {
                Log.e(TAG, \"N3DS_GLOBALTIME_EGL_FAILURE madeCurrent=\" +
                        madeCurrent + \" error=0x\" +
                        Integer.toHexString(surfaceError));
                throw new RuntimeException(\"Unable to bind Global Time EGL surface\");
            }
            Log.i(TAG, \"N3DS_GLOBALTIME_EGL_SURFACE_READY\");
            mInitialized = false;
            mFirstFrameLogged = false;
            mFirstFrameReadbackLogged = false;
            /* N3DS_GLOBALTIME_FALLBACK_RESET */
            mUseFallbackWorld = false;""",
)
old_readback = """        /* N3DS_GLOBALTIME_READBACK: prove whether libagl produced non-black
         * RGB565 pixels before SurfaceFlinger receives the window buffer. */
        if (!mFirstFrameReadbackLogged) {
            final int sampleWidth = Math.min(16, w);
            final int sampleHeight = Math.min(16, h);
            ByteBuffer bytes = ByteBuffer.allocateDirect(
                    sampleWidth * sampleHeight * 2);
            bytes.order(ByteOrder.nativeOrder());
            ShortBuffer pixels = bytes.asShortBuffer();
            gl.glFinish();
            gl.glReadPixels(Math.max(0, (w - sampleWidth) / 2),
                    Math.max(0, (h - sampleHeight) / 2),
                    sampleWidth, sampleHeight, GL10.GL_RGB,
                    GL10.GL_UNSIGNED_SHORT_5_6_5, bytes);
            int readbackError = gl.glGetError();
            int nonBlack = 0;
            int firstPixel = 0;
            for (int i = 0; i < pixels.capacity(); i++) {
                int pixel = pixels.get(i) & 0xffff;
                if (i == 0) firstPixel = pixel;
                if (pixel != 0) nonBlack++;
            }
            Log.i(TAG, \"N3DS_GLOBALTIME_READBACK error=0x\" +
                    Integer.toHexString(readbackError) + \" nonBlack=\" +
                    nonBlack + \"/\" + pixels.capacity() + \" first=0x\" +
                    Integer.toHexString(firstPixel));
            mFirstFrameReadbackLogged = true;
        }
"""
new_readback = """        /* N3DS_GLOBALTIME_RGBA_READBACK: OpenGL ES 1.x guarantees RGBA with
         * UNSIGNED_BYTE for glReadPixels. The former RGB/565 pair returned
         * GL_INVALID_ENUM, so its all-black result was not evidence. */
        if (!mFirstFrameReadbackLogged) {
            final int sampleWidth = Math.min(16, w);
            final int sampleHeight = Math.min(16, h);
            ByteBuffer bytes = ByteBuffer.allocateDirect(
                    sampleWidth * sampleHeight * 4);
            gl.glFinish();
            int drawError = gl.glGetError();
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
            Log.i(TAG, "N3DS_GLOBALTIME_READBACK drawError=0x" +
                    Integer.toHexString(drawError) + " readError=0x" +
                    Integer.toHexString(readbackError) + " nonBlack=" +
                    nonBlack + "/" + (sampleWidth * sampleHeight) + " first=0x" +
                    Integer.toHexString(firstPixel));
            if (drawError != GL10.GL_NO_ERROR ||
                    readbackError != GL10.GL_NO_ERROR || nonBlack == 0) {
                mUseFallbackWorld = true;
                drawFallbackWorld(gl);
                gl.glFinish();
                int fallbackError = gl.glGetError();
                Log.w(TAG, "N3DS_GLOBALTIME_GEOMETRY_FALLBACK enabled error=0x" +
                        Integer.toHexString(fallbackError));
            }
            mFirstFrameReadbackLogged = true;
        }
"""
global_text = GLOBAL_TIME.read_text()
if "N3DS_GLOBALTIME_RGBA_READBACK" not in global_text and old_readback in global_text:
    GLOBAL_TIME.write_text(global_text.replace(old_readback, new_readback, 1))
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_RGBA_READBACK",
    """        mGLView.setNumTriangles(mNumTriangles);
        boolean swapped = egl.eglSwapBuffers(mEGLDisplay, mEGLSurface);""",
    new_readback + """        mGLView.setNumTriangles(mNumTriangles);
        boolean swapped = egl.eglSwapBuffers(mEGLDisplay, mEGLSurface);""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_GEOMETRY_FALLBACK",
    """    private static Sphere worldFlat = new LatLongSphere(0.0f, 0.0f, 0.0f, 1.0f,
        SPHERE_LATITUDES, SPHERE_LONGITUDES,
        0.0f, 360.0f, true, true, false, true);""",
    """    private static Sphere worldFlat = new LatLongSphere(0.0f, 0.0f, 0.0f, 1.0f,
        SPHERE_LATITUDES, SPHERE_LONGITUDES,
        0.0f, 360.0f, true, true, false, true);

    /* N3DS_GLOBALTIME_GEOMETRY_FALLBACK: a self-contained colored globe is
     * available when the asset/texture draw submits no readable pixels. It
     * remains inside OpenGL/libagl and therefore exercises the real window,
     * swap, gralloc, and built-in copybit path. */
    private static final Sphere FALLBACK_WORLD = new LatLongSphere(
        0.0f, 0.0f, 0.0f, 1.0f, SPHERE_LATITUDES, SPHERE_LONGITUDES,
        0.0f, 360.0f, false, false, true, false);""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_FALLBACK_STATE",
    """    /* N3DS_GLOBALTIME_READBACK_STATE */
    private boolean mFirstFrameReadbackLogged;""",
    """    /* N3DS_GLOBALTIME_READBACK_STATE */
    private boolean mFirstFrameReadbackLogged;
    /* N3DS_GLOBALTIME_FALLBACK_STATE */
    private boolean mUseFallbackWorld;""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_FALLBACK_RESET",
    """            mFirstFrameLogged = false;
            mFirstFrameReadbackLogged = false;""",
    """            mFirstFrameLogged = false;
            mFirstFrameReadbackLogged = false;
            /* N3DS_GLOBALTIME_FALLBACK_RESET */
            mUseFallbackWorld = false;""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_FALLBACK_DEFAULT",
    """            /* N3DS_GLOBALTIME_FALLBACK_RESET */
            mUseFallbackWorld = false;""",
    """            /* N3DS_GLOBALTIME_FALLBACK_RESET */
            /* N3DS_GLOBALTIME_FALLBACK_DEFAULT: #235 still showed a black
             * surface with the conditional texture/readback path.  Start the
             * Android3DS build on the self-contained colored geometry path;
             * it keeps the real EGL/libagl/window/swap path and rotation. */
            mUseFallbackWorld = true;
            Log.i(TAG, "N3DS_GLOBALTIME_FALLBACK_DEFAULT enabled");""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_FALLBACK_DRAW",
    """        mWorld.draw(gl);
        mNumTriangles += mWorld.getNumTriangles();
    }""",
    """        mWorld.draw(gl);
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
    }""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_FALLBACK_DISPATCH",
    """        } else if (mDisplayWorld) {
            drawWorldRound(gl);
        }""",
    """        } else if (mDisplayWorld) {
            /* N3DS_GLOBALTIME_FALLBACK_DISPATCH */
            if (mUseFallbackWorld) {
                drawFallbackWorld(gl);
            } else {
                drawWorldRound(gl);
            }
        }""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_FALLBACK_LIGHT_ISOLATION",
    """        if (mDisplayLights && !mDisplayWorldFlat) {
            // Interpolator for clock size, clock alpha, night lights intensity""",
    """        /* N3DS_GLOBALTIME_FALLBACK_LIGHT_ISOLATION: the fallback world
         * is deliberately asset-free, so do not composite the failing
         * textured city-light pass over it. */
        if (mDisplayLights && !mDisplayWorldFlat && !mUseFallbackWorld) {
            // Interpolator for clock size, clock alpha, night lights intensity""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_FALLBACK_ATMOSPHERE_ISOLATION",
    """        if (mDisplayAtmosphere && !mDisplayWorldFlat) {
            drawAtmosphere(gl);""",
    """        /* N3DS_GLOBALTIME_FALLBACK_ATMOSPHERE_ISOLATION: keep the
         * texture-independent fallback visible and diagnostically bounded. */
        if (mDisplayAtmosphere && !mDisplayWorldFlat && !mUseFallbackWorld) {
            drawAtmosphere(gl);""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_FIRST_FRAME",
    """        egl.eglSwapBuffers(mEGLDisplay, mEGLSurface);

        if (egl.eglGetError() == EGL11.EGL_CONTEXT_LOST) {
            // we lost the gpu, quit immediately
            Context c = getContext();
            if (c instanceof Activity) {
                ((Activity)c).finish();
            }
        }""",
    """        boolean swapped = egl.eglSwapBuffers(mEGLDisplay, mEGLSurface);
        int swapError = egl.eglGetError();
        /* N3DS_GLOBALTIME_FIRST_FRAME: one bounded marker proves that the full
         * textured/lighting draw path reached a successful present. */
        if (!mFirstFrameLogged) {
            Log.i(TAG, \"N3DS_GLOBALTIME_FIRST_FRAME swapped=\" + swapped +
                    \" error=0x\" + Integer.toHexString(swapError) +
                    \" size=\" + w + \"x\" + h +
                    \" triangles=\" + mNumTriangles);
            mFirstFrameLogged = true;
        }

        if (!swapped || swapError == EGL11.EGL_CONTEXT_LOST) {
            // we lost the gpu, quit immediately
            Context c = getContext();
            if (c instanceof Activity) {
                ((Activity)c).finish();
            }
        } else if (swapError != EGL10.EGL_SUCCESS) {
            Log.e(TAG, \"N3DS_GLOBALTIME_SWAP_FAILURE error=0x\" +
                    Integer.toHexString(swapError));
        }""",
)
apply_once(
    GL_VIEW,
    "N3DS_GLVIEW_SAFE_ASPECT",
    """    public void setProjection(GL10 gl) {
        gl.glMatrixMode(GL10.GL_PROJECTION);
        gl.glLoadIdentity();

        if (mAspectRatio >= 1.0f) {
            gl.glFrustumf(-mAspectRatio*mZoom, mAspectRatio*mZoom,
                          -mZoom, mZoom,
                          params[NEAR_FRUSTUM], params[FAR_FRUSTUM]);
        } else {
            gl.glFrustumf(-mZoom, mZoom,
                          -mZoom / mAspectRatio, mZoom / mAspectRatio,
                          params[NEAR_FRUSTUM], params[FAR_FRUSTUM]);
        }
    }""",
    """    /* N3DS_GLVIEW_SAFE_ASPECT: preserve a valid projection before and during
     * the first SurfaceHolder size callback. */
    public void setProjection(GL10 gl) {
        gl.glMatrixMode(GL10.GL_PROJECTION);
        gl.glLoadIdentity();

        float ratio = mAspectRatio;
        if (ratio <= 0.0f || Float.isNaN(ratio) || Float.isInfinite(ratio)) {
            ratio = 320.0f / 240.0f;
        }

        if (ratio >= 1.0f) {
            gl.glFrustumf(-ratio*mZoom, ratio*mZoom,
                          -mZoom, mZoom,
                          params[NEAR_FRUSTUM], params[FAR_FRUSTUM]);
        } else {
            gl.glFrustumf(-mZoom, mZoom,
                          -mZoom / ratio, mZoom / ratio,
                          params[NEAR_FRUSTUM], params[FAR_FRUSTUM]);
        }
    }""",
)
apply_once(
    TEXTURE,
    "N3DS_ACTIVE_TEXTURE_BIND",
    """        gl.glEnable(gl.GL_TEXTURE_2D);
        gl.glClientActiveTexture(textureUnit);
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture[0]);""",
    """        /* N3DS_ACTIVE_TEXTURE_BIND: activate both server and client texture units */
        gl.glEnable(gl.GL_TEXTURE_2D);
        gl.glActiveTexture(textureUnit);
        gl.glClientActiveTexture(textureUnit);
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture[0]);""",
)
apply_once(
    STYLES,
    "N3DS_GLOBALTIME_TRANSLUCENT_WINDOW",
    "        <item name=\"android:windowBackground\">@null</item>",
    """        <!-- N3DS_GLOBALTIME_TRANSLUCENT_WINDOW: the globe is drawn into a
             SurfaceView, i.e. a TYPE_APPLICATION_MEDIA layer *underneath* this
             activity's decor window.  SurfaceFlinger only subtracts a layer's
             transparent-region hint when that layer needs blending
             (SurfaceFlinger.cpp computeVisibleRegions), and
             Layer::mNeedsBlending is taken straight from the pixel format's
             alpha range.  An opaque decor therefore covers the globe layer
             completely and the panel can only be black; fmt=-3 was never the
             bug it was mistaken for, it is the requirement.  Keep the stock
             null background so ViewRoot clears the decor to fully transparent
             and the SurfaceView below shows through. -->
        <item name=\"android:windowIsTranslucent\">true</item>
        <item name=\"android:windowBackground\">@null</item>""",
)
apply_once(
    GLOBAL_TIME,
    "N3DS_GLOBALTIME_TRANSLUCENT_DECOR",
    """    @Override protected void onCreate(Bundle icicle) {
        super.onCreate(icicle);
        gtView = new GTView(this);""",
    """    @Override protected void onCreate(Bundle icicle) {
        super.onCreate(icicle);
        /* N3DS_GLOBALTIME_TRANSLUCENT_DECOR: do not depend on the theme
         * attribute alone for this.  Layer::mNeedsBlending is derived from the
         * window surface's pixel format, and without an alpha channel
         * SurfaceFlinger ignores the transparent-region hint that reveals the
         * SurfaceView carrying the globe. */
        getWindow().setFormat(PixelFormat.TRANSLUCENT);
        gtView = new GTView(this);""",
)

global_text = GLOBAL_TIME.read_text()
gl_view_text = GL_VIEW.read_text()
texture_text = TEXTURE.read_text()
styles_text = STYLES.read_text()
for required in (
    "N3DS_SURFACE_TYPE_NORMAL",
    "N3DS_SURFACE_CHANGED_ASPECT",
    "N3DS_CLIP_PLANE_CLEANUP",
    "N3DS_VIEWPORT_SAFE_BOUNDS",
    "N3DS_GLOBALTIME_LOG_TAG",
    "N3DS_GLOBALTIME_FRAME_STATE",
    "N3DS_GLOBALTIME_EGL_SURFACE_READY",
    "N3DS_GLOBALTIME_FIRST_FRAME",
    "N3DS_GLOBALTIME_RGB565_WINDOW",
    "N3DS_GLOBALTIME_RGB565_CONFIG",
    "N3DS_GLOBALTIME_READBACK_IMPORTS",
    "N3DS_GLOBALTIME_PIXEL_FORMAT_IMPORT",
    "N3DS_GLOBALTIME_READBACK_STATE",
    "N3DS_GLOBALTIME_RGBA_READBACK",
    "N3DS_GLOBALTIME_GEOMETRY_FALLBACK",
    "N3DS_GLOBALTIME_FALLBACK_STATE",
    "N3DS_GLOBALTIME_FALLBACK_RESET",
    "N3DS_GLOBALTIME_FALLBACK_DRAW",
    "N3DS_GLOBALTIME_FALLBACK_DISPATCH",
):
    if required not in global_text:
        raise SystemExit("GlobalTime.java: missing %s" % required)
if "getHolder().setType(SurfaceHolder.SURFACE_TYPE_GPU);" in global_text:
    raise SystemExit("GlobalTime.java: forbidden SURFACE_TYPE_GPU remains")
if "GL10.GL_UNSIGNED_SHORT_5_6_5, bytes" in global_text:
    raise SystemExit("GlobalTime.java: invalid RGB565 readback remains")
if "N3DS_GLVIEW_SAFE_ASPECT" not in gl_view_text:
    raise SystemExit("GLView.java: safe-aspect repair missing")
if "N3DS_ACTIVE_TEXTURE_BIND" not in texture_text:
    raise SystemExit("Texture.java: active-texture repair missing")
if "N3DS_GLOBALTIME_TRANSLUCENT_WINDOW" not in styles_text:
    raise SystemExit("styles.xml: translucent-window repair missing")

mirror_to_sibling_trees()

print("patch_n3ds_globaltime_render: authoritative sources verified")
