#include "streetpass_journal.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define SP_STATE_MAGIC 0x3154534au /* JST1 */
#define SP_STATE_VERSION 2u
#define SP_QUEUE_MAGIC 0x31515453u /* STQ1 */

static uint16_t get_u16(const uint8_t *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t get_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t get_u64(const uint8_t *p) {
    uint64_t value = 0;
    unsigned int i;
    for (i = 0; i < 8; ++i)
        value |= ((uint64_t)p[i]) << (i * 8);
    return value;
}

static void put_u16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static void put_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static void put_u64(uint8_t *p, uint64_t v) {
    unsigned int i;
    for (i = 0; i < 8; ++i)
        p[i] = (uint8_t)(v >> (i * 8));
}

struct disk_state {
    uint32_t magic;
    uint32_t version;
    struct sp_journal_state state;
    uint32_t checksum;
} __attribute__((packed));

static int write_all(int fd, const void *data, size_t length) {
    const uint8_t *p = (const uint8_t *)data;
    while (length) {
        ssize_t n = write(fd, p, length);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            return -errno;
        p += n;
        length -= (size_t)n;
    }
    return 0;
}

static int read_all(int fd, void *data, size_t length) {
    uint8_t *p = (uint8_t *)data;
    while (length) {
        ssize_t n = read(fd, p, length);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            return n == 0 ? -EIO : -errno;
        p += n;
        length -= (size_t)n;
    }
    return 0;
}

static int mkdir_one(const char *path) {
    if (mkdir(path, 0700) == 0 || errno == EEXIST)
        return 0;
    return -errno;
}

static int sync_directory(const char *path) {
    int fd = open(path, O_RDONLY | O_DIRECTORY);
    int result;
    if (fd < 0)
        return -errno;
    result = fsync(fd) == 0 ? 0 : -errno;
    close(fd);
    return result;
}

static int path_join(char *out, size_t capacity, const char *directory,
                     const char *name) {
    int n = snprintf(out, capacity, "%s/%s", directory, name);
    return n < 0 || (size_t)n >= capacity ? -ENAMETOOLONG : 0;
}

const char *sp_state_name(enum sp_runtime_state state) {
    switch (state) {
    case SP_STATE_DISABLED: return "Disabled";
    case SP_STATE_STARTING: return "Starting";
    case SP_STATE_SEARCHING: return "Searching";
    case SP_STATE_AUTHENTICATING: return "Authenticating";
    case SP_STATE_EXCHANGING: return "Exchanging";
    case SP_STATE_DEGRADED: return "Degraded";
    case SP_STATE_DISCONNECTED: return "Disconnected";
    case SP_STATE_ERROR: return "Error";
    default: return "Unknown";
    }
}

int sp_journal_open(struct sp_journal *journal, const char *directory) {
    if (!journal || !directory || !*directory)
        return -EINVAL;
    memset(journal, 0, sizeof(*journal));
    if (strlen(directory) >= sizeof(journal->directory))
        return -ENAMETOOLONG;
    strcpy(journal->directory, directory);
    if (path_join(journal->state_path, sizeof(journal->state_path), directory,
                  "state.bin") ||
        path_join(journal->queue_path, sizeof(journal->queue_path), directory,
                  "outbox.bin"))
        return -ENAMETOOLONG;
    if (mkdir_one(directory))
        return -errno;
    memset(&journal->state, 0, sizeof(journal->state));
    journal->state.runtime_state = SP_STATE_DISABLED;
    return 0;
}

int sp_journal_load(struct sp_journal *journal) {
    struct disk_state disk;
    int fd;
    int result;
    if (!journal)
        return -EINVAL;
    fd = open(journal->state_path, O_RDONLY);
    if (fd < 0) {
        if (errno == ENOENT)
            return 0;
        return -errno;
    }
    result = read_all(fd, &disk, sizeof(disk));
    close(fd);
    if (result)
        return result;
    if (disk.magic != SP_STATE_MAGIC || disk.version != SP_STATE_VERSION ||
        disk.checksum != sp_checksum32(&disk.state, sizeof(disk.state)))
        return -EBADMSG;
    if (disk.state.sent_sequence > disk.state.next_sequence ||
        disk.state.acknowledged_sequence > disk.state.sent_sequence)
        return -EBADMSG;
    journal->state = disk.state;
    return 0;
}

int sp_journal_store(struct sp_journal *journal) {
    struct disk_state disk;
    char temporary[352];
    int fd;
    int result;
    if (!journal)
        return -EINVAL;
    memset(&disk, 0, sizeof(disk));
    disk.magic = SP_STATE_MAGIC;
    disk.version = SP_STATE_VERSION;
    disk.state = journal->state;
    disk.checksum = sp_checksum32(&disk.state, sizeof(disk.state));
    if (snprintf(temporary, sizeof(temporary), "%s.tmp", journal->state_path)
        >= (int)sizeof(temporary))
        return -ENAMETOOLONG;
    fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0)
        return -errno;
    result = write_all(fd, &disk, sizeof(disk));
    if (!result && fsync(fd) != 0)
        result = -errno;
    close(fd);
    if (result) {
        unlink(temporary);
        return result;
    }
    if (rename(temporary, journal->state_path) != 0)
        return -errno;
    return sync_directory(journal->directory);
}

int sp_journal_enqueue(struct sp_journal *journal, uint64_t sequence,
                       const void *payload, size_t length) {
    uint8_t header[16];
    int fd;
    int result;
    if (!journal || (!payload && length) || length > SP_JOURNAL_MAX_RECORD)
        return -EINVAL;
    put_u32(header + 0, SP_QUEUE_MAGIC);
    put_u64(header + 4, sequence);
    put_u16(header + 12, (uint16_t)length);
    put_u16(header + 14, 0);
    fd = open(journal->queue_path, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (fd < 0)
        return -errno;
    result = write_all(fd, header, sizeof(header));
    if (!result)
        result = write_all(fd, payload, length);
    if (!result && fsync(fd) != 0)
        result = -errno;
    close(fd);
    return result;
}

int sp_journal_acknowledge(struct sp_journal *journal, uint64_t sequence) {
    char temporary[352];
    int in_fd = -1;
    int out_fd = -1;
    uint8_t header[16];
    unsigned int records = 0;
    int result = 0;
    if (!journal)
        return -EINVAL;
    if (sequence > journal->state.acknowledged_sequence)
        journal->state.acknowledged_sequence = sequence;
    in_fd = open(journal->queue_path, O_RDONLY);
    if (in_fd < 0 && errno != ENOENT)
        return -errno;
    if (in_fd >= 0) {
        if (snprintf(temporary, sizeof(temporary), "%s.tmp", journal->queue_path)
            >= (int)sizeof(temporary)) {
            close(in_fd);
            return -ENAMETOOLONG;
        }
        out_fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC, 0600);
        if (out_fd < 0) {
            close(in_fd);
            return -errno;
        }
        for (;;) {
            uint8_t payload[SP_JOURNAL_MAX_RECORD];
            uint16_t length;
            uint64_t record_sequence;
            ssize_t n = read(in_fd, header, sizeof(header));
            if (n == 0)
                break;
            if (n < 0 && errno == EINTR)
                continue;
            if (n != (ssize_t)sizeof(header) || get_u32(header) != SP_QUEUE_MAGIC) {
                result = -EBADMSG;
                break;
            }
            record_sequence = get_u64(header + 4);
            length = get_u16(header + 12);
            if (length > SP_JOURNAL_MAX_RECORD || read_all(in_fd, payload, length)) {
                result = -EBADMSG;
                break;
            }
            if (record_sequence > UINT64_MAX - (uint64_t)length)
                result = -EBADMSG;
            if (!result && record_sequence + length > sequence) {
                if (!result)
                    result = write_all(out_fd, header, sizeof(header));
                if (!result)
                    result = write_all(out_fd, payload, length);
            }
            if (++records > SP_JOURNAL_MAX_PENDING * 8u) {
                result = -EOVERFLOW;
                break;
            }
        }
        if (!result && fsync(out_fd) != 0)
            result = -errno;
        close(in_fd);
        close(out_fd);
        if (!result) {
            if (rename(temporary, journal->queue_path) != 0)
                result = -errno;
            else
                result = sync_directory(journal->directory);
        } else {
            unlink(temporary);
        }
    }
    if (!result)
        result = sp_journal_store(journal);
    return result;
}

int sp_journal_replay(struct sp_journal *journal, sp_journal_record_fn callback,
                      void *context) {
    int fd;
    unsigned int records = 0;
    if (!journal || !callback)
        return -EINVAL;
    fd = open(journal->queue_path, O_RDONLY);
    if (fd < 0)
        return errno == ENOENT ? 0 : -errno;
    for (;;) {
        uint8_t header[16];
        uint8_t payload[SP_JOURNAL_MAX_RECORD];
        uint16_t length;
        uint64_t record_sequence;
        ssize_t n = read(fd, header, sizeof(header));
        int result;
        if (n == 0)
            break;
        if (n < 0 && errno == EINTR)
            continue;
        if (n != (ssize_t)sizeof(header) || get_u32(header) != SP_QUEUE_MAGIC) {
            close(fd);
            return -EBADMSG;
        }
        record_sequence = get_u64(header + 4);
        length = get_u16(header + 12);
        if (length > SP_JOURNAL_MAX_RECORD || read_all(fd, payload, length)) {
            close(fd);
            return -EBADMSG;
        }
        if (record_sequence > UINT64_MAX - (uint64_t)length) {
            close(fd);
            return -EBADMSG;
        }
        if (record_sequence + length > journal->state.acknowledged_sequence) {
            result = callback(record_sequence, payload, length, context);
            if (result) {
                close(fd);
                return result;
            }
        }
        if (++records > SP_JOURNAL_MAX_PENDING * 8u) {
            close(fd);
            return -EOVERFLOW;
        }
    }
    close(fd);
    return 0;
}
