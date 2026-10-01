#include "streetpass_adb_proxy.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

void sp_adb_proxy_init(struct sp_adb_proxy *proxy) {
    if (proxy) {
        proxy->fd = -1;
        proxy->enabled = 0;
    }
}

void sp_adb_proxy_close(struct sp_adb_proxy *proxy) {
    if (!proxy)
        return;
    if (proxy->fd >= 0)
        close(proxy->fd);
    proxy->fd = -1;
    proxy->enabled = 0;
}

int sp_adb_proxy_connect(struct sp_adb_proxy *proxy, int service_enabled,
                         uint16_t port) {
    struct sockaddr_in address;
    int fd;
    int flags;
    if (!proxy || !port)
        return -EINVAL;
    sp_adb_proxy_close(proxy);
    if (!service_enabled)
        return -EPERM;
    fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0)
        return -errno;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons(port);
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        int result = -errno;
        close(fd);
        return result;
    }
    flags = fcntl(fd, F_GETFL, 0);
    if (flags >= 0)
        (void)fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    proxy->fd = fd;
    proxy->enabled = 1;
    return 0;
}

int sp_adb_proxy_write(struct sp_adb_proxy *proxy, const void *data,
                       size_t length) {
    const uint8_t *p = (const uint8_t *)data;
    if (!proxy || proxy->fd < 0 || (!data && length))
        return -ENOTCONN;
    while (length) {
        ssize_t n = send(proxy->fd, p, length, MSG_NOSIGNAL);
        if (n < 0 && (errno == EINTR))
            continue;
        if (n < 0)
            return -errno;
        if (n == 0)
            return -EPIPE;
        p += n;
        length -= (size_t)n;
    }
    return 0;
}

int sp_adb_proxy_read(struct sp_adb_proxy *proxy, void *data, size_t capacity,
                      size_t *length) {
    ssize_t n;
    if (!proxy || proxy->fd < 0 || !data || !length)
        return -ENOTCONN;
    n = recv(proxy->fd, data, capacity, 0);
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
        *length = 0;
        return 0;
    }
    if (n < 0)
        return -errno;
    if (n == 0)
        return -EPIPE;
    *length = (size_t)n;
    return 0;
}
