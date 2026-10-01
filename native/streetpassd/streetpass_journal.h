#ifndef ANDROID3DS_STREETPASS_JOURNAL_H
#define ANDROID3DS_STREETPASS_JOURNAL_H

#include "streetpass_protocol.h"

#include <stddef.h>
#include <stdint.h>

#define SP_JOURNAL_MAX_PENDING 128u
#define SP_JOURNAL_MAX_RECORD 16384u

enum sp_runtime_state {
    SP_STATE_DISABLED = 0,
    SP_STATE_STARTING,
    SP_STATE_SEARCHING,
    SP_STATE_AUTHENTICATING,
    SP_STATE_EXCHANGING,
    SP_STATE_DEGRADED,
    SP_STATE_DISCONNECTED,
    SP_STATE_ERROR
};

struct sp_journal_state {
    uint32_t enabled;
    uint32_t adb_enabled;
    uint32_t runtime_state;
    uint8_t session[16];
    uint64_t next_sequence;
    uint64_t sent_sequence;
    uint64_t acknowledged_sequence;
    uint64_t receive_sequence;
    struct sp_peer_identity peer;
    char last_error[96];
};

struct sp_journal {
    char directory[256];
    char state_path[320];
    char queue_path[320];
    struct sp_journal_state state;
};

typedef int (*sp_journal_record_fn)(uint64_t sequence,
                                    const uint8_t *payload, size_t length,
                                    void *context);

int sp_journal_open(struct sp_journal *journal, const char *directory);
int sp_journal_load(struct sp_journal *journal);
int sp_journal_store(struct sp_journal *journal);
int sp_journal_enqueue(struct sp_journal *journal, uint64_t sequence,
                       const void *payload, size_t length);
int sp_journal_acknowledge(struct sp_journal *journal, uint64_t sequence);
int sp_journal_replay(struct sp_journal *journal, sp_journal_record_fn callback,
                      void *context);

const char *sp_state_name(enum sp_runtime_state state);

#endif
