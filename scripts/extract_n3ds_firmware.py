#!/usr/bin/env python3
"""Carve the Wi-Fi firmware Android3DS needs out of your own console's NWM module.

The New 3DS Wi-Fi chip (an Atheros AR6014) is booted with four blobs that
Nintendo keeps inside the NWM system module, title 0004013000002D02. They are
Nintendo's code, so the repository does not carry them: this script takes a
dump from your console and writes the four files the kernel's ath6kl driver
requests (ath6k/AR6002/nwm/*.bin) into the Buildroot overlay, from where
build_minimal_initramfs.sh bakes them into the initramfs.

Input is any one of:
  - the decrypted NWM content (.app / .cxi, an NCCH image),
  - its ExeFS .code, compressed or already decompressed.

The NWM .code is loaded at 0x00100000 and keeps a table of (end, start)
pointer pairs for its firmware blocks. Every pair whose length matches a
wanted blob is cut out and checked against the SHA-256 of the firmware this
port was tested with. Nothing is written unless all four match.

--dsp also copies a dspfirm.cdc (dumped with the DSP1 homebrew) into the
overlay. It is optional: sound goes through CSND, and without it ctr_dsp only
logs "audio unavailable".

    scripts/extract_n3ds_firmware.py nwm.app
    scripts/extract_n3ds_firmware.py 0004013000002D02.code --dsp dspfirm.cdc
"""

import argparse
import contextlib
import hashlib
import io
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY_FIRMWARE = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/usr/lib/firmware"
CODE_BASE = 0x00100000

# Name -> (size, SHA-256) of the blobs the shipped ath6kl.ko loads
# ("Nintendo AR6014 four-blob bootstrap"), from NWM title version 11264.
NWM_BLOBS = {
    "database.bin": (488, "58da8ad2fea337e962d372f63fba639ec4b2bc9c6d5d812e00fa920304d59e03"),
    "main_type4.bin": (42475, "99eefbd87d843bef410f954c97eb9d1ec15d60aa2baf680849b12a33bf33d70b"),
    "stub_code.bin": (790, "c9605f17190be86b6a7aa54cc474b05992b3a91f9ea9801d4e2cf54827fa17ea"),
    "stub_data.bin": (56, "3487dcfde4fc771a7a5daa2ad8a3ff345b66bf048eb4e661cfa82d070c6d2d5d"),
}
DSP_FIRMWARE = (49756, "8e213f3e71d2e3e45d1169bac6465a70eabeb22b303f1fa6d7679370ffad0f54")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exefs_code(ncch: bytes) -> bytes:
    """Return the ExeFS .code of a decrypted NCCH image."""
    if ncch[0x188 + 7] & 0x4 == 0:
        sys.exit("this NCCH image is encrypted: decrypt it with GodMode9 first (README, Firmware)")
    exefs = struct.unpack_from("<I", ncch, 0x1A0)[0] * 0x200
    if exefs == 0 or exefs + 0x200 > len(ncch):
        sys.exit("this NCCH image has no ExeFS")
    for i in range(10):
        name, offset, size = struct.unpack_from("<8sII", ncch, exefs + i * 16)
        if name.rstrip(b"\0") == b".code":
            start = exefs + 0x200 + offset
            return ncch[start:start + size]
    sys.exit("no .code in this NCCH image's ExeFS")


def decompress(code: bytes):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from blz_decompress import decompress_overlay_lz

    try:
        with contextlib.redirect_stderr(io.StringIO()):
            return decompress_overlay_lz(code)
    except Exception:
        return None


def carve(code: bytes) -> dict:
    """Find each wanted blob through the (end, start) pointer pairs."""
    want = {size: (name, digest) for name, (size, digest) in NWM_BLOBS.items()}
    found = {}
    top = CODE_BASE + len(code)
    for i in range(0, len(code) - 7, 4):
        end, start = struct.unpack_from("<II", code, i)
        if not CODE_BASE <= start < end <= top or end - start not in want:
            continue
        name, digest = want[end - start]
        blob = code[start - CODE_BASE:end - CODE_BASE]
        if name not in found and sha256(blob) == digest:
            found[name] = blob
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("nwm", type=Path, help="decrypted NWM .app/.cxi, or its .code")
    parser.add_argument("--dsp", type=Path, help="optional dspfirm.cdc dumped with DSP1")
    parser.add_argument("--out", type=Path, default=OVERLAY_FIRMWARE,
                        help="firmware directory to write into (default: the Buildroot overlay)")
    parser.add_argument("--check", action="store_true", help="verify only, write nothing")
    args = parser.parse_args()

    data = args.nwm.read_bytes()
    if data[0x100:0x104] == b"NCCH":
        title = data[0x118:0x120][::-1].hex()
        print(f"NCCH image, program ID {title}")
        if title != "0004013000002d02":
            print("  warning: NWM is 0004013000002d02; this looks like a different title")
        data = exefs_code(data)

    found = carve(data)
    if len(found) < len(NWM_BLOBS):
        unpacked = decompress(data)
        if unpacked:
            print(f".code is compressed: {len(data)} -> {len(unpacked)} bytes")
            found = carve(unpacked)

    missing = sorted(set(NWM_BLOBS) - set(found))
    if missing:
        sys.exit("could not find " + ", ".join(missing) + ". Is this NWM (0004013000002D02)? "
                 "A different system version may carry different firmware, which this port "
                 "has not been tested with.")

    dsp = None
    if args.dsp:
        dsp = args.dsp.read_bytes()
        if (len(dsp), sha256(dsp)) != DSP_FIRMWARE:
            print("warning: dspfirm.cdc differs from the tested one (it is optional; copying anyway)")

    nwm_dir = args.out / "ath6k/AR6002/nwm"
    for name in sorted(found):
        print(f"  {name:15} {len(found[name]):6} bytes  sha256 OK")
    if args.check:
        print("check only: nothing written")
        return
    nwm_dir.mkdir(parents=True, exist_ok=True)
    for name, blob in found.items():
        (nwm_dir / name).write_bytes(blob)
    print(f"wrote {len(found)} files to {nwm_dir}")
    if dsp is not None:
        (args.out / "3ds").mkdir(parents=True, exist_ok=True)
        (args.out / "3ds/dspfirm.cdc").write_bytes(dsp)
        print(f"wrote {args.out / '3ds/dspfirm.cdc'}")
    print("next: scripts/build_minimal_initramfs.sh, then scripts/sync_android_to_sdcard.sh")


if __name__ == "__main__":
    main()
