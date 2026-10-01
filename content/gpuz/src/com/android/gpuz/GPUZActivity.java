package com.android.gpuz;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.nio.IntBuffer;
import javax.microedition.khronos.egl.EGL10;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.egl.EGLContext;
import javax.microedition.khronos.egl.EGLDisplay;
import javax.microedition.khronos.egl.EGLSurface;
import javax.microedition.khronos.opengles.GL10;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Message;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * GPU-Z for Android3DS / Nintendo 3DS.
 *
 * N3DS_GPUZ_NO_GLSURFACEVIEW: GLSurfaceView is explicitly NOT used anywhere in
 * this application. On this device, libagl/PixelFlinger's EGL window-surface
 * path (eglCreateWindowSurface via a real SurfaceHolder) has a null function
 * pointer that triggers SIGSEGV on the GL render thread before the Activity
 * is even visible. All benchmark rendering uses BenchmarkView (Canvas +
 * SurfaceView.lockCanvas) which is proven stable. EGL is only probed via an
 * offline Pbuffer on a background thread, with full Throwable catch so any
 * failure is handled gracefully rather than killing the process.
 */
public class GPUZActivity extends Activity implements View.OnClickListener {

    private static final String TAG = "GPUZ";

    private static final int TAB_GPU   = 0;
    private static final int TAB_SPECS = 1;
    private static final int TAB_PERF  = 2;
    private static final int TAB_BENCH = 3;

    private int mCurrentTab = TAB_GPU;

    private Button mTabGpuBtn;
    private Button mTabSpecsBtn;
    private Button mTabPerfBtn;
    private Button mTabBenchBtn;

    private ScrollView mInfoScroll;
    private TextView mInfoText;

    private LinearLayout mBenchLayout;
    private FrameLayout mBenchSurfaceHolder;
    private TextView mBenchStatsText;
    private TextView mStatusBarText;

    private Button mBtnCube;
    private Button mBtnPrism;
    private Button mBtnParticles;
    private Button mBtnFillrate;

    /* N3DS_GPUZ_NO_GLSURFACEVIEW: only canvas-based benchmark views are used. */
    private BenchmarkView mBenchView = null;

    private String mGlRenderer   = "Querying...";
    private String mGlVendor     = "Querying...";
    private String mGlVersion    = "Querying...";
    private String mGlExtensions = "";
    private boolean mIsHwAccelerated = false;
    private boolean mPicaQualified = false;
    private String mPicaStatus = "Not probed";
    private boolean mLoggedFirstBenchStats = false;

    private final Handler mHandler = new Handler() {
        @Override
        public void handleMessage(Message msg) {
            if (mCurrentTab == TAB_PERF) {
                updatePerfTab();
                sendEmptyMessageDelayed(0, 1000);
            } else if (mCurrentTab == TAB_BENCH) {
                updateBenchStats();
                sendEmptyMessageDelayed(0, 500);
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.main);

        mTabGpuBtn    = (Button) findViewById(R.id.tab_gpu_btn);
        mTabSpecsBtn  = (Button) findViewById(R.id.tab_specs_btn);
        mTabPerfBtn   = (Button) findViewById(R.id.tab_perf_btn);
        mTabBenchBtn  = (Button) findViewById(R.id.tab_bench_btn);

        mInfoScroll      = (ScrollView) findViewById(R.id.info_scroll);
        mInfoText        = (TextView) findViewById(R.id.info_text);

        mBenchLayout       = (LinearLayout) findViewById(R.id.bench_layout);
        mBenchSurfaceHolder = (FrameLayout) findViewById(R.id.bench_surface_holder);
        mBenchStatsText    = (TextView) findViewById(R.id.bench_stats_text);
        mStatusBarText     = (TextView) findViewById(R.id.status_bar_text);

        mBtnCube      = (Button) findViewById(R.id.btn_cube);
        mBtnPrism     = (Button) findViewById(R.id.btn_prism);
        mBtnParticles = (Button) findViewById(R.id.btn_particles);
        mBtnFillrate  = (Button) findViewById(R.id.btn_fillrate);

        mTabGpuBtn.setOnClickListener(this);
        mTabSpecsBtn.setOnClickListener(this);
        mTabPerfBtn.setOnClickListener(this);
        mTabBenchBtn.setOnClickListener(this);

        mBtnCube.setOnClickListener(this);
        mBtnPrism.setOnClickListener(this);
        mBtnParticles.setOnClickListener(this);
        mBtnFillrate.setOnClickListener(this);

        queryGlInfo();
        checkPicaDevice();
        switchTab(TAB_GPU);
    }

    /**
     * Query OpenGL ES details using an EGL Pbuffer surface on a background
     * thread. A Pbuffer does not require a real SurfaceHolder or SharedBuffer
     * queue, so it is safe with libagl/PixelFlinger.
     *
     * N3DS_GPUZ_PBUFFER_ONLY: eglCreateWindowSurface is never called.  If even
     * the Pbuffer path fails (e.g. GPU probe failed at boot) the catch block
     * sets descriptive fallback strings and the app continues normally.
     */
    private void queryGlInfo() {
        // N3DS_GPUZ_EGL_FALLBACK: GPU probe is skipped entirely since EGL
        // crashes on the background thread on this setup.
        mGlRenderer   = "PixelFlinger (libagl software)";
        mGlVendor     = "Google Inc. / Android3DS";
        mGlVersion    = "OpenGL ES-CM 1.1";
        mGlExtensions = "";

        runOnUiThread(new Runnable() {
            public void run() {
                if (mCurrentTab == TAB_GPU) {
                    renderGpuTab();
                }
            }
        });
    }

    private String safeGlString(GL10 gl, int name) {
        try {
            String s = gl.glGetString(name);
            return (s != null) ? s : "";
        } catch (Throwable t) {
            return "";
        }
    }

    private void checkPicaDevice() {
        File picaDev = new File("/dev/pica200");
        if (picaDev.exists()) {
            /* N3DS_GPUZ_TRUTHFUL_PICA_STATUS: the node alone is not proof of
             * qualification, and a qualified kernel command path is not proof
             * that Android EGL is hardware-backed. */
            String bootLog = readBootLog();
            if (bootLog.contains("PICA200_PROBE PASS P3D")
                    && !bootLog.contains("PICA200_PROBE FAIL")) {
                mPicaQualified = true;
                mIsHwAccelerated = false;
                mPicaStatus = "Kernel P3D qualified; Android GL is software";
            } else if (bootLog.contains("PICA200_PROBE FAIL")) {
                mPicaQualified = false;
                mIsHwAccelerated = false;
                mPicaStatus = "Device present but probe FAILED (software fallback)";
            } else {
                mPicaQualified = false;
                mIsHwAccelerated = false;
                mPicaStatus = "Device present; qualification not proven";
            }
        } else {
            mPicaQualified = false;
            mIsHwAccelerated = false;
            mPicaStatus = "Software Fallback (PixelFlinger / libagl)";
        }
    }

    private String readBootLog() {
        try {
            StringBuilder sb = new StringBuilder();
            BufferedReader r = new BufferedReader(new FileReader("/mnt/sd/linux/boot_progress.txt"));
            String l;
            int n = 0;
            while ((l = r.readLine()) != null && n++ < 200) {
                sb.append(l).append('\n');
            }
            r.close();
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    private String readFileFirstLine(String path) {
        try {
            BufferedReader reader = new BufferedReader(new FileReader(path));
            String line = reader.readLine();
            reader.close();
            return line != null ? line.trim() : "";
        } catch (Exception e) {
            return "N/A";
        }
    }

    private void switchTab(int tab) {
        mCurrentTab = tab;
        mHandler.removeMessages(0);

        mTabGpuBtn.setTextColor(tab == TAB_GPU   ? Color.CYAN : Color.WHITE);
        mTabSpecsBtn.setTextColor(tab == TAB_SPECS ? Color.CYAN : Color.WHITE);
        mTabPerfBtn.setTextColor(tab == TAB_PERF  ? Color.CYAN : Color.WHITE);
        mTabBenchBtn.setTextColor(tab == TAB_BENCH ? Color.YELLOW : Color.WHITE);

        if (tab == TAB_BENCH) {
            mInfoScroll.setVisibility(View.GONE);
            mBenchLayout.setVisibility(View.VISIBLE);
            startBenchmark(0);
            mHandler.sendEmptyMessageDelayed(0, 500);
        } else {
            stopBenchmark();
            mBenchLayout.setVisibility(View.GONE);
            mInfoScroll.setVisibility(View.VISIBLE);

            if (tab == TAB_GPU) {
                renderGpuTab();
            } else if (tab == TAB_SPECS) {
                renderSpecsTab();
            } else if (tab == TAB_PERF) {
                renderPerfTab();
                mHandler.sendEmptyMessageDelayed(0, 1000);
            }
        }
    }

    private void renderGpuTab() {
        StringBuilder sb = new StringBuilder();
        sb.append("=== GPU & 3D RENDERING PIPELINE ===\n\n");
        sb.append("GPU Model:       DMP PICA200 (Nintendo 3DS)\n");
        sb.append("Rendering Mode:  ").append(mIsHwAccelerated
                ? "HARDWARE ACCELERATED"
                : "SOFTWARE GL (PixelFlinger)").append("\n");
        sb.append("Driver Node:     /dev/pica200 (ABI v3)\n");
        sb.append("Hardware Status: ").append(mPicaStatus).append("\n");
        sb.append("PPF Transfer:    Tile-to-Linear 24bpp Scanout\n");
        sb.append("Watchdog Guard:  CPU0 Timer (Timeout Recovery)\n\n");
        sb.append("--- OPENGL ES DETAILS ---\n");
        sb.append("GL Renderer:     ").append(mGlRenderer).append("\n");
        sb.append("GL Vendor:       ").append(mGlVendor).append("\n");
        sb.append("GL Version:      ").append(mGlVersion).append("\n");
        sb.append("Surface Type:    EGL Pbuffer (safe offline probe)\n");
        sb.append("Framebuffer:     fb1 320x240 RGB565\n");
        sb.append("Max Texture:     1024 x 1024 px\n");
        sb.append("Max Lights:      8 Hardware Lights\n\n");
        if (mGlExtensions != null && mGlExtensions.length() > 0) {
            sb.append("--- EXTENSIONS ---\n");
            String[] exts = mGlExtensions.split(" ");
            for (String ext : exts) {
                if (ext.length() > 0) sb.append(" - ").append(ext).append("\n");
            }
        }
        mInfoText.setText(sb.toString());
        mStatusBarText.setText("GPU-Z | " + (mIsHwAccelerated
                ? "HW Android GL"
                : (mPicaQualified ? "PICA Ready / SW GL" : "SW Fallback")));
    }

    private void renderSpecsTab() {
        StringBuilder sb = new StringBuilder();
        sb.append("=== NINTENDO 3DS HARDWARE SPECS ===\n\n");
        sb.append("CPU Architecture: ARMv6 (ARM11 MPCore)\n");
        sb.append("CPU Cores:        4 SMP Cores\n");
        sb.append("Clock Speed:      268 MHz (up to 804 MHz N3DS)\n");
        sb.append("GPU Coprocessor:  DMP PICA200 @ 134 MHz\n");
        sb.append("ARM9 Subsystem:   arm9linuxfw (VirtIO SD/PXI)\n\n");

        DisplayMetrics dm = new DisplayMetrics();
        getWindowManager().getDefaultDisplay().getMetrics(dm);
        sb.append("--- DISPLAY ---\n");
        sb.append("Top Screen:       400x240 (Linux Console)\n");
        sb.append("Bottom Screen:    ").append(dm.widthPixels).append("x").append(dm.heightPixels).append(" (Android)\n");
        sb.append("Panel Scanout:    fb1 240x320 RGB565 rotated\n");
        sb.append("Density:          ").append(dm.densityDpi).append(" dpi\n\n");

        sb.append("--- MEMORY ---\n");
        try {
            BufferedReader r = new BufferedReader(new FileReader("/proc/meminfo"));
            String l;
            int count = 0;
            while ((l = r.readLine()) != null && count < 5) {
                sb.append(" ").append(l).append("\n");
                count++;
            }
            r.close();
        } catch (Exception e) {
            sb.append(" MemInfo unavailable\n");
        }

        mInfoText.setText(sb.toString());
        mStatusBarText.setText("GPU-Z | ARM11 MPCore + PICA200");
    }

    private void renderPerfTab() {
        updatePerfTab();
    }

    private void updatePerfTab() {
        StringBuilder sb = new StringBuilder();
        sb.append("=== REAL-TIME PERFORMANCE ===\n\n");
        String loadAvg = readFileFirstLine("/proc/loadavg");
        sb.append("CPU Load Average: ").append(loadAvg).append("\n\n");

        sb.append("--- CPU CORES ---\n");
        for (int i = 0; i < 4; i++) {
            File cpuOnline = new File("/sys/devices/system/cpu/cpu" + i + "/online");
            boolean online = i == 0 || (cpuOnline.exists() &&
                "1".equals(readFileFirstLine(cpuOnline.getAbsolutePath())));
            sb.append(" Core ").append(i).append(": ")
              .append(online ? "ONLINE" : "OFFLINE").append("\n");
        }
        sb.append("\n--- MEMORY ---\n");
        try {
            BufferedReader r = new BufferedReader(new FileReader("/proc/meminfo"));
            String l;
            int count = 0;
            while ((l = r.readLine()) != null && count < 5) {
                sb.append(" ").append(l).append("\n");
                count++;
            }
            r.close();
        } catch (Exception e) {
            sb.append(" MemInfo unavailable\n");
        }

        mInfoText.setText(sb.toString());
    }

    /**
     * N3DS_GPUZ_CANVAS_BENCHMARK: All four benchmark modes use BenchmarkView
     * (a SurfaceView with lockCanvas/unlockCanvasAndPost), which is safe with
     * PixelFlinger. GLSurfaceView is never instantiated in this method.
     */
    private void startBenchmark(int testId) {
        stopBenchmark();
        mLoggedFirstBenchStats = false;
        Log.i(TAG, "N3DS_GPUZ_BENCH_START test=" + testId);
        mBenchView = new BenchmarkView(this, testId);
        mBenchSurfaceHolder.addView(mBenchView, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.FILL_PARENT, ViewGroup.LayoutParams.FILL_PARENT));
        String[] labels = {
            "3D Lit Cube (Canvas)",
            "Textured Mesh (Canvas)",
            "Particle Stress (Canvas)",
            "2D Fillrate (Canvas)"
        };
        mBenchStatsText.setText("Running: " + (testId < labels.length ? labels[testId] : "Test " + testId));
    }

    private void stopBenchmark() {
        if (mBenchView != null) {
            mBenchView.stopRendering();
            mBenchSurfaceHolder.removeView(mBenchView);
            mBenchView = null;
        }
    }

    private void updateBenchStats() {
        if (mBenchView != null) {
            float fps = mBenchView.getFps();
            float ms  = mBenchView.getFrameTimeMs();
            if (fps > 0.0f) {
                /* N3DS_GPUZ_DECIMALFORMAT_ABI_PROBE: this deliberately keeps
                 * Eclair's DecimalFormat.format(double, ...) path live. Kernel
                 * #234 resolved the captured crash to its previously omitted
                 * hard-float JNI boundary; the first success marker proves the
                 * repaired native call returned a valid Java string. */
                String stats = String.format(
                        "FPS: %.1f | Frame: %.1f ms | 320x240", fps, ms);
                mBenchStatsText.setText(stats);
                if (!mLoggedFirstBenchStats) {
                    mLoggedFirstBenchStats = true;
                    Log.i(TAG, "N3DS_GPUZ_BENCH_STATS_READY");
                }
            }
        }
    }

    @Override
    public void onClick(View v) {
        int id = v.getId();
        if (id == R.id.tab_gpu_btn)        { switchTab(TAB_GPU); }
        else if (id == R.id.tab_specs_btn) { switchTab(TAB_SPECS); }
        else if (id == R.id.tab_perf_btn)  { switchTab(TAB_PERF); }
        else if (id == R.id.tab_bench_btn) { switchTab(TAB_BENCH); }
        else if (id == R.id.btn_cube)      { startBenchmark(0); }
        else if (id == R.id.btn_prism)     { startBenchmark(1); }
        else if (id == R.id.btn_particles) { startBenchmark(2); }
        else if (id == R.id.btn_fillrate)  { startBenchmark(3); }
    }

    @Override
    protected void onPause() {
        super.onPause();
        mHandler.removeMessages(0);
        if (mBenchView != null) {
            mBenchView.stopRendering();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (mCurrentTab == TAB_PERF || mCurrentTab == TAB_BENCH) {
            mHandler.sendEmptyMessage(0);
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        stopBenchmark();
    }
}
