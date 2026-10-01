#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
echo "=== locate nwm blobs ==="
find "${ANDROID3DS_ROOT}" -path '*ath6k/AR6002/nwm*' 2>/dev/null | sort
echo
DB=$(find "${ANDROID3DS_ROOT}" -path '*ath6k/AR6002/nwm/database.bin' 2>/dev/null | head -1)
echo "=== database.bin = $DB ==="
ls -la "$DB"
echo "--- full hexdump (488 bytes) ---"
hexdump -C "$DB"
