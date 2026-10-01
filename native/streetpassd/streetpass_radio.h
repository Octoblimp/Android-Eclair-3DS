#ifndef ANDROID3DS_STREETPASS_RADIO_H
#define ANDROID3DS_STREETPASS_RADIO_H

#include <stddef.h>
#include <stdint.h>

#include "streetpass_config.h"
#include "streetpass_protocol.h"
#include "streetpass_ath6kl.h"

#define SP_MANAGED_CONNECT_TIMEOUT_MS 3000
#define SP_RAW_VENDOR_FRAME_MAX 251u

enum sp_radio_kind {
    SP_RADIO_UNAVAILABLE = 0,
    SP_RADIO_MOCK = 1,
    SP_RADIO_RAW80211 = 2,
    SP_RADIO_MANAGED_TCP = 3
};

struct sp_radio {
    enum sp_radio_kind kind;
    int opened;
    int fd;
    uint32_t sent_frames;
    char error[96];
    uint8_t key[64];
    size_t key_length;
    struct sp_managed_config managed;
    struct sp_raw_config raw;
    uint8_t local_mac[6];
    uint8_t rx_header[4];
    size_t rx_header_length;
    uint8_t rx_frame[SP_TUNNEL_MAX_FRAME];
    size_t rx_length;
    size_t rx_received;
};

/* Raw mode is a bounded directed probe transport over the legacy AR6014 WMI
 * optional-frame ABI. It deliberately does not claim Action/data/CCMP support. */
int sp_radio_open(struct sp_radio *radio, enum sp_radio_kind kind,
                  const struct sp_managed_config *managed,
                  const struct sp_raw_config *raw,
                  const void *key, size_t key_length);
void sp_radio_close(struct sp_radio *radio);
int sp_radio_poll(struct sp_radio *radio, void *frame, size_t capacity,
                  size_t *length);
int sp_radio_send(struct sp_radio *radio, const void *frame, size_t length);
const char *sp_radio_kind_name(enum sp_radio_kind kind);

#endif
