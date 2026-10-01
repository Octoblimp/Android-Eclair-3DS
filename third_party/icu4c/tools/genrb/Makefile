LOCAL_PATH:= $(call my-dir)

## create genrb
include $(CLEAR_VARS)

LOCAL_SRC_FILES := \
	genrb.c \
	parse.c \
	prscmnts.cpp \
	rbutil.c \
	read.c \
	reslist.c \
	rle.c \
	ustr.c \
	wrtjava.c \
	errmsg.c \
	wrtxml.c

LOCAL_STATIC_LIBRARIES := libicui18n libicuuc libicudata libicutu

ifneq ($(TARGET_ARCH),arm)
LOCAL_LDLIBS += -lpthread -ldl
endif

LOCAL_CFLAGS += 

LOCAL_C_INCLUDES +=       \
	$(LOCAL_PATH) \
	$(LOCAL_PATH)/../toolutil \
	$(LOCAL_PATH)/../../common \
	$(LOCAL_PATH)/../../i18n

LOCAL_MODULE := genrb

include $(BUILD_HOST_EXECUTABLE)


## create derb
include $(CLEAR_VARS)

LOCAL_SRC_FILES := \
	derb.c

LOCAL_STATIC_LIBRARIES := libicui18n libicuuc libicudata libicutu

ifneq ($(TARGET_ARCH),arm)
LOCAL_LDLIBS += -lpthread -ldl
endif

LOCAL_CFLAGS += 

LOCAL_C_INCLUDES +=       \
	$(LOCAL_PATH) \
	$(LOCAL_PATH)/../toolutil \
	$(LOCAL_PATH)/../../common \
	$(LOCAL_PATH)/../../i18n

LOCAL_MODULE := derb

include $(BUILD_HOST_EXECUTABLE)
