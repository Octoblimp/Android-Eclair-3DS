#!/bin/sh
# Phase 2: manual WiFi connect helper. Run this from the autologin shell:
#   sh /mnt/sd/linux/wifi_connect.sh
# (or wherever the SD card ends up mounted -- adjust MNT below if needed).
#
# Reads credentials from linux/wpa_supplicant.conf on the SD card (edit
# wpa_supplicant.conf.template on your PC, rename it, and drop it there --
# no typing needed on the 3DS's touch keyboard). Prints status at each
# step so a failure is easy to localize (driver bind vs association vs
# DHCP), which is more useful for this first real test than an opaque
# all-in-one auto-connect.

MNT=/mnt/sd
mkdir -p "$MNT"

echo "=== bringing up SD card (if not already mounted) ==="
mount -t vfat -o rw /dev/vda1 "$MNT" 2>/dev/null
mount | grep -q "$MNT" || mount -t vfat -o rw /dev/vda "$MNT" 2>/dev/null

if [ ! -f "$MNT/linux/wpa_supplicant.conf" ]; then
	echo "ERROR: $MNT/linux/wpa_supplicant.conf not found."
	echo "Copy wpa_supplicant.conf.template to your SD card as"
	echo "linux/wpa_supplicant.conf (edited with your real SSID/password) first."
	exit 1
fi
cp "$MNT/linux/wpa_supplicant.conf" /tmp/wpa_supplicant.conf

echo "=== ls /sys/class/net (does a wlan-type interface exist at all?) ==="
ls /sys/class/net

echo "=== ifconfig wlan0 up ==="
ifconfig wlan0 up
if [ $? -ne 0 ]; then
	echo "ERROR: no wlan0 interface -- the ath6kl driver likely didn't bind"
	echo "to the WiFi chip (check dmesg for ath6kl/sdio probe messages)."
	exit 1
fi

echo "=== starting wpa_supplicant (background) ==="
wpa_supplicant -B -i wlan0 -c /tmp/wpa_supplicant.conf -D nl80211

echo "=== waiting up to 15s for association ==="
i=0
while [ "$i" -lt 15 ]; do
	if iw dev wlan0 link 2>/dev/null | grep -q "Connected"; then
		echo "Associated:"
		iw dev wlan0 link
		break
	fi
	sleep 1
	i=$((i + 1))
done
if [ "$i" -eq 15 ]; then
	echo "Did not associate within 15s. Current state:"
	iw dev wlan0 link
fi

echo "=== requesting DHCP lease (up to ~15s) ==="
udhcpc -i wlan0 -n -q -t 5 -T 3

echo "=== final status ==="
ifconfig wlan0
echo; echo "route:"; route -n 2>/dev/null || ip route 2>/dev/null
