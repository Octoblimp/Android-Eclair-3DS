#!/bin/bash
# Host test for firm_linux_loader's fdt_patch_initrd().
#
# The patcher runs exactly once per boot, on the ARM9, with no console left by
# the time it matters -- getting it wrong means a silent panic on hardware. So
# compile the *same* fdt.c for the host and run it against the real .dtb blobs,
# then verify the result with an independent Python FDT walker.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

L="${ANDROID3DS_ROOT}"/third_party/firm_linux_loader
DTS="${ANDROID3DS_ROOT}"/third_party/linux/arch/arm/boot/dts
W="${ANDROID3DS_ROOT}"/build/fdt_test
mkdir -p "$W"

cat > "$W/driver.c" <<'EOF'
#include <stdio.h>
#include <stdlib.h>
#include "fdt.h"

int main(int argc, char **argv)
{
	/* argv: in.dtb out.dtb start end */
	FILE *f = fopen(argv[1], "rb");
	long n;
	unsigned char *buf;
	bool ok;

	fseek(f, 0, SEEK_END); n = ftell(f); fseek(f, 0, SEEK_SET);
	buf = malloc(n);
	if (fread(buf, 1, n, f) != (size_t)n) return 2;
	fclose(f);

	ok = fdt_patch_initrd(buf, strtoul(argv[3], NULL, 0),
			      strtoul(argv[4], NULL, 0));

	f = fopen(argv[2], "wb");
	fwrite(buf, 1, n, f);
	fclose(f);

	printf("%s\n", ok ? "PATCHED" : "FAILED");
	return ok ? 0 : 1;
}
EOF

gcc -Wall -Wextra -O1 -I "$L/arm9/include" -o "$W/driver" \
    "$W/driver.c" "$L/arm9/source/fdt.c"

cat > "$W/check.py" <<'EOF'
import struct, sys

FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9

def props(blob, path_want):
    """Independent walker: returns {name: raw bytes} for the wanted node."""
    magic, _, off_s, off_str = struct.unpack_from(">4I", blob, 0)
    assert magic == 0xd00dfeed, "bad magic"
    size_s = struct.unpack_from(">I", blob, 36)[0]
    p, end = off_s, off_s + size_s
    stack, out = [], {}
    while p < end:
        tok = struct.unpack_from(">I", blob, p)[0]; p += 4
        if tok == FDT_BEGIN_NODE:
            name = blob[p:blob.index(b"\0", p)].decode()
            p += (len(name) + 1 + 3) & ~3
            stack.append(name)
        elif tok == FDT_END_NODE:
            stack.pop()
        elif tok == FDT_PROP:
            ln, noff = struct.unpack_from(">2I", blob, p)
            val = blob[p+8:p+8+ln]
            p += 8 + ((ln + 3) & ~3)
            nm = blob[off_str+noff:blob.index(b"\0", off_str+noff)].decode()
            if stack == path_want:
                out[nm] = val
        elif tok == FDT_NOP:
            pass
        elif tok == FDT_END:
            break
        else:
            raise SystemExit("bad token %d" % tok)
    return out

orig = open(sys.argv[1], "rb").read()
new  = open(sys.argv[2], "rb").read()
want_start = int(sys.argv[3], 0)
want_end   = int(sys.argv[4], 0)

assert len(orig) == len(new), "size changed"

got = props(new, ["", "chosen"])
s = struct.unpack(">I", got["linux,initrd-start"])[0]
e = struct.unpack(">I", got["linux,initrd-end"])[0]
assert s == want_start, "start %08x != %08x" % (s, want_start)
assert e == want_end,   "end   %08x != %08x" % (e, want_end)

# Nothing outside those two cells may move.
diff = [i for i in range(len(orig)) if orig[i] != new[i]]
runs = []
for i in diff:
    if runs and i == runs[-1][1]:
        runs[-1][1] = i + 1
    else:
        runs.append([i, i + 1])
assert all(b - a <= 4 for a, b in runs), "wide diff: %r" % runs
assert len(runs) <= 2, "more than two cells touched: %r" % runs

print("    OK  start=%08x end=%08x  bytes changed at %s"
      % (s, e, ", ".join("0x%x" % a for a, _ in runs)))
EOF

fail=0
run() {   # run <dtb> <start> <end>
    local dtb="$1" start="$2" end="$3"
    printf "  %-22s " "$(basename "$dtb")"
    if ! "$W/driver" "$dtb" "$W/out.dtb" "$start" "$end" > "$W/r.txt" 2>&1; then
        echo "DRIVER SAID $(cat "$W/r.txt")"; fail=1; return
    fi
    echo "$(cat "$W/r.txt")"
    python3 "$W/check.py" "$dtb" "$W/out.dtb" "$start" "$end" || fail=1
}

echo "=== real blobs, realistic sizes ==="
# 11,733,820 = the initramfs that crashed against the old 8 MiB window
run "$DTS/nintendo3ds_ctr.dtb" 0x22000000 $((0x22000000 + 11733820))
run "$DTS/nintendo3ds_ktr.dtb" 0x22000000 $((0x22000000 + 11733820))

echo
echo "=== negative: bad magic must be rejected ==="
python3 - "$DTS/nintendo3ds_ktr.dtb" "$W/badmagic.dtb" <<'EOF'
import sys
b = bytearray(open(sys.argv[1], "rb").read())
b[0:4] = b"\xde\xad\xbe\xef"
open(sys.argv[2], "wb").write(b)
EOF
if "$W/driver" "$W/badmagic.dtb" "$W/out.dtb" 0x22000000 0x22c00000 \
        | grep -q FAILED; then
    echo "  OK  rejected"
else
    echo "  BAD  accepted a non-FDT blob"; fail=1
fi

echo
echo "=== negative: missing property must be reported, not half-applied ==="
# Rename linux,initrd-end in the strings block to an equal-length name so the
# blob stays structurally valid and only the lookup fails.
python3 - "$DTS/nintendo3ds_ktr.dtb" "$W/noend.dtb" <<'EOF'
import sys
b = bytearray(open(sys.argv[1], "rb").read())
i = b.find(b"linux,initrd-end\x00")
assert i >= 0
b[i:i+16] = b"linux,initrd-XXX"
open(sys.argv[2], "wb").write(b)
EOF
if "$W/driver" "$W/noend.dtb" "$W/out.dtb" 0x22000000 0x22c00000 \
        | grep -q FAILED; then
    echo "  OK  reported failure"
else
    echo "  BAD  claimed success with only one property present"; fail=1
fi

echo
[ $fail -eq 0 ] && echo "ALL FDT TESTS PASSED" || { echo "FDT TESTS FAILED"; exit 1; }
