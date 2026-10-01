#!/usr/bin/env python3
"""Static security contract for the native modern-HTTPS transport."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "native/telco_https.c").read_text(encoding="utf-8")
build = (ROOT / "scripts/build_telco_https.sh").read_text(encoding="utf-8")
fetch = (ROOT / "scripts/fetch_telco_https_dependencies.sh").read_text(encoding="utf-8")

for marker in (
    'N3DS-TELCO-HTTPS/1', 'MAX_BODY 16384', 'MAX_RESPONSE 131072',
    'CURLOPT_SSL_VERIFYPEER', 'CURLOPT_SSL_VERIFYHOST',
    'CURLOPT_PROTOCOLS_STR', 'CURLOPT_CAINFO', 'CURLOPT_FOLLOWLOCATION, 0L',
    'Authorization: Bearer %s', 'safe_token',
):
    assert marker in source, marker
assert 'argv' not in source.split('int main(', 1)[1].split('{', 1)[0]
assert '/system/etc/security/cacert.pem' in source
assert 'mbedtls-3.6.5' in build and 'curl-8.18.0' in build
assert 'statically linked' in build and 'STAGE_TELCO_HTTPS' in build
assert '4a11f1777bb95bf4ad96721cac945a26e04bf19f57d905f241fe77ebeddf46d8' in fetch
assert '40df79166e74aa20149365e11ee4c798a46ad57c34e4f68fd13100e2c9a91946' in fetch
print('telco_https: PASS')
