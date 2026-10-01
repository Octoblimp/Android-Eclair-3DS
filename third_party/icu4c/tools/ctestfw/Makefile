LOCAL_PATH:= $(call my-dir)

## create ctestfw
include $(CLEAR_VARS)

LOCAL_SRC_FILES := \
	ctest.c \
	datamap.cpp \
	testdata.cpp \
	tstdtmod.cpp \
	dbgutil.cpp \
	udbgutil.cpp \
	uperf.cpp

LOCAL_STATIC_LIBRARIES := libicutu libicui18n libicuuc

ifneq ($(TARGET_ARCH),arm)
LOCAL_LDLIBS += -lpthread -ldl
endif

LOCAL_CFLAGS += 

LOCAL_C_INCLUDES +=       \
	$(LOCAL_PATH) \
	$(LOCAL_PATH)/../toolutil \
	$(LOCAL_PATH)/../../common

LOCAL_MODULE := libicutest

include $(BUILD_HOST_LIBRARY)
