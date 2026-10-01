#!/usr/bin/env python3
"""Remove divisions from the 3DS RGB565 scanout hot loop.

The PICA200 cannot safely be driven until Linux owns its command submission,
memory, cache, and interrupt lifecycle.  Meanwhile every Android frame passes
through this CPU rotation/conversion.  Standard bit replication preserves the
channel endpoints and distributes the source bits without three divides per
pixel (230,400 divides for each 320x240 post).
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


SOURCE = Path(f"{A3DS_ROOT}/third_party/libhardware/modules/gralloc/framebuffer.cpp")
text = SOURCE.read_text()

old = """            const uint8_t r = (uint8_t)(((p >> 11) & 0x1F) * 255 / 31);
            const uint8_t g = (uint8_t)(((p >>  5) & 0x3F) * 255 / 63);
            const uint8_t b = (uint8_t)(( p        & 0x1F) * 255 / 31);
"""
new = """            /* Standard RGB565 bit replication, avoiding three integer
             * divisions for every one of the 76,800 posted pixels. */
            const uint8_t r5 = (uint8_t)((p >> 11) & 0x1F);
            const uint8_t g6 = (uint8_t)((p >>  5) & 0x3F);
            const uint8_t b5 = (uint8_t)( p        & 0x1F);
            const uint8_t r = (uint8_t)((r5 << 3) | (r5 >> 2));
            const uint8_t g = (uint8_t)((g6 << 2) | (g6 >> 4));
            const uint8_t b = (uint8_t)((b5 << 3) | (b5 >> 2));
"""

if ("Standard RGB565 bit replication" not in text
        and "N3DS_CACHE_FRIENDLY_ROTATE" not in text):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"RGB565 hot loop: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)

# Default channel order.  The hardware-verified 2026-08-03 fbtest photo
# analysis proves the panel 3-cycles the written bytes: displayed =
# (byte0, byte2, byte1).  Writing (r,b,g) -- index {0,2,1} -- therefore
# displays (r,g,b).  The historical "bgr" default ({2,1,0}) was the wrong
# order and is what caused the inverted colours.
old_chan = """    /* Default "bgr": the framebuffer declares r8g8b8, which for a packed
     * 24bpp little-endian pixel means byte 0 is blue. Index into {r,g,b}. */
    module->n3ds_chan[0] = 2;
    module->n3ds_chan[1] = 1;
    module->n3ds_chan[2] = 0;
"""
new_chan = """    /* Default "rbg": the hardware-verified fbtest photo analysis proves the
     * panel 3-cycles the written bytes (displayed = (byte0, byte2, byte1)),
     * so writing (r,b,g) -- index {0,2,1} -- displays (r,g,b). Index into
     * {r,g,b}. */
    module->n3ds_chan[0] = 0;
    module->n3ds_chan[1] = 2;
    module->n3ds_chan[2] = 1;
"""
if 'Default "rbg"' not in text:
    count = text.count(old_chan)
    if count != 1:
        raise SystemExit(f"channel default: expected exactly one match, found {count}")
    text = text.replace(old_chan, new_chan, 1)

SOURCE.write_text(text)
print("patch_n3ds_gralloc: division-free RGB565 expansion enabled")
