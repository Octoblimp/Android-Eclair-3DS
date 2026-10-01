/*
 * Android3DS built-in copybit HAL.
 *
 * The image is fully static, so the normal /system/lib/hw/copybit.*.so
 * discovery path cannot work.  This module is linked beside gralloc and is
 * returned by hw_get_module_static.cpp.  It deliberately uses the CPU and
 * gralloc mappings: the current PICA200 UAPI has no accepted general-purpose
 * 2D blit ABI, while CPU copies are deterministic and retain libagl's own
 * fallback for unsupported formats.
 */

#define LOG_TAG "copybit.n3ds"

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <cutils/log.h>
#include <cutils/properties.h>
#include <hardware/copybit.h>
#include <hardware/gralloc.h>

#include "gralloc_priv.h"

/* N3DS_COPYBIT_CPU_HAL: real built-in copybit implementation. */

extern "C" struct hw_module_t n3ds_gralloc_module;

struct n3ds_copybit_context {
    copybit_device_t device;
    int transform;
    int plane_alpha;
    int dither;
};

struct mapped_image {
    uint8_t *base;
    int locked;
};

struct rgba_pixel {
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint8_t a;
};

static int bytes_per_pixel(int format)
{
    switch (format) {
    case COPYBIT_FORMAT_RGBA_8888:
    case COPYBIT_FORMAT_RGBX_8888:
    case COPYBIT_FORMAT_BGRA_8888:
        return 4;
    case COPYBIT_FORMAT_RGB_888:
        return 3;
    case COPYBIT_FORMAT_RGB_565:
    case COPYBIT_FORMAT_RGBA_5551:
    case COPYBIT_FORMAT_RGBA_4444:
        return 2;
    default:
        return 0;
    }
}

static int map_image(const copybit_image_t *image, int usage,
                     mapped_image *mapped)
{
    private_handle_t *handle;
    gralloc_module_t *gralloc;
    void *address = NULL;
    int bpp;
    int result;

    if (image == NULL || mapped == NULL || image->w == 0 || image->h == 0)
        return -EINVAL;
    bpp = bytes_per_pixel(image->format);
    if (bpp == 0)
        return -ENOSYS;

    mapped->base = NULL;
    mapped->locked = 0;
    handle = private_handle_t::dynamicCast(image->handle);
    if (handle != NULL) {
        uint64_t required = (uint64_t)image->w * image->h * bpp;
        if (required > (uint64_t)(uint32_t)handle->size)
            return -EINVAL;
        if (handle->base != 0) {
            /* The caller may already own the EGL/gralloc lock.  Re-locking a
             * write buffer would return EBUSY, so use its validated mapping. */
            mapped->base = reinterpret_cast<uint8_t *>(handle->base);
            return 0;
        }
        gralloc = reinterpret_cast<gralloc_module_t *>(&n3ds_gralloc_module);
        result = gralloc->lock(gralloc, image->handle, usage, 0, 0,
                               image->w, image->h, &address);
        if (result != 0)
            return result;
        mapped->base = static_cast<uint8_t *>(address);
        mapped->locked = 1;
        return 0;
    }

    /* A few legacy callers provide a raw base without a gralloc handle. */
    if (image->handle == NULL && image->base != NULL) {
        mapped->base = static_cast<uint8_t *>(image->base);
        return 0;
    }
    return -EINVAL;
}

static void unmap_image(const copybit_image_t *image, mapped_image *mapped)
{
    if (image != NULL && mapped != NULL && mapped->locked) {
        gralloc_module_t *gralloc =
            reinterpret_cast<gralloc_module_t *>(&n3ds_gralloc_module);
        gralloc->unlock(gralloc, image->handle);
        mapped->locked = 0;
    }
}

static rgba_pixel read_pixel(const uint8_t *p, int format)
{
    rgba_pixel out = { 0, 0, 0, 255 };
    uint16_t v;
    switch (format) {
    case COPYBIT_FORMAT_RGBA_8888:
        out.r = p[0]; out.g = p[1]; out.b = p[2]; out.a = p[3];
        break;
    case COPYBIT_FORMAT_RGBX_8888:
        out.r = p[0]; out.g = p[1]; out.b = p[2];
        break;
    case COPYBIT_FORMAT_BGRA_8888:
        out.b = p[0]; out.g = p[1]; out.r = p[2]; out.a = p[3];
        break;
    case COPYBIT_FORMAT_RGB_888:
        out.r = p[0]; out.g = p[1]; out.b = p[2];
        break;
    case COPYBIT_FORMAT_RGB_565:
        memcpy(&v, p, sizeof(v));
        out.r = (uint8_t)((((v >> 11) & 31) << 3) | ((v >> 13) & 7));
        out.g = (uint8_t)((((v >> 5) & 63) << 2) | ((v >> 9) & 3));
        out.b = (uint8_t)(((v & 31) << 3) | ((v >> 2) & 7));
        break;
    case COPYBIT_FORMAT_RGBA_5551:
        memcpy(&v, p, sizeof(v));
        out.r = (uint8_t)((((v >> 11) & 31) << 3) | ((v >> 13) & 7));
        out.g = (uint8_t)((((v >> 6) & 31) << 3) | ((v >> 8) & 7));
        out.b = (uint8_t)((((v >> 1) & 31) << 3) | ((v >> 3) & 7));
        out.a = (v & 1) ? 255 : 0;
        break;
    case COPYBIT_FORMAT_RGBA_4444:
        memcpy(&v, p, sizeof(v));
        out.r = (uint8_t)(((v >> 12) & 15) * 17);
        out.g = (uint8_t)(((v >> 8) & 15) * 17);
        out.b = (uint8_t)(((v >> 4) & 15) * 17);
        out.a = (uint8_t)((v & 15) * 17);
        break;
    }
    return out;
}

static void write_pixel(uint8_t *p, int format, const rgba_pixel &in)
{
    uint16_t v;
    switch (format) {
    case COPYBIT_FORMAT_RGBA_8888:
        p[0] = in.r; p[1] = in.g; p[2] = in.b; p[3] = in.a;
        break;
    case COPYBIT_FORMAT_RGBX_8888:
        p[0] = in.r; p[1] = in.g; p[2] = in.b; p[3] = 255;
        break;
    case COPYBIT_FORMAT_BGRA_8888:
        p[0] = in.b; p[1] = in.g; p[2] = in.r; p[3] = in.a;
        break;
    case COPYBIT_FORMAT_RGB_888:
        p[0] = in.r; p[1] = in.g; p[2] = in.b;
        break;
    case COPYBIT_FORMAT_RGB_565:
        v = (uint16_t)(((in.r >> 3) << 11) |
                       ((in.g >> 2) << 5) | (in.b >> 3));
        memcpy(p, &v, sizeof(v));
        break;
    case COPYBIT_FORMAT_RGBA_5551:
        v = (uint16_t)(((in.r >> 3) << 11) |
                       ((in.g >> 3) << 6) |
                       ((in.b >> 3) << 1) | (in.a >= 128));
        memcpy(p, &v, sizeof(v));
        break;
    case COPYBIT_FORMAT_RGBA_4444:
        v = (uint16_t)(((in.r >> 4) << 12) |
                       ((in.g >> 4) << 8) |
                       ((in.b >> 4) << 4) | (in.a >> 4));
        memcpy(p, &v, sizeof(v));
        break;
    }
}

static rgba_pixel blend_pixel(const rgba_pixel &src, const rgba_pixel &dst,
                              int plane_alpha)
{
    rgba_pixel out;
    unsigned alpha = ((unsigned)src.a * (unsigned)plane_alpha + 127) / 255;
    unsigned inverse = 255 - alpha;
    out.r = (uint8_t)(((unsigned)src.r * alpha +
                       (unsigned)dst.r * inverse + 127) / 255);
    out.g = (uint8_t)(((unsigned)src.g * alpha +
                       (unsigned)dst.g * inverse + 127) / 255);
    out.b = (uint8_t)(((unsigned)src.b * alpha +
                       (unsigned)dst.b * inverse + 127) / 255);
    out.a = (uint8_t)(alpha + ((unsigned)dst.a * inverse + 127) / 255);
    return out;
}

static int clamp_int(int value, int low, int high)
{
    if (value < low) return low;
    if (value > high) return high;
    return value;
}

static int n3ds_copybit_stretch(copybit_device_t *device,
                                const copybit_image_t *dst,
                                const copybit_image_t *src,
                                const copybit_rect_t *dst_rect,
                                const copybit_rect_t *src_rect,
                                const copybit_region_t *region)
{
    n3ds_copybit_context *ctx =
        reinterpret_cast<n3ds_copybit_context *>(device);
    mapped_image src_map;
    mapped_image dst_map;
    copybit_rect_t clip;
    copybit_rect_t full_clip;
    const copybit_region_t *iterator = region;
    int src_bpp;
    int dst_bpp;
    int dl, dt, dr, db, dw, dh;
    int result;

    if (ctx == NULL || dst == NULL || src == NULL ||
            dst_rect == NULL || src_rect == NULL)
        return -EINVAL;
    if ((ctx->transform & ~(COPYBIT_TRANSFORM_FLIP_H |
                            COPYBIT_TRANSFORM_FLIP_V |
                            COPYBIT_TRANSFORM_ROT_90)) != 0)
        return -EINVAL;
    src_bpp = bytes_per_pixel(src->format);
    dst_bpp = bytes_per_pixel(dst->format);
    if (src_bpp == 0 || dst_bpp == 0)
        return -ENOSYS;

    dl = dst_rect->l < dst_rect->r ? dst_rect->l : dst_rect->r;
    dr = dst_rect->l < dst_rect->r ? dst_rect->r : dst_rect->l;
    dt = dst_rect->t < dst_rect->b ? dst_rect->t : dst_rect->b;
    db = dst_rect->t < dst_rect->b ? dst_rect->b : dst_rect->t;
    dw = dr - dl;
    dh = db - dt;
    if (dw <= 0 || dh <= 0 || src_rect->l == src_rect->r ||
            src_rect->t == src_rect->b)
        return -EINVAL;

    result = map_image(src, GRALLOC_USAGE_SW_READ_OFTEN, &src_map);
    if (result != 0)
        return result;
    result = map_image(dst, GRALLOC_USAGE_SW_WRITE_OFTEN, &dst_map);
    if (result != 0) {
        unmap_image(src, &src_map);
        return result;
    }

    full_clip.l = dl;
    full_clip.t = dt;
    full_clip.r = dr;
    full_clip.b = db;
    for (;;) {
        int l, t, r, b;
        if (iterator != NULL) {
            if (iterator->next == NULL || !iterator->next(iterator, &clip))
                break;
        } else {
            clip = full_clip;
            iterator = reinterpret_cast<const copybit_region_t *>(1);
        }

        l = clamp_int(clip.l, dl, dr);
        t = clamp_int(clip.t, dt, db);
        r = clamp_int(clip.r, dl, dr);
        b = clamp_int(clip.b, dt, db);
        l = clamp_int(l, 0, (int)dst->w);
        r = clamp_int(r, 0, (int)dst->w);
        t = clamp_int(t, 0, (int)dst->h);
        b = clamp_int(b, 0, (int)dst->h);

        for (int y = t; y < b; ++y) {
            for (int x = l; x < r; ++x) {
                int64_t u = ((int64_t)(x - dl) * 65536 + dw / 2) / dw;
                int64_t v = ((int64_t)(y - dt) * 65536 + dh / 2) / dh;
                int64_t temp;
                int sx, sy;
                const uint8_t *src_pixel;
                uint8_t *dst_pixel;
                rgba_pixel source;

                if (ctx->transform & COPYBIT_TRANSFORM_ROT_90) {
                    temp = u;
                    u = v;
                    v = 65535 - temp;
                }
                if (ctx->transform & COPYBIT_TRANSFORM_FLIP_H)
                    u = 65535 - u;
                if (ctx->transform & COPYBIT_TRANSFORM_FLIP_V)
                    v = 65535 - v;

                sx = src_rect->l +
                    (int)(((int64_t)(src_rect->r - src_rect->l) * u) >> 16);
                sy = src_rect->t +
                    (int)(((int64_t)(src_rect->b - src_rect->t) * v) >> 16);
                sx = clamp_int(sx, 0, (int)src->w - 1);
                sy = clamp_int(sy, 0, (int)src->h - 1);
                src_pixel = src_map.base +
                    ((size_t)sy * src->w + sx) * src_bpp;
                dst_pixel = dst_map.base +
                    ((size_t)y * dst->w + x) * dst_bpp;
                source = read_pixel(src_pixel, src->format);
                if (source.a != 255 || ctx->plane_alpha != 255) {
                    rgba_pixel destination = read_pixel(dst_pixel, dst->format);
                    source = blend_pixel(source, destination,
                                         ctx->plane_alpha);
                }
                write_pixel(dst_pixel, dst->format, source);
            }
        }

        if (iterator == reinterpret_cast<const copybit_region_t *>(1))
            break;
    }

    unmap_image(dst, &dst_map);
    unmap_image(src, &src_map);
    return 0;
}

static int n3ds_copybit_blit(copybit_device_t *device,
                             const copybit_image_t *dst,
                             const copybit_image_t *src,
                             const copybit_region_t *region)
{
    copybit_rect_t dst_rect;
    copybit_rect_t src_rect;
    if (dst == NULL || src == NULL)
        return -EINVAL;
    dst_rect.l = 0; dst_rect.t = 0;
    dst_rect.r = (int)dst->w; dst_rect.b = (int)dst->h;
    src_rect.l = 0; src_rect.t = 0;
    src_rect.r = (int)src->w; src_rect.b = (int)src->h;
    return n3ds_copybit_stretch(device, dst, src, &dst_rect, &src_rect,
                                region);
}

static int n3ds_copybit_set_parameter(copybit_device_t *device,
                                      int name, int value)
{
    n3ds_copybit_context *ctx =
        reinterpret_cast<n3ds_copybit_context *>(device);
    if (ctx == NULL)
        return -EINVAL;
    switch (name) {
    case COPYBIT_ROTATION_DEG:
        if (value % 90 != 0)
            return -EINVAL;
        value %= 360;
        if (value < 0) value += 360;
        ctx->transform = value == 90 ? COPYBIT_TRANSFORM_ROT_90 :
            value == 180 ? COPYBIT_TRANSFORM_ROT_180 :
            value == 270 ? COPYBIT_TRANSFORM_ROT_270 : 0;
        return 0;
    case COPYBIT_TRANSFORM:
        if ((value & ~(COPYBIT_TRANSFORM_FLIP_H |
                       COPYBIT_TRANSFORM_FLIP_V |
                       COPYBIT_TRANSFORM_ROT_90)) != 0)
            return -EINVAL;
        ctx->transform = value;
        return 0;
    case COPYBIT_PLANE_ALPHA:
        if (value < 0 || value > 255)
            return -EINVAL;
        ctx->plane_alpha = value;
        return 0;
    case COPYBIT_DITHER:
        if (value != COPYBIT_DISABLE && value != COPYBIT_ENABLE)
            return -EINVAL;
        ctx->dither = value;
        return 0;
    case COPYBIT_BLUR:
        return value == COPYBIT_DISABLE ? 0 : -ENOSYS;
    default:
        return -EINVAL;
    }
}

static int n3ds_copybit_get(copybit_device_t *, int name)
{
    switch (name) {
    case COPYBIT_MINIFICATION_LIMIT:
    case COPYBIT_MAGNIFICATION_LIMIT:
        return 16;
    case COPYBIT_SCALING_FRAC_BITS:
        return 16;
    case COPYBIT_ROTATION_STEP_DEG:
        return 90;
    default:
        return -EINVAL;
    }
}

static int n3ds_copybit_close(hw_device_t *device)
{
    free(device);
    return 0;
}

/* N3DS_COPYBIT_BOOT_QUARANTINE: #238 proved that globally activating the
 * previously untested copybit path can prevent Android from reaching HOME.
 * Keep the real module built and registered, but fail closed into Eclair's
 * proven PixelFlinger/EGL fallback unless a developer explicitly opts in for
 * one diagnostic boot/session.  debug.* is deliberately non-persistent, so
 * an experimental enable cannot silently survive a reboot.
 */
static bool n3ds_copybit_explicitly_enabled()
{
    char value[PROPERTY_VALUE_MAX];
    property_get("debug.n3ds.copybit", value, "0");
    return strcmp(value, "1") == 0 ||
           strcmp(value, "true") == 0 ||
           strcmp(value, "on") == 0;
}

static int n3ds_copybit_open(const hw_module_t *module, const char *name,
                             hw_device_t **out_device)
{
    static int quarantine_logged;
    n3ds_copybit_context *ctx;
    if (module == NULL || name == NULL || out_device == NULL ||
            strcmp(name, COPYBIT_HARDWARE_COPYBIT0) != 0)
        return -EINVAL;
    *out_device = NULL;
    if (!n3ds_copybit_explicitly_enabled()) {
        if (!quarantine_logged) {
            LOGW("N3DS_COPYBIT_QUARANTINED default=software "
                 "opt_in=debug.n3ds.copybit");
            quarantine_logged = 1;
        }
        return -ENODEV;
    }
    LOGW("N3DS_COPYBIT_EXPERIMENTAL enabled by debug.n3ds.copybit");
    ctx = static_cast<n3ds_copybit_context *>(calloc(1, sizeof(*ctx)));
    if (ctx == NULL)
        return -ENOMEM;
    ctx->device.common.tag = HARDWARE_DEVICE_TAG;
    ctx->device.common.version = 0;
    ctx->device.common.module = const_cast<hw_module_t *>(module);
    ctx->device.common.close = n3ds_copybit_close;
    ctx->device.set_parameter = n3ds_copybit_set_parameter;
    ctx->device.get = n3ds_copybit_get;
    ctx->device.blit = n3ds_copybit_blit;
    ctx->device.stretch = n3ds_copybit_stretch;
    ctx->plane_alpha = 255;
    *out_device = &ctx->device.common;
    LOGI("N3DS_COPYBIT_READY backend=cpu formats=rgb565,rgba8888");
    return 0;
}

static hw_module_methods_t n3ds_copybit_module_methods = {
    open: n3ds_copybit_open
};

extern "C" struct copybit_module_t n3ds_copybit_module = {
    common: {
        tag: HARDWARE_MODULE_TAG,
        version_major: 1,
        version_minor: 0,
        id: COPYBIT_HARDWARE_MODULE_ID,
        name: "Nintendo 3DS CPU copybit HAL",
        author: "Android3DS",
        methods: &n3ds_copybit_module_methods
    }
};
