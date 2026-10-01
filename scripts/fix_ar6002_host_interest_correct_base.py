"""Phase 2 / AR6002: apply the hardware-confirmed host-interest base.

ar6002_locate_host_interest() (added this session) issued BMISetAppStart
with two different addresses and diffed target RAM between them --
non-circular, since BMISetAppStart is a target-side command (bmi.c:423)
and the ROM stores the value into ITS OWN hi_app_start, independent of
whatever base we assume on the host side.

Result, confirmed on hardware:

    AR6002 HI-LOCATE: hi_app_start at 0x0052001c => host interest base 0x00520000

hi_app_start is host_interest_s offset 0x1c (targaddrs.h), so base =
0x0052001c - 0x1c = 0x00520000 -- exactly RAM start, no +0x400/+0x600
offset at all. Neither the REV2 (+0x400) nor REV4 (+0x600) convention in
addrs.h applies to this chip; it's a third layout. This also explains why
every previous post-load/post-appstart dump read zeros: reads at +0x400
into a struct based at +0x0 landed 0x400 bytes past every real field.
"""
from a3ds_paths import A3DS_ROOT

path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/include/common/targaddrs.h"

with open(path) as f:
    c = f.read()

old = """/* This chip's ROM is 256KB at 0x4E0000, so it covers 0x500400 and RAM does
 * not start until 0x520000 -- confirmed on hardware by a BMI write/readback
 * probe: 0x500400/0x500418/0x500454/0x50046C are all read-only, while
 * 0x524C00 and 0x53FE18 round-trip. The stock 0x00500400 is the REV2 value
 * and puts every host-interest access into ROM, where writes are silently
 * dropped and reads return ROM contents. 0x520600 (the REV4 +0x600 layout)
 * is the other candidate if this one proves wrong. */
#define AR6002_HOST_INTEREST_ADDRESS    0x00520400"""

assert old in c, "expected marker block not found"

new = """/* This chip's ROM is 256KB at 0x4E0000-0x520000, so RAM starts at
 * 0x520000 (confirmed by a BMI write/readback probe: 0x500400 and below
 * are read-only, 0x520000 and above round-trip).
 *
 * The base itself -- not just the RAM boundary -- is confirmed
 * non-circularly by ar6002_locate_host_interest(): BMISetAppStart is a
 * target-side command (bmi.c BMI_SET_APP_START), so issuing it with two
 * different addresses and diffing target RAM finds the ROM's own
 * hi_app_start, independent of any base we assume host-side. Result on
 * hardware: hi_app_start at 0x0052001c, i.e. host interest at RAM start
 * with no offset -- neither the REV2 (+0x400) nor REV4 (+0x600)
 * convention in addrs.h. */
#define AR6002_HOST_INTEREST_ADDRESS    0x00520000"""

n = c.count(old)
assert n == 1, f"expected exactly 1 match, found {n}"
c = c.replace(old, new)

with open(path, "w") as f:
    f.write(c)
print("OK")
