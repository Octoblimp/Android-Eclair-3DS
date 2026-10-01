#ifndef ANDROID3DS_STREETPASS_PROTOCOL_H
#define ANDROID3DS_STREETPASS_PROTOCOL_H

/*
 * Android3DS StreetPass protocol boundary.
 *
 * The Nintendo radio conversation is not an IP link.  This header therefore
 * describes the small, authenticated/resumable application tunnel used by
 * streetpassd and the host bridge after a raw-radio backend has delivered an
 * exchange. It is independent of association/IP. The selected legacy AR6014
 * driver now exposes a bounded directed probe request/response backend; the
 * unproven Nintendo Action/data/CCMP stages remain outside that ABI.
 */

#include <stddef.h>
#include <stdint.h>

#define SP_NINTENDO_CONTINUOUS_SCAN_SSID "Nintendo_3DS_continuous_scan_000"
#define SP_NINTENDO_VENDOR_OUI "\x00\x1f\x32"
#define SP_NINTENDO_SERVICE_TAG 0x11u
#define SP_NINTENDO_CONSOLE_ID_TAG 0xf0u
#define SP_NINTENDO_SERVICE_RECORD_SIZE 5u
#define SP_NINTENDO_MAX_SERVICES 51u
#define SP_TUNNEL_MAGIC "SPB1"
#define SP_TUNNEL_VERSION 1u
#define SP_TUNNEL_HEADER_SIZE 44u
#define SP_TUNNEL_TAG_SIZE 32u
#define SP_TUNNEL_MAX_PAYLOAD 65536u
#define SP_TUNNEL_MAX_FRAME (SP_TUNNEL_HEADER_SIZE + SP_TUNNEL_MAX_PAYLOAD + \
                             SP_TUNNEL_TAG_SIZE)
#define SP_MANAGED_MAGIC "SPM1"
#define SP_MANAGED_VERSION 1u
#define SP_MANAGED_IDENTITY_BODY_SIZE 12u
#define SP_MANAGED_IDENTITY_SIZE (SP_MANAGED_IDENTITY_BODY_SIZE + SP_TUNNEL_TAG_SIZE)

enum sp_tunnel_type {
    SP_TUNNEL_HELLO = 0x01,
    SP_TUNNEL_DATA = 0x02,
    SP_TUNNEL_ACK = 0x04,
    SP_TUNNEL_PING = 0x08,
    SP_TUNNEL_PONG = 0x10,
    SP_TUNNEL_CLOSE = 0x20,
    SP_TUNNEL_RESUME = 0x40
};

/* All multibyte fields are network byte order. The wire header is exactly 44B. */
struct sp_tunnel_header {
    uint8_t version;
    uint8_t flags;
    uint8_t channel;
    uint8_t reserved;
    uint8_t session[16];
    uint64_t sequence;
    uint64_t acknowledgement;
    uint32_t payload_length;
};

struct sp_peer_identity {
    uint8_t console_id[8];
    uint8_t mac[6];
    uint32_t service_mask;
    char name[64];
};

struct sp_bridge_identity {
    char name[65];
    char fingerprint[97];
};

/* Internal journal integrity checksum; never substitutes for frame HMAC. */
uint32_t sp_checksum32(const void *data, size_t length);
void sp_hmac_sha256(const void *key, size_t key_length,
                    const void *data, size_t data_length,
                    uint8_t output[SP_TUNNEL_TAG_SIZE]);

int sp_frame_encode(const struct sp_tunnel_header *header,
                    const void *payload, size_t payload_length,
                    const void *key, size_t key_length,
                    void *output, size_t output_capacity, size_t *output_length);
int sp_frame_decode(const void *input, size_t input_length,
                    struct sp_tunnel_header *header,
                    void *payload, size_t payload_capacity, size_t *payload_length,
                    const void *key, size_t key_length);

/*
 * Parse the bounded Nintendo vendor payload carried after the vendor OUI.
 * Required service (0x11) and console-id (0xf0) TLVs use the documented
 * one-byte-id, one-byte-length encoding. Unknown TLVs are skipped safely.
 * No peer is accepted merely because a frame has a plausible length.
 */
int sp_parse_nintendo_tag(const void *data, size_t length,
                          struct sp_peer_identity *peer);
int sp_build_hello_payload(const char *name, const char *fingerprint,
                           void *output, size_t capacity, size_t *length);
int sp_parse_hello_payload(const void *data, size_t length,
                           struct sp_bridge_identity *identity);
int sp_build_resume_payload(const uint8_t session[16], uint64_t tx_next,
                            uint64_t rx_next, void *output, size_t capacity,
                            size_t *length);
int sp_parse_resume_payload(const void *data, size_t length,
                            uint8_t session[16], uint64_t *tx_next,
                            uint64_t *rx_next);

/* Conservative validators for the documented SPTCP/SPMTP magic/type layer. */
int sp_validate_sptcp(const void *data, size_t length,
                      uint16_t *flags, uint32_t *sequence,
                      uint32_t *acknowledgement, size_t *payload_offset,
                      size_t *payload_length);
int sp_validate_spmtp(const void *data, size_t length,
                      uint8_t *packet_type, size_t *payload_offset,
                      size_t *payload_length);

#endif
