#include "streetpass_config.h"

#include <arpa/inet.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static int copy_value(char *destination, size_t capacity, const char *value) {
    size_t length;
    if (!destination || !value)
        return -EINVAL;
    length = strlen(value);
    if (!length || length >= capacity)
        return -ENAMETOOLONG;
    memcpy(destination, value, length + 1);
    return 0;
}

int sp_parse_mac_address(const char *text, uint8_t mac[6]) {
    unsigned int value;
    unsigned int index;
    if (!text || !mac)
        return -EINVAL;
    if (strlen(text) != 17)
        return -EINVAL;
    for (index = 0; index < 6; ++index) {
        size_t offset = index * 3;
        char high = text[offset];
        char low = text[offset + 1];
        if ((index && text[offset - 1] != ':') ||
            !((high >= '0' && high <= '9') ||
              (high >= 'a' && high <= 'f') ||
              (high >= 'A' && high <= 'F')) ||
            !((low >= '0' && low <= '9') ||
              (low >= 'a' && low <= 'f') ||
              (low >= 'A' && low <= 'F')))
            return -EINVAL;
        value = (unsigned int)(high <= '9' ? high - '0' :
                               high <= 'F' ? high - 'A' + 10 : high - 'a' + 10);
        value <<= 4;
        value |= (unsigned int)(low <= '9' ? low - '0' :
                                low <= 'F' ? low - 'A' + 10 : low - 'a' + 10);
        mac[index] = (uint8_t)value;
    }
    if (!(mac[0] | mac[1] | mac[2] | mac[3] | mac[4] | mac[5]) || (mac[0] & 1))
        return -EINVAL;
    return 0;
}

int sp_load_managed_config(const char *path, struct sp_managed_config *config) {
    FILE *file;
    struct stat metadata;
    char line[256];
    unsigned int seen = 0;
    if (!path || !config)
        return -EINVAL;
    memset(config, 0, sizeof(*config));
    if (stat(path, &metadata) != 0)
        return -errno;
    if (!S_ISREG(metadata.st_mode) || metadata.st_size <= 0 || metadata.st_size > 4096)
        return -EACCES;
    file = fopen(path, "r");
    if (!file)
        return -errno;
    while (fgets(line, sizeof(line), file)) {
        char *equals;
        char *key;
        char *value;
        size_t length = strlen(line);
        if (length == sizeof(line) - 1 && line[length - 1] != '\n' && !feof(file)) {
            fclose(file);
            return -E2BIG;
        }
        if (length && line[length - 1] == '\n')
            line[--length] = '\0';
        if (length && line[length - 1] == '\r')
            line[--length] = '\0';
        if (!line[0] || line[0] == '#')
            continue;
        equals = strchr(line, '=');
        if (!equals || equals == line || !equals[1] || strchr(equals + 1, '=')) {
            fclose(file);
            return -EINVAL;
        }
        key = line;
        value = equals + 1;
        *equals = '\0';
        if (!strcmp(key, "schema")) {
            if ((seen & 1u) || strcmp(value, "1")) { fclose(file); return -EINVAL; }
            seen |= 1u;
        } else if (!strcmp(key, "mac")) {
            if ((seen & 2u) || sp_parse_mac_address(value, config->mac)) { fclose(file); return -EINVAL; }
            seen |= 2u;
        } else if (!strcmp(key, "endpoint")) {
            struct in_addr address;
            if ((seen & 4u) || inet_pton(AF_INET, value, &address) != 1 ||
                address.s_addr == htonl(INADDR_ANY) ||
                (ntohl(address.s_addr) >= 0xe0000000u)) { fclose(file); return -EINVAL; }
            if (copy_value(config->endpoint, sizeof(config->endpoint), value)) { fclose(file); return -EINVAL; }
            seen |= 4u;
        } else if (!strcmp(key, "port")) {
            char *end;
            unsigned long port;
            errno = 0;
            if (seen & 8u) { fclose(file); return -EINVAL; }
            port = strtoul(value, &end, 10);
            if (errno || !*value || *end || port < 1024u || port > 65535u) { fclose(file); return -EINVAL; }
            config->port = (uint16_t)port;
            seen |= 8u;
        } else if (!strcmp(key, "protocol")) {
            if ((seen & 16u) || copy_value(config->protocol, sizeof(config->protocol), value) ||
                strcmp(value, SP_MANAGED_PROTOCOL)) { fclose(file); return -EINVAL; }
            seen |= 16u;
        } else {
            fclose(file);
            return -EINVAL;
        }
    }
    if (ferror(file)) {
        fclose(file);
        return -EIO;
    }
    fclose(file);
    if (seen != 31u)
        return -EINVAL;
    return 0;
}

int sp_load_raw_config(const char *path, struct sp_raw_config *config) {
    FILE *file;
    struct stat metadata;
    char line[256];
    unsigned int seen = 0;
    if (!path || !config)
        return -EINVAL;
    memset(config, 0, sizeof(*config));
    if (stat(path, &metadata) != 0)
        return -errno;
    if (!S_ISREG(metadata.st_mode) || metadata.st_size <= 0 || metadata.st_size > 4096)
        return -EACCES;
    file = fopen(path, "r");
    if (!file)
        return -errno;
    while (fgets(line, sizeof(line), file)) {
        char *equals;
        char *key;
        char *value;
        size_t length = strlen(line);
        if (length == sizeof(line) - 1 && line[length - 1] != '\n' && !feof(file)) {
            fclose(file);
            return -E2BIG;
        }
        if (length && line[length - 1] == '\n')
            line[--length] = '\0';
        if (length && line[length - 1] == '\r')
            line[--length] = '\0';
        if (!line[0] || line[0] == '#')
            continue;
        equals = strchr(line, '=');
        if (!equals || equals == line || !equals[1] || strchr(equals + 1, '=')) {
            fclose(file);
            return -EINVAL;
        }
        key = line;
        value = equals + 1;
        *equals = '\0';
        if (!strcmp(key, "schema")) {
            if ((seen & 1u) || strcmp(value, "1")) { fclose(file); return -EINVAL; }
            seen |= 1u;
        } else if (!strcmp(key, "interface")) {
            size_t i;
            if ((seen & 2u) || copy_value(config->interface,
                                           sizeof(config->interface), value)) {
                fclose(file); return -EINVAL;
            }
            for (i = 0; config->interface[i]; ++i) {
                char c = config->interface[i];
                if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                      (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.')) {
                    fclose(file); return -EINVAL;
                }
            }
            if (!strcmp(config->interface, "YOUR_LINUX_INTERFACE")) {
                fclose(file); return -EINVAL;
            }
            seen |= 2u;
        } else if (!strcmp(key, "peer_mac")) {
            if ((seen & 4u) || sp_parse_mac_address(value, config->peer_mac)) {
                fclose(file); return -EINVAL;
            }
            seen |= 4u;
        } else if (!strcmp(key, "channel")) {
            char *end;
            unsigned long channel;
            errno = 0;
            if (seen & 8u) { fclose(file); return -EINVAL; }
            channel = strtoul(value, &end, 10);
            if (errno || !*value || *end || channel < 1u || channel > 14u) {
                fclose(file); return -EINVAL;
            }
            config->channel = (uint8_t)channel;
            seen |= 8u;
        } else {
            fclose(file);
            return -EINVAL;
        }
    }
    if (ferror(file)) {
        fclose(file);
        return -EIO;
    }
    fclose(file);
    return seen == 15u ? 0 : -EINVAL;
}
