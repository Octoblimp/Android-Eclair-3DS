"""
Port of Barubary/dsdecmp's LZOvl (LZ-Overlay / "backward LZ") decompressor,
used for 3DS/NDS .code section compression. Ported faithfully from:
https://github.com/Barubary/dsdecmp/blob/master/CSharp/DSDecmp/Formats/LZOvl.cs
"""
import sys


def decompress_overlay_lz(data: bytes) -> bytes:
    in_length = len(data)

    extra_size = int.from_bytes(data[in_length - 4:in_length], "little")
    print(f"extraSize = {extra_size:#x}", file=sys.stderr)

    if extra_size == 0:
        return data[:in_length - 4]

    header_size = data[in_length - 5]
    compressed_size_raw = int.from_bytes(data[in_length - 8:in_length - 5], "little")
    compressed_size = compressed_size_raw - header_size
    print(f"headerSize = {header_size:#x}, compressedSize_raw = {compressed_size_raw:#x}, "
          f"compressedSize = {compressed_size:#x}", file=sys.stderr)

    if compressed_size + header_size >= in_length:
        compressed_size = in_length - header_size
        print(f"clamped compressedSize = {compressed_size:#x}", file=sys.stderr)

    prefix_len = in_length - header_size - compressed_size
    uncompressed_prefix = data[0:prefix_len]
    print(f"uncompressed prefix length = {prefix_len:#x}", file=sys.stderr)

    compressed_buf = data[prefix_len:prefix_len + compressed_size]

    decompressed_length = compressed_size + header_size + extra_size
    print(f"decompressed_length (of compressed portion) = {decompressed_length:#x}", file=sys.stderr)
    outbuffer = bytearray(decompressed_length)

    current_out_size = 0
    read_bytes = 0
    flags = 0
    mask = 1

    while current_out_size < decompressed_length:
        if mask == 1:
            if read_bytes >= compressed_size:
                raise ValueError(f"NotEnoughData: out={current_out_size} of {decompressed_length}")
            flags = compressed_buf[len(compressed_buf) - 1 - read_bytes]
            read_bytes += 1
            mask = 0x80
        else:
            mask >>= 1

        if flags & mask:
            if read_bytes + 1 >= in_length:
                raise ValueError("NotEnoughData (length/disp bytes)")
            byte1 = compressed_buf[compressed_size - 1 - read_bytes]
            read_bytes += 1
            byte2 = compressed_buf[compressed_size - 1 - read_bytes]
            read_bytes += 1

            length = (byte1 >> 4) + 3
            disp = (((byte1 & 0x0F) << 8) | byte2) + 3

            if disp > current_out_size:
                if current_out_size < 2:
                    raise ValueError(f"Invalid data: disp {disp:#x} > current_out_size {current_out_size:#x}")
                disp = 2

            buf_idx = current_out_size - disp
            for _ in range(length):
                if current_out_size >= decompressed_length:
                    break
                nxt = outbuffer[len(outbuffer) - 1 - buf_idx]
                buf_idx += 1
                outbuffer[len(outbuffer) - 1 - current_out_size] = nxt
                current_out_size += 1
        else:
            if read_bytes >= in_length:
                raise ValueError("NotEnoughData (literal byte)")
            nxt = compressed_buf[len(compressed_buf) - 1 - read_bytes]
            read_bytes += 1
            outbuffer[len(outbuffer) - 1 - current_out_size] = nxt
            current_out_size += 1

    return uncompressed_prefix + bytes(outbuffer)


if __name__ == "__main__":
    in_path = sys.argv[1]
    out_path = sys.argv[2]
    with open(in_path, "rb") as f:
        data = f.read()
    result = decompress_overlay_lz(data)
    with open(out_path, "wb") as f:
        f.write(result)
    print(f"Decompressed {len(data)} -> {len(result)} bytes, written to {out_path}", file=sys.stderr)
