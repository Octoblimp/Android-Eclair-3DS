from a3ds_paths import A3DS_ROOT
DRV = f"{A3DS_ROOT}/third_party/linux/drivers/staging/android"

kconfig_path = f"{DRV}/Kconfig"
with open(kconfig_path) as f:
    kconfig = f.read()

old = """config ANDROID_LOW_MEMORY_KILLER
	bool "Android Low Memory Killer"
	default y
	help
	  Registers a shrinker that kills processes based on their
	  oom_adj (/proc/<pid>/oom_adj, real AOSP ActivityManager writes
	  this directly) once free memory drops below configurable
	  thresholds -- ported from the Eclair-era
	  android-goldfish-2.6.29 driver of the same name. See
	  Documentation/../lowmemorykiller.txt for the adj/minfree tuning
	  format.

endif # if ANDROID"""

assert old in kconfig, "LMK Kconfig block not found verbatim"

new = """config ANDROID_LOW_MEMORY_KILLER
	bool "Android Low Memory Killer"
	default y
	help
	  Registers a shrinker that kills processes based on their
	  oom_adj (/proc/<pid>/oom_adj, real AOSP ActivityManager writes
	  this directly) once free memory drops below configurable
	  thresholds -- ported from the Eclair-era
	  android-goldfish-2.6.29 driver of the same name. See
	  Documentation/../lowmemorykiller.txt for the adj/minfree tuning
	  format.

config ANDROID_WAKELOCK
	bool "Android wake_lock compat API"
	select PM_WAKEUP
	default y
	help
	  The old Eclair-era wake_lock_init/wake_lock/wake_lock_timeout/
	  wake_unlock/wake_lock_active in-kernel C API, implemented as a
	  compat shim over the mainline wakeup_source API. Needed by
	  ANDROID_EARLY_SUSPEND and by kernel drivers (e.g. the /dev/alarm
	  driver) that call it directly, the way real Eclair-era drivers
	  did. Not the same thing as CONFIG_PM_WAKELOCKS, which is the
	  separate, already-mainlined /sys/power/wake_lock userspace sysfs
	  interface.

config ANDROID_EARLY_SUSPEND
	bool "Android early suspend"
	select ANDROID_WAKELOCK
	default y
	help
	  The level-ordered register_early_suspend()/
	  unregister_early_suspend() notifier chain real Eclair-era
	  drivers (framebuffer blanking, touch power gating) call
	  directly -- ported from the Eclair-era android-goldfish-2.6.29
	  driver of the same name. This mechanism itself was never
	  mainlined.

endif # if ANDROID"""

kconfig = kconfig.replace(old, new)
with open(kconfig_path, "w") as f:
    f.write(kconfig)

makefile_path = f"{DRV}/Makefile"
with open(makefile_path) as f:
    makefile = f.read()

old_mk = "obj-$(CONFIG_ANDROID_LOW_MEMORY_KILLER)\t+= lowmemorykiller.o\n"
assert old_mk in makefile, "LMK Makefile line not found verbatim"
makefile = makefile.replace(
    old_mk,
    old_mk
    + "obj-$(CONFIG_ANDROID_WAKELOCK)\t\t+= android_wakelock.o\n"
    + "obj-$(CONFIG_ANDROID_EARLY_SUSPEND)\t+= android_earlysuspend.o\n",
)
with open(makefile_path, "w") as f:
    f.write(makefile)

print("OK")
