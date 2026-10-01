LOCAL_PATH:= $(call my-dir)

include $(CLEAR_VARS)

LOCAL_SRC_FILES := genprops.c props2.c store.c

LOCAL_STATIC_LIBRARIES := libicutu libicuuc libicudata libicui18n

ifneq ($(TARGET_ARCH),arm)
LOCAL_LDLIBS += -lpthread -ldl
endif

LOCAL_CFLAGS += 

LOCAL_C_INCLUDES += \
	$(LOCAL_PATH) \
	$(LOCAL_PATH)/../toolutil \
	$(LOCAL_PATH)/../../common

LOCAL_MODULE := genprops

include $(BUILD_HOST_EXECUTABLE)
