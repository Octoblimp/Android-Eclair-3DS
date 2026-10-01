# hal/Makefile -- cross-compile the Phase 5 HAL modules.
#
# Built against this project's existing armv6-eabihf glibc toolchain
# (same one used for the kernel/buildroot), NOT bionic -- there is no
# Android userspace to load these .so files into yet (Phase 6). This
# only validates: real Eclair HAL headers, correct hw_module_t ABI
# layout, clean compile/link. See hal/lights/lights.c and
# hal/sensors/sensors.c file headers for the same caveat.
#
# Usage (from inside WSL, matching how this project builds everything
# else):
#   make CROSS_COMPILE=arm-buildroot-linux-gnueabihf-
# (toolchain bin/ dir must already be on PATH -- see docs/BUILD.md)

CROSS_COMPILE ?= arm-buildroot-linux-gnueabihf-
CC := $(CROSS_COMPILE)gcc

CFLAGS := -Wall -Wextra -fPIC -I include -std=gnu11
LDFLAGS := -shared

OUT := out
TARGETS := $(OUT)/lights.default.so $(OUT)/sensors.default.so

.PHONY: all clean
all: $(TARGETS)

$(OUT):
	mkdir -p $(OUT)

$(OUT)/lights.default.so: lights/lights.c include/hardware/lights.h include/hardware/hardware.h | $(OUT)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<

$(OUT)/sensors.default.so: sensors/sensors.c include/hardware/sensors.h include/hardware/hardware.h include/cutils/native_handle.h | $(OUT)
	$(CC) $(CFLAGS) $(LDFLAGS) -pthread -o $@ $< -lm

clean:
	rm -rf $(OUT)
