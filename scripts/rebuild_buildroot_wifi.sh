#!/bin/bash
# Re-extract and rebuild Buildroot's wpa_supplicant after the generated
# package patches have been refreshed.  The extracted source is also consumed
# by build_libhardware.sh for wpa_ctrl.c, so this must run before the native
# stack and before the minimal initramfs is assembled.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
BUILDROOT="$ROOT/third_party/buildroot"
WPA_SOURCE="$BUILDROOT/output/build/wpa_supplicant-2.10/wpa_supplicant/ctrl_iface.c"
WPA_TARGET="$BUILDROOT/output/target/usr/sbin/wpa_supplicant"
WPA_PATCH_DIR="$BUILDROOT/package/wpa_supplicant"

if [ ! -d "$BUILDROOT" ]; then
	echo "rebuild_buildroot_wifi: missing $BUILDROOT" >&2
	exit 1
fi

for patch in \
	0003-n3ds-remembered-network-ranking.patch \
	0004-n3ds-remembered-first-discovery.patch \
	0005-n3ds-scan-security-integrity.patch; do
	test -s "$WPA_PATCH_DIR/$patch" || {
		echo "rebuild_buildroot_wifi: generated package patch missing: $WPA_PATCH_DIR/$patch" >&2
		exit 1
	}
done

echo "=== forcing clean Buildroot wpa_supplicant rebuild ==="
# A package-only rebuild is intentional: the generated 0003-0005 patches are
# already present, and dirclean makes Buildroot re-extract/reapply them rather
# than silently retaining an incrementally patched source or target binary.
make -C "$BUILDROOT" wpa_supplicant-dirclean
make -C "$BUILDROOT" wpa_supplicant

test -s "$WPA_SOURCE"
test -x "$WPA_TARGET"
for marker in \
	'N3DS-PRIVACY' \
	'N3DS-WPA-RAW' \
	'N3DS-RSN-RAW' \
	'N3DS-SECURITY-UNKNOWN'; do
	strings "$WPA_TARGET" | grep -F "$marker" >/dev/null || {
		echo "rebuild_buildroot_wifi: runtime marker missing from $WPA_TARGET: $marker" >&2
		exit 1
	}
done

echo "rebuild_buildroot_wifi: rebuilt and verified $WPA_TARGET"
