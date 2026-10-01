#include "streetpass_radio.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <net/if.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

static uint32_t get_be_u32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static void put_be_u32(uint8_t *p, uint32_t value) {
    p[0] = (uint8_t)(value >> 24);
    p[1] = (uint8_t)(value >> 16);
    p[2] = (uint8_t)(value >> 8);
    p[3] = (uint8_t)value;
}

static int write_all(int fd, const void *data, size_t length) {
    const uint8_t *p = (const uint8_t *)data;
    while (length) {
        ssize_t n = send(fd, p, length, MSG_NOSIGNAL);
        if (n < 0 && errno == EINTR)
            continue;
        if (n < 0)
            return -errno;
        if (!n)
            return -EPIPE;
        p += n;
        length -= (size_t)n;
    }
    return 0;
}

static int connect_managed(struct sp_radio *radio) {
    struct sockaddr_in address;
    struct pollfd wait_fd;
    struct timespec now;
    int64_t deadline;
    int64_t remaining;
    int fd;
    int flags;
    int result;
    int socket_error;
    socklen_t socket_error_length;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons(radio->managed.port);
    if (inet_pton(AF_INET, radio->managed.endpoint, &address.sin_addr) != 1)
        return -EINVAL;
    fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0)
        return -errno;
    flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) {
        result = -errno;
        close(fd);
        return result;
    }
    do {
        result = connect(fd, (struct sockaddr *)&address, sizeof(address));
    } while (result < 0 && errno == EINTR);
    if (result == 0) {
        radio->fd = fd;
        return 0;
    }
    if (errno != EINPROGRESS && errno != EALREADY) {
        result = -errno;
        close(fd);
        return result;
    }
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        result = -errno;
        close(fd);
        return result;
    }
    deadline = (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000 +
               SP_MANAGED_CONNECT_TIMEOUT_MS;
    memset(&wait_fd, 0, sizeof(wait_fd));
    wait_fd.fd = fd;
    wait_fd.events = POLLOUT;
    for (;;) {
        if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
            result = -errno;
            close(fd);
            return result;
        }
        remaining = deadline - ((int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000);
        if (remaining <= 0) {
            close(fd);
            return -ETIMEDOUT;
        }
        result = poll(&wait_fd, 1, remaining > INT_MAX ? INT_MAX : (int)remaining);
        if (result < 0 && errno == EINTR)
            continue;
        if (result < 0) {
            result = -errno;
            close(fd);
            return result;
        }
        if (result == 0) {
            close(fd);
            return -ETIMEDOUT;
        }
        if (!(wait_fd.revents & (POLLOUT | POLLERR | POLLHUP | POLLNVAL)))
            continue;
        socket_error = 0;
        socket_error_length = sizeof(socket_error);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &socket_error,
                       &socket_error_length) != 0) {
            result = -errno;
            close(fd);
            return result;
        }
        if (socket_error) {
            close(fd);
            return -socket_error;
        }
        break;
    }
    radio->fd = fd;
    return 0;
}

static int send_identity(struct sp_radio *radio) {
    uint8_t identity[SP_MANAGED_IDENTITY_SIZE];
    memcpy(identity, SP_MANAGED_MAGIC, 4);
    identity[4] = SP_MANAGED_VERSION;
    identity[5] = 0;
    memcpy(identity + 6, radio->managed.mac, 6);
    sp_hmac_sha256(radio->key, radio->key_length, identity,
                   SP_MANAGED_IDENTITY_BODY_SIZE,
                   identity + SP_MANAGED_IDENTITY_BODY_SIZE);
    return write_all(radio->fd, identity, sizeof(identity));
}

static uint16_t raw_channel_mhz(uint8_t channel) {
    if (channel == 14)
        return 2484;
    return (uint16_t)(2407u + 5u * channel);
}

static int raw_ioctl(struct sp_radio *radio,
                     struct n3ds_streetpass_ioctl *request) {
    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    if (strlen(radio->raw.interface) >= sizeof(ifr.ifr_name))
        return -ENAMETOOLONG;
    memcpy(ifr.ifr_name, radio->raw.interface,
           strlen(radio->raw.interface) + 1);
    ifr.ifr_data = (void *)request;
    if (ioctl(radio->fd, N3DS_STREETPASS_IOCTL, &ifr) != 0)
        return -errno;
    return 0;
}

static int open_raw(struct sp_radio *radio, const struct sp_raw_config *raw) {
    struct n3ds_streetpass_ioctl request;
    int result;
    if (!raw || !raw->interface[0] || raw->channel < 1 || raw->channel > 14)
        return -EINVAL;
    memcpy(&radio->raw, raw, sizeof(*raw));
    radio->fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (radio->fd < 0)
        return -errno;
    memset(&request, 0, sizeof(request));
    request.version = N3DS_STREETPASS_ABI_VERSION;
    request.op = N3DS_STREETPASS_CONFIG;
    request.channel_mhz = raw_channel_mhz(raw->channel);
    memcpy(request.peer_mac, raw->peer_mac, sizeof(request.peer_mac));
    result = raw_ioctl(radio, &request);
    if (result) {
        close(radio->fd);
        radio->fd = -1;
        return result;
    }
    if ((request.capabilities & N3DS_STREETPASS_REQUIRED_CAPS) !=
        N3DS_STREETPASS_REQUIRED_CAPS) {
        close(radio->fd);
        radio->fd = -1;
        return -EOPNOTSUPP;
    }
    memcpy(radio->local_mac, request.local_mac, sizeof(radio->local_mac));
    return 0;
}

const char *sp_radio_kind_name(enum sp_radio_kind kind) {
    switch (kind) {
    case SP_RADIO_UNAVAILABLE: return "unavailable";
    case SP_RADIO_MOCK: return "mock";
    case SP_RADIO_RAW80211: return "raw80211";
    case SP_RADIO_MANAGED_TCP: return "managed-tcp";
    default: return "unknown";
    }
}

int sp_radio_open(struct sp_radio *radio, enum sp_radio_kind kind,
                  const struct sp_managed_config *managed,
                  const struct sp_raw_config *raw,
                  const void *key, size_t key_length) {
    int result;
    if (!radio || (!key && key_length) || key_length > sizeof(radio->key))
        return -EINVAL;
    memset(radio, 0, sizeof(*radio));
    radio->kind = kind;
    radio->fd = -1;
    if (key_length)
        memcpy(radio->key, key, key_length);
    radio->key_length = key_length;
    if (kind == SP_RADIO_MOCK) {
        radio->opened = 1;
        return 0;
    }
    if (kind == SP_RADIO_RAW80211) {
        if (key_length < 16) {
            snprintf(radio->error, sizeof(radio->error),
                     "raw probe transport requires the paired key");
            return -EACCES;
        }
        result = open_raw(radio, raw);
        if (result) {
            snprintf(radio->error, sizeof(radio->error),
                     "ath6kl directed-probe setup failed: %d", result);
            return result;
        }
        radio->opened = 1;
        return 0;
    }
    if (kind != SP_RADIO_MANAGED_TCP) {
        snprintf(radio->error, sizeof(radio->error), "radio backend unavailable");
        return -EOPNOTSUPP;
    }
    if (!managed || !managed->endpoint[0] || !managed->port ||
        strcmp(managed->protocol, SP_MANAGED_PROTOCOL) || key_length < 16) {
        snprintf(radio->error, sizeof(radio->error),
                 "managed transport config or pairing key is invalid");
        return -EACCES;
    }
    memcpy(&radio->managed, managed, sizeof(*managed));
    result = connect_managed(radio);
    if (result) {
        /* Keep the diagnostic bounded even when a config file contains the
         * maximum endpoint length; this also keeps -Wformat-truncation builds
         * fail-fast without dropping the useful endpoint prefix. */
        snprintf(radio->error, sizeof(radio->error),
                 "managed TCP connect to %.*s:%u failed", 40,
                 radio->managed.endpoint, (unsigned int)radio->managed.port);
        return result;
    }
    result = send_identity(radio);
    if (result) {
        close(radio->fd);
        radio->fd = -1;
        snprintf(radio->error, sizeof(radio->error),
                 "managed identity preamble send failed");
        return result;
    }
    radio->opened = 1;
    return 0;
}

void sp_radio_close(struct sp_radio *radio) {
    if (radio && radio->fd >= 0 && radio->kind == SP_RADIO_RAW80211) {
        struct n3ds_streetpass_ioctl request;
        memset(&request, 0, sizeof(request));
        request.version = N3DS_STREETPASS_ABI_VERSION;
        request.op = N3DS_STREETPASS_DISABLE;
        (void)raw_ioctl(radio, &request);
    }
    if (!radio)
        return;
    if (radio->fd >= 0)
        close(radio->fd);
    radio->fd = -1;
    radio->opened = 0;
    radio->rx_header_length = 0;
    radio->rx_length = 0;
    radio->rx_received = 0;
}

static int receive_bytes(struct sp_radio *radio, void *data, size_t capacity,
                         size_t *length) {
    ssize_t n;
    n = recv(radio->fd, data, capacity, MSG_DONTWAIT);
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
        return 0;
    if (n < 0 && errno == EINTR)
        return 0;
    if (n < 0)
        return -errno;
    if (n == 0)
        return -ECONNRESET;
    *length = (size_t)n;
    return 1;
}

int sp_radio_poll(struct sp_radio *radio, void *frame, size_t capacity,
                  size_t *length) {
    size_t n;
    int result;
    if (!radio || !length || (!frame && capacity))
        return -EINVAL;
    *length = 0;
    if (!radio->opened)
        return -ENODEV;
    if (radio->kind == SP_RADIO_MOCK)
        return 0;
    if (radio->kind == SP_RADIO_RAW80211) {
        struct n3ds_streetpass_ioctl request;
        size_t offset;
        memset(&request, 0, sizeof(request));
        request.version = N3DS_STREETPASS_ABI_VERSION;
        request.op = N3DS_STREETPASS_RX;
        result = raw_ioctl(radio, &request);
        if (result == -EAGAIN)
            return 0;
        if (result)
            return result;
        if (request.channel_mhz != raw_channel_mhz(radio->raw.channel) ||
            memcmp(request.peer_mac, radio->raw.peer_mac, 6) ||
            request.data_len > sizeof(request.data))
            return -EPROTO;
        offset = request.frame_type == N3DS_STREETPASS_OPT_PROBE_RESP ? 12u : 0u;
        if (request.frame_type != N3DS_STREETPASS_OPT_PROBE_REQ &&
            request.frame_type != N3DS_STREETPASS_OPT_PROBE_RESP)
            return -EPROTO;
        while (offset + 2u <= request.data_len) {
            size_t ie_length = request.data[offset + 1u];
            const uint8_t *ie = request.data + offset + 2u;
            if (offset + 2u + ie_length > request.data_len)
                return -EBADMSG;
            if (request.data[offset] == 221u && ie_length >= 4u &&
                ie[0] == 0x00 && ie[1] == 0x1f && ie[2] == 0x32 &&
                ie[3] == 0xa3) {
                size_t payload = ie_length - 4u;
                if (payload > capacity)
                    return -EMSGSIZE;
                memcpy(frame, ie + 4u, payload);
                *length = payload;
                return 0;
            }
            offset += 2u + ie_length;
        }
        return 0;
    }
    if (radio->kind != SP_RADIO_MANAGED_TCP)
        return -ENOSYS;
    if (radio->rx_header_length < sizeof(radio->rx_header)) {
        result = receive_bytes(radio, radio->rx_header + radio->rx_header_length,
                                sizeof(radio->rx_header) - radio->rx_header_length,
                                &n);
        if (result < 0)
            return result;
        if (!result)
            return 0;
        radio->rx_header_length += n;
        if (radio->rx_header_length < sizeof(radio->rx_header))
            return 0;
        radio->rx_length = get_be_u32(radio->rx_header);
        if (!radio->rx_length || radio->rx_length > SP_TUNNEL_MAX_FRAME)
            return -EMSGSIZE;
    }
    result = receive_bytes(radio, radio->rx_frame + radio->rx_received,
                           radio->rx_length - radio->rx_received, &n);
    if (result < 0)
        return result;
    if (!result)
        return 0;
    radio->rx_received += n;
    if (radio->rx_received < radio->rx_length)
        return 0;
    if (radio->rx_length > capacity)
        return -EMSGSIZE;
    memcpy(frame, radio->rx_frame, radio->rx_length);
    *length = radio->rx_length;
    radio->rx_header_length = 0;
    radio->rx_length = 0;
    radio->rx_received = 0;
    return 0;
}

int sp_radio_send(struct sp_radio *radio, const void *frame, size_t length) {
    uint8_t prefix[4];
    int result;
    if (!radio || (!frame && length))
        return -EINVAL;
    if (!radio->opened)
        return -ENODEV;
    if (length > SP_TUNNEL_MAX_FRAME || !length)
        return -EMSGSIZE;
    if (radio->kind == SP_RADIO_MOCK) {
        radio->sent_frames++;
        return 0;
    }
    if (radio->kind == SP_RADIO_RAW80211) {
        static const uint8_t ssid[] = "Nintendo_3DS_continuous_scan_000";
        struct n3ds_streetpass_ioctl request;
        size_t offset = 0;
        if (!frame || !length || length > SP_RAW_VENDOR_FRAME_MAX)
            return -EMSGSIZE;
        memset(&request, 0, sizeof(request));
        request.version = N3DS_STREETPASS_ABI_VERSION;
        request.op = N3DS_STREETPASS_TX;
        request.frame_type = N3DS_STREETPASS_OPT_PROBE_REQ;
        request.channel_mhz = raw_channel_mhz(radio->raw.channel);
        request.data[offset++] = 0;
        request.data[offset++] = (uint8_t)(sizeof(ssid) - 1u);
        memcpy(request.data + offset, ssid, sizeof(ssid) - 1u);
        offset += sizeof(ssid) - 1u;
        request.data[offset++] = 221u;
        request.data[offset++] = (uint8_t)(4u + length);
        request.data[offset++] = 0x00;
        request.data[offset++] = 0x1f;
        request.data[offset++] = 0x32;
        request.data[offset++] = 0xa3;
        memcpy(request.data + offset, frame, length);
        offset += length;
        request.data_len = (uint16_t)offset;
        result = raw_ioctl(radio, &request);
        if (!result)
            radio->sent_frames++;
        return result;
    }
    if (radio->kind != SP_RADIO_MANAGED_TCP)
        return -EOPNOTSUPP;
    put_be_u32(prefix, (uint32_t)length);
    result = write_all(radio->fd, prefix, sizeof(prefix));
    if (!result)
        result = write_all(radio->fd, frame, length);
    if (!result)
        radio->sent_frames++;
    return result;
}
