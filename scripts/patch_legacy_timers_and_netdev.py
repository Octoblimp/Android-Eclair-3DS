from a3ds_paths import A3DS_ROOT
base = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy"

def load(rel):
    with open(f"{base}/{rel}") as f:
        return f.read()

def save(rel, content):
    with open(f"{base}/{rel}", "w") as f:
        f.write(content)

def replace_once(content, old, new, label):
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    return content.replace(old, new)

# --- osapi_linux.h: modernize the timer init macro ---
# The old macro set ->function/->data for the pre-4.15 "void f(unsigned long)"
# callback convention. Modern timer_setup()-based callbacks are typed
# "void f(struct timer_list *)" and derive their argument via from_timer()
# inside the callback instead of an explicit stored arg -- so pArg becomes
# unused here, but is kept as a macro parameter (cast to void) so none of
# the 3 real call sites need to change their call syntax.
path = "os/linux/include/osapi_linux.h"
c = load(path)
c = replace_once(
    c,
    "#define A_INIT_TIMER(pTimer, pFunction, pArg) do {              \\\n"
    "    init_timer(pTimer);                                         \\\n"
    "    (pTimer)->function = (pFunction);                           \\\n"
    "    (pTimer)->data   = (unsigned long)(pArg);                   \\\n"
    "} while (0)",
    "#define A_INIT_TIMER(pTimer, pFunction, pArg) do {              \\\n"
    "    timer_setup((pTimer), (pFunction), 0);                      \\\n"
    "    (void)(pArg);                                               \\\n"
    "} while (0)",
    "A_INIT_TIMER macro",
)
save(path, c)

# --- ar6000_drv.c: the 2 real (non-#ifdef'd-out) timer callbacks, plus
# ndo_set_multicast_list -> ndo_set_rx_mode, plus alloc_netdev_mq's new
# name_assign_type argument.
path = "os/linux/ar6000_drv.c"
c = load(path)

c = replace_once(
    c,
    "static void ar6000_detect_error(unsigned long ptr);",
    "static void ar6000_detect_error(struct timer_list *t);",
    "ar6000_detect_error forward decl",
)
c = replace_once(
    c,
    "static void disconnect_timer_handler(unsigned long ptr);",
    "static void disconnect_timer_handler(struct timer_list *t);",
    "disconnect_timer_handler forward decl",
)
c = replace_once(
    c,
    "static void disconnect_timer_handler(unsigned long ptr)\n"
    "{\n"
    "    struct net_device *dev = (struct net_device *)ptr;\n"
    "    struct ar6_softc *ar = (struct ar6_softc *)ar6k_priv(dev);\n"
    "\n"
    "    A_UNTIMEOUT(&ar->disconnect_timer);",
    "static void disconnect_timer_handler(struct timer_list *t)\n"
    "{\n"
    "    struct ar6_softc *ar = from_timer(ar, t, disconnect_timer);\n"
    "\n"
    "    A_UNTIMEOUT(&ar->disconnect_timer);",
    "disconnect_timer_handler body",
)
c = replace_once(
    c,
    "static void ar6000_detect_error(unsigned long ptr)\n"
    "{\n"
    "    struct net_device *dev = (struct net_device *)ptr;\n"
    "    struct ar6_softc *ar = (struct ar6_softc *)ar6k_priv(dev);\n"
    "    WMI_TARGET_ERROR_REPORT_EVENT errEvent;",
    "static void ar6000_detect_error(struct timer_list *t)\n"
    "{\n"
    "    struct ar6_softc *ar = from_timer(ar, t, arHBChallengeResp.timer);\n"
    "    WMI_TARGET_ERROR_REPORT_EVENT errEvent;",
    "ar6000_detect_error body",
)
c = replace_once(
    c,
    "    .ndo_set_multicast_list = ar6000_set_multicast_list,",
    "    .ndo_set_rx_mode        = ar6000_set_multicast_list,",
    "ndo_set_multicast_list -> ndo_set_rx_mode",
)
c = replace_once(
    c,
    'dev = alloc_netdev_mq(0, "wlan%d", ether_setup, 1);',
    'dev = alloc_netdev_mq(0, "wlan%d", NET_NAME_UNKNOWN, ether_setup, 1);',
    "alloc_netdev_mq name_assign_type",
)
save(path, c)

# --- reorder/rcv_aggr.c: the one real timer callback there ---
path = "reorder/rcv_aggr.c"
c = load(path)
c = replace_once(
    c,
    "static void\naggr_timeout(unsigned long arg);",
    "static void\naggr_timeout(struct timer_list *t);",
    "aggr_timeout forward decl",
)
c = replace_once(
    c,
    "aggr_timeout(unsigned long arg)\n"
    "{\n"
    "    u8 i,j;\n"
    "    struct aggr_info *p_aggr = (struct aggr_info *)arg;",
    "aggr_timeout(struct timer_list *t)\n"
    "{\n"
    "    u8 i,j;\n"
    "    struct aggr_info *p_aggr = from_timer(p_aggr, t, timer);",
    "aggr_timeout body",
)
save(path, c)

print("ALL TIMER/NETDEV PATCHES APPLIED OK")
