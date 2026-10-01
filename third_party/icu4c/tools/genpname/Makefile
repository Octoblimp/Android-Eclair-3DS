LOCAL_PATH:= $(call my-dir)

include $(CLEAR_VARS)

LOCAL_SRC_FILES := genpname.cpp

LOCAL_C_INCLUDES += \
	$(LOCAL_PATH)   \
	$(LOCAL_PATH)/../toolutil \
	$(LOCAL_PATH)/../../common

ifneq ($(TARGET_ARCH),arm)
LOCAL_LDLIBS += -lpthread -ldl
endif

LOCAL_CFLAGS +=

LOCAL_STATIC_LIBRARIES := libicuuc libicudata libicui18n libicutu

LOCAL_MODULE := genpname

include $(BUILD_HOST_EXECUTABLE)
