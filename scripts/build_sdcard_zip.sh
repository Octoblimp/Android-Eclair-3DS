#!/bin/bash
# build_sdcard_zip.sh -- pack the canonical WSL staging tree (sdcard/) into the
# flashable sdcard.zip, verifying the archive against the tree it came from.
#
# Why this exists: until 2026-09-11 there was no script for this. The zip was
# hand-assembled, and on 2026-09-10 the respin failed silently -- `zip` is not
# installed in this WSL image, so it died with exit 127 and nothing checked.
# The old archive stayed in place, so every "rebuild and reflash" after that
# flashed identical bytes (md5 1ff0364ece373c42fe4dcb210bf90cdd, unchanged
# since 2026-09-09). That is why no build ever changed the hardware behaviour.
#
# Two defences against a repeat: packing is done by python3's zipfile (no
# external binary to go missing), and the archive is re-read and compared to
# the staging tree before it is allowed to replace the live zip.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="$ROOT/sdcard"
WIN_ROOT="${ANDROID3DS_WIN}"
OUT="$WIN_ROOT/sdcard.zip"
OLD_DIR="$WIN_ROOT/old_zips"

die() { echo "ERROR: $*" >&2; exit 1; }

[ -d "$STAGING" ] || die "missing staging tree $STAGING"
# A zip extracted into the staging tree doubles the archive. Already happened
# once in the Windows copy (sdcard/sdcard/linux/...).
[ -e "$STAGING/sdcard" ] && die "nested $STAGING/sdcard exists -- delete it first"

echo "== 1. required files =="
REQUIRED=(
  linux/zImage
  linux/System.map
  linux/initramfs.cpio.gz
  linux/nintendo3ds_ctr.dtb
  linux/nintendo3ds_ktr.dtb
  linux/arm9linuxfw.bin
  linux/enable_pica_qualification
  linux/android/etc/init.rc
  linux/android/system/framework/core.jar
  linux/android/system/framework/framework.jar
  linux/android/system/framework/services.jar
  luma/payloads/down_firm_linux_loader.firm
)
for f in "${REQUIRED[@]}"; do
  [ -f "$STAGING/$f" ] || die "missing required file sdcard/$f"
done
# One loader payload only (hold DOWN at boot). The unprefixed duplicate is
# retired; build_firm_loader.sh deletes it, this keeps it from being packed.
[ -e "$STAGING/luma/payloads/firm_linux_loader.firm" ] \
  && die "sdcard/luma/payloads/firm_linux_loader.firm is back -- only down_firm_linux_loader.firm ships; delete it"
echo "   all ${#REQUIRED[@]} required files present"

echo "== 2. zImage / System.map pairing =="
[ "$STAGING/linux/System.map" -ot "$STAGING/linux/zImage" ] \
  && die "System.map older than zImage -- backtraces would decode against a stale map"
echo "   System.map is not older than zImage"

echo "== 3. dexpreopt freshness (the fields Dalvik really compares) =="
# NOT a file-mtime comparison. dvmCheckOptHeaderAndDependencies() validates the
# modWhen + CRC-32 of the jar's classes.dex CENTRAL DIRECTORY entry against the
# copy recorded in the odex's dependency section; the jar's filesystem mtime is
# never read. `jar_dexdep.py pin` rewrites that central-directory timestamp
# after a jar is built, which moves the file mtime forward without changing a
# single byte Dalvik looks at -- so an mtime gate here fails on precisely the
# builds that are correct, and sends the developer back into a four-minute
# dexpreopt that regenerates an identical cache.
CACHE="$STAGING/linux/android/data/dalvik-cache"
for j in core ext framework services; do
  jar="$STAGING/linux/android/system/framework/$j.jar"
  odex="$CACHE/system@framework@$j.jar@classes.dex"
  [ -f "$jar" ] || continue
  [ -f "$odex" ] || die "no odex for $j.jar -- run build_dexpreopt_qemu.sh AFTER sync_android_to_sdcard.sh"
done
python3 "$ROOT/scripts/jar_dexdep.py" verify "$STAGING/linux/android" \
  || die "bootclasspath odex would be rejected at boot -- re-run build_dexpreopt_qemu.sh AFTER sync_android_to_sdcard.sh"
python3 - "$ROOT" "$STAGING/linux/android" <<'PYEOF' \
  || die "a bundled app odex would be rejected at boot -- re-run its scripts/prebake_*_odex.sh"
import importlib.util, sys
spec = importlib.util.spec_from_file_location(
    "jar_dexdep", sys.argv[1] + "/scripts/jar_dexdep.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sys.exit(mod.verify_apps(sys.argv[2]))
PYEOF

echo "== 4. archive previous zip =="
mkdir -p "$OLD_DIR"
if [ -f "$OUT" ]; then
  prev="$OLD_DIR/sdcard.zip.stale-$(date -r "$OUT" +%Y-%m-%d-%H%M)"
  [ -e "$prev" ] || cp -p "$OUT" "$prev"
  echo "   previous -> $(basename "$prev")  md5 $(md5sum "$OUT" | cut -d' ' -f1)"
fi

echo "== 5. pack + verify =="
TMPZIP="$(mktemp -u /tmp/sdcard.XXXXXX.zip)"
trap 'rm -f "$TMPZIP"' EXIT
python3 "$ROOT/scripts/pack_sdcard_zip.py" "$ROOT" "$STAGING" "$TMPZIP" || die "pack/verify failed"

echo "== 6. the zip must not be a duplicate of an archived one =="
NEW_MD5="$(md5sum "$TMPZIP" | cut -d' ' -f1)"
for old in "$OLD_DIR"/*; do
  [ -f "$old" ] || continue
  if [ "$(md5sum "$old" | cut -d' ' -f1)" = "$NEW_MD5" ]; then
    die "new zip is byte-identical to $(basename "$old") -- the staging tree did not change"
  fi
done
echo "   md5 $NEW_MD5 is distinct from all $(ls -1 "$OLD_DIR" | wc -l) archived zips"

cp "$TMPZIP" "$OUT"
chmod 644 "$OUT"

echo
echo "== RESULT =="
echo "   $OUT"
echo "   size $(stat -c%s "$OUT")  md5 $(md5sum "$OUT" | cut -d' ' -f1)"
for f in linux/zImage linux/System.map linux/nintendo3ds_ktr.dtb \
         linux/android/system/framework/services.jar \
         linux/android/data/dalvik-cache/system@framework@services.jar@classes.dex \
         linux/android/etc/ctr_poweroff.sh; do
  [ -f "$STAGING/$f" ] && printf '   %-62s %8s  %s\n' \
    "$f" "$(stat -c%s "$STAGING/$f")" "$(date -r "$STAGING/$f" +%m-%d\ %H:%M)"
done
