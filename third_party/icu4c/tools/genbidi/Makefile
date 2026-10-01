LOCAL_PATH:= $(call my-dir)

# the device command line tool
include $(CLEAR_VARS)

LOCAL_SRC_FILES := genbidi.c store.c

LOCAL_C_INCLUDES +=            \
	$(LOCAL_PATH)/../toolutil  \
	$(LOCAL_PATH)/../../common \
	$(LOCAL_PATH)/../../i18n

LOCAL_STATIC_LIBRARIES += libicuuc libicudata libicui18n libicutu

ifneq ($(TARGET_ARCH),arm)
LOCAL_LDLIBS += -lpthread -ldl -licudata
endif

LOCAL_CFLAGS :=

LOCAL_MODULE := genbidi

# the host command line tool

include $(BUILD_HOST_EXECUTABLE)
