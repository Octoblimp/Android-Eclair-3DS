#include "streetpass_journal.h"
#include "streetpass_config.h"
#include "streetpass_radio.h"
#include "streetpass_adb_proxy.h"
#include "streetpass_session.h"
#include "streetpass_led.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t running = 1;

static void stop_handler(int signal_number) {
    (void)signal_number;
    running = 0;
}

static int read_secret_file(const char *path, uint8_t *output,
                            size_t capacity, size_t *length) {
    int fd;
    ssize_t n;
    struct stat metadata;
    if (!path || !output || !length)
        return -EINVAL;
    fd = open(path, O_RDONLY);
    if (fd < 0)
        return -errno;
    if (fstat(fd, &metadata) != 0 || !S_ISREG(metadata.st_mode) ||
        (metadata.st_mode & 0077) || metadata.st_size < 16 ||
        (uintmax_t)metadata.st_size > (uintmax_t)capacity) {
        close(fd);
        return -EACCES;
    }
    n = read(fd, output, (size_t)metadata.st_size);
    close(fd);
    if (n < 0)
        return -errno;
    if (n != metadata.st_size)
        return -EACCES;
    *length = (size_t)n;
    return 0;
}

static int read_session_id(const struct sp_journal *journal, uint8_t output[16]) {
    int fd;
    ssize_t n;
    static const uint8_t zero[16] = {0};
    if (!journal || !output)
        return -EINVAL;
    if (memcmp(journal->state.session, zero, sizeof(zero))) {
        memcpy(output, journal->state.session, sizeof(zero));
        return 0;
    }
    fd = open("/dev/urandom", O_RDONLY);
    if (fd < 0)
        return -errno;
    n = read(fd, output, 16);
    close(fd);
    if (n != 16)
        return -EIO;
    return 0;
}

static int deliver_to_adb(const uint8_t *payload, size_t length, void *context) {
    struct sp_adb_proxy *proxy = (struct sp_adb_proxy *)context;
    return sp_adb_proxy_write(proxy, payload, length);
}

static int pump_adb_to_session(struct sp_session *session,
                               struct sp_adb_proxy *proxy) {
    uint8_t buffer[4096];
    size_t available;
    size_t length;
    int result;
    if (!session || !proxy || proxy->fd < 0)
        return 0;
    available = sp_session_queue_available(session);
    if (!available)
        return 0;
    if (available > sizeof(buffer))
        available = sizeof(buffer);
    result = sp_adb_proxy_read(proxy, buffer, available, &length);
    if (result)
        return result;
    if (!length)
        return 0;
    return sp_session_queue_data(session, buffer, length);
}

static int mkdir_path(const char *path) {
    if (mkdir(path, 0700) == 0 || errno == EEXIST)
        return 0;
    return -errno;
}

static int read_property_flag(const char *property, int *value) {
    FILE *pipe;
    char command[192];
    char line[32];
    int n;
    if (!property || !value)
        return -EINVAL;
    n = snprintf(command, sizeof(command), "/system/bin/getprop %s", property);
    if (n < 0 || (size_t)n >= sizeof(command))
        return -ENAMETOOLONG;
    pipe = popen(command, "r");
    if (!pipe)
        return -errno;
    if (!fgets(line, sizeof(line), pipe)) {
        pclose(pipe);
        return 1;
    }
    pclose(pipe);
    *value = (line[0] == '1' || line[0] == 'y' || line[0] == 'Y' ||
              line[0] == 't' || line[0] == 'T');
    return 0;
}

static int read_flag(const char *property, int fallback) {
    int value = fallback;
    if (read_property_flag(property, &value) == 0)
        return value;
    return fallback;
}

static int atomic_write_status(const char *directory,
                               const struct sp_journal_state *state,
                               const char *backend, const char *error) {
    char path[352];
    char temporary[368];
    FILE *file;
    int n;
    int fd;
    if (!directory || !state)
        return -EINVAL;
    n = snprintf(path, sizeof(path), "%s/status", directory);
    if (n < 0 || (size_t)n >= sizeof(path))
        return -ENAMETOOLONG;
    n = snprintf(temporary, sizeof(temporary), "%s.tmp", path);
    if (n < 0 || (size_t)n >= sizeof(temporary))
        return -ENAMETOOLONG;
    file = fopen(temporary, "w");
    if (!file)
        return -errno;
    fprintf(file, "enabled=%u\n", state->enabled ? 1u : 0u);
    fprintf(file, "adb_enabled=%u\n", state->adb_enabled ? 1u : 0u);
    fprintf(file, "state=%s\n", sp_state_name((enum sp_runtime_state)state->runtime_state));
    fprintf(file, "peer=%s\n", state->peer.name[0] ? state->peer.name : "");
    fprintf(file, "backend=%s\n", backend ? backend : "unknown");
    fprintf(file, "error=%s\n", error ? error : state->last_error);
    if (fflush(file) != 0)
        n = -errno;
    else {
        fd = fileno(file);
        n = fsync(fd) == 0 ? 0 : -errno;
    }
    fclose(file);
    if (n)
        return n;
    if (rename(temporary, path) != 0)
        return -errno;
    fd = open(directory, O_RDONLY | O_DIRECTORY);
    if (fd < 0)
        return -errno;
    n = fsync(fd) == 0 ? 0 : -errno;
    close(fd);
    return n;
}

static void set_property(const char *name, const char *value) {
    pid_t pid;
    int status;
    if (!name || !value)
        return;
    pid = fork();
    if (pid == 0) {
        execl("/system/bin/setprop", "setprop", name, value, (char *)0);
        _exit(127);
    }
    if (pid > 0)
        waitpid(pid, &status, 0);
}

static void publish_status(struct sp_led *led, const char *directory,
                           struct sp_journal *journal,
                           enum sp_runtime_state state, const char *backend,
                           const char *error) {
    char last_seen[32];
    static unsigned int previous_state = UINT_MAX;
    static unsigned int previous_enabled = UINT_MAX;
    static unsigned int previous_adb_enabled = UINT_MAX;
    static char previous_backend[32];
    static char previous_error[sizeof(journal->state.last_error)];
    static char previous_peer[sizeof(journal->state.peer.name)];
    int changed;

    if (led)
        sp_led_set_state(led, (unsigned)state, journal->state.enabled != 0);
    if (state != SP_STATE_EXCHANGING)
        memset(&journal->state.peer, 0, sizeof(journal->state.peer));
    journal->state.runtime_state = state;
    if (error)
        snprintf(journal->state.last_error, sizeof(journal->state.last_error),
                 "%s", error);
    else
        journal->state.last_error[0] = '\0';
    changed = previous_state != (unsigned)state ||
              previous_enabled != journal->state.enabled ||
              previous_adb_enabled != journal->state.adb_enabled ||
              strcmp(previous_backend, backend ? backend : "unknown") != 0 ||
              strcmp(previous_error, journal->state.last_error) != 0 ||
              strcmp(previous_peer, journal->state.peer.name) != 0;
    if (!changed)
        return;
    previous_state = (unsigned)state;
    previous_enabled = journal->state.enabled;
    previous_adb_enabled = journal->state.adb_enabled;
    snprintf(previous_backend, sizeof(previous_backend), "%s",
             backend ? backend : "unknown");
    snprintf(previous_error, sizeof(previous_error), "%s",
             journal->state.last_error);
    snprintf(previous_peer, sizeof(previous_peer), "%s",
             journal->state.peer.name);
    (void)sp_journal_store(journal);
    (void)atomic_write_status(directory, &journal->state, backend, error);
    set_property("sys.streetpass.state", sp_state_name(state));
    set_property("sys.streetpass.peer",
                 state == SP_STATE_EXCHANGING && journal->state.peer.name[0]
                     ? journal->state.peer.name : "none");
    /* No real backend in this tree can authenticate a peer yet. Keep the
     * daemon-owned status explicit instead of allowing init/request
     * properties to masquerade as a last-seen radio exchange. */
    if (state == SP_STATE_EXCHANGING && journal->state.peer.name[0])
        snprintf(last_seen, sizeof(last_seen), "%lu",
                 (unsigned long)time(NULL));
    else
        strcpy(last_seen, "never");
    set_property("sys.streetpass.last_seen", last_seen);
}

static enum sp_radio_kind parse_backend(const char *name) {
    if (!name || !strcmp(name, "unavailable"))
        return SP_RADIO_UNAVAILABLE;
    if (!strcmp(name, "raw80211"))
        return SP_RADIO_RAW80211;
    if (!strcmp(name, "mock"))
        return SP_RADIO_MOCK;
    if (!strcmp(name, "managed") || !strcmp(name, "managed-tcp"))
        return SP_RADIO_MANAGED_TCP;
    return SP_RADIO_UNAVAILABLE;
}

static void usage(const char *program) {
    fprintf(stderr, "usage: %s [--state-dir DIR] [--control FILE] "
                    "[--backend unavailable|managed|mock] [--key-file FILE] "
                    "[--transport-config FILE] [--once]\n",
            program);
}

static void sleep_millis(unsigned int milliseconds) {
    struct timespec delay;
    delay.tv_sec = milliseconds / 1000u;
    delay.tv_nsec = (long)(milliseconds % 1000u) * 1000000L;
    while (nanosleep(&delay, &delay) != 0 && errno == EINTR)
        ;
}

int main(int argc, char **argv) {
    const char *directory = "/data/misc/streetpass";
    const char *control = "/data/misc/streetpass/control";
    const char *backend_name = "unavailable";
    /* The init service uses this provisioned, mode-0600 file.  A missing or
     * malformed file keeps the daemon fail-closed; --key-file remains useful
     * for factory/test layouts without changing the default boundary. */
    const char *key_path = "/tmp/streetpass/key";
    const char *transport_config_path = NULL;
    struct sp_managed_config managed_config;
    struct sp_raw_config raw_config;
    struct sp_journal journal;
    struct sp_radio radio;
    struct sp_adb_proxy adb_proxy;
    struct sp_session session;
    struct sp_led led;
    enum sp_radio_kind backend;
    uint8_t key[64];
    size_t key_length = 0;
    uint8_t session_id[16];
    int once = 0;
    int session_ready = 0;
    int resume_sent = 0;
    int i;
    int result;
    int enabled;
    int adb_enabled;
    static uint8_t frame[SP_TUNNEL_MAX_FRAME];
    static uint8_t outgoing[SP_TUNNEL_MAX_FRAME];
    size_t frame_length;
    size_t outgoing_length;

    for (i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--once")) {
            once = 1;
        } else if (!strcmp(argv[i], "--state-dir") && i + 1 < argc) {
            directory = argv[++i];
        } else if (!strcmp(argv[i], "--control") && i + 1 < argc) {
            control = argv[++i];
        } else if (!strcmp(argv[i], "--backend") && i + 1 < argc) {
            backend_name = argv[++i];
        } else if (!strcmp(argv[i], "--key-file") && i + 1 < argc) {
            key_path = argv[++i];
        } else if (!strcmp(argv[i], "--transport-config") && i + 1 < argc) {
            transport_config_path = argv[++i];
        } else {
            usage(argv[0]);
            return 2;
        }
    }

    if (mkdir_path(directory)) {
        fprintf(stderr, "streetpassd: cannot create state directory %s\n", directory);
        return 1;
    }
    result = sp_journal_open(&journal, directory);
    if (result || (result = sp_journal_load(&journal))) {
        fprintf(stderr, "streetpassd: journal failure: %d\n", result);
        return 1;
    }
    if (key_path)
        result = read_secret_file(key_path, key, sizeof(key), &key_length);
    else
        result = -EACCES;
    if (!result && !read_session_id(&journal, session_id) &&
        !sp_session_init(&session, &journal, session_id, key, key_length)) {
        memcpy(journal.state.session, session_id, sizeof(session_id));
        (void)sp_journal_store(&journal);
        session_ready = 1;
    } else {
        key_length = 0;
        memset(&session, 0, sizeof(session));
    }
    signal(SIGTERM, stop_handler);
    signal(SIGINT, stop_handler);
    backend = parse_backend(backend_name);
    memset(&managed_config, 0, sizeof(managed_config));
    memset(&raw_config, 0, sizeof(raw_config));
    if (!transport_config_path) {
        transport_config_path = backend == SP_RADIO_RAW80211
            ? "/mnt/sd/linux/android/persistent/shared/streetpass-radio.conf"
            : "/mnt/sd/linux/android/persistent/shared/streetpass-transport.conf";
    }
    if (backend == SP_RADIO_MANAGED_TCP) {
        result = sp_load_managed_config(transport_config_path, &managed_config);
        if (result) {
            snprintf(journal.state.last_error, sizeof(journal.state.last_error),
                     "managed-config-invalid");
        }
    } else if (backend == SP_RADIO_RAW80211) {
        result = sp_load_raw_config(transport_config_path, &raw_config);
        if (result) {
            snprintf(journal.state.last_error, sizeof(journal.state.last_error),
                     "raw-config-invalid");
        }
    }
    memset(&radio, 0, sizeof(radio));
    sp_adb_proxy_init(&adb_proxy);
    (void)sp_led_init(&led, NULL);

    publish_status(&led, directory, &journal, SP_STATE_DISABLED,
                   sp_radio_kind_name(backend), "");
    while (running) {
        (void)control;
        enabled = read_flag("persist.sys.streetpass.enabled", 0);
        adb_enabled = read_flag("persist.sys.streetpass.adb", 0);
        journal.state.enabled = enabled ? 1u : 0u;
        journal.state.adb_enabled = (enabled && adb_enabled) ? 1u : 0u;

        if (!enabled) {
            sp_radio_close(&radio);
            sp_adb_proxy_close(&adb_proxy);
            if (session_ready)
                sp_session_mark_radio_lost(&session);
            resume_sent = 0;
            publish_status(&led, directory, &journal, SP_STATE_DISABLED,
                           sp_radio_kind_name(backend), "");
        } else if (!session_ready) {
            sp_radio_close(&radio);
            sp_adb_proxy_close(&adb_proxy);
            publish_status(&led, directory, &journal, SP_STATE_ERROR,
                           sp_radio_kind_name(backend),
                           "key-material-unavailable");
        } else if (!radio.opened) {
            sp_adb_proxy_close(&adb_proxy);
            publish_status(&led, directory, &journal, SP_STATE_STARTING,
                           sp_radio_kind_name(backend), "");
            result = sp_radio_open(&radio, backend,
                                   backend == SP_RADIO_MANAGED_TCP
                                       ? &managed_config : NULL,
                                   backend == SP_RADIO_RAW80211
                                       ? &raw_config : NULL,
                                   key, key_length);
            if (result) {
                publish_status(&led, directory, &journal, SP_STATE_ERROR,
                               sp_radio_kind_name(backend),
                               radio.error[0] ? radio.error : "radio-open-failed");
            } else {
                session.connected = 1;
                session.authenticated = 0;
                resume_sent = 0;
                publish_status(&led, directory, &journal, SP_STATE_SEARCHING,
                               sp_radio_kind_name(backend), "");
            }
        } else {
            if (!journal.state.adb_enabled)
                sp_adb_proxy_close(&adb_proxy);
            if (sp_session_is_authenticated(&session) && journal.state.adb_enabled &&
                adb_proxy.fd < 0)
                (void)sp_adb_proxy_connect(&adb_proxy, 1, 5555);

            if (!resume_sent) {
                result = sp_session_build_resume(&session, outgoing,
                                                 sizeof(outgoing), &outgoing_length);
                if (!result)
                    result = sp_radio_send(&radio, outgoing, outgoing_length);
                if (result) {
                    sp_session_mark_radio_lost(&session);
                    sp_radio_close(&radio);
                    publish_status(&led, directory, &journal, SP_STATE_DEGRADED,
                                   sp_radio_kind_name(backend), "resume-send-failed");
                    if (once)
                        break;
                    sp_led_tick(&led, 0);
                    sleep_millis(100);
                    continue;
                }
                resume_sent = 1;
            }
            result = sp_radio_poll(&radio, frame, sizeof(frame), &frame_length);
            if (result) {
                sp_session_mark_radio_lost(&session);
                sp_radio_close(&radio);
                publish_status(&led, directory, &journal, SP_STATE_DEGRADED,
                               sp_radio_kind_name(backend), "radio-poll-failed");
            } else if (frame_length) {
                result = sp_session_receive(&session, frame, frame_length,
                                            deliver_to_adb, &adb_proxy);
                if (result) {
                    publish_status(&led, directory, &journal, SP_STATE_AUTHENTICATING,
                                   sp_radio_kind_name(backend),
                                   "peer-authentication-required");
                } else if (sp_session_is_authenticated(&session)) {
                    publish_status(&led, directory, &journal, SP_STATE_EXCHANGING,
                                   sp_radio_kind_name(backend), "");
                } else {
                    publish_status(&led, directory, &journal, SP_STATE_AUTHENTICATING,
                                   sp_radio_kind_name(backend), "");
                }
            } else {
                publish_status(&led, directory, &journal,
                               sp_session_is_authenticated(&session)
                                   ? SP_STATE_EXCHANGING : SP_STATE_SEARCHING,
                               sp_radio_kind_name(backend), "");
            }
            if (sp_session_is_authenticated(&session)) {
                result = pump_adb_to_session(&session, &adb_proxy);
                if (result && result != -EAGAIN)
                    publish_status(&led, directory, &journal, SP_STATE_DEGRADED,
                                   sp_radio_kind_name(backend), "adb-read-failed");
                if (!sp_session_next_frame(&session, outgoing, sizeof(outgoing),
                                           &outgoing_length) && outgoing_length) {
                    if (sp_radio_send(&radio, outgoing, outgoing_length))
                        publish_status(&led, directory, &journal, SP_STATE_DEGRADED,
                                       sp_radio_kind_name(backend),
                                       "tunnel-send-failed");
                }
            }
        }
        if (once)
            break;
        sp_led_tick(&led, 0);
        sleep_millis(100);
    }
    sp_radio_close(&radio);
    sp_adb_proxy_close(&adb_proxy);
    publish_status(&led, directory, &journal,
                   read_flag("persist.sys.streetpass.enabled", 0)
                       ? SP_STATE_DISCONNECTED : SP_STATE_DISABLED,
                   sp_radio_kind_name(backend),
                   journal.state.last_error[0] ? journal.state.last_error :
                                                "daemon-stopped");
    sp_led_close(&led);
    return 0;
}
