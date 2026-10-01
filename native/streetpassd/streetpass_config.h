#ifndef ANDROID3DS_STREETPASS_CONFIG_H
#define ANDROID3DS_STREETPASS_CONFIG_H

#include <stddef.h>
#include <stdint.h>

#define SP_MANAGED_PROTOCOL "managed-tcp-v1"
#define SP_MANAGED_ENDPOINT_MAX 64u
#define SP_MANAGED_PROTOCOL_MAX 32u
#define SP_RAW_INTERFACE_MAX 16u

struct sp_managed_config {
    uint8_t mac[6];
    char endpoint[SP_MANAGED_ENDPOINT_MAX];
    uint16_t port;
    char protocol[SP_MANAGED_PROTOCOL_MAX];
};

struct sp_raw_config {
    char interface[SP_RAW_INTERFACE_MAX];
    uint8_t peer_mac[6];
    uint8_t channel;
};

int sp_parse_mac_address(const char *text, uint8_t mac[6]);
int sp_load_managed_config(const char *path, struct sp_managed_config *config);
int sp_load_raw_config(const char *path, struct sp_raw_config *config);

#endif
