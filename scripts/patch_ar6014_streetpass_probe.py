#!/usr/bin/env python3
"""Expose Nintendo AR6014 optional probe frames through a bounded netdev ABI."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy")
DRV_H = ROOT / "os/linux/include/ar6000_drv.h"
API_H = ROOT / "include/a_drv_api.h"
LINUX_API_H = ROOT / "os/linux/include/ar6xapi_linux.h"
WMI_C = ROOT / "wmi/wmi.c"
DRV_C = ROOT / "os/linux/ar6000_drv.c"
MARKER = "N3DS_AR6014_STREETPASS_PROBE_ABI"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch(path: Path, transform) -> None:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return
    updated = transform(text)
    if updated == text or MARKER not in updated:
        raise RuntimeError(f"{path}: patch did not install marker")
    path.write_text(updated, encoding="utf-8")


def patch_driver_header(text: str) -> str:
    anchor = "struct ar6_softc {\n"
    block = r'''/* N3DS_AR6014_STREETPASS_PROBE_ABI: fixed-width, pointer-free
 * userspace ABI for Nintendo's proven optional probe command/event only. */
#define N3DS_STREETPASS_IOCTL       (SIOCDEVPRIVATE + 15)
#define N3DS_STREETPASS_ABI_VERSION 1
#define N3DS_STREETPASS_DATA_MAX    MAX_OPT_DATA_LEN
#define N3DS_STREETPASS_RX_SLOTS    4

enum n3ds_streetpass_op {
    N3DS_STREETPASS_CONFIG = 1,
    N3DS_STREETPASS_TX = 2,
    N3DS_STREETPASS_RX = 3,
    N3DS_STREETPASS_DISABLE = 4,
    N3DS_STREETPASS_GET_CAPS = 5,
};

#define N3DS_STREETPASS_CAP_PROBE_TX BIT(0)
#define N3DS_STREETPASS_CAP_PROBE_RX BIT(1)
#define N3DS_STREETPASS_CAP_PEER_FILTER BIT(2)
#define N3DS_STREETPASS_CAP_CHANNEL BIT(3)

struct n3ds_streetpass_ioctl {
    u32 version;
    u32 op;
    u32 capabilities;
    s32 status;
    u16 channel_mhz;
    u16 data_len;
    u8 frame_type;
    s8 snr;
    u8 reserved[2];
    u8 peer_mac[ATH_MAC_LEN];
    u8 local_mac[ATH_MAC_LEN];
    u8 bssid[ATH_MAC_LEN];
    u8 data[N3DS_STREETPASS_DATA_MAX];
};

'''
    text = replace_once(text, anchor, block + anchor, "driver ABI")
    field_anchor = ("struct ar6_softc {\n"
                    "    struct net_device       *arNetDev;    /* net_device pointer */\n")
    fields = field_anchor + r'''    bool                     streetpass_enabled;
    u16                      streetpass_channel_mhz;
    u8                       streetpass_peer_mac[ATH_MAC_LEN];
    u8                       streetpass_local_mac[ATH_MAC_LEN];
    u8                       streetpass_rx_head;
    u8                       streetpass_rx_tail;
    u8                       streetpass_rx_count;
    u32                      streetpass_rx_dropped;
    struct n3ds_streetpass_ioctl
                              streetpass_rx[N3DS_STREETPASS_RX_SLOTS];
'''
    return replace_once(text, field_anchor, fields, "driver state")


def patch_api_header(text: str) -> str:
    anchor = "#define A_WMI_BSSINFO_EVENT_RX(ar, datp, len)   \\\n    ar6000_bssInfo_event_rx((ar), (datap), (len))\n"
    block = anchor + "\n/* N3DS_AR6014_STREETPASS_PROBE_ABI */\n" + \
        "#define A_WMI_OPT_FRAME_EVENT_RX(ar, datp, len) \\\n    ar6000_streetpass_opt_event_rx((ar), (datp), (len))\n"
    return replace_once(text, anchor, block, "WMI callback macro")


def patch_linux_api_header(text: str) -> str:
    anchor = "void ar6000_bssInfo_event_rx(struct ar6_softc *ar, u8 *data, int len);\n"
    block = anchor + "/* N3DS_AR6014_STREETPASS_PROBE_ABI */\n" + \
        "void ar6000_streetpass_opt_event_rx(struct ar6_softc *ar, u8 *data, int len);\n"
    return replace_once(text, anchor, block, "Linux callback prototype")


def patch_wmi(text: str) -> str:
    anchor = "    bih = (WMI_OPT_RX_INFO_HDR *)datap;\n    buf = datap + sizeof(WMI_OPT_RX_INFO_HDR);\n"
    block = "    bih = (WMI_OPT_RX_INFO_HDR *)datap;\n" + \
        "    /* N3DS_AR6014_STREETPASS_PROBE_ABI: deliver the validated event\n" + \
        "     * before the legacy scan-table compatibility copy. */\n" + \
        "    A_WMI_OPT_FRAME_EVENT_RX(wmip->wmi_devt, datap, len);\n" + \
        "    buf = datap + sizeof(WMI_OPT_RX_INFO_HDR);\n"
    text = replace_once(text, anchor, block, "optional RX callback")
    tx_anchor = "    WMI_OPT_TX_FRAME_CMD *cmd;\n    osbuf = A_NETBUF_ALLOC(optIEDataLen + sizeof(*cmd));\n"
    tx_block = "    WMI_OPT_TX_FRAME_CMD *cmd;\n" + \
        "    /* N3DS_AR6014_STREETPASS_PROBE_ABI: never overrun the firmware\n" + \
        "     * command buffer and do not expose unproven CPPP/action types. */\n" + \
        "    if (optIEDataLen > MAX_OPT_DATA_LEN ||\n" + \
        "        (frmType != OPT_PROBE_REQ && frmType != OPT_PROBE_RESP) ||\n" + \
        "        (!optIEData && optIEDataLen))\n" + \
        "        return A_EINVAL;\n" + \
        "    osbuf = A_NETBUF_ALLOC(optIEDataLen + sizeof(*cmd));\n"
    return replace_once(text, tx_anchor, tx_block, "optional TX bounds")


def patch_driver(text: str) -> str:
    decl = "static int ar6000_close(struct net_device *dev);\n"
    text = replace_once(text, decl, decl +
        "/* N3DS_AR6014_STREETPASS_PROBE_ABI */\n"
        "static int ar6000_streetpass_ioctl(struct net_device *dev, struct ifreq *ifr, int cmd);\n",
        "ioctl declaration")
    ops = "    .ndo_set_rx_mode        = ar6000_set_multicast_list,\n"
    text = replace_once(text, ops, ops +
        "    .ndo_do_ioctl           = ar6000_streetpass_ioctl,\n",
        "netdev ioctl op")
    close_anchor = "    struct ar6_softc    *ar = (struct ar6_softc *)ar6k_priv(dev);\n    netif_stop_queue(dev);\n\n    ar6000_disconnect(ar);\n"
    close_block = "    struct ar6_softc    *ar = (struct ar6_softc *)ar6k_priv(dev);\n" + \
        "    unsigned long flags;\n    netif_stop_queue(dev);\n\n" + \
        "    /* N3DS_AR6014_STREETPASS_PROBE_ABI: optional mode and queued\n" + \
        "     * peer frames must not survive interface teardown. */\n" + \
        "    if (ar->streetpass_enabled && ar->arWmiReady)\n" + \
        "        (void)wmi_set_opt_mode_cmd(ar->arWmi, SPECIAL_OFF);\n" + \
        "    spin_lock_irqsave(&ar->arLock, flags);\n" + \
        "    ar->streetpass_enabled = false;\n" + \
        "    ar->streetpass_rx_head = ar->streetpass_rx_tail = 0;\n" + \
        "    ar->streetpass_rx_count = 0;\n" + \
        "    spin_unlock_irqrestore(&ar->arLock, flags);\n\n" + \
        "    ar6000_disconnect(ar);\n"
    text = replace_once(text, close_anchor, close_block, "close cleanup")
    insert = "\nvoid\nar6000_bssInfo_event_rx(struct ar6_softc *ar, u8 *datap, int len)\n"
    implementation = r'''
static bool n3ds_streetpass_channel_valid(u16 mhz)
{
    return mhz == 2484 ||
           (mhz >= 2412 && mhz <= 2472 && ((mhz - 2412) % 5) == 0);
}

static bool n3ds_streetpass_peer_valid(const u8 *mac)
{
    return is_valid_ether_addr(mac);
}

/* N3DS_AR6014_STREETPASS_PROBE_ABI */
static int ar6000_streetpass_ioctl(struct net_device *dev, struct ifreq *ifr,
                                  int cmd)
{
    struct ar6_softc *ar = (struct ar6_softc *)ar6k_priv(dev);
    struct n3ds_streetpass_ioctl request;
    unsigned long flags;
    u16 channel;
    int status = 0;

    if (cmd != N3DS_STREETPASS_IOCTL)
        return -EOPNOTSUPP;
    if (!capable(CAP_NET_ADMIN))
        return -EPERM;
    if (!ifr || !ifr->ifr_data)
        return -EINVAL;
    if (copy_from_user(&request, ifr->ifr_data, sizeof(request)))
        return -EFAULT;
    if (request.version != N3DS_STREETPASS_ABI_VERSION)
        return -EPROTONOSUPPORT;
    request.capabilities = N3DS_STREETPASS_CAP_PROBE_TX |
                           N3DS_STREETPASS_CAP_PROBE_RX |
                           N3DS_STREETPASS_CAP_PEER_FILTER |
                           N3DS_STREETPASS_CAP_CHANNEL;
    request.status = 0;

    switch (request.op) {
    case N3DS_STREETPASS_GET_CAPS:
        memcpy(request.local_mac, dev->dev_addr, ATH_MAC_LEN);
        break;
    case N3DS_STREETPASS_CONFIG:
        if (!ar->arWmiReady)
            return -EIO;
        if (ar->arConnected || ar->arConnectPending)
            return -EBUSY;
        if (!n3ds_streetpass_peer_valid(request.peer_mac) ||
            !n3ds_streetpass_channel_valid(request.channel_mhz))
            return -EINVAL;
        channel = request.channel_mhz;
        spin_lock_irqsave(&ar->arLock, flags);
        ar->streetpass_enabled = true;
        ar->streetpass_channel_mhz = channel;
        memcpy(ar->streetpass_peer_mac, request.peer_mac, ATH_MAC_LEN);
        memcpy(ar->streetpass_local_mac, dev->dev_addr, ATH_MAC_LEN);
        ar->streetpass_rx_head = ar->streetpass_rx_tail = 0;
        ar->streetpass_rx_count = 0;
        spin_unlock_irqrestore(&ar->arLock, flags);
        status = wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE,
                                           1, &channel);
        if (!status)
            status = wmi_set_opt_mode_cmd(ar->arWmi, SPECIAL_ON);
        if (status) {
            spin_lock_irqsave(&ar->arLock, flags);
            ar->streetpass_enabled = false;
            spin_unlock_irqrestore(&ar->arLock, flags);
            return -EIO;
        }
        memcpy(request.local_mac, dev->dev_addr, ATH_MAC_LEN);
        break;
    case N3DS_STREETPASS_TX:
        if (!ar->streetpass_enabled || !ar->arWmiReady)
            return -ENODEV;
        if (request.data_len > N3DS_STREETPASS_DATA_MAX ||
            (request.frame_type != OPT_PROBE_REQ &&
             request.frame_type != OPT_PROBE_RESP))
            return -EINVAL;
        status = wmi_opt_tx_frame_cmd(ar->arWmi, request.frame_type,
                                      ar->streetpass_peer_mac,
                                      ar->streetpass_peer_mac,
                                      request.data_len, request.data);
        if (status)
            return -EIO;
        memcpy(request.peer_mac, ar->streetpass_peer_mac, ATH_MAC_LEN);
        memcpy(request.local_mac, ar->streetpass_local_mac, ATH_MAC_LEN);
        memcpy(request.bssid, ar->streetpass_peer_mac, ATH_MAC_LEN);
        break;
    case N3DS_STREETPASS_RX:
        spin_lock_irqsave(&ar->arLock, flags);
        if (!ar->streetpass_rx_count) {
            spin_unlock_irqrestore(&ar->arLock, flags);
            return -EAGAIN;
        }
        memcpy(&request, &ar->streetpass_rx[ar->streetpass_rx_tail],
               sizeof(request));
        ar->streetpass_rx_tail =
            (ar->streetpass_rx_tail + 1) % N3DS_STREETPASS_RX_SLOTS;
        ar->streetpass_rx_count--;
        spin_unlock_irqrestore(&ar->arLock, flags);
        break;
    case N3DS_STREETPASS_DISABLE:
        if (ar->arWmiReady)
            status = wmi_set_opt_mode_cmd(ar->arWmi, SPECIAL_OFF);
        spin_lock_irqsave(&ar->arLock, flags);
        ar->streetpass_enabled = false;
        ar->streetpass_rx_head = ar->streetpass_rx_tail = 0;
        ar->streetpass_rx_count = 0;
        spin_unlock_irqrestore(&ar->arLock, flags);
        if (status)
            return -EIO;
        break;
    default:
        return -EOPNOTSUPP;
    }

    return copy_to_user(ifr->ifr_data, &request, sizeof(request)) ?
           -EFAULT : 0;
}

void ar6000_streetpass_opt_event_rx(struct ar6_softc *ar, u8 *datap, int len)
{
    WMI_OPT_RX_INFO_HDR *event;
    struct n3ds_streetpass_ioctl *slot;
    unsigned long flags;
    int body_len;

    if (!ar || !datap || len <= sizeof(*event) ||
        len > sizeof(*event) + N3DS_STREETPASS_DATA_MAX)
        return;
    event = (WMI_OPT_RX_INFO_HDR *)datap;
    body_len = len - sizeof(*event);
    if ((event->frameType != OPT_PROBE_REQ &&
         event->frameType != OPT_PROBE_RESP) ||
        !n3ds_streetpass_channel_valid(event->channel))
        return;

    spin_lock_irqsave(&ar->arLock, flags);
    if (!ar->streetpass_enabled ||
        event->channel != ar->streetpass_channel_mhz ||
        memcmp(event->srcAddr, ar->streetpass_peer_mac, ATH_MAC_LEN)) {
        spin_unlock_irqrestore(&ar->arLock, flags);
        return;
    }
    if (ar->streetpass_rx_count == N3DS_STREETPASS_RX_SLOTS) {
        ar->streetpass_rx_dropped++;
        spin_unlock_irqrestore(&ar->arLock, flags);
        return;
    }
    slot = &ar->streetpass_rx[ar->streetpass_rx_head];
    memset(slot, 0, sizeof(*slot));
    slot->version = N3DS_STREETPASS_ABI_VERSION;
    slot->op = N3DS_STREETPASS_RX;
    slot->capabilities = N3DS_STREETPASS_CAP_PROBE_TX |
                         N3DS_STREETPASS_CAP_PROBE_RX |
                         N3DS_STREETPASS_CAP_PEER_FILTER |
                         N3DS_STREETPASS_CAP_CHANNEL;
    slot->channel_mhz = event->channel;
    slot->data_len = body_len;
    slot->frame_type = event->frameType;
    slot->snr = event->snr;
    memcpy(slot->peer_mac, event->srcAddr, ATH_MAC_LEN);
    memcpy(slot->local_mac, ar->streetpass_local_mac, ATH_MAC_LEN);
    memcpy(slot->bssid, event->bssid, ATH_MAC_LEN);
    memcpy(slot->data, datap + sizeof(*event), body_len);
    ar->streetpass_rx_head =
        (ar->streetpass_rx_head + 1) % N3DS_STREETPASS_RX_SLOTS;
    ar->streetpass_rx_count++;
    spin_unlock_irqrestore(&ar->arLock, flags);
}
'''
    return replace_once(text, insert, implementation + insert, "driver implementation")


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f"missing selected driver tree: {ROOT}")
    patch(DRV_H, patch_driver_header)
    patch(API_H, patch_api_header)
    patch(LINUX_API_H, patch_linux_api_header)
    patch(WMI_C, patch_wmi)
    patch(DRV_C, patch_driver)
    print("patch_ar6014_streetpass_probe: installed")


if __name__ == "__main__":
    main()
