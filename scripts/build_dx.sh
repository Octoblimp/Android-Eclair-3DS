#!/bin/bash
# Build dx, the dex compiler, from dalvik/dx.
#
# dx turns .class files into a classes.dex. core.jar (Dalvik's bootclasspath)
# cannot be produced without it, and there is no prebuilt in this tree -- only
# the Java source. It is a host tool, so it runs on the JDK, not on the 3DS.
#
# JDK 8 specifically: dx is Java 5/6 source, and it uses APIs (and a
# -source/-target level) that javac 11+ refuses outright.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JAR="$JDK/bin/jar"

DX_SRC="${ANDROID3DS_ROOT}"/third_party/dalvik/dx/src
OUT="${ANDROID3DS_ROOT}"/build/dx
LOG="${ANDROID3DS_ROOT}"/build_dx.log

rm -rf "$OUT"
mkdir -p "$OUT/classes"

echo "=== compiling dx ==="
find "$DX_SRC" -name "*.java" > "$OUT/sources.txt"
echo "  $(wc -l < "$OUT/sources.txt") source files"

# -nowarn: this is 2009 code built with a 2014 compiler; the deprecation and
# unchecked-conversion noise is not actionable here.
"$JAVAC" -source 6 -target 6 -nowarn -encoding UTF-8 \
    -d "$OUT/classes" \
    @"$OUT/sources.txt" > "$LOG" 2>&1 || {
        echo "FAILED -- last 40 lines of $LOG:"
        tail -40 "$LOG"
        exit 1
    }
grep -c "error:" "$LOG" 2>/dev/null || true

echo "=== packaging dx.jar ==="
# dx reads its own resources (the .properties for the command line) from the
# jar, so copy any non-.java files across too.
( cd "$DX_SRC" && find . -type f ! -name "*.java" -exec cp --parents {} "$OUT/classes/" \; ) 2>/dev/null || true

"$JAR" cfe "$OUT/dx.jar" com.android.dx.command.Main -C "$OUT/classes" .

cat > "$OUT/dx" <<EOF
#!/bin/sh
exec $JDK/bin/java -Xmx1024M -jar $OUT/dx.jar "\$@"
EOF
chmod 755 "$OUT/dx"

ls -la "$OUT/dx.jar" "$OUT/dx"
echo "=== dx smoke test ==="
"$OUT/dx" --version
