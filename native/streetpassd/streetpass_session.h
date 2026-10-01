#ifndef ANDROID3DS_STREETPASS_SESSION_H
#define ANDROID3DS_STREETPASS_SESSION_H

#include "streetpass_journal.h"

#include <stddef.h>
#include <stdint.h>

/* A complete authenticated SPB1 data frame must fit in one 255-byte vendor
 * IE after the OUI/type prefix. 128 bytes of ADB data plus the 76-byte SPB1
 * envelope leaves bounded room for the probe transport wrapper. */
#define SP_SESSION_DATA_MAX 128u
#define SP_SESSION_MAX_INFLIGHT (256u * 1024u)
#define SP_SESSION_MAX_QUEUE (512u * 1024u)
#define SP_SESSION_MAX_REORDER 4u

struct sp_session_reorder {
    uint64_t sequence;
    uint16_t length;
    uint8_t used;
    uint8_t payload[SP_SESSION_DATA_MAX];
};

struct sp_session {
    struct sp_journal *journal;
    uint8_t key[64];
    size_t key_length;
    uint8_t session[16];
    uint64_t tx_next;
    uint64_t tx_sent_next;
    uint64_t receive_next;
    uint64_t peer_acknowledgement;
    size_t queued_bytes;
    int connected;
    int authenticated;
    int acknowledgement_dirty;
    struct sp_session_reorder reorder[SP_SESSION_MAX_REORDER];
};

typedef int (*sp_session_deliver_fn)(const uint8_t *payload, size_t length,
                                     void *context);

int sp_session_init(struct sp_session *session, struct sp_journal *journal,
                    const uint8_t session_id[16], const void *key,
                    size_t key_length);
int sp_session_queue_data(struct sp_session *session, const void *data,
                          size_t length);
int sp_session_next_frame(struct sp_session *session, void *output,
                          size_t capacity, size_t *length);
int sp_session_build_hello(struct sp_session *session, const char *name,
                           const char *fingerprint, void *output,
                           size_t capacity, size_t *length);
int sp_session_build_resume(struct sp_session *session, void *output,
                            size_t capacity, size_t *length);
int sp_session_receive(struct sp_session *session, const void *frame,
                       size_t frame_length, sp_session_deliver_fn deliver,
                       void *context);
void sp_session_mark_radio_lost(struct sp_session *session);
int sp_session_has_pending(const struct sp_session *session);
size_t sp_session_queue_available(const struct sp_session *session);
int sp_session_is_authenticated(const struct sp_session *session);

#endif
