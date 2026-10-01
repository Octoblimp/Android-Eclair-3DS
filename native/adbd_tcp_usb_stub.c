#include <stdio.h>
/* Android3DS has no USB gadget connection.  Keep adbd's transport ABI while
 * making USB initialization inert; adb.c selects the configured TCP port. */
#include <stddef.h>
#include "sysdeps.h"
#include "adb.h"
#include <android/log.h>

/* N3DS_ADBD_TCP_READY: only a successfully bound/listening transport may
 * publish readiness. No packets, shell commands or credentials are logged. */
void n3ds_adbd_tcp_status(int port, int error)
{
    char value[16];
    if (error) {
        property_set("sys.adb.tcp.ready", "0");
        __android_log_print(ANDROID_LOG_ERROR, "adbd",
                "N3DS_ADBD_TCP_BIND_FAILED port=%d errno=%d", port, error);
        fprintf(stderr, "N3DS_ADBD_TCP_BIND_FAILED port=%d errno=%d\n", port, error);
    } else {
        snprintf(value, sizeof(value), "%d", port);
        property_set("sys.adb.tcp.ready", value);
        __android_log_print(ANDROID_LOG_INFO, "adbd",
                "N3DS_ADBD_TCP_LISTENING port=%d", port);
        fprintf(stderr, "N3DS_ADBD_TCP_LISTENING port=%d\n", port);
    }
}

void usb_init(void) {}
void usb_cleanup(void) {}
int usb_write(usb_handle *h, const void *data, int len) { return -1; }
int usb_read(usb_handle *h, void *data, int len) { return -1; }
void usb_kick(usb_handle *h) {}
int usb_close(usb_handle *h) { return 0; }
