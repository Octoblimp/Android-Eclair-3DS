LOCAL_PATH:= $(call my-dir)

include $(CLEAR_VARS)

LOCAL_SRC_FILES := genuca.cpp

LOCAL_STATIC_LIBRARIES := libicutu libicui18n libicuuc libicudata

ifneq ($(TARGET_ARCH),arm)
LOCAL_LDLIBS += -lpthread -ldl
endif

LOCAL_CFLAGS += 

LOCAL_C_INCLUDES += \
	$(LOCAL_PATH) \
	$(LOCAL_PATH)/../toolutil \
	$(LOCAL_PATH)/../../common \
	$(LOCAL_PATH)/../../i18n

LOCAL_MODULE := genuca

include $(BUILD_HOST_EXECUTABLE)
