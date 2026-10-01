#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
D="${ANDROID3DS_ROOT}"/third_party/linux/drivers/staging/ath6k_legacy
echo "=== dset descriptor / DSET types ==="
grep -rn "dset_descriptor\|DSET_TYPE\|dset_list_head\|dset_RAM_index\|BPATCH\|bpatch" $D --include=*.h --include=*.c
echo
echo "=== AR6K_PATCH_FILE / DATASET_PATCH ==="
grep -rn "AR6K_PATCH_FILE\|DATASET_PATCH_ADDRESS" $D --include=*.h --include=*.c
