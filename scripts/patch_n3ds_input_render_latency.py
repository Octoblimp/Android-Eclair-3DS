#!/usr/bin/env python3
"""Bound touch delivery and remove the measured software-post hot spots."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
TOUCH = ROOT / "third_party/linux/drivers/platform/nintendo3ds/tsc/touch.c"
POLICY = ROOT / ("third_party/frameworks/policies/base/phone/com/android/"
                 "internal/policy/impl/PhoneWindowManager.java")
GLOBAL_ACTIONS = ROOT / ("third_party/frameworks/policies/base/phone/com/android/"
                         "internal/policy/impl/GlobalActions.java")
FRAMEBUFFER = ROOT / "third_party/libhardware/modules/gralloc/framebuffer.cpp"
HAL_LOOKUP = ROOT / ("third_party/libhardware/modules/gralloc/"
                     "hw_get_module_static.cpp")
GRALLOC_PRIV = ROOT / "third_party/libhardware/modules/gralloc/gralloc_priv.h"
PICA_UAPI = ROOT / "third_party/linux/include/uapi/linux/ctr_pica.h"
PICA_GRALLOC_HEADER = ROOT / ("third_party/libhardware/modules/gralloc/"
                              "ctr_pica_uapi.h")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# Keep gralloc's build independent of kernel include-path internals while using
# the exact generated ABI header as its single source of truth.
PICA_GRALLOC_HEADER.write_text(PICA_UAPI.read_text())


touch = TOUCH.read_text()
if "N3DS_TOUCH_LATEST_SAMPLE_DELIVERY" not in touch:
    touch = replace_once(
        touch,
        "#include <linux/input.h>\n",
        "#include <linux/input.h>\n#include <linux/jiffies.h>\n",
        "touch jiffies include")
    touch = replace_once(
        touch,
        "#define POLL_INTERVAL_MS 1\n",
        "#define POLL_INTERVAL_MS 1\n"
        "/* Keep the requested 1 ms ADC sampling, but do not enqueue 1000 old\n"
        " * MotionEvents per second into Eclair. Deliver the newest sample at\n"
        " * 125 Hz; DOWN and UP remain immediate. */\n"
        "#define REPORT_INTERVAL_MS 8\n",
        "touch report interval")
    touch = replace_once(
        touch,
        "\tunsigned int polls;\n",
        "\tunsigned int polls;\n\tunsigned long last_report;\n",
        "touch timestamp field")
    old = """\tif (down) {
\t\tx = scale_axis(raw_x, raw_min_x, raw_max_x, SCREEN_WIDTH);
\t\ty = scale_axis(raw_y, raw_min_y, raw_max_y, SCREEN_HEIGHT);
\t\tts->last_x = x;
\t\tts->last_y = y;
\t\tinput_report_abs(input, ABS_X, x);
\t\tinput_report_abs(input, ABS_Y, y);
"""
    new = """\tif (down) {
\t\tx = scale_axis(raw_x, raw_min_x, raw_max_x, SCREEN_WIDTH);
\t\ty = scale_axis(raw_y, raw_min_y, raw_max_y, SCREEN_HEIGHT);
\t\t/* N3DS_TOUCH_LATEST_SAMPLE_DELIVERY: input-polldev invokes us every
\t\t * real 1 ms tick. Eclair's pre-batched input queue otherwise preserves
\t\t * every sample while the 268 MHz compositor is drawing, producing the
\t\t * measured multi-second trail. Skip stale intermediate coordinates and
\t\t * publish the newest one at a still-fast 125 Hz. */
\t\tif (ts->down && time_before(jiffies, ts->last_report +
\t\t\t\tmsecs_to_jiffies(REPORT_INTERVAL_MS))) {
\t\t\tts->down = down;
\t\t\treturn;
\t\t}
\t\tif (ts->down && x == ts->last_x && y == ts->last_y) {
\t\t\tts->down = down;
\t\t\treturn;
\t\t}
\t\tts->last_x = x;
\t\tts->last_y = y;
\t\tts->last_report = jiffies;
\t\tinput_report_abs(input, ABS_X, x);
\t\tinput_report_abs(input, ABS_Y, y);
"""
    touch = replace_once(touch, old, new, "touch delivery block")
TOUCH.write_text(touch)


policy = POLICY.read_text()
if "N3DS_SELECT_DIRECT_GLOBAL_ACTIONS" not in policy:
    needle = """        if (type == RawInputEvent.EV_KEY) {
            if (code == KeyEvent.KEYCODE_ENDCALL
                    || code == KeyEvent.KEYCODE_POWER) {
"""
    replacement = """        if (type == RawInputEvent.EV_KEY) {
            // N3DS_SELECT_DIRECT_GLOBAL_ACTIONS: ctr_navkey has already
            // verified a physical 0.5-second SELECT hold before it emits
            // POWER. Do not start Eclair's second 500 ms timer: the UI handler
            // was measured more than 650 ms behind during composition, so UP
            // removed the callback before it ran. Queue the native dialog once
            // and consume both synthetic POWER edges here.
            if ("n3ds".equals(SystemProperties.get("ro.product.device"))
                    && code == KeyEvent.KEYCODE_POWER) {
                result &= ~ACTION_PASS_TO_USER;
                if (down) {
                    Log.i(TAG, "n3ds SELECT hold: showing GlobalActions");
                    mHandler.post(mPowerLongPress);
                }
                return result;
            }
            if (code == KeyEvent.KEYCODE_ENDCALL
                    || code == KeyEvent.KEYCODE_POWER) {
"""
    policy = replace_once(policy, needle, replacement, "direct SELECT policy")
POLICY.write_text(policy)


# This target intentionally has no AudioService.  The stock Eclair dialog
# assumes one exists both while preparing the menu and when its silent-mode
# item is pressed.  Keep Android's native dialog, but remove that inapplicable
# action and guard its state update instead of letting system_server die.
global_actions = GLOBAL_ACTIONS.read_text()
if "N3DS_POWER_MENU_WITHOUT_AUDIO_SERVICE" not in global_actions:
    global_actions = replace_once(
        global_actions,
        "                });\n\n        mAdapter = new MyAdapter();\n",
        "                });\n\n"
        "        // N3DS_POWER_MENU_WITHOUT_AUDIO_SERVICE: this image does not\n"
        "        // start AudioService. Omit the silent action so displaying or\n"
        "        // pressing it cannot dereference a null AudioManager.\n"
        "        if (android.os.ServiceManager.checkService(Context.AUDIO_SERVICE) == null) {\n"
        "            mItems.remove(mSilentModeToggle);\n"
        "        }\n\n"
        "        mAdapter = new MyAdapter();\n",
        "audio-less GlobalActions items")
    global_actions = replace_once(
        global_actions,
        "        final boolean silentModeOn =\n"
        "                mAudioManager.getRingerMode() != AudioManager.RINGER_MODE_NORMAL;\n"
        "        mSilentModeToggle.updateState(\n"
        "                silentModeOn ? ToggleAction.State.On : ToggleAction.State.Off);\n",
        "        if (mAudioManager != null && android.os.ServiceManager.checkService(Context.AUDIO_SERVICE) != null) {\n"
        "            final boolean silentModeOn = mAudioManager.getRingerMode()\n"
        "                    != AudioManager.RINGER_MODE_NORMAL;\n"
        "            mSilentModeToggle.updateState(silentModeOn\n"
        "                    ? ToggleAction.State.On : ToggleAction.State.Off);\n"
        "        }\n",
        "audio-less GlobalActions preparation")
GLOBAL_ACTIONS.write_text(global_actions)


framebuffer = FRAMEBUFFER.read_text()
start = framebuffer.index("static void n3ds_blit(")
end = framebuffer.index("\nstatic int fb_post", start)
new_function = r'''static void n3ds_blit(private_module_t* m, uint8_t* dstBase, const uint16_t* src)
{
    const int canvasW = m->info.xres;         /* 320 */
    const int canvasH = m->info.yres;         /* 240 */
    const int span    = m->n3ds_panel_xres;   /* 240 */
    const int stride  = m->n3ds_panel_stride;
    const int srcStrideIn16 = m->finfo.line_length >> 1;
    const int c0 = m->n3ds_chan[0];
    const int c1 = m->n3ds_chan[1];
    const int c2 = m->n3ds_chan[2];

    /* N3DS_DIRTY_ROW_SCANOUT: full-frame cache-friendly scanout ensures
     * both double-buffered framebuffers remain 100% synchronized and free of
     * ghost rows or boot artifacts across flips. */

    /* N3DS_CACHE_FRIENDLY_ROTATE_V2: precompute the logical source row for
     * every physical framebuffer column once per post. */
    int sourceRow[N3DS_PANEL_XRES];
    for (int fbx = 0; fbx < span; fbx++) {
        int y = span - 1 + m->n3ds_y_offset - fbx;
        while (y >= span) y -= span;
        while (y < 0) y += span;
        sourceRow[fbx] = y;
    }

    for (int x = 0; x < canvasW; x++) {
        uint8_t* d = dstBase + (size_t)x * stride;
        for (int fbx = 0; fbx < span; fbx++, d += 3) {
            const int y = sourceRow[fbx];
            const uint16_t p = src[(size_t)y * srcStrideIn16 + x];
            /* Standard RGB565 bit replication after cache-friendly transpose. */
            const uint8_t r5 = (uint8_t)((p >> 11) & 0x1F);
            const uint8_t g6 = (uint8_t)((p >>  5) & 0x3F);
            const uint8_t b5 = (uint8_t)( p        & 0x1F);
            const uint8_t rgb[3] = {
                (uint8_t)((r5 << 3) | (r5 >> 2)),
                (uint8_t)((g6 << 2) | (g6 >> 4)),
                (uint8_t)((b5 << 3) | (b5 >> 2))
            };
            d[0] = rgb[c0];
            d[1] = rgb[c1];
            d[2] = rgb[c2];
        }
    }
}
'''
framebuffer = framebuffer[:start] + new_function + framebuffer[end:]
FRAMEBUFFER.write_text(framebuffer)


priv = GRALLOC_PRIV.read_text()
pica_fields = '''
    /* N3DS_PICA_GRALLOC_DMA_FIELDS: SurfaceFlinger's two canvas
     * buffers come from the kernel GPU allocator when available. */
    int      n3ds_pica_fd;
    uint32_t n3ds_pica_handle;
    uint32_t n3ds_pica_gpu_address;
'''
priv = priv.replace(pica_fields, "")
GRALLOC_PRIV.write_text(priv)


framebuffer = FRAMEBUFFER.read_text()
if ("N3DS_CACHE_FRIENDLY_ROTATE" in framebuffer
        and "Standard RGB565 bit replication after cache-friendly transpose" not in framebuffer):
    framebuffer = framebuffer.replace(
        "                const uint8_t r5 = (uint8_t)((p >> 11) & 0x1F);",
        "                /* Standard RGB565 bit replication after cache-friendly transpose. */\n"
        "                const uint8_t r5 = (uint8_t)((p >> 11) & 0x1F);", 1)
framebuffer = framebuffer.replace("#include <linux/ctr_pica.h>",
                                  "#include \"ctr_pica_uapi.h\"")
framebuffer = framebuffer.replace('open("/dev/pica200", O_RDWR | O_CLOEXEC, 0)',
                                  'open("/dev/pica200", O_RDWR, 0)')
ashmem_pool = r'''    int poolFd = ashmem_create_region("n3ds-fb", poolSize);
    if (poolFd < 0) {
        LOGE("gralloc: cannot create the %zu byte framebuffer pool: %s",
             poolSize, strerror(errno));
        munmap(module->n3ds_panel, module->n3ds_panel_size);
        module->n3ds_panel = NULL;
        close(fd);
        module->n3ds_fd = -1;
        return -errno;
    }

    void* vaddr = mmap(0, poolSize, PROT_READ | PROT_WRITE, MAP_SHARED,
                       poolFd, 0);
    if (vaddr == MAP_FAILED) {
        LOGE("gralloc: cannot map the framebuffer pool: %s", strerror(errno));
        close(poolFd);
        munmap(module->n3ds_panel, module->n3ds_panel_size);
        module->n3ds_panel = NULL;
        close(fd);
        module->n3ds_fd = -1;
        return -errno;
    }
'''
pica_pool = r'''    /* N3DS_PICA_GRALLOC_DMA_POOL: make the compositor's native-window
     * buffers coherent and GPU-addressable through the protected kernel ABI.
     * No register mapping or physical allocator is exposed to userspace. */
    int poolFd = open("/dev/pica200", O_RDWR, 0);
    void* vaddr = MAP_FAILED;
    struct ctr_pica_alloc picaAlloc;
    memset(&picaAlloc, 0, sizeof(picaAlloc));
    module->n3ds_pica_fd = -1;
    module->n3ds_pica_handle = 0;
    module->n3ds_pica_gpu_address = 0;
    if (poolFd >= 0) {
        picaAlloc.size = poolSize;
        if (ioctl(poolFd, CTR_PICA_IOC_ALLOC, &picaAlloc) == 0) {
            vaddr = mmap(0, picaAlloc.size, PROT_READ | PROT_WRITE,
                         MAP_SHARED, poolFd,
                         (off_t)picaAlloc.handle * (off_t)getpagesize());
            if (vaddr != MAP_FAILED) {
                module->n3ds_pica_fd = poolFd;
                module->n3ds_pica_handle = picaAlloc.handle;
                module->n3ds_pica_gpu_address = picaAlloc.gpu_address;
                poolSize = picaAlloc.size;
                LOGI("gralloc: PICA coherent framebuffer pool handle=%u gpu=%08x size=%zu",
                     picaAlloc.handle, picaAlloc.gpu_address, poolSize);
            }
        }
        if (vaddr == MAP_FAILED) {
            if (picaAlloc.handle) {
                struct ctr_pica_free picaFree;
                memset(&picaFree, 0, sizeof(picaFree));
                picaFree.handle = picaAlloc.handle;
                ioctl(poolFd, CTR_PICA_IOC_FREE, &picaFree);
            }
            close(poolFd);
            poolFd = -1;
        }
    }
    if (vaddr == MAP_FAILED) {
        LOGW("gralloc: /dev/pica200 unavailable; using CPU-safe ashmem fallback");
        poolFd = ashmem_create_region("n3ds-fb", poolSize);
        if (poolFd >= 0)
            vaddr = mmap(0, poolSize, PROT_READ | PROT_WRITE, MAP_SHARED,
                         poolFd, 0);
    }
    if (poolFd < 0 || vaddr == MAP_FAILED) {
        LOGE("gralloc: cannot allocate the %zu byte framebuffer pool: %s",
             poolSize, strerror(errno));
        if (poolFd >= 0) close(poolFd);
        munmap(module->n3ds_panel, module->n3ds_panel_size);
        module->n3ds_panel = NULL;
        close(fd);
        module->n3ds_fd = -1;
        return -errno;
    }
'''
if "N3DS_PICA_GRALLOC_DMA_POOL" in framebuffer:
    framebuffer = replace_once(framebuffer, pica_pool, ashmem_pool,
                               "remove unproven PICA gralloc pool")
framebuffer = framebuffer.replace('#include "ctr_pica_uapi.h"\n', '')
framebuffer = framebuffer.replace(
    "    size_t poolSize = roundUpToPageSize(bufferSize * NUM_BUFFERS);\n",
    "    const size_t poolSize = roundUpToPageSize(bufferSize * NUM_BUFFERS);\n")
FRAMEBUFFER.write_text(framebuffer)


lookup = HAL_LOOKUP.read_text()
if "N3DS_QUIET_BUILTIN_HAL_LOOKUP" not in lookup:
    lookup = replace_once(
        lookup,
        "            LOGI(\"hw_get_module('%s') -> built-in\", id);\n",
        "            /* N3DS_QUIET_BUILTIN_HAL_LOOKUP: this is a hot path;\n"
        "             * successful lookups are routine, not log events. */\n",
        "quiet HAL lookup")
HAL_LOOKUP.write_text(lookup)

for path, marker in ((TOUCH, "N3DS_TOUCH_LATEST_SAMPLE_DELIVERY"),
                     (POLICY, "N3DS_SELECT_DIRECT_GLOBAL_ACTIONS"),
                     (GLOBAL_ACTIONS, "N3DS_POWER_MENU_WITHOUT_AUDIO_SERVICE"),
                     (FRAMEBUFFER, "N3DS_CACHE_FRIENDLY_ROTATE_V2"),
                     (HAL_LOOKUP, "N3DS_QUIET_BUILTIN_HAL_LOOKUP")):
    if path.read_text().count(marker) != 1:
        raise SystemExit(f"{path}: marker missing or duplicated")
if FRAMEBUFFER.read_text().count("N3DS_DIRTY_ROW_SCANOUT") != 1:
    raise SystemExit("dirty-row scanout marker missing or duplicated")

print("patch_n3ds_input_render_latency: latest touch, direct SELECT, tiled post")
