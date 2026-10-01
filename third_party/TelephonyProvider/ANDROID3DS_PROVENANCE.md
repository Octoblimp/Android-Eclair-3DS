# TelephonyProvider source provenance

Official Android Open Source Project `platform/packages/providers/TelephonyProvider`.
Fetched 2026-09-06 from https://android.googlesource.com/platform/packages/providers/TelephonyProvider
at tag `android-2.0_r1`, peeled commit
`ed0b8ba72d3c238b3866f7b9ff29693cd3ef915d`.

This matches the canonical framework's `android-2.0_r1` tag. Original Java,
resources, manifest and license headers are retained unchanged. The workspace
build script compiles the provider with the existing framework and platform
signature, supplying the missing `sms`, `mms`, and `mms-sms` storage authorities.
This adds local message storage; the fictional carrier still uses 3DSTelco HTTPS.
