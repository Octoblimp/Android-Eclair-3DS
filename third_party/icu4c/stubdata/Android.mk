# Copyright (C) 2008 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# ######################################################################
# To get your own ICU userdata:
#
# Go to http://apps.icu-project.org/datacustom/ and configure yourself
# a data file.  Unzip the file it gives you, and save that somewhere,
# Set the icu_var_name variable to the location of that file in the tree.
#
# Make sure to choose ICU4C at the bottom.  You should also
# make sure to pick all of the following options, as they are required
# by the system.  Things will fail quietly if you don't have them:
#
# >>> base list goes here once we have it <<<
#
# ######################################################################
LOCAL_PATH:= $(call my-dir)


# This sets LOCAL_PRELINK_MODULE := false because the prelink map requires
# a unique address for each shared library, but I think all the variants
# of libicudata.so actually need to be mapped at the same address so they
# can be interchangable.

##

# Build configuration:
#
# "Large" includes all the supported locales.
# Japanese includes US and Japan.
# US-Euro is needed for IT or PL builds
# Default is suitable for CS, DE, EN, ES, FR, NL
# US has only EN and ES


config := $(word 1, \
            $(if $(findstring ar,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring da,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring el,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring fi,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring he,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring hr,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring hu,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring id,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring ko,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring nb,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring pt,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring ro,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring ru,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring sk,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring sr,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring sv,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring th,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring tr,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring uk,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring zh,$(PRODUCT_LOCALES)),large) \
            $(if $(findstring ja,$(PRODUCT_LOCALES)),us-japan) \
            $(if $(findstring it,$(PRODUCT_LOCALES)),us-euro) \
            $(if $(findstring pl,$(PRODUCT_LOCALES)),us-euro) \
            $(if $(findstring cs,$(PRODUCT_LOCALES)),default) \
            $(if $(findstring de,$(PRODUCT_LOCALES)),default) \
            $(if $(findstring fr,$(PRODUCT_LOCALES)),default) \
            $(if $(findstring nl,$(PRODUCT_LOCALES)),default) \
            us)

icu_var_name := icudt38_dat
##


###### Japanese

include $(CLEAR_VARS)
LOCAL_MODULE := libicudata-jp
LOCAL_MODULE_CLASS := SHARED_LIBRARIES
LOCAL_PRELINK_MODULE := false

ifeq ($(config),us-japan)
	LOCAL_MODULE_STEM := libicudata
	LOCAL_MODULE_TAGS := user
else
	LOCAL_MODULE_TAGS := optional
endif

intermediates := $(call local-intermediates-dir)
icu_data_file := $(LOCAL_PATH)/icudt38l-us-japan.dat

asm_file := $(intermediates)/icu_data_jp.S
LOCAL_GENERATED_SOURCES += $(asm_file)
$(asm_file): PRIVATE_VAR_NAME := $(icu_var_name)
$(asm_file): $(icu_data_file) $(ICUDATA)
	@echo icudata: $@
	$(hide) mkdir -p $(dir $@)
	$(hide) $(ICUDATA) $(PRIVATE_VAR_NAME) < $< > $@

LOCAL_CFLAGS  += -D_REENTRANT -DPIC -fPIC 
LOCAL_CFLAGS  += -O3 -nodefaultlibs -nostdlib 

include $(BUILD_SHARED_LIBRARY)

###### Large

include $(CLEAR_VARS)
LOCAL_MODULE := libicudata-large
LOCAL_MODULE_CLASS := SHARED_LIBRARIES
LOCAL_PRELINK_MODULE := false

ifeq ($(config),large)
	LOCAL_MODULE_STEM := libicudata
	LOCAL_MODULE_TAGS := user
else
	LOCAL_MODULE_TAGS := optional
endif

intermediates := $(call local-intermediates-dir)
icu_data_file := $(LOCAL_PATH)/icudt38l-large.dat

asm_file := $(intermediates)/icu_data_large.S
LOCAL_GENERATED_SOURCES += $(asm_file)
$(asm_file): PRIVATE_VAR_NAME := $(icu_var_name)
$(asm_file): $(icu_data_file) $(ICUDATA)
	@echo icudata: $@
	$(hide) mkdir -p $(dir $@)
	$(hide) $(ICUDATA) $(PRIVATE_VAR_NAME) < $< > $@

LOCAL_CFLAGS  += -D_REENTRANT -DPIC -fPIC 
LOCAL_CFLAGS  += -O3 -nodefaultlibs -nostdlib 

include $(BUILD_SHARED_LIBRARY)

###### Euro

include $(CLEAR_VARS)
LOCAL_MODULE := libicudata-eu
LOCAL_MODULE_CLASS := SHARED_LIBRARIES
LOCAL_PRELINK_MODULE := false

ifeq ($(config),us-euro)
	LOCAL_MODULE_STEM := libicudata
	LOCAL_MODULE_TAGS := user
else
	LOCAL_MODULE_TAGS := optional
endif

intermediates := $(call local-intermediates-dir)
icu_data_file := $(LOCAL_PATH)/icudt38l-us-euro.dat

asm_file := $(intermediates)/icu_data_eu.S
LOCAL_GENERATED_SOURCES += $(asm_file)
$(asm_file): PRIVATE_VAR_NAME := $(icu_var_name)
$(asm_file): $(icu_data_file) $(ICUDATA)
	@echo icudata: $@
	$(hide) mkdir -p $(dir $@)
	$(hide) $(ICUDATA) $(PRIVATE_VAR_NAME) < $< > $@

LOCAL_CFLAGS  += -D_REENTRANT -DPIC -fPIC 
LOCAL_CFLAGS  += -O3 -nodefaultlibs -nostdlib 

include $(BUILD_SHARED_LIBRARY)

###### Default

include $(CLEAR_VARS)
LOCAL_MODULE := libicudata-default
LOCAL_MODULE_CLASS := SHARED_LIBRARIES
LOCAL_PRELINK_MODULE := false

ifeq ($(config),default)
	LOCAL_MODULE_STEM := libicudata
	LOCAL_MODULE_TAGS := user
else
	LOCAL_MODULE_TAGS := optional
endif

intermediates := $(call local-intermediates-dir)
icu_data_file := $(LOCAL_PATH)/icudt38l-default.dat

asm_file := $(intermediates)/icu_data_default.S
LOCAL_GENERATED_SOURCES += $(asm_file)
$(asm_file): PRIVATE_VAR_NAME := $(icu_var_name)
$(asm_file): $(icu_data_file) $(ICUDATA)
	@echo icudata: $@
	$(hide) mkdir -p $(dir $@)
	$(hide) $(ICUDATA) $(PRIVATE_VAR_NAME) < $< > $@

LOCAL_CFLAGS  += -D_REENTRANT -DPIC -fPIC 
LOCAL_CFLAGS  += -O3 -nodefaultlibs -nostdlib 

include $(BUILD_SHARED_LIBRARY)

###### US

include $(CLEAR_VARS)
LOCAL_MODULE := libicudata-us
LOCAL_MODULE_CLASS := SHARED_LIBRARIES
LOCAL_PRELINK_MODULE := false

ifeq ($(config),us)
	LOCAL_MODULE_STEM := libicudata
	LOCAL_MODULE_TAGS := user
else
	LOCAL_MODULE_TAGS := optional
endif

intermediates := $(call local-intermediates-dir)
icu_data_file := $(LOCAL_PATH)/icudt38l-us.dat

asm_file := $(intermediates)/icu_data_us.S
LOCAL_GENERATED_SOURCES += $(asm_file)
$(asm_file): PRIVATE_VAR_NAME := $(icu_var_name)
$(asm_file): $(icu_data_file) $(ICUDATA)
	@echo icudata: $@
	$(hide) mkdir -p $(dir $@)
	$(hide) $(ICUDATA) $(PRIVATE_VAR_NAME) < $< > $@

LOCAL_CFLAGS  += -D_REENTRANT -DPIC -fPIC 
LOCAL_CFLAGS  += -O3 -nodefaultlibs -nostdlib 

include $(BUILD_SHARED_LIBRARY)
######
