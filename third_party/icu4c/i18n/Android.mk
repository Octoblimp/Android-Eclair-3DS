LOCAL_PATH:= $(call my-dir)
include $(CLEAR_VARS)

# LOCAL_ARM_MODE := arm

LOCAL_SRC_FILES := \
	bocsu.c     ucln_in.c  ucol_wgt.c \
	ulocdata.c  utmscale.c

LOCAL_SRC_FILES += \
        indiancal.cpp   dtptngen.cpp dtrule.cpp   \
        persncal.cpp    rbtz.cpp     reldtfmt.cpp \
        taiwncal.cpp    tzrule.cpp   tztrans.cpp  \
        udatpg.cpp      vtzone.cpp                \
	anytrans.cpp    astro.cpp    buddhcal.cpp \
	basictz.cpp     calendar.cpp casetrn.cpp  \
	choicfmt.cpp    coleitr.cpp  coll.cpp     \
	cpdtrans.cpp    csdetect.cpp csmatch.cpp  \
	csr2022.cpp     csrecog.cpp  csrmbcs.cpp  \
	csrsbcs.cpp     csrucode.cpp csrutf8.cpp  \
	curramt.cpp     currfmt.cpp  currunit.cpp \
	datefmt.cpp     dcfmtsym.cpp decimfmt.cpp \
	digitlst.cpp    dtfmtsym.cpp esctrn.cpp   \
	fmtable_cnv.cpp fmtable.cpp  format.cpp   \
	funcrepl.cpp    gregocal.cpp gregoimp.cpp \
	hebrwcal.cpp    inputext.cpp islamcal.cpp \
	japancal.cpp    measfmt.cpp  measure.cpp  \
	msgfmt.cpp      name2uni.cpp nfrs.cpp     \
	nfrule.cpp      nfsubs.cpp   nortrans.cpp \
	nultrans.cpp    numfmt.cpp   olsontz.cpp  \
	quant.cpp       rbnf.cpp     rbt.cpp      \
	rbt_data.cpp    rbt_pars.cpp rbt_rule.cpp \
	rbt_set.cpp     regexcmp.cpp regexst.cpp  \
	rematch.cpp     remtrans.cpp repattrn.cpp \
	search.cpp      simpletz.cpp smpdtfmt.cpp \
	sortkey.cpp     strmatch.cpp strrepl.cpp  \
	stsearch.cpp    tblcoll.cpp  timezone.cpp \
	titletrn.cpp    tolowtrn.cpp toupptrn.cpp \
	translit.cpp    transreg.cpp tridpars.cpp \
	ucal.cpp        ucol_bld.cpp ucol_cnt.cpp \
	ucol.cpp        ucoleitr.cpp ucol_elm.cpp \
	ucol_res.cpp    ucol_sit.cpp ucol_tok.cpp \
	ucsdet.cpp      ucurr.cpp    udat.cpp     \
	umsg.cpp        unesctrn.cpp uni2name.cpp \
	unum.cpp        uregexc.cpp  uregex.cpp   \
	usearch.cpp     utrans.cpp   windtfmt.cpp \
	winnmfmt.cpp    zonemeta.cpp zstrfmt.cpp

LOCAL_C_INCLUDES =       \
	$(LOCAL_PATH)         \
	$(LOCAL_PATH)/../common

LOCAL_CFLAGS += -D_REENTRANT -DPIC -DU_I18N_IMPLEMENTATION -fPIC 
LOCAL_CFLAGS += -O3

ifneq ($(TARGET_SIMULATOR),true)
LOCAL_CFLAGS += -DARM_FLAG
endif

LOCAL_SHARED_LIBRARIES +=  libicuuc libicudata
LOCAL_LDLIBS           += -lpthread -lm

LOCAL_MODULE := libicui18n

include $(BUILD_SHARED_LIBRARY)
