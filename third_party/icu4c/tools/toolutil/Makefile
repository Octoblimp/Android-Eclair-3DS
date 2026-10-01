LOCAL_PATH:= $(call my-dir)
include $(CLEAR_VARS)

LOCAL_SRC_FILES := \
	filestrm.c     \
    package.cpp    \
	pkgitems.cpp   \
	propsvec.c     \
	swapimpl.cpp   \
	toolutil.c     \
	unewdata.c     \
	ucm.c          \
	ucmstate.c     \
	uoptions.c     \
	uparse.c       \
	ucbuf.c        \
	xmlparser.cpp  \
	writesrc.c

LOCAL_C_INCLUDES +=         \
	$(LOCAL_PATH)/../../common \
	$(LOCAL_PATH)/../../i18n

LOCAL_CFLAGS += -D_REENTRANT -DPIC -fPIC 
LOCAL_CFLAGS += -O3 -nodefaultlibs -nostdlib 

LOCAL_STATIC_LIBRARIES += libicuuc libicui18n

LOCAL_MODULE := libicutu

include $(BUILD_HOST_STATIC_LIBRARY)
