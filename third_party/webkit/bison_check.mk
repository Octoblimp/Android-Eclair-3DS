##
##
## Copyright 2008 The Android Open Source Project
##

ifeq ($(HOST_OS),linux)
LOCAL_BISON := 
LOCAL_YACC := bison -d
else
LOCAL_YACC := $(YACC)
endif

define local-transform-y-to-cpp
	mkdir -p $(dir $@)
	echo "WebCore Yacc: $(PRIVATE_MODULE) <= $<"
	$(LOCAL_YACC) $(PRIVATE_YACCFLAGS) -o $@ $<
	touch $(@:$1=$(YACC_HEADER_SUFFIX))
	echo '#ifndef '$(@F:$1=_h) > $(@:$1=.h)
	echo '#define '$(@F:$1=_h) >> $(@:$1=.h)
	cat $(@:$1=$(YACC_HEADER_SUFFIX)) >> $(@:$1=.h)
	echo '#endif' >> $(@:$1=.h)
	rm -f $(@:$1=$(YACC_HEADER_SUFFIX))
endef

