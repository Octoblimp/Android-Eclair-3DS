"""Phase 3: enable the Android kernel subsystem in defconfig + the live .config.

Neither ANDROID, ASHMEM, nor ANDROID_BINDER_IPC were ever turned on in this
tree -- '.config' shows "# CONFIG_ANDROID is not set". This turns on the
menu and the pieces ported/needed so far (binder, ashmem, the new logger).
ANDROID_BINDER_DEVICES defaults to "binder,hwbinder,vndbinder" upstream --
that's the post-Treble (8.0+) multi-domain scheme; Eclair (API 5) predates
HALs/Treble entirely and only ever opens a single /dev/binder, so it's set
to just "binder" here for authenticity to what Eclair's libbinder actually
expects, not because the modern default would fail to build.

BINDERFS and BINDER_IPC_SELFTEST are left off: Eclair doesn't use binderfs
(that's a 9.0+ mechanism), and the selftest is a debug-only feature with
its own risk of masking or adding noise unrelated to real functionality.
"""
from a3ds_paths import A3DS_ROOT

DEFCONFIG = f"{A3DS_ROOT}/third_party/linux/arch/arm/configs/nintendo3ds_defconfig"
DOTCONFIG = f"{A3DS_ROOT}/third_party/linux/.config"

ANDROID_BLOCK = """
# Eclair (API 5) needs the classic Android kernel subsystem: binder IPC,
# ashmem, and the four-buffer logger (/dev/log_{main,events,radio}) that
# real AOSP liblog/logd read/write/ioctl() directly. BINDER_DEVICES is set
# to a single "binder" node -- Eclair predates the Treble HAL split that
# the modern "binder,hwbinder,vndbinder" default assumes.
CONFIG_ANDROID=y
CONFIG_ANDROID_BINDER_IPC=y
CONFIG_ANDROID_BINDER_DEVICES="binder"
CONFIG_ASHMEM=y
CONFIG_LOGGER=y
"""

with open(DEFCONFIG, "a") as f:
    f.write(ANDROID_BLOCK)

with open(DOTCONFIG) as f:
    c = f.read()

old = """#
# Android
#
# CONFIG_ANDROID is not set
# end of Android"""

assert old in c, ".config Android block not found verbatim"

new = """#
# Android
#
CONFIG_ANDROID=y
CONFIG_ANDROID_BINDER_IPC=y
CONFIG_ANDROID_BINDER_DEVICES="binder"
# CONFIG_ANDROID_BINDERFS is not set
# CONFIG_ANDROID_BINDER_IPC_SELFTEST is not set
CONFIG_ASHMEM=y
CONFIG_LOGGER=y
# end of Android"""

c = c.replace(old, new)
with open(DOTCONFIG, "w") as f:
    f.write(c)

print("OK")
