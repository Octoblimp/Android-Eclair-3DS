#!/bin/bash
# Build framework.jar -- stage 4 of the framework.jar plan
# (docs/HANDOFF.md "Immediate next steps" item 3). This is the
# `com.android.internal.os.ZygoteInit`-containing jar that app_process's
# gRegJNI[]/native-registration wall (see "framework.jar wall, pinpointed
# exactly" in HANDOFF.md) has been blocked on since Phase 6 started.
#
# Mirrors build_core_jar.sh's javac+dx pattern (JDK 8, -source/-target 6,
# same reasoning: OpenJDK 6 isn't packaged for modern Ubuntu, 8 is the last
# JVM that accepts -target 6), but with -bootclasspath core.jar instead of
# empty (this is NOT a core library the way core.jar is -- it can and does
# reference java.lang.*/java.util.* etc normally) and with:
#   - AIDL-generated Java stubs for every real .aidl file under the ten
#     FRAMEWORKS_BASE_SUBDIRS (build/core/pathmap.mk), run through the aidl
#     built in scripts/build_aidl.sh
#   - android/R.java + android/Manifest.java + com/android/internal/R.java
#     from scripts/build_framework_res.sh (stage 3)
#
# DEFERRED (not compiled), each for a real reason, not laziness -- see the
# EXCLUDE_PATTERNS block below for the exact grep patterns and rationale.
# **None of this is permanent.** The user has stated intent to implement
# both a PICA200 GPU driver + real OpenGL ES, and a real WebKit engine,
# after userspace/boot-to-home-screen (Phase 6) is done. Every GL- and
# WebKit-touching removal/deferral in this script and in the source patches
# it depends on (Canvas.java, ViewRoot.java, Linkify.java, Browser.java) is
# scaffolding to unblock the current goal, not an architectural decision --
# restore each one (and the android.webkit package + the WebKit-only
# android.net.http backend cluster + org.bouncycastle-backed SSL cert
# handling, all deferred below) together with the driver/engine that backs
# it. See docs/SCOPE.md.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"

AIDL="${ANDROID3DS_ROOT}"/build/aidl/aidl
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
# NOT build/core/core.jar -- that's the dex-wrapped jar meant for Dalvik's
# own bootclasspath (see build_core_jar.sh's final step). javac needs real
# .class files, which is classes.jar, built one step earlier in that script.
CORE_CLASSES_JAR="${ANDROID3DS_ROOT}"/build/core/classes.jar
FWRES="${ANDROID3DS_ROOT}"/build/framework_res
OUT="${ANDROID3DS_ROOT}"/build/framework_jar
LOG="${ANDROID3DS_ROOT}"/build_framework_jar.log

DIRS="core/java graphics/java location/java media/java opengl/java sax/java telephony/java wifi/java vpn/java keystore/java"

rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/aidl_gen"

# --- 1. Collect the real .java source list, minus deferred files -----------
#
# org/mobilecontrol/%: upstream's OWN filter (see frameworks/base/Android.mk
# "TODO: Move SyncML into its own library") -- not our decision.
#
# junit.framework: JUnit test framework. Never needed in a production boot
# image; these are test-support classes (e.g. TestSuiteBuilder), not
# anything ZygoteInit/SystemServer touches.
#
# org.apache.http/commons: NOT excluded, see step 1b below -- the first pass
# at this script excluded all org.apache.* wholesale and that was wrong.
# org.apache.harmony.* (ddmc, xml, xnet.provider.jsse, luni.internal.util)
# is dalvik/libcore's OWN internal implementation -- already compiled into
# core.jar/classes.jar, and it's what Settings/Debug/DatabaseUtils/Xml/
# ActivityThread/TimeUtils/Checkin/DdmRegister actually needed (confirmed
# by reading each file: one import line each, all org.apache.harmony.*).
# Those are load-bearing classes referenced by hundreds of other files, so
# wholesale-excluding them cascaded into ~1300 bogus "cannot find symbol"
# errors on the first attempt. The genuinely-external part was much
# narrower: org.apache.commons.codec (Base64/Hex, used by Settings/
# DatabaseUtils/Checkin) and org.apache.http itself (AndroidHttpClient and
# friends) -- both real gaps, but both small and self-contained, so fetched
# from platform/external/apache-http @ eclair-release (394 files, no
# further external deps) instead of deferring ~45 files.
#
# org.bouncycastle.*: SSL certificate helpers (SslCertificate,
# DomainNameChecker, CertTool, CacheManager, LocalTransport).  An earlier
# pass recorded these as deferred-not-vendored because real BouncyCastle was
# too large a fetch.  That was never true of this tree:
# dalvik/libcore/security/src/main/java/org/bouncycastle holds 472 .java
# files that build_core_jar.sh already compiles, so the -bootclasspath handed
# to javac below has carried org.bouncycastle all along and SslCertificate
# and DomainNameChecker have been compiling into framework.jar the whole
# time.  Nothing is excluded for BouncyCastle's sake.
#
# org.ccil.cowan.tagsoup: exactly one file, android/text/Html.java (HTML ->
# Spanned conversion). Narrow, leaf utility; not on the boot path.
#
# The complete Eclair EGL/GLES Java surface is required.  Android3DS now
# builds libagl, restores the stock EGLImpl/GLImpl JNI registrations and has
# a hardware-qualified PICA kernel boundary.  Excluding these classes breaks
# established applications (including GPU-Z) at compile time and would break
# their runtime ABI even if an application carried compile-only stubs.
EXCLUDE_GREP='^import (org\.ccil|com\.google\.wireless\.gdata2?)\.'

# There are no path-based exclusions any more.  core/java/android/webkit/ was
# held out while libwebcore.a existed but nothing registered it: the Java API
# would have been present with no natives behind it and WebViewCore's class
# initialiser would have thrown UnsatisfiedLinkError on first touch.  The
# engine is linked into app_process now and registered from gRegJNI[] as
# android::register_android_webkit_WebCore, so the whole package compiles
# again.  Ordering note for anyone re-treading this: the jar has to ship
# BEFORE gRegJNI[] names that registration, because startReg() FindClass's
# android/webkit/WebViewCore -- get it backwards and zygote exits 0 in
# silence, see [[project_gregjni_order_is_load_bearing]].

ALL_SRCS="$OUT/all_srcs.txt"
: > "$ALL_SRCS"
for d in $DIRS; do
    find "$FWBASE/$d" -name "*.java" -not -path "*org/mobilecontrol*" >> "$ALL_SRCS"
done
# N3DS_CONFIG_NDEBUG (#324): back to the release variant.  The debug one
# (below) kept every framework LOGV/DEBUG_* path live: ViewRoot built and
# logged a "Drawing:" line per frame, ActivityThread three lines per
# broadcast, BatteryStats one a second -- all written to logcat.txt on the
# SD card.  Debug a single class with its own DEBUG_* constant instead.
find "$FWBASE/core/config/ndebug" -name "*.java" >> "$ALL_SRCS"
# 2026-08-04 (later session): was core/config/ndebug (ConfigBuildFlags.DEBUG
# = false). That's the single switch behind android.util.Config.DEBUG, which
# every file's "LOCAL_LOGV = Config.LOGV || false"-style constant ultimately
# derives from -- so it silently kept a second, framework-wide layer of
# LOGV/DEBUG_* gates closed even after AndroidConfig.h's NDEBUG was fixed.
# Flipped to the "debug" variant (DEBUG = true) as part of turning all
# debugging back on. Needs a framework.jar (and therefore services.jar)
# rebuild to take effect.

# org.apache.http/commons.codec/commons.logging -- see EXCLUDE_GREP comment
# below for why this is vendored rather than deferred.
APACHE_HTTP="${ANDROID3DS_ROOT}"/third_party/apache-http
find "$APACHE_HTTP/src" -name "*.java" >> "$ALL_SRCS"

# Cascade files: don't themselves match EXCLUDE_GREP (no
# matching import line, or same-package so no import needed at all), but
# reference a type from an already-excluded file, so they fail to compile
# too. Found by iterating real javac errors, not guessed up front:
#   - EditStyledText.java, SuggestionsAdapter.java (+ SearchDialog.java,
#     which needs SuggestionsAdapter), Gmail.java: android.text.Html
#     (org.ccil.cowan.tagsoup, deferred -- real HTML tokenizing, not a
#     narrow-fixable Assert-style usage like Layout.java/Proxy.java were).
#     None of these are on the boot-to-home-screen path (rich-text editing
#     widget, search-suggestions UI, a content provider for a Gmail app that
#     doesn't exist in this build).
#   - RecurrenceSet.java: android.provider.Calendar (imports gdata2, deferred)
#   - SSLCertificateSocketFactory.java and GoogleWebContentHelper.java were
#     both listed here too, the first blamed on org.bouncycastle and the
#     second on android.webkit.  Neither reason survives -- bouncycastle was
#     never missing and webkit is back -- so both compile now.
#   - SearchDialogWrapper.java, SearchManagerService.java: cascade from
#     SearchDialog.java above (SuggestionsAdapter -> Html -> org.ccil).
#   - The GL debug wrappers are intentionally retained with the rest of the
#     complete EGL/GLES Java API.
#
# Browser.java and Linkify.java were ALSO in this cascade list originally
# (both needed android.webkit -- WebIconDatabase and WebView.findAddress()
# respectively) but got narrow source patches instead of deferral, since
# TextView itself calls Linkify.addLinks() and URLSpan needs
# Browser.EXTRA_APPLICATION_ID -- both too load-bearing to cut.  Those two
# patches came out again with this change; both files are stock.
#   - The android/net/http/ cluster (Connection, ConnectionThread,
#     RequestQueue, RequestHandle, RequestFeeder, EventHandler,
#     LoggingEventHandler, CertificateChainValidator,
#     CertificateValidatorCache, HttpConnection, HttpsConnection,
#     AndroidHttpClientConnection, IdleCache, HttpAuthHeader, Timer,
#     Headers, CharArrayBuffers, Request, SslError) is WebKit's OWN legacy
#     HTTP backend -- RequestHandle imports android.webkit.CookieManager --
#     and was deferred for exactly as long as android.webkit was.  It is
#     back, and it is the code WebCore's resource loader actually calls:
#     without it the engine links but cannot fetch a page.  Unrelated to
#     AndroidHttpClient.java and HttpLog.java, which were never excluded.
EXCLUDE_EXTRA_FILES="
core/java/com/android/internal/widget/EditStyledText.java
core/java/android/pim/RecurrenceSet.java
core/java/android/app/SuggestionsAdapter.java
core/java/android/app/SearchDialog.java
core/java/android/server/search/SearchDialogWrapper.java
core/java/android/server/search/SearchManagerService.java
core/java/android/provider/Gmail.java
"

EXCLUDED="$OUT/excluded_srcs.txt"
{ grep -lE "$EXCLUDE_GREP" $(cat "$ALL_SRCS") || true; \
  for f in $EXCLUDE_EXTRA_FILES; do echo "$FWBASE/$f"; done; \
} | sort -u > "$EXCLUDED"

SRCS="$OUT/sources.txt"
grep -vFf "$EXCLUDED" "$ALL_SRCS" > "$SRCS" || cp "$ALL_SRCS" "$SRCS"

echo "total .java found: $(wc -l < "$ALL_SRCS")"
echo "deferred (excluded): $(wc -l < "$EXCLUDED")"
echo "compiling: $(wc -l < "$SRCS")"

# --- 2. Generate AIDL stubs for every real .aidl file under these dirs ------
AIDL_INCLUDES=""
for d in $DIRS; do
    AIDL_INCLUDES="$AIDL_INCLUDES -I$FWBASE/$d"
done

AIDL_COUNT=0
AIDL_FAIL=0
for d in $DIRS; do
    while IFS= read -r f; do
        # This source snapshot contains a stale duplicate with the wrong
        # filename: IInputConnectionCallback.aidl declares
        # IInputMethodCallback (which is already correctly declared by
        # IInputMethodCallback.aidl) and imports the long-removed
        # TextBoxAttribute.  It cannot generate an IInputConnectionCallback
        # and compiling it only creates a duplicate interface, so skip it
        # explicitly and require every real AIDL input below to succeed.
        if [ "$f" = "$FWBASE/core/java/com/android/internal/view/IInputConnectionCallback.aidl" ]; then
            echo "  aidl SKIP stale duplicate: $f"
            continue
        fi
        rel=$(echo "$f" | sed "s#^$FWBASE/$d/##; s#\.aidl\$#.java#")
        outjava="$OUT/aidl_gen/$rel"
        mkdir -p "$(dirname "$outjava")"
        if "$AIDL" $AIDL_INCLUDES "$f" "$outjava" > "$OUT/aidl_gen.log" 2>&1; then
            AIDL_COUNT=$((AIDL_COUNT+1))
            # Plain "parcelable Foo;" declaration files (no interface body)
            # produce no .java -- they exist only so other .aidl files can
            # import the type. Only queue real generated output.
            if [ -s "$outjava" ]; then
                echo "$outjava" >> "$SRCS"
            fi
        else
            AIDL_FAIL=$((AIDL_FAIL+1))
            echo "  aidl FAILED: $f"
            cat "$OUT/aidl_gen.log"
        fi
    done < <(find "$FWBASE/$d" -name "*.aidl")
done
echo "aidl: $AIDL_COUNT generated, $AIDL_FAIL failed"
if [ "$AIDL_FAIL" -ne 0 ]; then
    echo "FATAL: one or more required AIDL interfaces failed to generate" >&2
    exit 1
fi

# --- 3. Add stage-3's R.java/Manifest.java ----------------------------------
find "$FWRES/gen" -name "*.java" >> "$SRCS"

echo "final source count: $(wc -l < "$SRCS")"

# --- 4. Compile ---------------------------------------------------------
set +e
"$JAVAC" -J-Xmx3g -source 6 -target 6 -nowarn -encoding UTF-8 \
    -bootclasspath "$CORE_CLASSES_JAR" \
    -Xmaxerrs 100000 \
    -d "$OUT/classes" \
    @"$SRCS" > "$LOG" 2>&1
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
    grep -B1 -A2 "error:" "$LOG" | head -100
    exit 1
fi

echo "=== javac clean, $(find "$OUT/classes" -name '*.class' | wc -l) classes ==="

# --- 5. Package + dex, same pattern as build_core_jar.sh --------------------
JAR="$JDK/bin/jar"
DX="${ANDROID3DS_ROOT}"/build/dx/dx

# Resource files ship alongside classes.dex in the real Android.mk build via
# LOCAL_JAVA_RESOURCE_FILES.  In particular, ZygoteInit asks its boot-class
# loader for the root resource "preloaded-classes".  A preload is executable
# code: Class.forName(..., true, ...) runs static initializers.  Do not preload
# subsystems whose native libraries/JNI registrations are deliberately absent
# from this Phase-6 image:
#   - Bluetooth (the 3DS has no Bluetooth hardware)
#   - media/speech-recognition (libmedia_jni/srec_jni are not ported yet)
#   - OpenGL (no PICA200 GLES driver or GLES JNI bridge yet)
#
# Also omit stock entries which are not present in either the built core.jar
# class set or this framework build.  This removes source packages deliberately
# deferred above (WebKit, TagSoup, BouncyCastle helpers, etc.) instead of making
# every zygote boot rediscover them as ClassNotFoundException noise.
PRELOAD_RESOURCE="$OUT/preloaded-classes"
PRELOAD_CLASSES="$OUT/preload-available-classes.txt"
PRELOAD_MISSING="$OUT/preloaded-classes.omitted-missing"
PRELOAD_UNSUPPORTED_RE='^(android[.]bluetooth[.]|android[.]server[.]Bluetooth|android[.]media[.]|android[.]speech[.]srec[.]|android[.]opengl[.]|com[.]android[.]internal[.]location[.]GpsLocationProvider$)'

{
    "$JAR" tf "$CORE_CLASSES_JAR" | sed -n 's#/#.#g; s#\.class$##p'
    find "$OUT/classes" -name '*.class' -printf '%P\n' \
        | sed 's#/#.#g; s#\.class$##'
} | sort -u > "$PRELOAD_CLASSES"
: > "$PRELOAD_MISSING"

awk -v unsupported="$PRELOAD_UNSUPPORTED_RE" -v missing="$PRELOAD_MISSING" '
    NR == FNR { available[$0] = 1; next }
    /^#/ { print; next }
    $0 ~ unsupported { next }
    available[$0] { print; next }
    { print > missing }
' "$PRELOAD_CLASSES" "$FWBASE/preloaded-classes" > "$PRELOAD_RESOURCE"
test -s "$PRELOAD_RESOURCE"
if grep -Eq "$PRELOAD_UNSUPPORTED_RE" "$PRELOAD_RESOURCE"; then
    echo "FATAL: unsupported native subsystem survived the preload filter" >&2
    exit 1
fi
echo "=== preload set: $(grep -vc '^#' "$PRELOAD_RESOURCE") retained, $(wc -l < "$PRELOAD_MISSING") unavailable omitted ==="

echo "=== packaging classes.jar ==="
"$JAR" cf "$OUT/classes.jar" -C "$OUT/classes" .
ls -la "$OUT/classes.jar"

echo "=== dx --dex --core-library ==="
# --core-library: framework.jar's own Android.mk sets LOCAL_DX_FLAGS :=
# --core-library too (it implements some java.*-adjacent extension points),
# same reasoning as core.jar's own dx invocation.
"$DX" --dex --core-library --output="$OUT/classes.dex" "$OUT/classes.jar"
ls -la "$OUT/classes.dex"

echo "=== framework.jar ==="
( cd "$OUT" && "$JAR" cf framework.jar classes.dex && \
    "$JAR" uf framework.jar preloaded-classes )
ls -la "$OUT/framework.jar"
echo "=== framework.jar preload resource ==="
"$JAR" tf "$OUT/framework.jar" | grep -x "preloaded-classes" \
    || { echo "FATAL: framework.jar is missing preloaded-classes" >&2; exit 1; }
"$JAR" xf "$OUT/framework.jar" preloaded-classes
if grep -Eq "$PRELOAD_UNSUPPORTED_RE" "$OUT/preloaded-classes"; then
    echo "FATAL: packaged preload resource still contains an unsupported native subsystem" >&2
    exit 1
fi
