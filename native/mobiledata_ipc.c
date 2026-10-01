/*
 * Private WPA2 provisioning bridge for 3DS Telco.
 *
 * init owns the listening socket and starts this process as root.  Settings
 * connects as the Android system UID; this process verifies that peer before
 * ever accepting a command.  The credential itself is copied only through a
 * pipe into mobiledata.sh --provision-secret, whose destination is tmpfs.
 * Nothing secret is put in argv, properties, logs, or the FAT-backed tree.
 */

/* #define _GNU_SOURCE */

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef SO_PEERCRED
#error "mobiledata_ipc requires Linux peer credentials"
#endif

#ifndef SETTINGS_UID
#define SETTINGS_UID 1000
#endif
#define SERVER_QUEUE_DEPTH 4
#define MAX_REQUEST 65       /* command byte plus at most 63 password bytes */
#define REQUEST_TIMEOUT 5

static int peer_is_settings(int fd)
{
    struct ucred cred;
    socklen_t length = sizeof(cred);

    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &cred, &length) != 0)
        return 0;
    return cred.uid == SETTINGS_UID;
}

static int write_all(int fd, const unsigned char *data, size_t length)
{
    while (length != 0) {
        ssize_t written = write(fd, data, length);
        if (written < 0 && errno == EINTR)
            continue;
        if (written <= 0)
            return -1;
        data += written;
        length -= (size_t)written;
    }
    return 0;
}

static int read_request(int fd, unsigned char *request, size_t *length)
{
    size_t used = 0;

    while (used < sizeof(unsigned char) * MAX_REQUEST) {
        ssize_t count = read(fd, request + used, MAX_REQUEST - used);
        if (count < 0 && errno == EINTR)
            continue;
        if (count < 0)
            return -1;
        if (count == 0)
            break;
        used += (size_t)count;
        if (used == MAX_REQUEST)
            return -1; /* 65 bytes means a command plus an overlong value */
    }
    *length = used;
    return 0;
}

static int valid_secret(const unsigned char *secret, size_t length)
{
    size_t i;

    if (length < 8 || length > 63)
        return 0;
    for (i = 0; i < length; ++i) {
        if (secret[i] < 0x20 || secret[i] > 0x7e)
            return 0;
    }
    return 1;
}

static int run_script(const char *operation, const unsigned char *secret,
                      size_t length)
{
    int pipefd[2];
    pid_t child;
    int status;

    if (pipe(pipefd) != 0)
        return -1;
    child = fork();
    if (child < 0) {
        close(pipefd[0]);
        close(pipefd[1]);
        return -1;
    }
    if (child == 0) {
        close(pipefd[1]);
        if (dup2(pipefd[0], STDIN_FILENO) < 0)
            _exit(127);
        close(pipefd[0]);
        execl("/etc/mobiledata.sh", "mobiledata.sh", operation,
              (char *)0);
        _exit(127);
    }

    close(pipefd[0]);
    if (length != 0 && write_all(pipefd[1], secret, length) != 0) {
        close(pipefd[1]);
        kill(child, SIGTERM);
        waitpid(child, &status, 0);
        return -1;
    }
    close(pipefd[1]);
    for (;;) {
        if (waitpid(child, &status, 0) >= 0)
            break;
        if (errno != EINTR)
            return -1;
    }
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : -1;
}

static int handle_client(int client)
{
    unsigned char request[MAX_REQUEST];
    size_t length = 0;
    int ok = 0;

    if (!peer_is_settings(client))
        return -1;
    if (setsockopt(client, SOL_SOCKET, SO_RCVTIMEO,
                   &(struct timeval){REQUEST_TIMEOUT, 0},
                   sizeof(struct timeval)) != 0)
        return -1;
    if (read_request(client, request, &length) != 0 || length == 0)
        return -1;
    if (request[0] == 'C' && length == 1) {
        ok = run_script("--clear-secret", 0, 0) == 0;
    } else if (request[0] == 'P'
               && valid_secret(request + 1, length - 1)) {
        ok = run_script("--provision-secret", request + 1, length - 1) == 0;
    }
    return ok ? 0 : -1;
}

int main(void)
{
    const char *value = getenv("ANDROID_SOCKET_mobiledata");
    int server;

    if (value == 0 || *value == '\0')
        return 1;
    server = atoi(value);
    if (server < 0)
        return 1;
    /* Android init creates and binds service sockets, but this vintage init
     * deliberately leaves listen(2) to the daemon.  Calling accept(2) on the
     * merely-bound fd returns EINVAL and caused init to restart this service
     * every five seconds. */
    if (listen(server, SERVER_QUEUE_DEPTH) != 0)
        return 1;
    for (;;) {
        int client = accept(server, 0, 0);
        unsigned char response[3] = {'E', 'R', 'R'};
        if (client < 0) {
            if (errno == EINTR)
                continue;
            return 1;
        }
        if (handle_client(client) == 0) {
            response[0] = 'O';
            response[1] = 'K';
        }
        (void)write_all(client, response, 2);
        close(client);
    }
}
