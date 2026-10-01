#!/bin/sh
# Exercise the exact filter used before wpa_supplicant parses its config.
set -eu

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

persist="$tmp_dir/persist.conf"
runtime="$tmp_dir/runtime.conf"
{
	echo 'ctrl_interface=DIR=/data/system/wpa_supplicant GROUP=1010'
	echo 'update_config=1'
	echo 'wifi_on_boot=1'
	echo 'ap_scan=1'
	echo 'network={'
	echo 'ssid="TEST_ONLY"'
	echo 'key_mgmt=NONE'
	echo '}'
} > "$persist"

sed '/^[[:space:]]*wifi_on_boot[[:space:]]*=/d' "$persist" > "$runtime"
! grep -q 'wifi_on_boot' "$runtime"
grep -q '^ctrl_interface=' "$runtime"
grep -q '^network=' "$runtime"

echo 'supplicant_boot_toggle: PASS'
