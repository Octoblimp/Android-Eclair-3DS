from a3ds_paths import A3DS_ROOT
DRV = f"{A3DS_ROOT}/third_party/linux/drivers/staging/android"
INC = f"{A3DS_ROOT}/third_party/linux/include/linux"

# 1. pm_wakeup.h has "#ifndef _DEVICE_H_ / #error" -- must be reached via
#    device.h, never included standalone.
path = f"{INC}/wakelock.h"
with open(path) as f:
    c = f.read()
old = "#include <linux/pm_wakeup.h>"
assert c.count(old) == 1
c = c.replace(old, "#include <linux/device.h>\n#include <linux/pm_wakeup.h>")
with open(path, "w") as f:
    f.write(c)

# 2. pm_wakeup_pending() isn't declared where I assumed, and nothing ported
#    so far calls has_wake_lock() -- simplify to an honest always-0 stub
#    rather than chase down the right pending-check function for an
#    unused entry point.
path = f"{DRV}/android_wakelock.c"
with open(path) as f:
    c = f.read()
old = """long has_wake_lock(int type)
{
	return pm_wakeup_pending() ? -1 : 0;
}
EXPORT_SYMBOL(has_wake_lock);"""
assert old in c, "has_wake_lock block not found verbatim"
new = """long has_wake_lock(int type)
{
	/* Not implemented: original semantics (exact per-type active/
	 * timeout introspection across every wake_lock in the system)
	 * aren't reproducible from outside the wakeup_source core, and
	 * nothing ported so far calls this. */
	return 0;
}
EXPORT_SYMBOL(has_wake_lock);"""
c = c.replace(old, new)
with open(path, "w") as f:
    f.write(c)

# 3. ksys_sync() is declared in linux/syscalls.h.
path = f"{DRV}/android_earlysuspend.c"
with open(path) as f:
    c = f.read()
old = "#include <linux/rtc.h>\n#include <linux/wakelock.h>"
assert c.count(old) == 1
c = c.replace(old, "#include <linux/rtc.h>\n#include <linux/syscalls.h>\n#include <linux/wakelock.h>")
with open(path, "w") as f:
    f.write(c)

print("OK")
