#!/usr/bin/env python3
"""Build bootanimation.zip from the genuine Eclair boot logo assets.

The two assets AOSP ships --

    frameworks/base/core/res/assets/images/android-logo-mask.png   (256x64 RGBA)
    frameworks/base/core/res/assets/images/android-logo-shine.png  (512x64 RGB)

-- are not themselves an animation. Upstream's BootAnimation::android()
composites them live: the shine scrolls horizontally behind the mask, and the
mask is an *inverted* cut-out (opaque black surround, alpha=0 glyphs) drawn
over it with GL_SRC_ALPHA/GL_ONE_MINUS_SRC_ALPHA, so the moving shine only
shows through the ANDROID wordmark.

This pre-renders that exact composite into the standard bootanimation.zip
frame format, using the same arithmetic as upstream:

    t      = 4 * (elapsed / 16667us) / shine.width
    offset = (1 - frac(t)) * shine.width
    x      = xc - offset

At upstream's 12fps the shine's 512px cycle takes 512/4 * 16667us = 2.133s.
Rendering 32 frames at 15fps reproduces that period exactly (32/15 = 2.133s)
and divides evenly into 512, giving a seamless 16px-per-frame loop.

Frames are FULL SCREEN (320x240) with the wordmark composited into the middle,
not bare 256x64 sprites.

That is deliberate. movie() centres each frame itself
(xc = (screenWidth - animation.width)/2), and for a 256x64 frame on a 320x240
canvas that computes (32, 88) -- provably centred *in the framebuffer*. On
hardware the logo still came out flush against the bottom of the panel, so the
framebuffer-to-panel mapping is not the clean bijection the arithmetic assumes.
A full-screen frame makes the question moot: xc and yc are both 0, the frame
covers the entire panel, and where the wordmark appears depends only on where
this script composites it -- which is verifiable exactly, on the host, before
shipping. It also survives a mirrored or 180-degree-rotated mapping, since a
centred logo inside a full-screen frame stays centred either way.

Entries are STORED, not deflated: BootAnimation::movie() mmaps each frame
directly and skips any entry whose method is not kCompressStored.

Only the standard library is used -- no PIL/numpy needed.
"""
from a3ds_paths import A3DS_ROOT

import os
import struct
import sys
import zipfile
import zlib

FRAMES = 32
FPS = 15

# The bottom screen, in landscape panel coordinates. Fixed -- every 3DS model
# has the same 320x240 bottom panel.
SCREEN_W = 320
SCREEN_H = 240

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = f"{A3DS_ROOT}/third_party/frameworks/base/core/res/assets/images"
MASK_PNG = os.path.join(ASSETS, "android-logo-mask.png")
SHINE_PNG = os.path.join(ASSETS, "android-logo-shine.png")


# --------------------------------------------------------------------------
# PNG reading
# --------------------------------------------------------------------------

def read_png(path):
    """Return (width, height, channels, bytearray of 8-bit samples)."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s: not a PNG" % path)

    pos = 8
    width = height = depth = colour = None
    idat = bytearray()

    while pos + 8 <= len(data):
        (clen,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + clen]

        if ctype == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            if depth != 8:
                raise ValueError("%s: only 8-bit PNGs supported" % path)
            if body[12] != 0:
                raise ValueError("%s: interlaced PNGs not supported" % path)
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break

        pos += 12 + clen

    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour)
    if channels is None:
        raise ValueError("%s: unsupported colour type %d" % (path, colour))

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(stride * height)
    prev = bytearray(stride)

    pos = 0
    for y in range(height):
        filt = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride

        if filt == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        elif filt != 0:
            raise ValueError("%s: bad filter %d" % (path, filt))

        out[y * stride:(y + 1) * stride] = line
        prev = line

    return width, height, channels, out


# --------------------------------------------------------------------------
# PNG writing
# --------------------------------------------------------------------------

def write_png(width, height, rgb):
    """Encode 24-bit RGB samples as a non-interlaced PNG."""
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)                                   # filter: None
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body +
                struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) +
            chunk(b"IEND", b""))


# --------------------------------------------------------------------------
# Frame rendering
# --------------------------------------------------------------------------

def render_frames():
    mw, mh, mc, mask = read_png(MASK_PNG)
    sw, sh, sc, shine = read_png(SHINE_PNG)

    if mc != 4:
        raise ValueError("mask must be RGBA, got %d channels" % mc)

    print("mask  %dx%d (%d ch)   shine %dx%d (%d ch)" % (mw, mh, mc, sw, sh, sc))

    # Where the wordmark sits inside a full-screen frame. This is the only
    # thing that decides where it appears on the panel now.
    ox = (SCREEN_W - mw) // 2
    oy = (SCREEN_H - mh) // 2
    print("compositing %dx%d logo at (%d, %d) in a %dx%d frame"
          % (mw, mh, ox, oy, SCREEN_W, SCREEN_H))

    frames = []
    for k in range(FRAMES):
        # Upstream: offset = (1 - frac(t)) * shine.w, x = xc - offset.
        # Sampling column `col` of the logo reads the shine at
        # (xc + col - x) % shine.w == (offset + col) % shine.w.
        offset = int(round((1.0 - k / float(FRAMES)) * sw)) % sw

        # Full-screen frame, black everywhere the logo does not cover.
        buf = bytearray(SCREEN_W * SCREEN_H * 3)
        for y in range(mh):
            srow = (y % sh) * sw * sc
            mrow = y * mw * 4
            drow = (oy + y) * SCREEN_W * 3 + ox * 3
            for x in range(mw):
                a = mask[mrow + x * 4 + 3]
                if a == 255:
                    # fully opaque surround -- mask colour wins outright
                    buf[drow + x * 3 + 0] = mask[mrow + x * 4 + 0]
                    buf[drow + x * 3 + 1] = mask[mrow + x * 4 + 1]
                    buf[drow + x * 3 + 2] = mask[mrow + x * 4 + 2]
                    continue

                sx = (offset + x) % sw
                sr = shine[srow + sx * sc + 0]
                sg = shine[srow + sx * sc + 1]
                sb = shine[srow + sx * sc + 2]

                if a == 0:
                    buf[drow + x * 3 + 0] = sr
                    buf[drow + x * 3 + 1] = sg
                    buf[drow + x * 3 + 2] = sb
                else:
                    ia = 255 - a
                    buf[drow + x * 3 + 0] = (mask[mrow + x * 4 + 0] * a + sr * ia) // 255
                    buf[drow + x * 3 + 1] = (mask[mrow + x * 4 + 1] * a + sg * ia) // 255
                    buf[drow + x * 3 + 2] = (mask[mrow + x * 4 + 2] * a + sb * ia) // 255

        frames.append((SCREEN_W, SCREEN_H, buf))

    return frames


def check_centred(width, height, rgb):
    """Assert the non-black content really is centred in the frame."""
    minx, miny, maxx, maxy = width, height, -1, -1
    for y in range(height):
        row = y * width * 3
        for x in range(width):
            o = row + x * 3
            if rgb[o] or rgb[o + 1] or rgb[o + 2]:
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
    left, right = minx, width - 1 - maxx
    top, bottom = miny, height - 1 - maxy
    print("  content bbox x=%d..%d y=%d..%d  margins L=%d R=%d T=%d B=%d"
          % (minx, maxx, miny, maxy, left, right, top, bottom))
    # The wordmark's own glyphs do not touch the mask's edges, so allow a
    # little slack; what matters is that opposite margins match.
    ok = abs(left - right) <= 2 and abs(top - bottom) <= 2
    print("  centred: %s" % ("YES" if ok else "NO"))
    return ok


def ascii_preview(width, height, rgb, cols=78, rows=13):
    """Render a frame as text so the result can be eyeballed before shipping."""
    ramp = " .:-=+*#%@"
    lines = []
    for r in range(rows):
        y = r * height // rows
        line = []
        for c in range(cols):
            x = c * width // cols
            o = (y * width + x) * 3
            lum = (rgb[o] * 30 + rgb[o + 1] * 59 + rgb[o + 2] * 11) // 100
            line.append(ramp[min(lum * len(ramp) // 256, len(ramp) - 1)])
        lines.append("".join(line))
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("usage: gen_bootanimation.py <output.zip>", file=sys.stderr)
        return 2
    out_path = sys.argv[1]

    frames = render_frames()

    print("\n--- frame 0 preview (full 320x240 frame) ---")
    print(ascii_preview(*frames[0]))
    print("--- frame %d preview ---" % (FRAMES // 2))
    print(ascii_preview(*frames[FRAMES // 2]))

    print("\n--- centring check ---")
    if not check_centred(*frames[0]):
        print("ERROR: logo is not centred in the frame", file=sys.stderr)
        return 1

    desc = "%d %d %d\np 0 0 part0\n" % (frames[0][0], frames[0][1], FPS)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("desc.txt", desc)
        for i, (w, h, rgb) in enumerate(frames):
            z.writestr("part0/%04d.png" % i, write_png(w, h, rgb))

    size = os.path.getsize(out_path)
    print("\ndesc.txt: %r" % desc)
    print("wrote %s (%d frames, %d bytes)" % (out_path, len(frames), size))

    # Re-open and confirm every entry really is stored, since movie() silently
    # ignores anything that is not.
    with zipfile.ZipFile(out_path) as z:
        bad = [i.filename for i in z.infolist()
               if i.compress_type != zipfile.ZIP_STORED]
        if bad:
            print("ERROR: not stored: %s" % bad, file=sys.stderr)
            return 1
        print("all %d entries stored" % len(z.infolist()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
