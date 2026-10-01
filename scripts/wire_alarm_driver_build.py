from a3ds_paths import A3DS_ROOT
KCONFIG = f"{A3DS_ROOT}/third_party/linux/drivers/rtc/Kconfig"
MAKEFILE = f"{A3DS_ROOT}/third_party/linux/drivers/rtc/Makefile"

with open(KCONFIG) as f:
    kconfig = f.read()

old = "endif # RTC_CLASS\n"
assert kconfig.count(old) == 1
new = """config RTC_INTF_ALARM
	bool "Android /dev/alarm driver"
	depends on RTC_CLASS
	select ANDROID_WAKELOCK
	default y
	help
	  Attaches to whatever RTC registers with rtc_class (real hardware
	  here, not the emulator's rtc-goldfish) and exposes /dev/alarm --
	  real AOSP AlarmManagerService opens this directly and ioctl()s it
	  for both wall-clock and elapsed-realtime alarms, wake or non-wake.
	  Ported from the Eclair-era android-goldfish-2.6.29 driver of the
	  same name.

endif # RTC_CLASS
"""
kconfig = kconfig.replace(old, new)
with open(KCONFIG, "w") as f:
    f.write(kconfig)

with open(MAKEFILE) as f:
    makefile = f.read()

old_mk = "obj-$(CONFIG_RTC_MC146818_LIB)\t+= rtc-mc146818-lib.o\n"
assert makefile.count(old_mk) == 1
makefile = makefile.replace(
    old_mk, old_mk + "obj-$(CONFIG_RTC_INTF_ALARM)\t+= alarm.o\n"
)
with open(MAKEFILE, "w") as f:
    f.write(makefile)

print("OK")
