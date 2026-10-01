/*
 * Certificate-verifying HTTPS transport for the original Android3DS Phone app.
 * Secrets and request bodies arrive only on stdin; argv and logs stay clean.
 */
#include <curl/curl.h>

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef N3DS_TELCO_CA_BUNDLE
#define N3DS_TELCO_CA_BUNDLE "/system/etc/security/cacert.pem"
#endif

#ifndef N3DS_TELCO_RESOLV_CONF
#define N3DS_TELCO_RESOLV_CONF "/etc/resolv.conf"
#endif

#define MAX_URL 1536
#define MAX_TOKEN 128
#define MAX_BODY 16384
#define MAX_RESPONSE 131072

struct buffer {
    unsigned char *data;
    size_t length;
};

/*
 * Say why a name lookup failed, because curl cannot.
 *
 * This binary is statically linked against musl, and musl's resolver reads
 * exactly one thing: /etc/resolv.conf.  It does not know Android properties
 * exist, so net.dns1 being correct means nothing here.  With no resolv.conf,
 * or one with no nameserver line, musl falls back to 127.0.0.1 -- where
 * nothing on this device listens -- and every lookup fails identically to a
 * genuine DNS outage.  The two need telling apart, and the file is the only
 * evidence that distinguishes them.
 *
 * Kept to two short lines: TelcoHttp collects this stream and shows it to the
 * user as the error message.
 */
static void describe_resolver(void)
{
    char line[256];
    char servers[160];
    size_t used = 0;
    int count = 0;
    FILE *file = fopen(N3DS_TELCO_RESOLV_CONF, "r");

    if (!file) {
        fprintf(stderr, "resolver: %s is missing, so musl had no nameserver "
                "to ask. It is written by /etc/android_resolvconf.sh when "
                "Wi-Fi takes a DHCP lease.\n", N3DS_TELCO_RESOLV_CONF);
        return;
    }
    servers[0] = '\0';
    while (fgets(line, sizeof(line), file)) {
        char *value;
        size_t length;
        if (strncmp(line, "nameserver", 10) != 0 ||
                (line[10] != ' ' && line[10] != '\t'))
            continue;
        ++count;
        for (value = line + 10; *value == ' ' || *value == '\t'; ++value)
            ;
        for (length = 0; value[length] && value[length] != ' ' &&
                value[length] != '\t' && value[length] != '\n' &&
                value[length] != '\r'; ++length)
            ;
        if (!length || used + length + 2 >= sizeof(servers))
            continue;
        if (used)
            servers[used++] = ' ';
        memcpy(servers + used, value, length);
        used += length;
        servers[used] = '\0';
    }
    fclose(file);

    if (!count)
        fprintf(stderr, "resolver: %s exists but lists no nameserver, so musl "
                "fell back to 127.0.0.1 and nothing answers there.\n",
                N3DS_TELCO_RESOLV_CONF);
    else
        fprintf(stderr, "resolver: asked %d nameserver(s) from %s (%s) and got "
                "no answer, so this is the network, not the handheld.\n",
                count, N3DS_TELCO_RESOLV_CONF, servers);
}

static int read_field(const char *name, char *value, size_t capacity)
{
    char line[1800];
    size_t prefix = strlen(name);
    size_t length;
    if (!fgets(line, sizeof(line), stdin) || strncmp(line, name, prefix) != 0 ||
            line[prefix] != ' ')
        return -1;
    length = strlen(line + prefix + 1);
    while (length && (line[prefix + 1 + length - 1] == '\n' ||
            line[prefix + 1 + length - 1] == '\r'))
        line[prefix + 1 + --length] = '\0';
    if (!length || length >= capacity)
        return -1;
    memcpy(value, line + prefix + 1, length + 1);
    return 0;
}

static size_t collect(void *bytes, size_t size, size_t count, void *opaque)
{
    struct buffer *buffer = (struct buffer *)opaque;
    size_t amount = size * count;
    unsigned char *next;
    if (amount > MAX_RESPONSE || buffer->length > MAX_RESPONSE - amount)
        return 0;
    next = (unsigned char *)realloc(buffer->data, buffer->length + amount + 1);
    if (!next)
        return 0;
    buffer->data = next;
    memcpy(buffer->data + buffer->length, bytes, amount);
    buffer->length += amount;
    buffer->data[buffer->length] = '\0';
    return amount;
}

static int safe_token(const char *token)
{
    const unsigned char *p = (const unsigned char *)token;
    size_t length = strlen(token);
    if (strcmp(token, "-") == 0)
        return 1;
    if (length < 40 || length > 120)
        return 0;
    while (*p) {
        if (!(('A' <= *p && *p <= 'Z') || ('a' <= *p && *p <= 'z') ||
                ('0' <= *p && *p <= '9') || *p == '_' || *p == '-'))
            return 0;
        ++p;
    }
    return 1;
}

int main(void)
{
    char magic[64], method[16], url[MAX_URL], token[MAX_TOKEN], bodySize[32];
    char blank[8], error[CURL_ERROR_SIZE] = {0};
    unsigned char *body = NULL;
    size_t bodyLength, got = 0;
    unsigned long parsed;
    struct buffer response = {0};
    struct curl_slist *headers = NULL;
    char *authorization = NULL;
    CURL *curl = NULL;
    CURLcode result;
    long status = 0;
    int exitCode = 1;

    if (!fgets(magic, sizeof(magic), stdin) || strcmp(magic, "N3DS-TELCO-HTTPS/1\n") != 0 ||
            read_field("METHOD", method, sizeof(method)) ||
            read_field("URL", url, sizeof(url)) ||
            read_field("TOKEN", token, sizeof(token)) ||
            read_field("BODY", bodySize, sizeof(bodySize)) ||
            !fgets(blank, sizeof(blank), stdin) || strcmp(blank, "\n") != 0) {
        fputs("invalid request envelope\n", stderr);
        return 2;
    }
    if ((strcmp(method, "GET") != 0 && strcmp(method, "POST") != 0) ||
            strncmp(url, "https://", 8) != 0 || !safe_token(token)) {
        fputs("invalid method, URL, or token\n", stderr);
        return 2;
    }
    errno = 0;
    parsed = strtoul(bodySize, NULL, 10);
    if (errno || parsed > MAX_BODY) {
        fputs("invalid request body length\n", stderr);
        return 2;
    }
    bodyLength = (size_t)parsed;
    if (bodyLength) {
        body = (unsigned char *)malloc(bodyLength);
        if (!body) return 3;
        while (got < bodyLength) {
            size_t count = fread(body + got, 1, bodyLength - got, stdin);
            if (!count) {
                fputs("short request body\n", stderr);
                goto cleanup;
            }
            got += count;
        }
    }

    if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) goto cleanup;
    curl = curl_easy_init();
    if (!curl) goto cleanup;
    headers = curl_slist_append(headers, "Accept: application/json");
    if (bodyLength) headers = curl_slist_append(headers, "Content-Type: application/json; charset=utf-8");
    if (strcmp(token, "-") != 0) {
        authorization = (char *)malloc(strlen(token) + 23);
        if (!authorization) goto cleanup;
        sprintf(authorization, "Authorization: Bearer %s", token);
        headers = curl_slist_append(headers, authorization);
    }
    if (!headers) goto cleanup;

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, method);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "Android3DS-3DSTelco/1");
    curl_easy_setopt(curl, CURLOPT_CAINFO, N3DS_TELCO_CA_BUNDLE);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 2L);
    curl_easy_setopt(curl, CURLOPT_PROTOCOLS_STR, "https");
    curl_easy_setopt(curl, CURLOPT_REDIR_PROTOCOLS_STR, "https");
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 0L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 15L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 35L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_HTTP_VERSION, CURL_HTTP_VERSION_1_1);
    /* DHCPv4 is the only address this device ever gets; see above. */
    curl_easy_setopt(curl, CURLOPT_IPRESOLVE, CURL_IPRESOLVE_V4);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, collect);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_ERRORBUFFER, error);
    if (bodyLength) {
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE_LARGE, (curl_off_t)bodyLength);
    }
    result = curl_easy_perform(curl);
    if (result != CURLE_OK) {
        fprintf(stderr, "HTTPS transport failed: %s\n", error[0] ? error : curl_easy_strerror(result));
        if (result == CURLE_COULDNT_RESOLVE_HOST ||
                result == CURLE_COULDNT_RESOLVE_PROXY)
            describe_resolver();
        goto cleanup;
    }
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    if (status < 100 || status > 599) {
        fputs("invalid HTTP response status\n", stderr);
        goto cleanup;
    }
    printf("N3DS-TELCO-HTTPS/1\nSTATUS %ld\nLENGTH %lu\n\n", status,
            (unsigned long)response.length);
    if (response.length && fwrite(response.data, 1, response.length, stdout) != response.length)
        goto cleanup;
    if (fflush(stdout) != 0) goto cleanup;
    exitCode = 0;

cleanup:
    if (curl) curl_easy_cleanup(curl);
    curl_slist_free_all(headers);
    curl_global_cleanup();
    free(authorization);
    free(response.data);
    free(body);
    return exitCode;
}
