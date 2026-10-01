#!/usr/bin/env python3
"""Remove the obsolete device-side host listener; publish actual TCP readiness."""
from a3ds_paths import A3DS_ROOT
from pathlib import Path

ROOT = Path(f'{A3DS_ROOT}/third_party/system_core/adb')
PATCHES = {
    'adb.c': [(
        '''    } else {
        if(install_listener("tcp:5037", "*smartsocket*", NULL)) {
            exit(1);
        }
    }

        /* for the device''',
        '''    } else {
        /* N3DS_ADBD_NO_DEVICE_HOST_LISTENER: 5037 is the PC adb server's
         * smart-socket protocol, not the device transport. A failed optional
         * bind here used to exit(1) before local_init could open port 5555.
         * Device shell/sync/JDWP services use the transport, not this listener. */
    }

        /* for the device'''), (
        '''    property_get("service.adb.tcp.port", value, "0");
    if (sscanf(value, "%d", &port) == 1 && port > 0) {''',
        '''    /* N3DS_ADBD_TCP_FAIL_CLOSED: no USB/default-port fallback when
     * debugging is disabled or a property is malformed. */
    property_set("sys.adb.tcp.ready", "0");
    property_get("service.adb.tcp.port", value, "0");
    {
        char *end;
        long requested = strtol(value, &end, 10);
        if (value[0] < '0' || value[0] > '9' || *end != '\\0' ||
            requested < 1 || requested > 65535) {
            return 0;
        }
        port = (int)requested;
    }
    if (port > 0) {''')],
    'transport_local.c': [(
        '#include "adb.h"',
        '''#include "adb.h"

/* N3DS_ADBD_TCP_READY: implemented in the TCP-only platform adapter. */
extern void n3ds_adbd_tcp_status(int port, int error);'''), (
        '''    int port = (int)arg;

    D("transport: server_socket_thread() starting\\n");''',
        '''    int port = (int)arg;
    int last_bind_error = 0;

    D("transport: server_socket_thread() starting\\n");'''), (
        '''            if(serverfd < 0) {
                D("server: cannot bind socket yet\\n");
                adb_sleep_ms(1000);
                continue;
            }
            close_on_exec(serverfd);''',
        '''            if(serverfd < 0) {
                int bind_error = errno;
                if (bind_error != last_bind_error) {
                    n3ds_adbd_tcp_status(port, bind_error);
                    last_bind_error = bind_error;
                }
                adb_sleep_ms(1000);
                continue;
            }
            close_on_exec(serverfd);
            n3ds_adbd_tcp_status(port, 0);''')],
}


def transform(text, pairs):
    for old, new in pairs:
        if text.count(new) == 1:
            continue
        if text.count(old) != 1:
            raise ValueError('missing, duplicate, or partial ADB patch anchor')
        text = text.replace(old, new)
    return text


def main():
    planned = [(ROOT / name, transform((ROOT / name).read_text(), pairs))
               for name, pairs in PATCHES.items()]
    for path, result in planned:
        if path.read_text() != result:
            path.write_text(result)
    print('adbd_tcp_lifecycle: patched / idempotent')


if __name__ == '__main__':
    main()
