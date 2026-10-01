#include "streetpass_journal.h"
#include "streetpass_config.h"
#include "streetpass_radio.h"
#include "streetpass_adb_proxy.h"
#include "streetpass_session.h"

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int replay_count;
static char delivered[64];
static size_t delivered_length;

static int count_record(uint64_t sequence, const uint8_t *payload,
                        size_t length, void *context) {
    (void)context;
    assert(sequence == 0 || sequence == 3);
    assert(length == 3);
    assert(!memcmp(payload, "adb", 3));
    ++replay_count;
    return 0;
}

static int collect_data(const uint8_t *payload, size_t length, void *context) {
    (void)context;
    assert(delivered_length + length <= sizeof(delivered));
    memcpy(delivered + delivered_length, payload, length);
    delivered_length += length;
    return 0;
}

static void test_frame(void) {
    struct sp_tunnel_header header;
    struct sp_tunnel_header decoded;
    uint8_t encoded[SP_TUNNEL_MAX_FRAME];
    uint8_t payload[32];
    size_t encoded_length;
    size_t payload_length;
    static const uint8_t key[] = "key";
    static const uint8_t session[16] = {
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15
    };
    memset(&header, 0, sizeof(header));
    header.version = SP_TUNNEL_VERSION;
    header.flags = SP_TUNNEL_DATA;
    header.channel = 1;
    memcpy(header.session, session, sizeof(session));
    header.sequence = 7;
    header.acknowledgement = 6;
    assert(!sp_frame_encode(&header, "adb", 3, key, sizeof(key) - 1,
                            encoded, sizeof(encoded), &encoded_length));
    assert(encoded_length == SP_TUNNEL_HEADER_SIZE + 3 + SP_TUNNEL_TAG_SIZE);
    assert(!memcmp(encoded, "SPB1", 4));
    assert(encoded[24] == 0 && encoded[31] == 7);
    assert(encoded[40] == 0 && encoded[43] == 3);
    {
        static const uint8_t expected_tag[SP_TUNNEL_TAG_SIZE] = {
            0xe0, 0xf1, 0xc5, 0x74, 0x4e, 0xa6, 0x69, 0x59,
            0xae, 0x86, 0xf9, 0xc8, 0xb5, 0xf3, 0x34, 0xd0,
            0xd4, 0xfe, 0x1f, 0xc2, 0xa3, 0x56, 0xe1, 0x45,
            0x50, 0x0e, 0xfb, 0x14, 0x87, 0xb7, 0xae, 0x44
        };
        assert(!memcmp(encoded + SP_TUNNEL_HEADER_SIZE + 3, expected_tag,
                       sizeof(expected_tag)));
    }
    assert(!sp_frame_decode(encoded, encoded_length, &decoded, payload,
                            sizeof(payload), &payload_length, key, sizeof(key) - 1));
    assert(!memcmp(decoded.session, header.session, sizeof(session)) &&
           decoded.sequence == 7);
    assert(payload_length == 3 && !memcmp(payload, "adb", 3));
    encoded[encoded_length - 1] ^= 1;
    assert(sp_frame_decode(encoded, encoded_length, &decoded, payload,
                           sizeof(payload), &payload_length, key,
                           sizeof(key) - 1) == -EBADMSG);
}

static void test_tag_and_layers(void) {
    uint8_t tag[] = {
        0x00, 0x1f, 0x32,
        SP_NINTENDO_SERVICE_TAG, 0x05, 'a', 'b', 'c', 'd', 'e',
        SP_NINTENDO_CONSOLE_ID_TAG, 0x08, 1, 2, 3, 4, 5, 6, 7, 8,
        0x7f, 0x01, 0xaa
    };
    struct sp_peer_identity peer;
    uint8_t sptcp[27] = {0x59, 0x59, 27, 0,
                         0xbe, 0xaf, 0xde, 0xad,
                         1, 0, 0, 0, 2, 0, 0, 0,
                         0x0c, 0x10, 0xb8, 0x38,
                         0, 0, 0, 0, 'a', 'd', 'b'};
    uint8_t spmtp[9] = {0x63, 0x63, 0x31, 0, 3, 0, 'x', 'y', 'z'};
    uint16_t flags;
    uint32_t sequence;
    uint32_t acknowledgement;
    size_t offset;
    size_t length;
    uint8_t type;
    assert(!sp_parse_nintendo_tag(tag, sizeof(tag), &peer));
    assert(peer.console_id[0] == 1 && peer.name[0] == '\0');
    assert(!sp_validate_sptcp(sptcp, sizeof(sptcp), &flags, &sequence,
                              &acknowledgement, &offset, &length));
    assert(flags == 0x10 && sequence == 1 && acknowledgement == 2 &&
           offset == 24 && length == 3);
    assert(!sp_validate_spmtp(spmtp, sizeof(spmtp), &type, &offset, &length));
    assert(type == 0x31 && offset == 6 && length == 3);
    tag[4] = 0x40;
    assert(sp_parse_nintendo_tag(tag, sizeof(tag), &peer) == -EMSGSIZE);
}

static void test_bridge_identity(void) {
    uint8_t payload[160];
    uint8_t session[16];
    uint8_t decoded_session[16];
    struct sp_bridge_identity identity;
    size_t length;
    uint64_t tx;
    uint64_t rx;
    unsigned int i;
    for (i = 0; i < sizeof(session); ++i)
        session[i] = (uint8_t)i;
    assert(!sp_build_hello_payload("Computer", "fingerprint", payload,
                                   sizeof(payload), &length));
    assert(!sp_parse_hello_payload(payload, length, &identity));
    assert(!strcmp(identity.name, "Computer"));
    assert(!strcmp(identity.fingerprint, "fingerprint"));
    payload[7] = 1;
    assert(sp_parse_hello_payload(payload, length, &identity) == -EPROTO);
    assert(!sp_build_resume_payload(session, 123, 456, payload,
                                     sizeof(payload), &length));
    assert(length == 36);
    assert(!sp_parse_resume_payload(payload, length, decoded_session, &tx, &rx));
    assert(!memcmp(session, decoded_session, sizeof(session)) && tx == 123 && rx == 456);
}

static void test_journal(void) {
    char directory[] = "/tmp/streetpass-journal-XXXXXX";
    struct sp_journal journal;
    struct sp_journal restored;
    char *path;
    assert(mkdtemp(directory) != NULL);
    assert(!sp_journal_open(&journal, directory));
    journal.state.enabled = 1;
    journal.state.next_sequence = 6;
    assert(!sp_journal_store(&journal));
    assert(!sp_journal_enqueue(&journal, 0, "adb", 3));
    assert(!sp_journal_enqueue(&journal, 3, "adb", 3));
    assert(!sp_journal_open(&restored, directory));
    assert(!sp_journal_load(&restored));
    assert(restored.state.enabled == 1 && restored.state.next_sequence == 6);
    replay_count = 0;
    assert(!sp_journal_replay(&restored, count_record, NULL));
    assert(replay_count == 2);
    assert(!sp_journal_acknowledge(&restored, 3));
    replay_count = 0;
    assert(!sp_journal_replay(&restored, count_record, NULL));
    assert(replay_count == 1);
    path = restored.queue_path;
    assert(access(path, F_OK) == 0);
    unlink(restored.state_path);
    unlink(restored.queue_path);
    rmdir(directory);
}

static void test_radio(void) {
    struct sp_radio radio;
    uint8_t frame[8];
    size_t length;
    /* Raw mode reaches the deployed probe ABI only after key/config checks. */
    assert(sp_radio_open(&radio, SP_RADIO_RAW80211, NULL, NULL, NULL, 0) ==
           -EACCES);
    assert(strstr(radio.error, "paired key") != NULL);
    assert(!sp_radio_open(&radio, SP_RADIO_MOCK, NULL, NULL, NULL, 0));
    assert(!sp_radio_poll(&radio, frame, sizeof(frame), &length));
    assert(length == 0);
    assert(!sp_radio_send(&radio, frame, sizeof(frame)));
    assert(radio.sent_frames == 1);
    sp_radio_close(&radio);
}

static void test_managed_config(void) {
    char path[] = "/tmp/streetpass-managed-config-XXXXXX";
    struct sp_managed_config config;
    int fd;
    FILE *file;
    fd = mkstemp(path);
    assert(fd >= 0);
    file = fdopen(fd, "w");
    assert(file != NULL);
    fputs("schema=1\nmac=02:11:22:33:44:55\nendpoint=127.0.0.1\n"
          "port=15556\nprotocol=managed-tcp-v1\n", file);
    assert(!fclose(file));
    assert(!sp_load_managed_config(path, &config));
    assert(config.mac[0] == 0x02 && config.port == 15556);
    file = fopen(path, "w");
    assert(file != NULL);
    fputs("schema=1\nmac=01:11:22:33:44:55\nendpoint=127.0.0.1\n"
          "port=15556\nprotocol=managed-tcp-v1\n", file);
    assert(!fclose(file));
    assert(sp_load_managed_config(path, &config) != 0);
    unlink(path);
}

static void test_raw_config(void) {
    char path[] = "/tmp/streetpass-raw-config-XXXXXX";
    struct sp_raw_config config;
    int fd;
    FILE *file;
    fd = mkstemp(path);
    assert(fd >= 0);
    file = fdopen(fd, "w");
    assert(file != NULL);
    fputs("schema=1\ninterface=wlan0\npeer_mac=e0:c2:64:00:53:86\n"
          "channel=1\n", file);
    assert(!fclose(file));
    assert(!sp_load_raw_config(path, &config));
    assert(!strcmp(config.interface, "wlan0"));
    assert(config.peer_mac[0] == 0xe0 && config.channel == 1);
    file = fopen(path, "w");
    assert(file != NULL);
    fputs("schema=1\ninterface=wlan0\npeer_mac=d8:43:ae:00:53:9b\n"
          "channel=0\n", file);
    assert(!fclose(file));
    assert(sp_load_raw_config(path, &config) != 0);
    unlink(path);
}

static void test_adb_gate(void) {
    struct sp_adb_proxy proxy;
    sp_adb_proxy_init(&proxy);
    assert(sp_adb_proxy_connect(&proxy, 0, 5555) == -EPERM);
    assert(proxy.fd < 0 && proxy.enabled == 0);
    sp_adb_proxy_close(&proxy);
}

static void test_session(void) {
    char sender_path[] = "/tmp/streetpass-session-s-XXXXXX";
    char receiver_path[] = "/tmp/streetpass-session-r-XXXXXX";
    struct sp_journal sender_journal;
    struct sp_journal receiver_journal;
    struct sp_session sender;
    struct sp_session receiver;
    uint8_t session_id[16];
    uint8_t frame[SP_TUNNEL_MAX_FRAME];
    uint8_t frame2[SP_TUNNEL_MAX_FRAME];
    uint8_t payload[64];
    struct sp_tunnel_header decoded;
    struct sp_tunnel_header ack_header;
    struct sp_tunnel_header resume_header;
    size_t frame_length;
    size_t frame2_length;
    size_t payload_length;
    unsigned int i;
    assert(mkdtemp(sender_path) && mkdtemp(receiver_path));
    for (i = 0; i < sizeof(session_id); ++i)
        session_id[i] = (uint8_t)(0xa0 + i);
    assert(!sp_journal_open(&sender_journal, sender_path));
    assert(!sp_journal_load(&sender_journal));
    assert(!sp_journal_open(&receiver_journal, receiver_path));
    assert(!sp_journal_load(&receiver_journal));
    assert(!sp_session_init(&sender, &sender_journal, session_id, "shared-key", 10));
    assert(!sp_session_init(&receiver, &receiver_journal, session_id, "shared-key", 10));
    /* DATA is accepted only after an authenticated control handshake. */
    assert(!sp_session_build_hello(&sender, "Computer", "fingerprint", frame,
                                   sizeof(frame), &frame_length));
    assert(!sp_session_receive(&receiver, frame, frame_length,
                               collect_data, NULL));
    assert(receiver.authenticated);
    assert(!sp_session_queue_data(&sender, "adb", 3));
    assert(sp_session_has_pending(&sender));
    assert(!sp_session_next_frame(&sender, frame, sizeof(frame), &frame_length));
    delivered_length = 0;
    assert(!sp_session_receive(&receiver, frame, frame_length, collect_data, NULL));
    assert(delivered_length == 3 && !memcmp(delivered, "adb", 3));
    assert(!sp_session_next_frame(&receiver, frame2, sizeof(frame2), &frame2_length));
    assert(!sp_session_receive(&sender, frame2, frame2_length, collect_data, NULL));
    assert(!sp_session_has_pending(&sender));
    memset(&ack_header, 0, sizeof(ack_header));
    ack_header.version = SP_TUNNEL_VERSION;
    ack_header.flags = SP_TUNNEL_ACK;
    memcpy(ack_header.session, session_id, sizeof(session_id));
    ack_header.acknowledgement = 0;
    assert(!sp_frame_encode(&ack_header, NULL, 0, "shared-key", 10,
                            frame2, sizeof(frame2), &frame2_length));
    assert(!sp_session_receive(&sender, frame2, frame2_length, collect_data, NULL));
    ack_header.acknowledgement = 4;
    assert(!sp_frame_encode(&ack_header, NULL, 0, "shared-key", 10,
                            frame2, sizeof(frame2), &frame2_length));
    assert(sp_session_receive(&sender, frame2, frame2_length, collect_data, NULL)
           == -ERANGE);
    /* A resume can acknowledge a durable record even when the peer has
     * additional outbound bytes not yet delivered to this endpoint. */
    assert(!sp_session_queue_data(&sender, "xyz", 3));
    assert(!sp_session_next_frame(&sender, frame, sizeof(frame), &frame_length));
    memset(&resume_header, 0, sizeof(resume_header));
    resume_header.version = SP_TUNNEL_VERSION;
    resume_header.flags = SP_TUNNEL_RESUME;
    memcpy(resume_header.session, session_id, sizeof(session_id));
    assert(!sp_build_resume_payload(session_id, 3, 6, payload,
                                     sizeof(payload), &payload_length));
    assert(!sp_frame_encode(&resume_header, payload, payload_length,
                            "shared-key", 10, frame2, sizeof(frame2),
                            &frame2_length));
    assert(!sp_session_receive(&sender, frame2, frame2_length,
                               collect_data, NULL));
    assert(sender.authenticated && !sp_session_has_pending(&sender));
    assert(!sp_session_build_hello(&sender, "Computer", "fingerprint", frame,
                                   sizeof(frame), &frame_length));
    assert(!sp_frame_decode(frame, frame_length, &decoded, payload, sizeof(payload),
                            &payload_length, "shared-key", 10));
    (void)frame_length;
    unlink(sender_journal.state_path);
    unlink(sender_journal.queue_path);
    unlink(receiver_journal.state_path);
    unlink(receiver_journal.queue_path);
    rmdir(sender_path);
    rmdir(receiver_path);
}

int main(void) {
    test_frame();
    test_tag_and_layers();
    test_bridge_identity();
    test_journal();
    test_radio();
    test_managed_config();
    test_raw_config();
    test_adb_gate();
    test_session();
    puts("streetpass protocol tests: PASS");
    return 0;
}
