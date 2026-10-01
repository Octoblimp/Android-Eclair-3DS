#!/bin/bash
# Build android.policy.jar + services.jar -- the SystemServer/WindowManagerService/
# ActivityManagerService/PackageManagerService half of the framework, deliberately
# excluded from build_framework_jar.sh's FRAMEWORKS_BASE_SUBDIRS (real AOSP builds
# these as their own modules too -- see frameworks/base/services/java/Android.mk's
# LOCAL_MODULE := services and frameworks/policies/base/phone/Android.mk's
# LOCAL_MODULE := android.policy_phone).
#
# Same javac+dx pattern as build_core_jar.sh/build_framework_jar.sh (JDK 8,
# -source/-target 6). Unlike framework.jar this needs no AIDL generation (services/
# java has zero .aidl files of its own -- it just implements Stub classes AIDL
# already generated for core/java's IPowerManager.aidl etc during the framework.jar
# build) and no R.java (already compiled into framework's classes.jar).
#
# Two real AOSP modules, compiled together into one jar for simplicity (real
# BOOTCLASSPATH flattens them into the same classloader anyway -- see
# docs/HANDOFF.md's zygote-socket-fix session recap for why putting services on
# BOOTCLASSPATH, not some separate app classpath, is what real init.rc does):
#   - frameworks/policies/base/phone -- android.policy (PhoneWindowManager,
#     Keyguard*, PhoneWindow, GlobalActions). "phone" variant chosen over "mid"
#     (tablet/MID variant) since it's the complete, standard WindowManagerPolicy
#     every real Eclair phone/tablet shipped; telephony absence is handled the
#     same way the rest of this project handles missing hardware (present in
#     code, unable to get a real signal), not by using a stripped policy.
#   - frameworks/base/services/java -- SystemServer + am/ (ActivityManagerService)
#     + status/ (StatusBarService) subpackages, 94 files total.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"

POLICY_SRC="${ANDROID3DS_ROOT}"/third_party/frameworks/policies/base/phone
SERVICES_SRC="${ANDROID3DS_ROOT}"/third_party/frameworks/base/services/java
CORE_CLASSES_JAR="${ANDROID3DS_ROOT}"/build/core/classes.jar
FRAMEWORK_CLASSES_JAR="${ANDROID3DS_ROOT}"/build/framework_jar/classes.jar
OUT="${ANDROID3DS_ROOT}"/build/services_jar
LOG="${ANDROID3DS_ROOT}"/build_services_jar.log

rm -rf "$OUT"
mkdir -p "$OUT/classes"

# BackupManagerService.java: needs com.android.internal.backup.LocalTransport,
# which build_framework_jar.sh already defers (LocalTransport imports
# org.bouncycastle.util.encoders.Base64 -- real crypto library, not vendored,
# same reasoning as every other org.bouncycastle deferral in that script).
# SystemServer.java's own call site is already commented out to match.
EXCLUDE_EXTRA_FILES="
com/android/server/BackupManagerService.java
"

ALL_SRCS="$OUT/all_srcs.txt"
RAW_SRCS="$OUT/raw_srcs.txt"
: > "$RAW_SRCS"
find "$POLICY_SRC" -name "*.java" >> "$RAW_SRCS"
find "$SERVICES_SRC" -name "*.java" >> "$RAW_SRCS"

: > "$ALL_SRCS"
while IFS= read -r f; do
    skip=0
    for x in $EXCLUDE_EXTRA_FILES; do
        case "$f" in
            *"$x") skip=1; break ;;
        esac
    done
    [ "$skip" -eq 0 ] && echo "$f" >> "$ALL_SRCS"
done < "$RAW_SRCS"

echo "total .java found: $(wc -l < "$RAW_SRCS"), compiling: $(wc -l < "$ALL_SRCS")"

set +e
"$JAVAC" -J-Xmx3g -source 6 -target 6 -nowarn -encoding UTF-8 \
    -bootclasspath "$CORE_CLASSES_JAR:$FRAMEWORK_CLASSES_JAR" \
    -Xmaxerrs 100000 \
    -d "$OUT/classes" \
    @"$ALL_SRCS" > "$LOG" 2>&1
RC=$?
set -e

ERRORS=$(grep -c "error:" "$LOG" || true)
echo "javac exit=$RC errors=$ERRORS"

if [ "$RC" -ne 0 ]; then
    echo
    echo "=== error summary (most common first) ==="
    grep "error:" "$LOG" | sed -E 's/.*error: //' | sed -E 's/[A-Za-z0-9_.$]+\.java//g' \
        | sort | uniq -c | sort -rn | head -40
    echo
    echo "=== first 20 errors verbatim ==="
    grep -B1 -A2 "error:" "$LOG" | head -150
    exit 1
fi

echo "=== javac clean, $(find "$OUT/classes" -name '*.class' | wc -l) classes ==="

JAR="$JDK/bin/jar"
DX="${ANDROID3DS_ROOT}"/build/dx/dx

echo "=== packaging classes.jar ==="
"$JAR" cf "$OUT/classes.jar" -C "$OUT/classes" .
ls -la "$OUT/classes.jar"

echo "=== dx --dex ==="
"$DX" --dex --output="$OUT/classes.dex" "$OUT/classes.jar"
ls -la "$OUT/classes.dex"

echo "=== services.jar ==="
( cd "$OUT" && "$JAR" cf services.jar classes.dex )
ls -la "$OUT/services.jar"
