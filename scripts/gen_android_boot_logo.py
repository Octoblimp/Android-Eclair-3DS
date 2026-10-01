"""Phase 5 (boot sequence): generate an Android-bugdroid-styled kernel
boot logo, replacing the stock Tux at drivers/video/logo/logo_linux_clut224.ppm.

Pure stdlib raster (no PIL/ImageMagick dependency in the WSL build
environment) -- draws a simplified bugdroid silhouette (capsule body,
two antennae, two eyes, arm/leg stubs) via geometric pixel tests, in
the same P3 ASCII PPM format as the file it replaces (confirmed via
`file`/`head` against the original: "P3 / # Standard 224-color Linux
logo / 80 80"). Only 3 distinct colors used (black background, Android
green, white eyes) -- trivially under CLUT224's 224-color limit, no
quantization step needed.

Background is pure black so it blends seamlessly into the
already-black top-screen framebuffer (see bootargs `quiet` change in
the same commit -- nothing else paints over this until the terminal is
revealed).
"""
from a3ds_paths import A3DS_ROOT

W = H = 80
BLACK = (0, 0, 0)
GREEN = (0xA4, 0xC6, 0x39)  # real Android brand green
WHITE = (255, 255, 255)

cx, cy = 40, 40


def dist(x, y, px, py):
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def seg_dist(x, y, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return dist(x, y, x1, y1)
    t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / length2))
    px, py = x1 + t * dx, y1 + t * dy
    return dist(x, y, px, py)


def pixel(x, y):
    # Body: capsule -- rectangle x in [15,65) y in [30,70), rounded top
    # via a semicircle of radius 25 centered at (40,30).
    in_body_rect = 15 <= x < 65 and 30 <= y < 70
    in_body_dome = y < 30 and dist(x, y, cx, 30) <= 25
    if in_body_rect or in_body_dome:
        # Eyes
        if dist(x, y, 30, 38) <= 4 or dist(x, y, 50, 38) <= 4:
            return WHITE
        return GREEN

    # Antennae: thick line + round tip
    if seg_dist(x, y, 25, 30, 15, 10) <= 2 or dist(x, y, 15, 10) <= 2:
        return GREEN
    if seg_dist(x, y, 55, 30, 65, 10) <= 2 or dist(x, y, 65, 10) <= 2:
        return GREEN

    # Arms
    if 5 <= x < 15 and 45 <= y < 53:
        return GREEN
    if 65 <= x < 75 and 45 <= y < 53:
        return GREEN

    # Legs
    if 25 <= x < 33 and 70 <= y < 78:
        return GREEN
    if 47 <= x < 55 and 70 <= y < 78:
        return GREEN

    return BLACK


lines = ["P3", "# Android bugdroid boot logo (android3ds Phase 5)", f"{W} {H}", "255"]
for y in range(H):
    row = []
    for x in range(W):
        r, g, b = pixel(x, y)
        row.append(f"{r} {g} {b}")
    lines.append("  ".join(row))

ppm = "\n".join(lines) + "\n"

OUT = f"{A3DS_ROOT}/third_party/linux/drivers/video/logo/logo_linux_clut224.ppm"
with open(OUT, "w") as f:
    f.write(ppm)

print(f"OK, wrote {OUT} ({len(ppm)} bytes)")
