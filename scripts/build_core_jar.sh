#!/bin/bash
# Build core.jar -- Dalvik's bootclasspath.
#
# This is what "ERROR: must specify non-'.' bootclasspath" is asking for. The
# VM itself is fine (every dvmStartup() phase succeeds on hardware); it simply
# has no java.lang.Object to load.
#
# Mirrors dalvik/libcore/Android.mk's "core" module:
#   LOCAL_SRC_FILES        := all */src/main/java/**/*.java
#   LOCAL_NO_STANDARD_LIBRARIES := true   -> javac -bootclasspath ''
#   LOCAL_DX_FLAGS         := --core-library
#
# The empty bootclasspath is the whole point: libcore *is* the class library,
# so it must not compile against the JDK's java.lang.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JAR="$JDK/bin/jar"
DX="${ANDROID3DS_ROOT}"/build/dx/dx

LIBCORE="${ANDROID3DS_ROOT}"/third_party/dalvik/libcore
OUT="${ANDROID3DS_ROOT}"/build/core
LOG="${ANDROID3DS_ROOT}"/build_core.log

rm -rf "$OUT"
mkdir -p "$OUT/classes"

echo "=== collecting sources ==="
( cd "$LIBCORE" && find */src/main/java -name "*.java" ) | sed "s|^|$LIBCORE/|" > "$OUT/sources.txt"
echo "  $(wc -l < "$OUT/sources.txt") java files"

echo "=== javac (empty bootclasspath) ==="
# -source/-target 6: Eclair's libcore is Java 5/6 source.
# -Xmaxerrs: we want the full picture on the first run, not the first 100.
set +e
"$JAVAC" -J-Xmx3g -source 6 -target 6 -nowarn -encoding UTF-8 \
    -bootclasspath '' \
    -Xmaxerrs 100000 \
    -d "$OUT/classes" \
    @"$OUT/sources.txt" > "$LOG" 2>&1
RC=$?
set -e

ERRORS=$(grep -c "error:" "$LOG" || true)
echo "  javac exit=$RC  errors=$ERRORS"

if [ "$RC" -ne 0 ]; then
    echo
    echo "=== error summary (most common first) ==="
    grep "error:" "$LOG" | sed -E 's/.*error: //' | sed -E 's/[A-Za-z0-9_.$]+\.java//g' \
        | sort | uniq -c | sort -rn | head -30
    echo
    echo "=== first 15 errors verbatim ==="
    grep -A2 "error:" "$LOG" | head -60
    exit 1
fi

echo "=== collecting resources ==="
# 2026-08-05: core.jar shipped as classes.dex + META-INF/MANIFEST.MF and
# nothing else -- zero resource entries. Two separate bugs caused that:
#
# 1. Only */src/main/resources was searched. In this Harmony snapshot exactly
#    ONE module (prefs) has such a directory; every other resource sits
#    beside its .java files under */src/main/java, which is where Android's
#    own build picks them up from. So 21 of the 22 .properties files were
#    never collected at all.
#
# 2. Even the one that was collected only reached classes.jar, which is just
#    dx's input. The final `jar cf core.jar classes.dex` then packaged the
#    dex alone, so no resource could ever have survived into core.jar
#    regardless of step 1.
#
# What that cost, observed on hardware: Dalvik resolves resources by reading
# the *jar* (dex holds code only), so ClassLoader.getResourceAsStream()
# returned null for everything. Harmony's ExternalMessages.properties is how
# every core-library exception turns its message key into English, so
# system_server's real failure surfaced as the meaningless
# "java.io.IOException: K0059" (K0059 = "Stream is closed"), preceded by a
# pile of ClassNotFoundException/NoClassDefFoundError for
# org.apache.harmony.luni.util.ExternalMessages_en_US and _en -- that part is
# normal ResourceBundle probing, but the .properties fallback behind it was
# missing too, so the lookup had nowhere to land. Missing
# java/util/logging/logging.properties is what made LogManager fail in the
# first place.
#
# Only .properties (plus any real src/main/resources tree) is taken. The 47
# package.html files under src/main/java are javadoc and have no business in
# the bootclasspath.
RES="$OUT/res"
rm -rf "$RES"
mkdir -p "$RES"
( cd "$LIBCORE" && find */src/main/java -type f -name "*.properties" ) | while read -r f; do
    rel="${f#*/src/main/java/}"
    mkdir -p "$RES/$(dirname "$rel")"
    cp "$LIBCORE/$f" "$RES/$rel"
done
for d in "$LIBCORE"/*/src/main/resources; do
    [ -d "$d" ] && cp -r "$d"/. "$RES/" 2>/dev/null || true
done
echo "  $(find "$RES" -type f | wc -l) resource files"

echo "=== packaging classes.jar ==="
cp -r "$RES"/. "$OUT/classes/"
"$JAR" cf "$OUT/classes.jar" -C "$OUT/classes" .
ls -la "$OUT/classes.jar"

echo "=== dx --dex --core-library ==="
# --core-library: dx otherwise refuses to dex classes in the java.* package.
"$DX" --dex --core-library --output="$OUT/classes.dex" "$OUT/classes.jar"
ls -la "$OUT/classes.dex"

echo "=== core.jar ==="
# classes.dex + the resource tree. NOT the .class files: Dalvik never reads
# them, and they would roughly double the jar.
( cd "$OUT" && "$JAR" cf core.jar classes.dex && "$JAR" uf core.jar -C "$RES" . )
ls -la "$OUT/core.jar"
echo "=== core.jar resource entries ==="
"$JAR" tf "$OUT/core.jar" | grep -c "\.properties$" || true
