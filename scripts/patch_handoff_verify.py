#!/usr/bin/env python3
"""HANDOFF: an absent System.map symbol is not absent code, and the fix for it.

Found while confirming that the zip the user is about to flash really carries
the DSP and camera evidence probes.  ctr_dsp_pipe_buffer_dump is nowhere in the
shipped System.map, and the code is in the shipped kernel anyway.  A session
that checks the map and concludes "my probe did not ship" would rebuild
something that was never broken.
"""
from a3ds_paths import A3DS_ROOT
import io

PATH = f"{A3DS_ROOT}/HANDOFF.md"

doc = io.open(PATH, encoding="utf-8").read()
orig = doc

section = """### Verifying a probe actually shipped: the System.map trap

`scripts/verify_zimage_strings.py` decompresses the `zImage` **out of the zip**
and greps the kernel's `.rodata` for the probe's format strings.

Use it instead of the System.map symbol check, which is necessary but **not
sufficient and actively misleading here**. Confirming the #302 zip found
`ctr_dsp_pipe_buffer_dump` nowhere in `System.map` -- and all three of its
`dev_info` strings present in the decompressed kernel. gcc inlined it. The same
map carries `ctr_dsp_swram_dump.part.0` and
`ctr_dsp_upload_firmware_once.part.0`, which is the compiler telling you plainly
that it is partial-inlining every static helper in these files.

A format string cannot be inlined away; it is in `.rodata` either way. So:
**symbol present proves it shipped, symbol absent proves nothing.** A session
that reads the map, concludes its probe did not ship, and rebuilds is chasing a
defect that does not exist.

Run against the current zip it prints, for all seven probes of #302:

    all evidence probes present in the shipped zImage

"""

anchor = "## 6. What to grep in the next capture\n"
assert anchor in doc, "section 6 anchor missing"
assert "the System.map trap" not in doc, "already present"
doc = doc.replace(anchor, section + anchor, 1)

assert doc != orig, "unchanged"
io.open(PATH, "w", encoding="utf-8", newline="\n").write(doc)
print("patched " + PATH)
