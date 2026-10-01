#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
D="${ANDROID3DS_ROOT}"/third_party/linux/drivers/staging/ath6k_legacy
echo "=== files ==="
find $D -name '*.c' -o -name '*.h' | head -60
echo "=== board data refs ==="
grep -rn "board_data" $D | head -40
echo "=== host interest ==="
grep -rn "HOST_INTEREST_ITEM_ADDRESS" $D | head -40
echo "=== configure_target ==="
grep -rn "ar6000_configure_target\|configure_target" $D | head -20
echo "=== bmi_get_config ==="
grep -rn "bmi_get_config" $D | head -20
