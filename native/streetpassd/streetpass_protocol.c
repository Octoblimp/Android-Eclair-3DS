#include "streetpass_protocol.h"

#include <errno.h>
#include <string.h>

static uint16_t get_le_u16(const uint8_t *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t get_le_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint32_t get_be_u32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static uint64_t get_be_u64(const uint8_t *p) {
    uint64_t v = 0;
    unsigned int i;
    for (i = 0; i < 8; ++i)
        v = (v << 8) | p[i];
    return v;
}

static void put_be_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

static void put_be_u64(uint8_t *p, uint64_t v) {
    unsigned int i;
    for (i = 0; i < 8; ++i)
        p[7 - i] = (uint8_t)(v >> (i * 8));
}

uint32_t sp_checksum32(const void *data, size_t length) {
    const uint8_t *p = (const uint8_t *)data;
    uint32_t value = 2166136261u;
    size_t i;
    for (i = 0; i < length; ++i)
        value = (value ^ p[i]) * 16777619u;
    return value;
}

struct sp_sha256 {
    uint32_t state[8];
    uint64_t bits;
    uint8_t block[64];
    size_t used;
};

static uint32_t rotr32(uint32_t value, unsigned int count) {
    return (value >> count) | (value << (32u - count));
}

static void sha256_transform(struct sp_sha256 *ctx, const uint8_t *block) {
    static const uint32_t k[64] = {
        0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u,
        0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
        0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u,
        0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
        0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu,
        0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
        0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
        0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
        0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u,
        0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
        0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u,
        0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
        0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u,
        0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
        0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
        0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u
    };
    uint32_t w[64];
    uint32_t a, b, c, d, e, f, g, h;
    unsigned int i;
    for (i = 0; i < 16; ++i)
        w[i] = get_be_u32(block + i * 4);
    for (i = 16; i < 64; ++i) {
        uint32_t s0 = rotr32(w[i - 15], 7) ^ rotr32(w[i - 15], 18) ^
                      (w[i - 15] >> 3);
        uint32_t s1 = rotr32(w[i - 2], 17) ^ rotr32(w[i - 2], 19) ^
                      (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = ctx->state[0]; b = ctx->state[1]; c = ctx->state[2]; d = ctx->state[3];
    e = ctx->state[4]; f = ctx->state[5]; g = ctx->state[6]; h = ctx->state[7];
    for (i = 0; i < 64; ++i) {
        uint32_t s1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        uint32_t choose = (e & f) ^ (~e & g);
        uint32_t temp1 = h + s1 + choose + k[i] + w[i];
        uint32_t s0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        uint32_t temp2 = s0 + majority;
        h = g; g = f; f = e; e = d + temp1;
        d = c; c = b; b = a; a = temp1 + temp2;
    }
    ctx->state[0] += a; ctx->state[1] += b; ctx->state[2] += c; ctx->state[3] += d;
    ctx->state[4] += e; ctx->state[5] += f; ctx->state[6] += g; ctx->state[7] += h;
}

static void sha256_init(struct sp_sha256 *ctx) {
    static const uint32_t initial[8] = {
        0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
        0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u
    };
    memcpy(ctx->state, initial, sizeof(initial));
    ctx->bits = 0;
    ctx->used = 0;
}

static void sha256_update(struct sp_sha256 *ctx, const void *data, size_t length) {
    const uint8_t *p = (const uint8_t *)data;
    while (length) {
        size_t n = 64 - ctx->used;
        if (n > length)
            n = length;
        memcpy(ctx->block + ctx->used, p, n);
        ctx->used += n;
        p += n;
        length -= n;
        if (ctx->used == 64) {
            sha256_transform(ctx, ctx->block);
            ctx->bits += 512;
            ctx->used = 0;
        }
    }
}

static void sha256_final(struct sp_sha256 *ctx, uint8_t output[32]) {
    unsigned int i;
    uint64_t bits = ctx->bits + (uint64_t)ctx->used * 8;
    ctx->block[ctx->used++] = 0x80;
    if (ctx->used > 56) {
        while (ctx->used < 64)
            ctx->block[ctx->used++] = 0;
        sha256_transform(ctx, ctx->block);
        ctx->used = 0;
    }
    while (ctx->used < 56)
        ctx->block[ctx->used++] = 0;
    for (i = 0; i < 8; ++i)
        ctx->block[56 + i] = (uint8_t)(bits >> (56 - i * 8));
    sha256_transform(ctx, ctx->block);
    for (i = 0; i < 8; ++i)
        put_be_u32(output + i * 4, ctx->state[i]);
}

void sp_hmac_sha256(const void *key, size_t key_length,
                    const void *data, size_t data_length,
                    uint8_t output[SP_TUNNEL_TAG_SIZE]) {
    uint8_t key_block[64];
    uint8_t inner[32];
    uint8_t ipad[64];
    uint8_t opad[64];
    struct sp_sha256 ctx;
    size_t i;
    memset(key_block, 0, sizeof(key_block));
    if (key_length > sizeof(key_block)) {
        sha256_init(&ctx);
        sha256_update(&ctx, key, key_length);
        sha256_final(&ctx, key_block);
    } else if (key_length) {
        memcpy(key_block, key, key_length);
    }
    for (i = 0; i < sizeof(key_block); ++i) {
        ipad[i] = key_block[i] ^ 0x36;
        opad[i] = key_block[i] ^ 0x5c;
    }
    sha256_init(&ctx);
    sha256_update(&ctx, ipad, sizeof(ipad));
    sha256_update(&ctx, data, data_length);
    sha256_final(&ctx, inner);
    sha256_init(&ctx);
    sha256_update(&ctx, opad, sizeof(opad));
    sha256_update(&ctx, inner, sizeof(inner));
    sha256_final(&ctx, output);
}

static int validate_frame_fields(uint8_t flags, uint8_t channel,
                                 uint32_t payload_length) {
    uint8_t control_flags;
    if (!flags || (flags & 0x80u))
        return -EPROTO;
    if (flags & SP_TUNNEL_DATA) {
        if ((flags & (uint8_t)~(SP_TUNNEL_DATA | SP_TUNNEL_ACK)) ||
            channel != 1 || payload_length == 0)
            return -EPROTO;
        return 0;
    }
    if (channel != 0)
        return -EPROTO;
    control_flags = flags & (uint8_t)~SP_TUNNEL_ACK;
    if (control_flags && (control_flags & (uint8_t)(control_flags - 1)))
        return -EPROTO;
    if ((flags & (SP_TUNNEL_ACK | SP_TUNNEL_CLOSE)) && payload_length)
        return -EPROTO;
    if ((flags & (SP_TUNNEL_PING | SP_TUNNEL_PONG)) && payload_length != 8)
        return -EPROTO;
    if ((flags & (SP_TUNNEL_HELLO | SP_TUNNEL_RESUME)) && !payload_length)
        return -EPROTO;
    return 0;
}

int sp_frame_encode(const struct sp_tunnel_header *header,
                    const void *payload, size_t payload_length,
                    const void *key, size_t key_length,
                    void *output, size_t output_capacity, size_t *output_length) {
    const uint8_t *in = (const uint8_t *)payload;
    uint8_t *out = (uint8_t *)output;
    uint8_t tag[SP_TUNNEL_TAG_SIZE];
    uint8_t *body;

    if (!header || (!payload && payload_length) || !key || !key_length ||
        !output || !output_length)
        return -EINVAL;
    if (payload_length > SP_TUNNEL_MAX_PAYLOAD ||
        output_capacity < SP_TUNNEL_HEADER_SIZE + payload_length + SP_TUNNEL_TAG_SIZE)
        return -EMSGSIZE;
    if (header->version != SP_TUNNEL_VERSION || header->reserved != 0)
        return -EPROTO;
    if (!(header->flags & SP_TUNNEL_DATA) && header->sequence != 0)
        return -EPROTO;
    if (validate_frame_fields(header->flags, header->channel,
                              (uint32_t)payload_length))
        return -EPROTO;
    body = out;
    memcpy(out, SP_TUNNEL_MAGIC, 4);
    out[4] = header->version;
    out[5] = header->flags;
    out[6] = header->channel;
    out[7] = 0;
    memcpy(out + 8, header->session, 16);
    put_be_u64(out + 24, header->sequence);
    put_be_u64(out + 32, header->acknowledgement);
    put_be_u32(out + 40, (uint32_t)payload_length);
    if (payload_length)
        memcpy(out + SP_TUNNEL_HEADER_SIZE, in, payload_length);
    sp_hmac_sha256(key, key_length, body, SP_TUNNEL_HEADER_SIZE + payload_length, tag);
    memcpy(out + SP_TUNNEL_HEADER_SIZE + payload_length, tag, sizeof(tag));
    *output_length = SP_TUNNEL_HEADER_SIZE + payload_length + SP_TUNNEL_TAG_SIZE;
    return 0;
}

int sp_frame_decode(const void *input, size_t input_length,
                    struct sp_tunnel_header *header,
                    void *payload, size_t payload_capacity, size_t *payload_length,
                    const void *key, size_t key_length) {
    const uint8_t *in = (const uint8_t *)input;
    uint32_t length;
    uint8_t expected[SP_TUNNEL_TAG_SIZE];
    uint8_t mismatch = 0;
    size_t i;
    struct sp_tunnel_header h;

    if (!input || !header || !payload_length || !key || !key_length)
        return -EINVAL;
    if (input_length < SP_TUNNEL_HEADER_SIZE + SP_TUNNEL_TAG_SIZE)
        return -EMSGSIZE;
    if (memcmp(in, SP_TUNNEL_MAGIC, 4) || in[4] != SP_TUNNEL_VERSION)
        return -EPROTO;
    if (in[7] != 0)
        return -EPROTO;
    length = get_be_u32(in + 40);
    if (length > SP_TUNNEL_MAX_PAYLOAD ||
        input_length != SP_TUNNEL_HEADER_SIZE + (size_t)length + SP_TUNNEL_TAG_SIZE)
        return -EMSGSIZE;
    if (validate_frame_fields(in[5], in[6], length))
        return -EPROTO;
    if (!(in[5] & SP_TUNNEL_DATA) && get_be_u64(in + 24) != 0)
        return -EPROTO;
    if (length && (!payload || payload_capacity < length))
        return -ENOSPC;
    sp_hmac_sha256(key, key_length, in, SP_TUNNEL_HEADER_SIZE + length, expected);
    for (i = 0; i < sizeof(expected); ++i)
        mismatch |= expected[i] ^ in[SP_TUNNEL_HEADER_SIZE + length + i];
    if (mismatch)
        return -EBADMSG;

    memset(&h, 0, sizeof(h));
    h.version = in[4];
    h.flags = in[5];
    h.channel = in[6];
    h.reserved = in[7];
    memcpy(h.session, in + 8, sizeof(h.session));
    h.sequence = get_be_u64(in + 24);
    h.acknowledgement = get_be_u64(in + 32);
    h.payload_length = length;
    if (length)
        memcpy(payload, in + SP_TUNNEL_HEADER_SIZE, length);
    *header = h;
    *payload_length = length;
    return 0;
}

int sp_parse_nintendo_tag(const void *data, size_t length,
                          struct sp_peer_identity *peer) {
    const uint8_t *p = (const uint8_t *)data;
    size_t off;
    int have_console_id = 0;
    int have_services = 0;

    if (!data || !peer || length < 5 || length > 1024 ||
        memcmp(p, SP_NINTENDO_VENDOR_OUI, 3))
        return -EINVAL;
    memset(peer, 0, sizeof(*peer));
    off = 3;
    while (off < length) {
        uint8_t id;
        uint8_t n;
        if (length - off < 2)
            return -EPROTO;
        id = p[off++];
        n = p[off++];
        if ((size_t)n > length - off)
            return -EMSGSIZE;
        switch (id) {
        case SP_NINTENDO_SERVICE_TAG:
            if (have_services || !n || n % SP_NINTENDO_SERVICE_RECORD_SIZE ||
                n / SP_NINTENDO_SERVICE_RECORD_SIZE > SP_NINTENDO_MAX_SERVICES)
                return -EPROTO;
            have_services = 1;
            break;
        case SP_NINTENDO_CONSOLE_ID_TAG:
            if (have_console_id || n != sizeof(peer->console_id))
                return -EPROTO;
            memcpy(peer->console_id, p + off, sizeof(peer->console_id));
            have_console_id = 1;
            break;
        case 0x04:
            /* Legacy/vendor metadata is bounded but not part of the
             * authenticated identity contract; skip it as unknown. */
            break;
        default:
            /* Forward-compatible but bounded: unknown fields are ignored. */
            break;
        }
        off += n;
    }
    return have_console_id && have_services ? 0 : -EPROTO;
}

static int valid_utf8_text(const uint8_t *text, size_t length) {
    size_t i = 0;
    while (i < length) {
        uint8_t c = text[i];
        size_t n;
        if (c < 0x20u || c == 0x7fu)
            return 0;
        if (c < 0x80u) {
            i++;
            continue;
        }
        if (c >= 0xc2u && c <= 0xdfu)
            n = 2;
        else if (c >= 0xe0u && c <= 0xefu)
            n = 3;
        else if (c >= 0xf0u && c <= 0xf4u)
            n = 4;
        else
            return 0;
        if (i + n > length)
            return 0;
        while (--n) {
            if ((text[i + n] & 0xc0u) != 0x80u)
                return 0;
        }
        /* Reject overlong encodings and UTF-16 surrogate code points. */
        if ((c == 0xe0u && text[i + 1] < 0xa0u) ||
            (c == 0xedu && text[i + 1] >= 0xa0u) ||
            (c == 0xf0u && text[i + 1] < 0x90u) ||
            (c == 0xf4u && text[i + 1] >= 0x90u))
            return 0;
        i += (c < 0xe0u ? 2 : c < 0xf0u ? 3 : 4);
    }
    return 1;
}

int sp_build_hello_payload(const char *name, const char *fingerprint,
                           void *output, size_t capacity, size_t *length) {
    size_t name_length;
    size_t fingerprint_length;
    uint8_t *out = (uint8_t *)output;
    if (!name || !fingerprint || !output || !length)
        return -EINVAL;
    name_length = strlen(name);
    fingerprint_length = strlen(fingerprint);
    if (!name_length || name_length > 64 || !fingerprint_length ||
        fingerprint_length > 96 || !valid_utf8_text((const uint8_t *)name,
                                                     name_length) ||
        !valid_utf8_text((const uint8_t *)fingerprint, fingerprint_length))
        return -EPROTO;
    if (capacity < 8 + name_length + fingerprint_length)
        return -ENOSPC;
    memcpy(out, "SPH1", 4);
    out[4] = 1;
    out[5] = (uint8_t)name_length;
    out[6] = (uint8_t)fingerprint_length;
    out[7] = 0;
    memcpy(out + 8, name, name_length);
    memcpy(out + 8 + name_length, fingerprint, fingerprint_length);
    *length = 8 + name_length + fingerprint_length;
    return 0;
}

int sp_parse_hello_payload(const void *data, size_t length,
                           struct sp_bridge_identity *identity) {
    const uint8_t *p = (const uint8_t *)data;
    size_t name_length;
    size_t fingerprint_length;
    if (!data || !identity || length < 8 || memcmp(p, "SPH1", 4) ||
        p[4] != 1 || p[7] != 0)
        return -EPROTO;
    name_length = p[5];
    fingerprint_length = p[6];
    if (!name_length || name_length > 64 || !fingerprint_length ||
        fingerprint_length > 96 || length != 8 + name_length + fingerprint_length)
        return -EPROTO;
    if (!valid_utf8_text(p + 8, name_length) ||
        !valid_utf8_text(p + 8 + name_length, fingerprint_length))
        return -EPROTO;
    memset(identity, 0, sizeof(*identity));
    memcpy(identity->name, p + 8, name_length);
    memcpy(identity->fingerprint, p + 8 + name_length, fingerprint_length);
    return 0;
}

int sp_build_resume_payload(const uint8_t session[16], uint64_t tx_next,
                            uint64_t rx_next, void *output, size_t capacity,
                            size_t *length) {
    uint8_t *out = (uint8_t *)output;
    if (!session || !output || !length)
        return -EINVAL;
    if (capacity < 36)
        return -ENOSPC;
    memcpy(out, "SPR1", 4);
    memcpy(out + 4, session, 16);
    put_be_u64(out + 20, tx_next);
    put_be_u64(out + 28, rx_next);
    *length = 36;
    return 0;
}

int sp_parse_resume_payload(const void *data, size_t length,
                            uint8_t session[16], uint64_t *tx_next,
                            uint64_t *rx_next) {
    const uint8_t *p = (const uint8_t *)data;
    if (!data || length != 36 || memcmp(p, "SPR1", 4) || !session)
        return -EPROTO;
    memcpy(session, p + 4, 16);
    if (tx_next)
        *tx_next = get_be_u64(p + 20);
    if (rx_next)
        *rx_next = get_be_u64(p + 28);
    return 0;
}

int sp_validate_sptcp(const void *data, size_t length,
                      uint16_t *flags, uint32_t *sequence,
                      uint32_t *acknowledgement, size_t *payload_offset,
                      size_t *payload_length) {
    const uint8_t *p = (const uint8_t *)data;
    size_t n;
    uint16_t max_buffer;
    if (!data || length < 24 || length > SP_TUNNEL_MAX_FRAME)
        return -EMSGSIZE;
    if (get_le_u16(p) != 0x5959u)
        return -EPROTO;
    if (get_le_u32(p + 4) != 0xaddeafbeu || p[16] != 0x0cu ||
        p[17] & (uint8_t)~0x3fu || get_le_u32(p + 20) != 0)
        return -EPROTO;
    max_buffer = get_le_u16(p + 18);
    n = get_le_u16(p + 2);
    if (!max_buffer || max_buffer > 0x38b8u || n < 24u || n != length ||
        n > 24u + 0x38b8u)
        return -EMSGSIZE;
    if (flags)
        *flags = p[17];
    if (sequence)
        *sequence = get_le_u32(p + 8);
    if (acknowledgement)
        *acknowledgement = get_le_u32(p + 12);
    if (payload_offset)
        *payload_offset = 24;
    if (payload_length)
        *payload_length = n - 24;
    return 0;
}

int sp_validate_spmtp(const void *data, size_t length,
                      uint8_t *packet_type, size_t *payload_offset,
                      size_t *payload_length) {
    const uint8_t *p = (const uint8_t *)data;
    size_t n;
    if (!data || length < 6 || length > SP_TUNNEL_MAX_FRAME)
        return -EMSGSIZE;
    if (get_le_u16(p) != 0x6363u)
        return -EPROTO;
    switch (p[2]) {
    case 0x11u: case 0x12u:
    case 0x21u: case 0x22u: case 0x23u: case 0x24u:
    case 0x31u: case 0x32u: case 0x33u: case 0x34u:
    case 0x41u: case 0x42u: case 0x43u:
    case 0x81u:
        break;
    default:
        return -EPROTO;
    }
    n = get_le_u16(p + 4);
    if (n > SP_TUNNEL_MAX_PAYLOAD || 6u + n != length)
        return -EMSGSIZE;
    if (packet_type)
        *packet_type = p[2];
    if (payload_offset)
        *payload_offset = 6;
    if (payload_length)
        *payload_length = n;
    return 0;
}
