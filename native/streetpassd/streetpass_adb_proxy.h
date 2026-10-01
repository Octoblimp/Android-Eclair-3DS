#ifndef ANDROID3DS_STREETPASS_ADB_PROXY_H
#define ANDROID3DS_STREETPASS_ADB_PROXY_H

#include <stddef.h>
#include <stdint.h>

struct sp_adb_proxy {
    int fd;
    int enabled;
};

void sp_adb_proxy_init(struct sp_adb_proxy *proxy);
void sp_adb_proxy_close(struct sp_adb_proxy *proxy);
/* Connect only to Android's loopback adbd endpoint after the explicit gate. */
int sp_adb_proxy_connect(struct sp_adb_proxy *proxy, int service_enabled,
                         uint16_t port);
int sp_adb_proxy_write(struct sp_adb_proxy *proxy, const void *data, size_t length);
int sp_adb_proxy_read(struct sp_adb_proxy *proxy, void *data, size_t capacity,
                      size_t *length);

#endif
