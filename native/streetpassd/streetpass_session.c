#include "streetpass_session.h"

#include <errno.h>
#include <string.h>

struct pending_record {
    uint64_t sequence;
    size_t length;
    uint8_t payload[SP_SESSION_DATA_MAX];
    int found;
};

static int count_pending(uint64_t sequence, const uint8_t *payload,
                         size_t length, void *context) {
    size_t *total = (size_t *)context;
    (void)sequence;
    (void)payload;
    if (*total > SP_SESSION_MAX_QUEUE - length)
        return -EOVERFLOW;
    *total += length;
    return 0;
}

static int find_pending(uint64_t sequence, const uint8_t *payload,
                        size_t length, void *context) {
    struct pending_record *record = (struct pending_record *)context;
    if (record->found)
        return 0;
    if (length > sizeof(record->payload))
        return -EMSGSIZE;
    record->sequence = sequence;
    record->length = length;
    memcpy(record->payload, payload, length);
    record->found = 1;
    return 0;
}

static int persist(struct sp_session *session) {
    struct sp_journal_state *state = &session->journal->state;
    memcpy(state->session, session->session, sizeof(state->session));
    state->next_sequence = session->tx_next;
    state->sent_sequence = session->tx_sent_next;
    state->acknowledged_sequence = session->peer_acknowledgement;
    state->receive_sequence = session->receive_next;
    return sp_journal_store(session->journal);
}

static int ranges_overlap(uint64_t left, size_t left_length,
                          uint64_t right, size_t right_length) {
    uint64_t left_end = left + left_length;
    uint64_t right_end = right + right_length;
    return left < right_end && right < left_end;
}

static int deliver_reorder(struct sp_session *session,
                           sp_session_deliver_fn deliver, void *context) {
    unsigned int i;
    for (;;) {
        int found = -1;
        for (i = 0; i < SP_SESSION_MAX_REORDER; ++i) {
            if (session->reorder[i].used &&
                session->reorder[i].sequence == session->receive_next) {
                found = (int)i;
                break;
            }
        }
        if (found < 0)
            return 0;
        if (deliver(session->reorder[found].payload,
                    session->reorder[found].length, context))
            return -EIO;
        if (session->receive_next > UINT64_MAX -
            (uint64_t)session->reorder[found].length)
            return -EOVERFLOW;
        session->receive_next += session->reorder[found].length;
        session->reorder[found].used = 0;
    }
}

int sp_session_init(struct sp_session *session, struct sp_journal *journal,
                    const uint8_t session_id[16], const void *key,
                    size_t key_length) {
    size_t queued = 0;
    if (!session || !journal || !session_id || !key || !key_length ||
        key_length > sizeof(session->key))
        return -EINVAL;
    memset(session, 0, sizeof(*session));
    session->journal = journal;
    memcpy(session->key, key, key_length);
    session->key_length = key_length;
    {
        static const uint8_t zero_session[16] = {0};
        if (memcmp(journal->state.session, zero_session, sizeof(zero_session)) &&
            memcmp(journal->state.session, session_id, sizeof(zero_session)))
            return -EPROTO;
    }
    memcpy(session->session, session_id, 16);
    session->tx_next = journal->state.next_sequence;
    session->tx_sent_next = journal->state.sent_sequence;
    if (session->tx_sent_next > session->tx_next ||
        journal->state.acknowledged_sequence > session->tx_sent_next)
        return -EBADMSG;
    session->peer_acknowledgement = journal->state.acknowledged_sequence;
    session->receive_next = journal->state.receive_sequence;
    if (sp_journal_replay(journal, count_pending, &queued))
        return -EBADMSG;
    session->queued_bytes = queued;
    return 0;
}

int sp_session_queue_data(struct sp_session *session, const void *data,
                          size_t length) {
    const uint8_t *p = (const uint8_t *)data;
    if (!session || (!data && length))
        return -EINVAL;
    if (length > UINT64_MAX - session->tx_next)
        return -EOVERFLOW;
    if (length > SP_SESSION_MAX_QUEUE - session->queued_bytes)
        return -EAGAIN;
    while (length) {
        size_t n = length > SP_SESSION_DATA_MAX ? SP_SESSION_DATA_MAX : length;
        if (sp_journal_enqueue(session->journal, session->tx_next, p, n))
            return -EIO;
        session->tx_next += n;
        session->queued_bytes += n;
        p += n;
        length -= n;
    }
    return persist(session);
}

int sp_session_next_frame(struct sp_session *session, void *output,
                          size_t capacity, size_t *length) {
    struct pending_record record;
    struct sp_tunnel_header header;
    static const uint8_t empty_key[1] = {0};
    int result;
    if (!session || !output || !length)
        return -EINVAL;
    *length = 0;
    memset(&record, 0, sizeof(record));
    if (sp_journal_replay(session->journal, find_pending, &record))
        return -EBADMSG;
    memset(&header, 0, sizeof(header));
    header.version = SP_TUNNEL_VERSION;
    memcpy(header.session, session->session, sizeof(header.session));
    header.acknowledgement = session->receive_next;
    if (record.found) {
        header.flags = SP_TUNNEL_DATA | SP_TUNNEL_ACK;
        header.channel = 1;
        header.sequence = record.sequence;
        if (record.sequence > UINT64_MAX - (uint64_t)record.length)
            return -EOVERFLOW;
        result = sp_frame_encode(&header, record.payload, record.length,
                                 session->key, session->key_length, output,
                                 capacity, length);
        if (result)
            return result;
        if (record.sequence + record.length > session->tx_sent_next) {
            session->tx_sent_next = record.sequence + record.length;
            if (persist(session))
                return -EIO;
        }
        return 0;
    }
    if (!session->acknowledgement_dirty)
        return 0;
    header.flags = SP_TUNNEL_ACK;
    header.channel = 0;
    if (sp_frame_encode(&header, empty_key, 0, session->key, session->key_length,
                        output, capacity, length))
        return -EMSGSIZE;
    session->acknowledgement_dirty = 0;
    return 0;
}

int sp_session_build_hello(struct sp_session *session, const char *name,
                           const char *fingerprint, void *output,
                           size_t capacity, size_t *length) {
    uint8_t payload[8 + 64 + 96];
    size_t payload_length;
    struct sp_tunnel_header header;
    int result;
    if (!session || !output || !length)
        return -EINVAL;
    result = sp_build_hello_payload(name, fingerprint, payload,
                                     sizeof(payload), &payload_length);
    if (result)
        return result;
    memset(&header, 0, sizeof(header));
    header.version = SP_TUNNEL_VERSION;
    header.flags = SP_TUNNEL_HELLO;
    memcpy(header.session, session->session, sizeof(header.session));
    return sp_frame_encode(&header, payload, payload_length,
                           session->key, session->key_length, output,
                           capacity, length);
}

int sp_session_build_resume(struct sp_session *session, void *output,
                            size_t capacity, size_t *length) {
    uint8_t payload[36];
    size_t payload_length;
    struct sp_tunnel_header header;
    if (!session || !output || !length)
        return -EINVAL;
    if (sp_build_resume_payload(session->session, session->tx_next,
                                session->receive_next, payload,
                                sizeof(payload), &payload_length))
        return -EINVAL;
    memset(&header, 0, sizeof(header));
    header.version = SP_TUNNEL_VERSION;
    header.flags = SP_TUNNEL_RESUME;
    memcpy(header.session, session->session, sizeof(header.session));
    return sp_frame_encode(&header, payload, payload_length, session->key,
                           session->key_length, output, capacity, length);
}

int sp_session_receive(struct sp_session *session, const void *frame,
                       size_t frame_length, sp_session_deliver_fn deliver,
                       void *context) {
    static uint8_t payload[SP_TUNNEL_MAX_PAYLOAD];
    struct sp_tunnel_header header;
    size_t payload_length;
    unsigned int i;
    int result;
    if (!session || !frame || !deliver)
        return -EINVAL;
    result = sp_frame_decode(frame, frame_length, &header, payload,
                             sizeof(payload), &payload_length, session->key,
                             session->key_length);
    if (result)
        return result;
    if (memcmp(header.session, session->session, sizeof(session->session)))
        return -EPROTO;
    /* The header carries a cumulative ACK on every authenticated frame;
     * delayed ACKs are harmless, while a forward ACK beyond the sent
     * watermark is impossible and rejected. */
    if (header.acknowledgement < session->peer_acknowledgement)
        goto process_non_ack;
    if (header.acknowledgement > session->tx_sent_next)
        return -ERANGE;
    if (header.acknowledgement > session->peer_acknowledgement) {
        if (sp_journal_acknowledge(session->journal,
                                   header.acknowledgement))
            return -EIO;
        session->peer_acknowledgement = header.acknowledgement;
        session->queued_bytes = 0;
        if (sp_journal_replay(session->journal, count_pending,
                              &session->queued_bytes))
            return -EBADMSG;
    }
process_non_ack:
    if (header.flags & SP_TUNNEL_DATA) {
        if (!session->authenticated)
            return -EACCES;
        if (payload_length > SP_SESSION_DATA_MAX)
            return -EMSGSIZE;
        if (header.sequence > UINT64_MAX - (uint64_t)payload_length)
            return -ERANGE;
        if (header.sequence < session->receive_next) {
            if (header.sequence + payload_length > session->receive_next)
                return -ERANGE;
            session->acknowledgement_dirty = 1;
        } else if (header.sequence == session->receive_next) {
            if (deliver(payload, payload_length, context))
                return -EIO;
            if (session->receive_next > UINT64_MAX -
                (uint64_t)payload_length)
                return -EOVERFLOW;
            session->receive_next += payload_length;
            result = deliver_reorder(session, deliver, context);
            if (result)
                return result;
            session->acknowledgement_dirty = 1;
            if (persist(session))
                return -EIO;
        } else {
            for (i = 0; i < SP_SESSION_MAX_REORDER; ++i) {
                if (session->reorder[i].used &&
                    ranges_overlap(header.sequence, payload_length,
                                   session->reorder[i].sequence,
                                   session->reorder[i].length))
                    return -ERANGE;
            }
            for (i = 0; i < SP_SESSION_MAX_REORDER; ++i) {
                if (!session->reorder[i].used) {
                    if (payload_length > SP_SESSION_DATA_MAX)
                        return -EMSGSIZE;
                    session->reorder[i].used = 1;
                    session->reorder[i].sequence = header.sequence;
                    session->reorder[i].length = (uint16_t)payload_length;
                    memcpy(session->reorder[i].payload, payload, payload_length);
                    return 0;
                }
            }
            return -EAGAIN;
        }
    }
    if (header.flags & SP_TUNNEL_HELLO) {
        struct sp_bridge_identity identity;
        size_t peer_name_length;
        if (sp_parse_hello_payload(payload, payload_length, &identity))
            return -EPROTO;
        memset(&session->journal->state.peer, 0,
               sizeof(session->journal->state.peer));
        peer_name_length = strnlen(identity.name, sizeof(identity.name));
        if (peer_name_length >= sizeof(session->journal->state.peer.name))
            peer_name_length = sizeof(session->journal->state.peer.name) - 1;
        memcpy(session->journal->state.peer.name, identity.name,
               peer_name_length);
        if (sp_journal_store(session->journal))
            return -EIO;
        session->authenticated = 1;
    } else if (header.flags & SP_TUNNEL_RESUME) {
        uint8_t remote_session[16];
        uint64_t remote_tx;
        uint64_t remote_rx;
        if (sp_parse_resume_payload(payload, payload_length, remote_session,
                                    &remote_tx, &remote_rx) ||
            memcmp(remote_session, session->session, sizeof(remote_session)) ||
            remote_rx > session->tx_next)
            return -ERANGE;
        /* The resume payload carries the peer's receive watermark for this
         * direction.  Apply it through the durable queue just like a frame
         * header ACK, while allowing an authenticated stale watermark. */
        if (remote_rx > session->peer_acknowledgement) {
            if (sp_journal_acknowledge(session->journal, remote_rx))
                return -EIO;
            session->peer_acknowledgement = remote_rx;
            session->queued_bytes = 0;
            if (sp_journal_replay(session->journal, count_pending,
                                  &session->queued_bytes))
                return -EBADMSG;
        }
        session->authenticated = 1;
    }
    return persist(session);
}

void sp_session_mark_radio_lost(struct sp_session *session) {
    if (session)
        session->connected = 0, session->authenticated = 0;
}

int sp_session_has_pending(const struct sp_session *session) {
    return session && session->queued_bytes != 0;
}

size_t sp_session_queue_available(const struct sp_session *session) {
    if (!session || session->queued_bytes >= SP_SESSION_MAX_QUEUE)
        return 0;
    return SP_SESSION_MAX_QUEUE - session->queued_bytes;
}

int sp_session_is_authenticated(const struct sp_session *session) {
    return session && session->connected && session->authenticated;
}
