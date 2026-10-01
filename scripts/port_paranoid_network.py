"""Phase 3: port CONFIG_ANDROID_PARANOID_NETWORK from android-goldfish-2.6.29
onto 5.11.

Real location (not in drivers/staging/android/ like the others): a
current_has_network() gid/capability check inlined into net/ipv4/af_inet.c's
inet_create() and net/ipv6/af_inet6.c's inet6_create() -- the two socket()
entry points for AF_INET/AF_INET6. Real AOSP's permission model denies raw
socket() to any process not in the "inet" (AID_INET, gid 3003) group and
without CAP_NET_RAW, which is how Android restricts network access per-app
(zygote drops to an unprivileged uid/gid set per app, only adding AID_INET
for apps holding the INTERNET permission) without needing SELinux or a
per-socket LSM hook.

Kernel-internal API changes needed, all mechanical:
  - in_egroup_p(gid_t) [[[removed]]] -> in_egroup_p(kgid_t); AID_INET is a
    raw number, so make_kgid(&init_user_ns, AID_INET) converts it to the
    now-required kgid_t.
  - inet_create()/inet6_create() both gained a trailing 'kern' parameter
    since 2.6.29 (kernel-internal socket creation, e.g. for in-kernel NFS/
    RPC/etc. clients, distinct from a userspace socket() call) -- the
    check is skipped when kern is set, matching how AOSP's own kernel
    trees updated this same patch when upstream added that parameter.
    Real Eclair userspace never sets it (it isn't visible from userspace
    at all), so this doesn't change userspace-facing behavior.
"""
from a3ds_paths import A3DS_ROOT

import os

INC = f"{A3DS_ROOT}/third_party/linux/include/linux"
AF_INET = f"{A3DS_ROOT}/third_party/linux/net/ipv4/af_inet.c"
AF_INET6 = f"{A3DS_ROOT}/third_party/linux/net/ipv6/af_inet6.c"
KCONFIG = f"{A3DS_ROOT}/third_party/linux/drivers/staging/android/Kconfig"

android_aid_h = """/* SPDX-License-Identifier: GPL-2.0 */
/* include/linux/android_aid.h
 *
 * Copyright (C) 2008 Google, Inc.
 *
 * Ported verbatim from android-goldfish-2.6.29 -- these AID numbers are
 * real Eclair/AOSP fixed uid/gid assignments (see system/core/include/
 * private/android_filesystem_config.h in the real AOSP tree); Zygote-
 * spawned app processes get AID_INET added to their supplementary groups
 * only if they hold the INTERNET permission.
 */
#ifndef _LINUX_ANDROID_AID_H
#define _LINUX_ANDROID_AID_H

/* AIDs that the kernel treats differently */
#define AID_NET_BT_ADMIN 3001
#define AID_NET_BT       3002
#define AID_INET         3003
#define AID_NET_RAW      3004
#define AID_NET_ADMIN    3005

#endif
"""

with open(os.path.join(INC, "android_aid.h"), "w") as f:
    f.write(android_aid_h)


def patch_file(path, create_fn_sig, label):
    with open(path) as f:
        c = f.read()

    check_block = """
#ifdef CONFIG_ANDROID_PARANOID_NETWORK
#include <linux/android_aid.h>
#include <linux/cred.h>

static inline int current_has_network(void)
{
	return in_egroup_p(make_kgid(&init_user_ns, AID_INET)) ||
		capable(CAP_NET_RAW);
}
#else
static inline int current_has_network(void)
{
	return 1;
}
#endif
"""

    old_sig = create_fn_sig
    assert c.count(old_sig) == 1, f"{label}: create() signature not found verbatim"
    c = c.replace(old_sig, check_block + "\n" + old_sig)

    old_body_start = "\tif (protocol < 0 || protocol >= IPPROTO_MAX)\n\t\treturn -EINVAL;\n"
    assert c.count(old_body_start) == 1, f"{label}: create() body start not found verbatim"
    c = c.replace(
        old_body_start,
        old_body_start + "\n\tif (!kern && !current_has_network())\n\t\treturn -EACCES;\n",
    )

    with open(path, "w") as f:
        f.write(c)


patch_file(
    AF_INET,
    "static int inet_create(struct net *net, struct socket *sock, int protocol,\n\t\t       int kern)\n{",
    "af_inet.c",
)
patch_file(
    AF_INET6,
    "static int inet6_create(struct net *net, struct socket *sock, int protocol,\n\t\t\tint kern)\n{",
    "af_inet6.c",
)
# (continuation-line whitespace above verified byte-exact via `cat -A`
# against the live tree before running this script -- inet_create uses
# two tabs + 7 spaces, inet6_create uses three tabs.)

# Kconfig
with open(KCONFIG) as f:
    kconfig = f.read()

old = """config ANDROID_EARLY_SUSPEND
	bool "Android early suspend"
	select ANDROID_WAKELOCK
	default y
	help
	  The level-ordered register_early_suspend()/
	  unregister_early_suspend() notifier chain real Eclair-era
	  drivers (framebuffer blanking, touch power gating) call
	  directly -- ported from the Eclair-era android-goldfish-2.6.29
	  driver of the same name. This mechanism itself was never
	  mainlined.

endif # if ANDROID"""

assert old in kconfig, "early suspend Kconfig block not found verbatim"

new = """config ANDROID_EARLY_SUSPEND
	bool "Android early suspend"
	select ANDROID_WAKELOCK
	default y
	help
	  The level-ordered register_early_suspend()/
	  unregister_early_suspend() notifier chain real Eclair-era
	  drivers (framebuffer blanking, touch power gating) call
	  directly -- ported from the Eclair-era android-goldfish-2.6.29
	  driver of the same name. This mechanism itself was never
	  mainlined.

config ANDROID_PARANOID_NETWORK
	bool "Android network permission checks"
	default y
	help
	  Denies AF_INET/AF_INET6 socket() to any process that isn't in
	  the "inet" group (AID_INET, gid 3003) and doesn't hold
	  CAP_NET_RAW -- how real AOSP enforces the INTERNET permission
	  per-app without SELinux. Ported from the Eclair-era
	  android-goldfish-2.6.29 patch of the same name
	  (net/ipv4/af_inet.c, net/ipv6/af_inet6.c).

endif # if ANDROID"""

kconfig = kconfig.replace(old, new)
with open(KCONFIG, "w") as f:
    f.write(kconfig)

print("OK")
