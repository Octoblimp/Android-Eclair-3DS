#!/bin/sh
#
# N3DS_PRUNE_RETIRED_APPS: delete apps this build no longer ships from the SD
# card's /system/app, before PackageManager scans it.
#
# sdcard.zip is extracted *over* the card, so it can add and replace files but
# never remove one.  Contacts.apk was dropped from the image in #317 and was
# still installed on the next boot: the copy from an older build was sitting
# on the card, /data is RAM so PackageManager rescans /system/app from scratch
# every boot, and a scan installs whatever it finds.  The same goes for the
# two apps retired before it.  Deleting them here is the only place a removal
# can happen.
#
# Runs from `on boot`, ahead of class_start, so nothing has opened these
# files yet.  Only the exact names below are touched, and the boot never
# depends on it: every failure is logged and the exit status is always 0.

# Retired apps, by /system/app basename.
#   Contacts    -- stock AOSP contacts, replaced by N3dsDialer (#317)
#   DevTools    -- replaced by the real AOSP Development app
#   N3dsCamera  -- replaced by the Camera app on CameraHardwareN3ds
#   N3DSKeyboard -- the custom keyboard, replaced by AOSP LatinIME
RETIRED="Contacts DevTools N3dsCamera N3DSKeyboard"

log() {
	echo "prune_retired_apps: $1" > /dev/kmsg 2>/dev/null
}

removed=0
for app in $RETIRED; do
	for f in "/system/app/$app.apk" "/system/app/$app.odex" \
		 "/data/dalvik-cache/system@app@$app.apk@classes.dex"; do
		[ -e "$f" ] || continue
		if rm -f "$f" 2>/dev/null && [ ! -e "$f" ]; then
			log "removed $f"
			removed=$((removed + 1))
		else
			log "could not remove $f"
		fi
	done
done

# No sync: init waits on this script, and a sync during boot can block for
# minutes behind SD writeback.  The deletion reaches the card with ordinary
# writeback or the poweroff remount -- and if it never does, this runs again
# before the next scan and removes the files again.
log "done, $removed file(s) removed (N3DS_PRUNE_RETIRED_APPS)"
exit 0
