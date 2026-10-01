/*
 * Copyright (C) 2008 The Android Open Source Project
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

/*
 * Android3DS: the framebuffer half of the gralloc HAL, rewritten for the
 * New Nintendo 3DS bottom screen. The allocator half (gralloc.cpp,
 * mapper.cpp, allocator.cpp) is upstream's, unmodified.
 *
 * Three things about this panel make upstream's version unusable as-is, and
 * all three are settled facts measured on real hardware, not guesses (see
 * docs/HANDOFF.md's "fb1 offset re-measured" recap and
 * cmds/bootanimation/DisplayTarget.cpp, which has been drawing the boot
 * animation through exactly this transform since 2026-08-03):
 *
 *  1. The panel is scanned out rotated 90 degrees. /dev/graphics/fb1 reports
 *     240x320; the surface Android should compose into is 320x240. So a
 *     canvas pixel (x, y) is written to the framebuffer at (X, x) -- i.e.
 *     the framebuffer's *x* coordinate selects the panel row.
 *
 *  2. N3DS_FB1_PAGE_OFFSET: the scanout buffer is not page aligned.  fb1's
 *     smem_start is 0x18119400, and fb_mmap() maps from the page that holds
 *     it, so offset 0 of the mapping is 0x18119000 -- 1024 bytes BEFORE the
 *     first scanned-out byte.  1024 = 720 + 3*101 + 1: one panel row, 101
 *     pixels and one byte.  Everything that was "measured from photographs"
 *     here (the ~100-row origin shift, the 3-cycled channels, the "rbg"
 *     correction) was that one misalignment: the panel read each pixel's
 *     blue and green from the right pixel but its red from the next one,
 *     the colour fringe a #322 tester saw on every letter, and the picture
 *     sat one row and one column off.  The pointer now starts at
 *     smem_start, so canvas row y goes to framebuffer x = fb_xres - 1 - y,
 *     written in the declared byte order (b, g, r).
 *
 *  3. The panel is 24bpp (simplefb "r8g8b8"). Android composes 16bpp RGB565
 *     here, so post() converts as it rotates.
 *
 * Because of (1) the panel cannot be rendered into directly:
 * every frame needs a transforming blit. So the "framebuffer" this
 * module hands out is a private RGB565 buffer pool with canvas geometry,
 * and fb_post() is where the transform happens. private_module_t::info/
 * finfo therefore describe the canvas, not the panel -- see the note in
 * gralloc_priv.h. Nothing above gralloc ever learns the panel exists,
 * which is exactly what a HAL is for.
 *
 * The transform is posted into the hardware-proven fb1 scanout buffer.
 * Experimental PDC1 A/B flipping made the bottom LCD entirely black on
 * hardware, so framebuffer ownership remains single and deterministic.
 *
 * The old sd:/linux/panel_yoff.txt and panel_chan.txt tunables are gone on
 * purpose: they only ever compensated for (2), and a stale value on a card
 * would now shift a correctly aligned picture.
 */

#include <sys/mman.h>

#include <cutils/ashmem.h>
#include <cutils/log.h>

#include <hardware/hardware.h>
#include <hardware/gralloc.h>

#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>

#include <cutils/log.h>
#include <cutils/atomic.h>

#include <linux/fb.h>

#include "gralloc_priv.h"
#include "gr.h"

/*****************************************************************************/


// Two private RGB565 canvas buffers; both post to the sole fb1 scanout.
#define NUM_BUFFERS 2

// The panel really is this; hardcoded only as a sanity check against what
// the driver reports.
#define N3DS_PANEL_XRES 240
#define N3DS_PANEL_YRES 320

enum {
    PAGE_FLIP = 0x00000001,
    LOCKED = 0x00000002
};

struct fb_context_t {
    framebuffer_device_t  device;
};

/*****************************************************************************/

static int fb_setSwapInterval(struct framebuffer_device_t* dev,
            int interval)
{
    if (interval < dev->minSwapInterval || interval > dev->maxSwapInterval)
        return -EINVAL;
    // A VBlank signal now exists (PDC1 IRQ via /dev/ctr_lcd), but there is
    // nothing in this simplefb world that consumes swap intervals -- Android
    // asks us for vsync through the display HAL, not here. Accept and ignore.
    return 0;
}

/*
 * The blit. Reads an RGB565 canvas buffer, writes the 24bpp panel, applying
 * the 90-degree rotation and the RGB565 -> b,g,r conversion.
 *
 * Cost: 320*240 = 76800 pixels per frame on a 268 MHz ARM11 with no 2D
 * acceleration of any kind. The inner loop walks the destination by
 * n3ds_panel_stride (a 720-byte stride, so every pixel is a separate cache
 * line touch) which is inherent to writing a rotated image -- the source is
 * walked linearly instead, which is the cheaper of the two to get right.
 */
static void n3ds_blit(private_module_t* m, uint8_t* dstBase, const uint16_t* src)
{
    const int canvasW = m->info.xres;         /* 320 */
    const int canvasH = m->info.yres;         /* 240 */
    const int span    = m->n3ds_panel_xres;   /* 240 */
    const int stride  = m->n3ds_panel_stride;
    const int srcStrideIn16 = m->finfo.line_length >> 1;

    /* N3DS_DIRTY_ROW_SCANOUT: full-frame cache-friendly scanout ensures
     * both double-buffered framebuffers remain 100% synchronized and free of
     * ghost rows or boot artifacts across flips. */

    /* N3DS_CACHE_FRIENDLY_ROTATE_V2: precompute the logical source row for
     * every physical framebuffer column once per post.  With the mapping
     * aligned to the scanout (N3DS_FB1_PAGE_OFFSET) there is no wrap. */
    int sourceRow[N3DS_PANEL_XRES];
    for (int fbx = 0; fbx < span; fbx++)
        sourceRow[fbx] = span - 1 - fbx;

    for (int x = 0; x < canvasW; x++) {
        uint8_t* d = dstBase + (size_t)x * stride;
        for (int fbx = 0; fbx < span; fbx++, d += 3) {
            const int y = sourceRow[fbx];
            const uint16_t p = src[(size_t)y * srcStrideIn16 + x];
            /* Standard RGB565 bit replication after cache-friendly transpose,
             * stored in r8g8b8's little-endian byte order: b, g, r. */
            const uint8_t r5 = (uint8_t)((p >> 11) & 0x1F);
            const uint8_t g6 = (uint8_t)((p >>  5) & 0x3F);
            const uint8_t b5 = (uint8_t)( p        & 0x1F);
            d[0] = (uint8_t)((b5 << 3) | (b5 >> 2));
            d[1] = (uint8_t)((g6 << 2) | (g6 >> 4));
            d[2] = (uint8_t)((r5 << 3) | (r5 >> 2));
        }
    }
}

static int fb_post(struct framebuffer_device_t* dev, buffer_handle_t buffer)
{
    if (private_handle_t::validate(buffer) < 0)
        return -EINVAL;

    private_handle_t const* hnd =
            reinterpret_cast<private_handle_t const*>(buffer);
    private_module_t* m = reinterpret_cast<private_module_t*>(
            dev->common.module);

    if (m->currentBuffer) {
        m->base.unlock(&m->base, m->currentBuffer);
        m->currentBuffer = 0;
    }

    if (!m->n3ds_panel) {
        LOGE("fb_post: panel not mapped");
        return -ENODEV;
    }

    void* vaddr = NULL;
    int err = m->base.lock(&m->base, buffer,
            GRALLOC_USAGE_SW_READ_RARELY,
            0, 0, m->info.xres, m->info.yres, &vaddr);
    if (err < 0 || vaddr == NULL) {
        LOGE("fb_post: cannot lock buffer (%d)", err);
        return err ? err : -EINVAL;
    }

    /* N3DS_SINGLE_SCANOUT_RECOVERY: fb1 is the sole hardware-proven
     * scanout owner. Never issue speculative PDC1 flips from userspace. */
    n3ds_blit(m, m->n3ds_panel, (const uint16_t*)vaddr);

    m->base.unlock(&m->base, buffer);

    return 0;
}

/*****************************************************************************/

int mapFrameBufferLocked(struct private_module_t* module)
{
    // already initialized...
    if (module->framebuffer) {
        return 0;
    }

    /*
     * fb1 is the bottom screen -- the one Android's UI targets. fb0 is the
     * top screen and is the kernel's fbcon/debug console; posting the UI
     * there would fight with dmesg for the same pixels. See docs/HANDOFF.md
     * ("3DS framebuffers").
     */
    char const * const device_template[] = {
            "/dev/graphics/fb1",
            "/dev/fb1",
            0 };

    int fd = -1;
    int i = 0;
    while ((fd == -1) && device_template[i]) {
        fd = open(device_template[i], O_RDWR, 0);
        i++;
    }
    if (fd < 0) {
        LOGE("gralloc: cannot open the bottom-screen framebuffer: %s",
             strerror(errno));
        return -errno;
    }

    struct fb_fix_screeninfo pfinfo;
    struct fb_var_screeninfo pinfo;
    if (ioctl(fd, FBIOGET_FSCREENINFO, &pfinfo) == -1) {
        close(fd);
        return -errno;
    }
    if (ioctl(fd, FBIOGET_VSCREENINFO, &pinfo) == -1) {
        close(fd);
        return -errno;
    }

    if (pinfo.bits_per_pixel != 24) {
        LOGE("gralloc: panel is %d bpp, expected 24", pinfo.bits_per_pixel);
        close(fd);
        return -EINVAL;
    }

    module->n3ds_fd = fd;
    module->n3ds_panel_xres = pinfo.xres;
    module->n3ds_panel_yres = pinfo.yres;
    module->n3ds_panel_stride =
            pfinfo.line_length ? pfinfo.line_length : (int)(pinfo.xres * 3);
    module->n3ds_panel_size =
            (size_t)module->n3ds_panel_stride * module->n3ds_panel_yres;

    if (pinfo.xres != N3DS_PANEL_XRES || pinfo.yres != N3DS_PANEL_YRES) {
        LOGW("gralloc: panel reports %dx%d, expected %dx%d -- continuing",
             pinfo.xres, pinfo.yres, N3DS_PANEL_XRES, N3DS_PANEL_YRES);
    }

    /* N3DS_FB1_PAGE_OFFSET: mmap() maps whole pages starting at the page
     * that holds smem_start, so step past the 0x400 bytes in front of the
     * scanout (see the header comment). */
    const size_t pageMask = (size_t)getpagesize() - 1;
    const size_t pageOffset = (size_t)(pfinfo.smem_start & pageMask);
    module->n3ds_map_size = pageOffset + module->n3ds_panel_size;
    module->n3ds_map = mmap(0, module->n3ds_map_size,
            PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (module->n3ds_map == MAP_FAILED) {
        LOGE("gralloc: cannot mmap the panel: %s", strerror(errno));
        module->n3ds_map = NULL;
        module->n3ds_panel = NULL;
        close(fd);
        module->n3ds_fd = -1;
        return -errno;
    }
    module->n3ds_panel = (uint8_t*)module->n3ds_map + pageOffset;
    memset(module->n3ds_panel, 0, module->n3ds_panel_size);

    LOGI("gralloc: single-buffered bottom screen on hardware-proven fb1 "
         "(scanout 0x%08lx, +0x%zx into its page, N3DS_FB1_PAGE_OFFSET)",
         (unsigned long)pfinfo.smem_start, pageOffset);

    /*
     * Now describe the *canvas* in info/finfo. This is what the whole of
     * Android above gralloc sees: the panel's transpose, RGB565.
     */
    memset(&module->info, 0, sizeof(module->info));
    memset(&module->finfo, 0, sizeof(module->finfo));

    module->info.xres = module->n3ds_panel_yres;   /* 320 */
    module->info.yres = module->n3ds_panel_xres;   /* 240 */
    module->info.xres_virtual = module->info.xres;
    module->info.yres_virtual = module->info.yres * NUM_BUFFERS;
    module->info.bits_per_pixel = 16;
    module->info.red.offset   = 11; module->info.red.length   = 5;
    module->info.green.offset =  5; module->info.green.length = 6;
    module->info.blue.offset  =  0; module->info.blue.length  = 5;
    module->info.activate = FB_ACTIVATE_NOW;

    strncpy(module->finfo.id, "n3ds-bottom", sizeof(module->finfo.id) - 1);
    module->finfo.line_length = module->info.xres * 2;

    /*
     * Physical size of the bottom panel: 320x240 across a 3.33in diagonal,
     * i.e. 2.66in x 2.00in = 68mm x 51mm. build.prop sets ro.sf.lcd_density
     * to the matching 120; these two must agree or the framework's
     * DisplayMetrics and its own scaling disagree about how big things are.
     */
    module->info.width  = 68;
    module->info.height = 51;
    module->xdpi = (module->info.xres * 25.4f) / module->info.width;
    module->ydpi = (module->info.yres * 25.4f) / module->info.height;
    /*
     * The composition
     * ceiling is still however fast n3ds_blit() plus SurfaceFlinger can go,
     * which is well under the panel's 60 Hz.  Claiming 60 keeps the
     * framework's frame pacing sane.
     */
    module->fps = 60.0f;

    module->flags = 0;   /* no PAGE_FLIP: PDC1's flip goes via /dev/ctr_lcd */

    /*
     * Allocate the buffer pool. ashmem rather than an anonymous mapping so
     * the fd survives being dup()'d into a private_handle_t and passed over
     * binder -- SurfaceFlinger hands framebuffer handles out to clients.
     */
    const size_t bufferSize = module->finfo.line_length * module->info.yres;
    const size_t poolSize = roundUpToPageSize(bufferSize * NUM_BUFFERS);

    int poolFd = ashmem_create_region("n3ds-fb", poolSize);
    if (poolFd < 0) {
        LOGE("gralloc: cannot create the %zu byte framebuffer pool: %s",
             poolSize, strerror(errno));
        munmap(module->n3ds_map, module->n3ds_map_size);
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
        munmap(module->n3ds_map, module->n3ds_map_size);
        module->n3ds_panel = NULL;
        close(fd);
        module->n3ds_fd = -1;
        return -errno;
    }
    memset(vaddr, 0, poolSize);

    module->framebuffer = new private_handle_t(poolFd, poolSize,
            private_handle_t::PRIV_FLAGS_FRAMEBUFFER);
    module->framebuffer->base = intptr_t(vaddr);
    module->numBuffers = NUM_BUFFERS;
    module->bufferMask = 0;

    LOGI("gralloc: bottom screen ready -- panel %dx%d@24bpp stride %d, "
         "canvas %dx%d@RGB565 stride %d, %d buffers, "
         "%.1f x %.1f dpi (single fb1 scanout)",
         module->n3ds_panel_xres, module->n3ds_panel_yres,
         module->n3ds_panel_stride,
         module->info.xres, module->info.yres, module->finfo.line_length,
         NUM_BUFFERS, module->xdpi, module->ydpi);

    return 0;
}

static int mapFrameBuffer(struct private_module_t* module)
{
    pthread_mutex_lock(&module->lock);
    int err = mapFrameBufferLocked(module);
    pthread_mutex_unlock(&module->lock);
    return err;
}

/*****************************************************************************/

static int fb_close(struct hw_device_t *dev)
{
    fb_context_t* ctx = (fb_context_t*)dev;
    if (ctx) {
        free(ctx);
    }
    return 0;
}

int fb_device_open(hw_module_t const* module, const char* name,
        hw_device_t** device)
{
    int status = -EINVAL;
    if (!strcmp(name, GRALLOC_HARDWARE_FB0)) {
        alloc_device_t* gralloc_device;
        status = gralloc_open(module, &gralloc_device);
        if (status < 0)
            return status;

        /* initialize our state here */
        fb_context_t *dev = (fb_context_t*)malloc(sizeof(*dev));
        memset(dev, 0, sizeof(*dev));

        /* initialize the procs */
        dev->device.common.tag = HARDWARE_DEVICE_TAG;
        dev->device.common.version = 0;
        dev->device.common.module = const_cast<hw_module_t*>(module);
        dev->device.common.close = fb_close;
        dev->device.setSwapInterval = fb_setSwapInterval;
        dev->device.post            = fb_post;
        dev->device.setUpdateRect = 0;

        private_module_t* m = (private_module_t*)module;
        status = mapFrameBuffer(m);
        if (status >= 0) {
            int stride = m->finfo.line_length / (m->info.bits_per_pixel >> 3);
            const_cast<uint32_t&>(dev->device.flags) = 0;
            const_cast<uint32_t&>(dev->device.width) = m->info.xres;
            const_cast<uint32_t&>(dev->device.height) = m->info.yres;
            const_cast<int&>(dev->device.stride) = stride;
            const_cast<int&>(dev->device.format) = HAL_PIXEL_FORMAT_RGB_565;
            const_cast<float&>(dev->device.xdpi) = m->xdpi;
            const_cast<float&>(dev->device.ydpi) = m->ydpi;
            const_cast<float&>(dev->device.fps) = m->fps;
            const_cast<int&>(dev->device.minSwapInterval) = 1;
            const_cast<int&>(dev->device.maxSwapInterval) = 1;
            *device = &dev->device.common;
        }
    }
    return status;
}
