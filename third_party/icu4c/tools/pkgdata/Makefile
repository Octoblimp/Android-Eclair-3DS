LOCAL_PATH:= $(call my-dir)

# the device command line tool
include $(CLEAR_VARS)

## Shared object suffix
SO = so
## Non-shared intermediate object suffix
STATIC_O = ao

LOCAL_SRC_FILES := \
	pkgdata.c      \
	pkgtypes.c     \
	make.c         \
	dllmode.c      \
	filemode.c     \
	sttcmode.c     \
	cmnmode.c      \
	winmode.c

LOCAL_C_INCLUDES +=            \
	$(LOCAL_PATH)/../toolutil  \
	$(LOCAL_PATH)/../../common

LOCAL_STATIC_LIBRARIES := libicutu libicui18n libicuuc

ifneq ($(TARGET_ARCH),arm)
LOCAL_LDLIBS += -lpthread -ldl
endif

LOCAL_CFLAGS := -DUDATA_SO_SUFFIX=\".$(SO)\" -DSTATIC_O=\"$(STATIC_O)\"
LOCAL_MODULE := pkgdata


# the host command line tool

include $(BUILD_HOST_EXECUTABLE)
