#!/bin/sh
# N3DS_UPDATE_SAFE_PREFS: initialize and synchronize user-owned state.
#
# The kernel owns block I/O and does not parse Android preferences.  This
# native init service runs after the SD card is mounted, creates the durable
# namespace, and keeps the framework's volatile Wi-Fi file in sync without
# ever printing its contents.
set -u

MODE=${1:-prepare}
PAYLOAD=/mnt/sd/linux/android
ROOT="$PAYLOAD/persistent"
USERS="$ROOT/users"
SHARED="$ROOT/shared"
SECURE="$ROOT/secure"
TEMPLATES="$PAYLOAD/templates"
RUNTIME_WIFI=/data/misc/wifi/wpa_supplicant.conf
PERSIST_WIFI="$SHARED/wpa_supplicant.conf"
PERSIST_MOBILE="$SHARED/mobile_registration.conf"
RUNTIME_TOUCHCAL=/data/misc/touchcalibration.conf
PERSIST_TOUCHCAL="$SHARED/touchcalibration.conf"
TOUCH_SYSFS_PARAMS=/sys/module/android3ds_touch/parameters
# N3DS_SETTINGS_PERSIST: Android keeps its own settings under /data, which is
# RAM on this port.  They are mirrored here and put back at every boot:
#   appdata/<package>/  shared_prefs, databases, files and app_* of every
#                       app (settings.db, Launcher layout, keyboard, Browser
#                       bookmarks...).  installd refills these when the
#                       package manager creates the package's directory, so
#                       they always get that boot's uid.
#   system/             /data/system files (wallpaper choice, widgets) and
#                       persist.sys.* properties (time zone, language).
#   datashared/         /data/shared (the dialer's contacts and call log).
APPDATA="$ROOT/appdata"
SYSDATA="$ROOT/system"
DATASHARED="$ROOT/datashared"
PERSIST_PROPS="$SYSDATA/persist.props"
SYSTEM_FILES="wallpaper_info.xml appwidgets.xml"
RESTORE_BOOTS="$ROOT/restore_boots"
RESTORE_BOOT_LIMIT=3
SAVE_BUDGET_KB=1024
STATE=${N3DS_PREFS_STATE:-/tmp/n3ds_prefs}
SETPROP=${N3DS_SETPROP:-/system/bin/setprop}
GETPROP=${N3DS_GETPROP:-/system/bin/getprop}
NO_SYNC=
MIRROR=

status() {
	echo "N3DS prefs: $1" > /dev/kmsg 2>/dev/null || true
}

# Routine news stays off the console (KERN_INFO).
info() {
	echo "<6>N3DS prefs: $1" > /dev/kmsg 2>/dev/null || true
}

secure_dir() {
	mkdir -p "$1" || return 1
	chmod 0700 "$1" 2>/dev/null || true
}

atomic_copy() {
	src=$1
	dst=$2
	mode=$3
	tmp="$dst.tmp.$$"
	[ -f "$src" ] || return 0
	if [ -f "$dst" ] && cmp -s "$src" "$dst" 2>/dev/null; then
		return 0
	fi
	if cp "$src" "$tmp" 2>/dev/null; then
		chmod "$mode" "$tmp" 2>/dev/null || true
		mv -f "$tmp" "$dst" 2>/dev/null || {
			rm -f "$tmp"
			return 1
		}
		sync
		return 0
	fi
	rm -f "$tmp"
	return 1
}

atomic_generated() {
	dst=$1
	uid=$2
	tmp="$dst.tmp.$$"
	[ -e "$dst" ] && return 0
	{
		echo "# Generated on first boot for Android user $uid."
		echo "# Keep secrets out of templates and release images."
		echo "schema=1"
		echo "user_id=$uid"
	} > "$tmp" 2>/dev/null || return 1
	chmod 0600 "$tmp" 2>/dev/null || true
	mv -f "$tmp" "$dst" 2>/dev/null || {
		rm -f "$tmp"
		return 1
	}
	sync
}

# N3DS_WIFI_FILE_BOOT_POLICY: wifi_on_boot is an Android3DS control value,
# not part of wpa_supplicant's configuration grammar.  Keep it in the durable
# user file but never pass it to the daemon.  The framework reads the durable
# value directly during WifiService startup.
write_runtime_wifi() {
	tmp="$RUNTIME_WIFI.tmp.$$"
	[ -f "$PERSIST_WIFI" ] || return 0
	if sed '/^[[:space:]]*wifi_on_boot[[:space:]]*=/d' \
		"$PERSIST_WIFI" > "$tmp" 2>/dev/null && \
		grep -q '^ctrl_interface=' "$tmp" 2>/dev/null; then
		chmod 0600 "$tmp" 2>/dev/null || true
		mv -f "$tmp" "$RUNTIME_WIFI" 2>/dev/null || {
			rm -f "$tmp"
			return 1
		}
		return 0
	fi
	rm -f "$tmp"
	return 1
}

sync_runtime_wifi() {
	tmp="$PERSIST_WIFI.tmp.$$"
	[ -f "$RUNTIME_WIFI" ] || return 0
	boot_setting=$(sed -n \
		's/^[[:space:]]*\(wifi_on_boot[[:space:]]*=[[:space:]]*[01]\)[[:space:]]*$/\1/p' \
		"$PERSIST_WIFI" 2>/dev/null | head -n 1)
	if cp "$RUNTIME_WIFI" "$tmp" 2>/dev/null; then
		if [ -n "$boot_setting" ]; then
			printf '\n%s\n' "$boot_setting" >> "$tmp" || {
				rm -f "$tmp"
				return 1
			}
		fi
		chmod 0600 "$tmp" 2>/dev/null || true
		mv -f "$tmp" "$PERSIST_WIFI" 2>/dev/null || {
			rm -f "$tmp"
			return 1
		}
		return 0
	fi
	rm -f "$tmp"
	return 1
}

# N3DS_TOUCH_CALIBRATION_PERSIST: Touch Diagnostic's Calibrate mode (running
# as the system user, since /data/misc is 01771 system:misc) writes a fresh
# calibration to $RUNTIME_TOUCHCAL. That path is RAM-backed like the wifi
# runtime file above, so import the durable copy at boot and apply it to the
# kernel driver's sysfs module params -- root-owned 0644, so only this root
# init step (not the app) can write them -- before anything else touches the
# panel. A calibration saved mid-session takes effect on the next boot, the
# same "calibrate once, keep it" model GodMode9 uses for its own HWCAL.
apply_touchcal() {
	[ -f "$RUNTIME_TOUCHCAL" ] || return 0
	[ -d "$TOUCH_SYSFS_PARAMS" ] || return 0
	while IFS='=' read -r key value; do
		case "$key" in
		cal_x0_raw|cal_x0_px|cal_x1_raw|cal_x1_px| \
		cal_y0_raw|cal_y0_px|cal_y1_raw|cal_y1_px)
			[ -w "$TOUCH_SYSFS_PARAMS/$key" ] &&
				echo "$value" > "$TOUCH_SYSFS_PARAMS/$key" 2>/dev/null
			;;
		esac
	done < "$RUNTIME_TOUCHCAL"
}

sync_runtime_touchcal() {
	atomic_copy "$RUNTIME_TOUCHCAL" "$PERSIST_TOUCHCAL" 0644
}

# N3DS_SETTINGS_PERSIST ---------------------------------------------------

# Sets MIRROR to where runtime file $1 is kept; fails for anything not kept.
mirror_of() {
	MIRROR=
	case "$1" in
	/data/data/*/*)
		rel=${1#/data/data/}
		pkg=${rel%%/*}
		sub=${rel#*/}
		case "/$sub" in
		*/.*|*-journal|*-wal|*-shm|*.bak|*.n3ds-restore) return 1 ;;
		esac
		# Messages are replayed from the 3DSTelco journal at every boot,
		# so a kept mmssms.db would show each one twice.
		[ "$pkg" = com.android.providers.telephony ] && return 1
		case "$sub" in
		databases/webviewCache.db) return 1 ;;
		shared_prefs/*|databases/*|files/*) ;;
		app_*/*)
			# The Browser's app_* directories are page caches.
			[ "$pkg" = com.android.browser ] && return 1 ;;
		*) return 1 ;;
		esac
		MIRROR="$APPDATA/$rel"
		;;
	/data/shared/*)
		rel=${1#/data/shared/}
		case "/$rel" in
		*/.*|*-journal|*-wal|*-shm|*.n3ds-restore) return 1 ;;
		esac
		MIRROR="$DATASHARED/$rel"
		;;
	/data/system/*)
		case " $SYSTEM_FILES " in
		*" ${1#/data/system/} "*) MIRROR="$SYSDATA/${1#/data/system/}" ;;
		*) return 1 ;;
		esac
		;;
	*) return 1 ;;
	esac
	return 0
}

# Prints every kept runtime file under 4 MB; with a stamp file argument, only
# those changed since it.
list_tracked() {
	roots=
	for d in /data/data/*/shared_prefs /data/data/*/databases \
		/data/data/*/files /data/data/*/app_* /data/shared; do
		[ -d "$d" ] && roots="$roots $d"
	done
	for f in $SYSTEM_FILES; do
		[ -f "/data/system/$f" ] && roots="$roots /data/system/$f"
	done
	[ -n "$roots" ] || return 0
	if [ -n "${1:-}" ]; then
		find $roots -type f -size -4096k -newer "$1" 2>/dev/null
	else
		find $roots -type f -size -4096k 2>/dev/null
	fi | while IFS= read -r path; do
		mirror_of "$path" && echo "$path"
	done
}

sqlite_ok() {
	[ "$(head -c 15 "$1" 2>/dev/null)" = "SQLite format 3" ]
}

# True while database $1 is inside a transaction (or was cut off in one):
# its rollback journal still starts with the journal magic.  Covers the
# DELETE, TRUNCATE and PERSIST journal modes alike.
journal_active() {
	[ -s "$1-wal" ] && return 0
	[ -s "$1-journal" ] || return 1
	[ "$(head -c 4 "$1-journal" 2>/dev/null | od -An -tx1 | tr -d ' \n')" = "d9d505f9" ]
}

# Copies $1 to a dot-temporary beside mirror path $2.  Returns 0 when staged,
# 2 when the mirror already matches, 1 when the file is mid-write (it is
# retried on the next pass).
stage_copy() {
	src=$1
	dst=$2
	tmp="${dst%/*}/.${dst##*/}.n3ds-save"
	# SharedPreferences renames the old file to .bak while it writes.
	[ -e "$src.bak" ] && return 1
	journal_active "$src" && return 1
	if [ -f "$dst" ] && cmp -s "$src" "$dst" 2>/dev/null; then
		return 2
	fi
	sum=$(cksum < "$src") || return 1
	mkdir -p "${dst%/*}" 2>/dev/null || return 1
	if cp "$src" "$tmp" 2>/dev/null &&
		[ "$(cksum < "$tmp")" = "$sum" ] &&
		[ "$(cksum < "$src")" = "$sum" ]; then
		return 0
	fi
	rm -f "$tmp"
	return 1
}

save_props() {
	[ -x "$GETPROP" ] || return 0
	"$GETPROP" 2>/dev/null |
		sed -n 's/^\[\(persist\.sys\.[A-Za-z0-9._-]*\)\]: \[\(.*\)\]$/\1=\2/p' \
		> "$STATE/props" 2>/dev/null || return 0
	# An empty read is a getprop hiccup, never a reason to forget.
	[ -s "$STATE/props" ] || return 0
	mkdir -p "$SYSDATA" 2>/dev/null || return 0
	atomic_copy "$STATE/props" "$PERSIST_PROPS" 0600 || true
}

# A kept file the app deleted during this boot leaves the mirror too.  Only
# files seen on an earlier pass of this boot qualify, so a file whose restore
# failed can never be mistaken for a deletion.
prune_mirror() {
	list_tracked > "$STATE/now"
	if [ -s "$STATE/now" ] && [ -s "$STATE/seen" ]; then
		grep -vxF -f "$STATE/now" "$STATE/seen" | while IFS= read -r gone; do
			[ -e "$gone" ] && continue
			mirror_of "$gone" && rm -f "$MIRROR"
		done
	fi
	mv -f "$STATE/now" "$STATE/seen"
}

# One save pass.  $1 caps the kB copied (0 = no cap); whatever does not fit
# waits for the next pass, so a burst of browsing cannot flood the card.
# Every copy is synced before it replaces the mirror file, so a power cut
# leaves either the old or the new file, never a torn one.
settings_pass() {
	budget=$1
	mkdir -p "$STATE" 2>/dev/null || return 0
	save_props
	: > "$STATE/next"
	if [ -f "$STATE/stamp" ]; then
		# find -newer has one-second resolution: let this second end so
		# a write in it is caught by this pass, not lost between two.
		sleep 1
		list_tracked "$STATE/stamp" > "$STATE/changed"
	else
		list_tracked > "$STATE/changed"
	fi
	[ -f "$STATE/pending" ] && cat "$STATE/pending" >> "$STATE/changed"
	sort -u "$STATE/changed" > "$STATE/todo"
	: > "$STATE/pending.new"
	: > "$STATE/staged"
	written=0
	while IFS= read -r src; do
		mirror_of "$src" || continue
		[ -f "$src" ] || continue
		size=$(( ($(wc -c < "$src") + 1023) / 1024 ))
		if [ "$budget" -gt 0 ] && [ "$written" -gt 0 ] &&
			[ $((written + size)) -gt "$budget" ]; then
			echo "$src" >> "$STATE/pending.new"
			continue
		fi
		stage_copy "$src" "$MIRROR"
		case $? in
		0)
			echo "$MIRROR" >> "$STATE/staged"
			written=$((written + size))
			;;
		1) echo "$src" >> "$STATE/pending.new" ;;
		esac
	done < "$STATE/todo"
	if [ -s "$STATE/staged" ]; then
		[ -n "$NO_SYNC" ] || sync
		while IFS= read -r dst; do
			tmp="${dst%/*}/.${dst##*/}.n3ds-save"
			mv -f "$tmp" "$dst" 2>/dev/null || rm -f "$tmp"
		done < "$STATE/staged"
		[ -n "$NO_SYNC" ] || sync
	fi
	mv -f "$STATE/pending.new" "$STATE/pending"
	[ -n "$NO_SYNC" ] && return 0
	mv -f "$STATE/next" "$STATE/stamp"
	prune_mirror
}

# The watcher starts at sys.boot_completed: Android came up with what was
# restored, so the boot-loop counter goes back to zero.
settings_watch_start() {
	if [ -f "$RESTORE_BOOTS" ] && [ "$(cat "$RESTORE_BOOTS" 2>/dev/null)" != 0 ]; then
		echo 0 > "$RESTORE_BOOTS.tmp" 2>/dev/null &&
			mv -f "$RESTORE_BOOTS.tmp" "$RESTORE_BOOTS" 2>/dev/null
	fi
	# A power cut during a pass leaves dot-temporaries behind.
	for d in "$APPDATA" "$SYSDATA" "$DATASHARED"; do
		[ -d "$d" ] && find "$d" -type f -name '.*.n3ds-save' 2>/dev/null
	done | while IFS= read -r f; do
		rm -f "$f"
	done
}

# Boot-loop breaker: count boots that restore settings; the watcher zeroes
# the count once Android finishes booting.  If RESTORE_BOOT_LIMIT boots in a
# row never got there, a restored file may be what kills them: set the whole
# saved copy aside, unread, and boot on defaults.
restore_guard() {
	have=
	for d in "$APPDATA" "$SYSDATA" "$DATASHARED"; do
		[ -d "$d" ] && have=1
	done
	[ -n "$have" ] || return 0
	n=$(cat "$RESTORE_BOOTS" 2>/dev/null)
	case "$n" in
	''|*[!0-9]*) n=0 ;;
	esac
	if [ "$n" -ge "$RESTORE_BOOT_LIMIT" ]; then
		rm -rf "$ROOT/quarantine"
		mkdir -p "$ROOT/quarantine"
		for d in appdata system datashared; do
			[ -d "$ROOT/$d" ] && mv "$ROOT/$d" "$ROOT/quarantine/$d"
		done
		status "settings restore skipped: $n boots in a row never finished; saved settings moved to persistent/quarantine"
		n=0
	else
		n=$((n + 1))
	fi
	echo "$n" > "$RESTORE_BOOTS.tmp" 2>/dev/null &&
		mv -f "$RESTORE_BOOTS.tmp" "$RESTORE_BOOTS" 2>/dev/null
}

restore_file() {
	src=$1
	dst=$2
	tmp="$dst.n3ds-restore"
	case "$dst" in
	*.db) sqlite_ok "$src" || return 1 ;;
	esac
	if cp "$src" "$tmp" 2>/dev/null && chown "$3" "$tmp" 2>/dev/null &&
		chmod "$4" "$tmp" 2>/dev/null && mv -f "$tmp" "$dst" 2>/dev/null; then
		return 0
	fi
	rm -f "$tmp"
	return 1
}

# Only persist.sys.* (time zone, language) is ever set back.  Never
# persist.service.adb.enable: see N3DS_ADB_DEFAULT_ON.
restore_props() {
	[ -f "$PERSIST_PROPS" ] && [ -x "$SETPROP" ] || return 0
	while IFS='=' read -r name value; do
		case "$name" in
		persist.service.adb.enable) continue ;;
		persist.sys.*) ;;
		*) continue ;;
		esac
		case "$name" in
		*[!A-Za-z0-9._-]*) continue ;;
		esac
		"$SETPROP" "$name" "$value" 2>/dev/null || true
	done < "$PERSIST_PROPS"
}

# Runs from prepare, before class_start: nothing in Android is up yet.  App
# data is restored later, by installd (N3DS_APPDATA_RESTORE).
restore_settings() {
	restore_guard
	restored=0
	if [ -d "$SYSDATA" ]; then
		# init.rc's own "mkdir /data/system" comes later and accepts this.
		mkdir -p /data/system 2>/dev/null
		chown 1000:1000 /data/system 2>/dev/null
		chmod 0775 /data/system 2>/dev/null
		for name in $SYSTEM_FILES; do
			[ -f "$SYSDATA/$name" ] || continue
			if restore_file "$SYSDATA/$name" "/data/system/$name" 1000:1000 0660; then
				restored=$((restored + 1))
			fi
		done
		restore_props
	fi
	if [ -d "$DATASHARED" ]; then
		# The dialer (android.uid.system) opens these world-writable.
		mkdir -p /data/shared 2>/dev/null
		(cd "$DATASHARED" && find . -type f) | while IFS= read -r rel; do
			rel=${rel#./}
			case "/$rel" in
			*/.*) continue ;;
			esac
			case "$rel" in
			*/*) mkdir -p "/data/shared/${rel%/*}" 2>/dev/null ;;
			esac
			restore_file "$DATASHARED/$rel" "/data/shared/$rel" 1000:1000 0666 || true
		done
		chown -R 1000:1000 /data/shared 2>/dev/null
		find /data/shared -type d | while IFS= read -r d; do
			chmod 0777 "$d" 2>/dev/null
		done
		chmod 0771 /data/shared 2>/dev/null
	fi
	# Everything changed after this moment is saved by the watcher.
	mkdir -p "$STATE" 2>/dev/null && : > "$STATE/stamp"
	info "settings restored ($restored /data/system files; app data follows via installd)"
}

user_ids() {
	# Eclair is single-user, but preserve any numeric user directories if a
	# later framework adds multi-user state.  Always provision user 0.
	printf '0\n'
	for path in /data/system/users/* /data/user/*; do
		[ -d "$path" ] || continue
		uid=${path##*/}
		case "$uid" in
			''|*[!0-9]*) ;;
			*) printf '%s\n' "$uid" ;;
		esac
	done
}

prepare() {
	tries=0
	while [ "$tries" -lt 20 ] && ! grep -q ' /mnt/sd ' /proc/mounts 2>/dev/null; do
		sleep 1
		tries=$((tries + 1))
	done
	[ -d "$PAYLOAD" ] && grep -q ' /mnt/sd ' /proc/mounts 2>/dev/null || {
		status "SD root unavailable; persistent state not initialized"
		return 1
	}
	secure_dir "$PAYLOAD" || return 1
	secure_dir "$ROOT" || return 1
	secure_dir "$USERS" || return 1
	secure_dir "$SHARED" || return 1
	secure_dir "$SECURE" || return 1

	# Migrate a user-supplied legacy file before creating the new shared file.
	# The candidate paths are never logged and are accepted only when they
	# contain a network block, avoiding migration of a release template.
	if [ ! -f "$PERSIST_WIFI" ]; then
		for legacy in /mnt/sd/linux/wpa_supplicant.conf \
			/mnt/sd/linux/android/data/wpa_supplicant.conf; do
			if [ -f "$legacy" ] && grep -q '^network=' "$legacy" 2>/dev/null; then
				atomic_copy "$legacy" "$PERSIST_WIFI" 0600 || true
				break
			fi
		done
	fi

	# Move the legacy root-level registration file into the durable shared
	# namespace without logging its provisioning code.  /sdcard is a bind mount
	# of $PAYLOAD, so Android applications see this as
	# /sdcard/persistent/shared/mobile_registration.conf.
	if [ ! -f "$PERSIST_MOBILE" ]; then
		for legacy_mobile in /mnt/sd/linux/mobile_registration.conf \
			/mnt/sd/linux/android/mobile_registration.conf; do
			if [ -f "$legacy_mobile" ]; then
				atomic_copy "$legacy_mobile" "$PERSIST_MOBILE" 0600 || true
				break
			fi
		done
	fi
	if [ ! -f "$PERSIST_MOBILE" ]; then
		tmp="$PERSIST_MOBILE.tmp.$$"
		{
			echo '# 3DSTelco Mobile Registration Configuration'
			echo '# Uncomment to enable Mobile Data at boot:'
			echo '# mobile_data_on_boot=1'
			echo '# setup_code='
		} > "$tmp" 2>/dev/null || true
		chmod 0600 "$tmp" 2>/dev/null || true
		mv -f "$tmp" "$PERSIST_MOBILE" 2>/dev/null || rm -f "$tmp"
		sync
	fi
	if [ ! -f "$PERSIST_WIFI" ]; then
		tmp="$PERSIST_WIFI.tmp.$$"
		{
			echo '# Generated on first boot; add network blocks locally.'
			echo 'ctrl_interface=DIR=/data/system/wpa_supplicant GROUP=1010'
			echo 'update_config=1'
			echo 'ap_scan=1'
		} > "$tmp" 2>/dev/null || true
		chmod 0600 "$tmp" 2>/dev/null || true
		mv -f "$tmp" "$PERSIST_WIFI" 2>/dev/null || rm -f "$tmp"
		sync
	fi

	for uid in $(user_ids); do
		user_dir="$USERS/$uid"
		secure_dir "$user_dir" || continue
		atomic_generated "$user_dir/preferences.conf" "$uid" || true
	done

	# N3DS_SETTINGS_PERSIST: before the Wi-Fi import, which may return early.
	restore_settings

	# Runtime Android state remains on the RAM-backed /data tree.  Import a
	# daemon-safe Wi-Fi file before supplicant starts; the durable boot toggle
	# stays only in the shared file.
	if [ -f "$PERSIST_WIFI" ]; then
		if ! write_runtime_wifi; then
			status "persistent Wi-Fi import failed"
			return 1
		fi
	fi

	if [ -f "$PERSIST_TOUCHCAL" ]; then
		atomic_copy "$PERSIST_TOUCHCAL" "$RUNTIME_TOUCHCAL" 0644 || true
	fi
	apply_touchcal

	status "persistent namespace ready; user files are not release artifacts"
}

sync_once() {
	if [ -f "$RUNTIME_WIFI" ]; then
		sync_runtime_wifi || true
	fi
	sync_runtime_touchcal || true
}

if [ "$MODE" = "--watch" ]; then
	# prepare already imported persistent -> runtime synchronously during
	# `on boot`.  Re-running it here at sys.boot_completed could erase a
	# framework update made during boot, so the watcher is copy-back only.
	[ -d "$SHARED" ] || {
		status "persistent namespace unavailable; sync watcher not started"
		exit 0
	}
	settings_watch_start
	pass=0
	while :; do
		sync_once
		# N3DS_SETTINGS_PERSIST: Android's settings every fourth wake (60 s).
		[ $((pass % 4)) -eq 0 ] && settings_pass "$SAVE_BUDGET_KB"
		pass=$((pass + 1))
		sleep 15
	done
elif [ "$MODE" = "--flush" ]; then
	# ctr_poweroff.sh, after Android has stopped: save what changed since the
	# last pass.  Uncapped and unsynced: the poweroff sync and remount follow.
	[ -d "$SHARED" ] || exit 0
	NO_SYNC=1
	sync_once
	settings_pass 0
elif [ "$MODE" = "--pass" ]; then
	# One complete save pass (the settings-persistence gate drives this).
	[ -d "$SHARED" ] || exit 0
	settings_pass 0
else
	prepare
fi
