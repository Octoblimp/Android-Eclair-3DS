# 3DSTelco VoIP: what the handheld speaks

The device side lives in
`content/stock-app-overlays/Phone/src/com/android/phone/VoipSession.java`
(media) and `TelcoService.java` (signalling). The server is the separate
3DSTelco PHP project (`public/src/VoipRelay.php`, `public/bin/voip_relay.php`,
`docs/protocol.md` there). This file describes the handheld's half, taken from
the client source.

## Why calls had no audio (2026-09-30)

`3dstelco.divergen.io` is proxied by Cloudflare, and Cloudflare's proxy carries
only HTTP(S). The handheld sent its UDP media to the API hostname, so every
packet was dropped before it reached the relay. There are two fixes, both
server-side:

- turn the proxy off for the API hostname, or
- add a DNS-only media hostname and set `voip_public_host` in the server's
  `config.php`.

The handheld follows either. With a `voip.host` it sends media there
(N3DS_TELCO_VOIP_HOST); with none it uses the API host. In both cases UDP 3478
must be open, and the relay must be running (`voip_relay.php --cron` from cron).

## 1. Signalling (HTTPS, bearer token)

| Method | Path | Request | What the client reads |
| --- | --- | --- | --- |
| POST | `/v1/enroll` | MAC-keyed enrolment | token |
| GET | `/v1/status` | none | `number`, `voip {host, port, relay}` |
| GET | `/v1/events?after=<cursor>` | none | `events[]` of `{id, type, payload}` |
| POST | `/v1/calls` | `{to, client_id}` | `call.id`, `call.callee_available` |
| POST | `/v1/calls/<id>/answer` | `{}` | `media_token`, `voip` |
| POST | `/v1/calls/<id>/reject`, `/end` | `{}` | nothing |
| POST | `/v1/calls/<id>/voicemail` | `{}` | `media_token`, `max_seconds`, `voip` |
| GET | `/v1/voicemails`, `/v1/voicemails/<id>/audio` | none | list, raw PCM |
| POST | `/v1/messages` | `{to, body, client_id}` | `message.id` |
| POST | `/v1/messages/<id>/delivered` | `{}` | nothing |

The device validates `to` before sending (N3DS_TELCO_WEB_NUMBERS):

- calls go to `[1-9][0-9]{2,3}` (a 3DS) or `[2-9][0-9]{9}` (a web account);
- texts may also go to a 6-digit service number.

A web account's number rings its signed-in portal page. The handheld cannot
tell the difference, because the relay does the bridging.

The events are `message`, `incoming_call`, `call_answered` (carries the
caller's `media_token` and `voip`), `call_rejected`, `call_ended` and
`voicemail`.

`status.voip.relay` is `down` when the server sees no relay heartbeat. The
handheld then reports "Online over Wi-Fi, call audio relay is offline" as its
service status.

## 2. Media (UDP)

The host is `voip.host`, falling back to the API host. The port is
`voip.port` (3478 by default). The media token is URL-safe base64 that decodes
to exactly 32 bytes.

```
T3V1 | 32-byte token | uint32 BE sequence | 320 B PCM     device -> relay, every 20 ms
T3A1 | uint32 BE sequence | PCM                           relay -> device
T3E1 | uint32 0                                           relay -> device: call over
T3P1 | nonce (0..32 B)                                    probe, echoed by the relay
```

All PCM is 8 kHz mono signed 16-bit little-endian.

The uplink sequence never breaks: muting zeroes the PCM, and a call with no
microphone sends clock-paced silence. The downlink is written straight to an
`AudioTrack`.

On `T3E1`, which the relay sends when the other side hangs up
(N3DS_TELCO_T3E1), the session polls at once. The `call_ended` event then tears
the call down within about two seconds, instead of at the next poll alarm.

Voicemail uses the same `T3V1` stream with the token from `/voicemail`. The
relay appends it to the recording, and the client stops after `max_seconds`.

## 3. Microphone

The microphone captures real audio since kernel #317 (`/dev/eac`, I2S2 clock
fix). `VoipSession` still treats the recorder as optional: a recorder that
will not open gives a one-way call with a "no microphone" note, not a refused
call.
