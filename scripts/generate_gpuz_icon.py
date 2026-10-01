import struct
import zlib
from pathlib import Path

def create_gpuz_png(filepath):
    width = 48
    height = 48
    
    # Generate RGBA image pixels
    raw_data = bytearray()
    for y in range(height):
        raw_data.append(0) # filter type 0 (None)
        for x in range(width):
            # Rounded rect mask
            dx = max(0, max(4 - x, x - (width - 5)))
            dy = max(0, max(4 - y, y - (height - 5)))
            corner_dist_sq = dx * dx + dy * dy
            if corner_dist_sq > 16:
                # Transparent outside
                raw_data.extend([0, 0, 0, 0])
                continue
                
            # Border & Inner fill
            is_border = (x <= 1 or x >= width - 2 or y <= 1 or y >= height - 2 or corner_dist_sq > 9)
            if is_border:
                # Dark cyan/slate border
                raw_data.extend([0x1E, 0x48, 0x58, 0xFF])
            else:
                # Dark tech gradient background
                val = int(0x12 + (y / float(height)) * 0x1A)
                # Chip outline in center (8..39 x 8..39)
                is_chip_edge = (x == 8 or x == 39 or y == 8 or y == 39) and (8 <= x <= 39 and 8 <= y <= 39)
                is_chip_pin = (y == 5 or y == 6 or y == 41 or y == 42) and (x % 4 == 0) and (10 <= x <= 37) or \
                              (x == 5 or x == 6 or x == 41 or x == 42) and (y % 4 == 0) and (10 <= y <= 37)
                
                if is_chip_pin:
                    # Gold/amber pin
                    raw_data.extend([0xE0, 0xA0, 0x20, 0xFF])
                elif is_chip_edge:
                    # Neon cyan trace
                    raw_data.extend([0x00, 0xE5, 0xFF, 0xFF])
                elif 9 <= x <= 38 and 9 <= y <= 38:
                    # Chip core
                    core_val = int(0x18 + (y / float(height)) * 0x14)
                    
                    # Simple stylized 'G' letter in center (14..22 x 18..30)
                    is_g = (16 <= x <= 22 and (y == 18 or y == 30)) or \
                           (x == 16 and 18 <= y <= 30) or \
                           (x == 22 and 24 <= y <= 30) or \
                           (19 <= x <= 22 and y == 24)
                    # Simple 'Z' letter in center (25..31 x 18..30)
                    is_z = (25 <= x <= 31 and (y == 18 or y == 30)) or \
                           (x == int(31 - (y - 18) * 0.5) and 18 <= y <= 30)
                           
                    if is_g or is_z:
                        # Bright white/cyan text
                        raw_data.extend([0xFF, 0xFF, 0xFF, 0xFF])
                    else:
                        raw_data.extend([core_val, core_val + 6, core_val + 14, 0xFF])
                else:
                    raw_data.extend([val, val + 4, val + 8, 0xFF])

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw_data), 9)
    
    png_bytes = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    Path(filepath).write_bytes(png_bytes)
    print(f"Generated PNG icon: {filepath} ({len(png_bytes)} bytes)")

create_gpuz_png("content/gpuz/res/drawable/icon_gpuz.png")
