################################################################################
#
# m4
#
################################################################################

M4_VERSION = 1.4.19
M4_SOURCE = m4-$(M4_VERSION).tar.xz
M4_SITE = $(BR2_GNU_MIRROR)/m4
M4_LICENSE = GPL-3.0+
M4_LICENSE_FILES = COPYING
HOST_M4_CONF_OPTS = --disable-static

# Phase 2 build-env fix: this old bundled gnulib snapshot (m4 1.4.19, from
# buildroot 2021.11) predates two host-GCC-14 behavior changes:
#
# 1. _GL_ATTRIBUTE_NODISCARD expands to the C23 [[__nodiscard__]] attribute
#    in a position GCC 14 rejects -- hit in gl_oset.h first, then gl_list.h
#    turned out to have the identical pattern too, so this strips the
#    macro usage from every lib/*.h at once rather than patching files one
#    at a time as each one surfaces. Fixed via source patch (post-patch,
#    before any configure runs) because a post-configure config.h patch
#    doesn't survive -- m4's build regenerates lib/config.h itself later
#    via a nested gnulib sub-configure step. It's purely an optimization
#    hint, safe to drop for a host-only build tool.
# 2. GCC 14 made implicit-function-declaration a hard error by default
#    (previously just a warning), and this old gnulib snapshot has several
#    (gl_list_nx_add_at and friends in lib/gl_xlist.h). Each of those then
#    also trips -Wint-conversion (an undeclared function is assumed to
#    return int, which then gets assigned to a pointer-typed variable),
#    which GCC 14 *also* promoted to a hard error by default -- a direct,
#    predictable side effect of the same root cause, not a separate bug.
#    Revert both warning classes back to non-fatal for this host-only
#    build rather than patching each missing declaration individually.
define HOST_M4_STRIP_NODISCARD_ATTR
	find $(@D)/lib -name '*.h' -exec sed -i 's/_GL_ATTRIBUTE_NODISCARD//' {} +
endef
HOST_M4_POST_PATCH_HOOKS += HOST_M4_STRIP_NODISCARD_ATTR

HOST_M4_CONF_ENV += CFLAGS="-Wno-error=implicit-function-declaration -Wno-error=int-conversion"

$(eval $(host-autotools-package))
