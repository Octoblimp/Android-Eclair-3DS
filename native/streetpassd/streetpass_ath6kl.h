#ifndef ANDROID3DS_STREETPASS_ATH6KL_H
#define ANDROID3DS_STREETPASS_ATH6KL_H

#include <stdint.h>
#include <linux/sockios.h>

#define N3DS_STREETPASS_IOCTL (SIOCDEVPRIVATE + 15)
#define N3DS_STREETPASS_ABI_VERSION 1u
#define N3DS_STREETPASS_DATA_MAX 1400u

enum n3ds_streetpass_op {
    N3DS_STREETPASS_CONFIG = 1,
    N3DS_STREETPASS_TX = 2,
    N3DS_STREETPASS_RX = 3,
    N3DS_STREETPASS_DISABLE = 4,
    N3DS_STREETPASS_GET_CAPS = 5,
};

#define N3DS_STREETPASS_CAP_PROBE_TX (1u << 0)
#define N3DS_STREETPASS_CAP_PROBE_RX (1u << 1)
#define N3DS_STREETPASS_CAP_PEER_FILTER (1u << 2)
#define N3DS_STREETPASS_CAP_CHANNEL (1u << 3)
#define N3DS_STREETPASS_REQUIRED_CAPS 0x0fu
#define N3DS_STREETPASS_OPT_PROBE_REQ 1u
#define N3DS_STREETPASS_OPT_PROBE_RESP 2u

struct n3ds_streetpass_ioctl {
    uint32_t version;
    uint32_t op;
    uint32_t capabilities;
    int32_t status;
    uint16_t channel_mhz;
    uint16_t data_len;
    uint8_t frame_type;
    int8_t snr;
    uint8_t reserved[2];
    uint8_t peer_mac[6];
    uint8_t local_mac[6];
    uint8_t bssid[6];
    uint8_t data[N3DS_STREETPASS_DATA_MAX];
};

#endif
