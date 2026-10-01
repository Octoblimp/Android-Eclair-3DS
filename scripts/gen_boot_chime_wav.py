"""Phase 5 (boot sequence): synthesize a short two-note boot chime as a
real WAV file (pure stdlib, no audio tooling needed in WSL) so the
boot-sound hook (boot_sound.sh) has an actual asset to play the moment
Phase 4 lands a working audio device -- not just a stubbed-out call
with nothing behind it.

Signed 16-bit little-endian stereo PCM, 44100 Hz: C5 (523.25 Hz) for 150ms
then G5 (783.99 Hz) for 350ms, each with a short linear fade in/out to avoid
click artifacts.  This exactly matches Eclair AudioHardwareGeneric's output
contract, so the boot hook can safely strip the canonical 44-byte header and
write the payload to /dev/eac.
"""
from a3ds_paths import A3DS_ROOT

import math
import struct

RATE = 44100


def note(freq, duration_s, amplitude=12000):
    n = round(RATE * duration_s)
    fade = max(1, int(n * 0.08))
    samples = bytearray()
    for i in range(n):
        env = 1.0
        if i < fade:
            env = i / fade
        elif i > n - fade:
            env = (n - i) / fade
        val = math.sin(2 * math.pi * freq * (i / RATE)) * amplitude * env
        sample = int(val)
        samples += struct.pack("<hh", sample, sample)
    return bytes(samples)


pcm = note(523.25, 0.15) + note(783.99, 0.35)

byte_rate = RATE * 2 * 2  # stereo, 16-bit
block_align = 4

riff = b"RIFF"
wave = b"WAVE"
fmt_chunk = struct.pack(
    "<4sIHHIIHH",
    b"fmt ", 16, 1, 2, RATE, byte_rate, block_align, 16,
)
data_chunk = struct.pack("<4sI", b"data", len(pcm)) + pcm
riff_size = 4 + len(fmt_chunk) + len(data_chunk)
wav = riff + struct.pack("<I", riff_size) + wave + fmt_chunk + data_chunk

OUT = f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/rootfs_overlay/usr/share/sounds/boot.wav"
import os
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "wb") as f:
    f.write(wav)

print(f"OK, wrote {OUT} ({len(wav)} bytes)")
