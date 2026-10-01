#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail
ROOT="${ANDROID3DS_ROOT}"
PROJECT="${ANDROID3DS_WIN}"
OUT="$ROOT/build/contacts_provider_smoke"
FAKEROOT="$OUT/fakeroot"
QEMU="$ROOT/toolchain/qemu/qemu-arm-static"
APP_PROCESS="$ROOT/build/app_process_qemu/app_process_qemu"
DEXOPT="$ROOT/build/dexopt/dexopt_qemu"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
CORE="$ROOT/build/core/classes.jar"
FW="$ROOT/build/framework_jar/classes.jar"
SD="$PROJECT/sdcard/linux/android"
test -s "$ROOT/build/contacts_provider/ContactsProvider.apk"
test -x "$APP_PROCESS"
rm -rf "$OUT"
mkdir -p "$OUT/classes" "$FAKEROOT/system/app" "$FAKEROOT/data/dalvik-cache"
cp -a "$ROOT/build/contacts_provider/classes/." "$OUT/classes/"
"$JDK/bin/javac" -nowarn -source 6 -target 6 -bootclasspath "$CORE:$FW" \
    -classpath "$FW:$CORE:$OUT/classes" -d "$OUT/classes" "$PROJECT/content/ContactsProviderSmoke.java"
"$ROOT/build/dx/dx" --dex --output="$OUT/smoke.jar" "$OUT/classes"
cp -a "$SD/system/." "$FAKEROOT/system/"
cp -a "$SD/data/dalvik-cache/." "$FAKEROOT/data/dalvik-cache/"
cp "$OUT/smoke.jar" "$FAKEROOT/system/app/ContactsProviderSmoke.apk"
set +e
a3ds_sudo unshare --mount -- bash -c '
set -e
mkdir -p /system /data
mount --bind "$1" /system
mount --bind "$2" /data
export ANDROID_ROOT=/system ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
: > /system/app/ContactsProviderSmoke.odex
exec 3< /system/app/ContactsProviderSmoke.apk
exec 4<> /system/app/ContactsProviderSmoke.odex
"$3" "$4" --zip 3 4 /system/app/ContactsProviderSmoke.apk ""
export CLASSPATH=/system/app/ContactsProviderSmoke.apk
exec timeout 45s "$3" "$5" /system/bin com.android.providers.contacts.ContactsProviderSmoke
' -- "$FAKEROOT/system" "$FAKEROOT/data" "$QEMU" "$DEXOPT" "$APP_PROCESS" > "$OUT/run.log" 2>&1
status=$?
set -e
cat "$OUT/run.log"
# app_process exits 1 after main in this binder-less test environment; the
# same convention is used by the existing DecimalFormat ARM smoke test.
test "$status" -le 1
grep -F 'PASS: ContactsProvider ARM schema, ICU names, contacts, call log and reopen' "$OUT/run.log"
