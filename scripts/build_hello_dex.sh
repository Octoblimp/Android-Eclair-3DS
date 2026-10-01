#!/bin/bash
# Build /system/framework/hello.jar -- a real Java class for Dalvik to run.
#
# As of the 2026-08-03 16:07 boot the VM initialises completely and stops with
# "Dalvik VM requires a class name", which dvmMain() prints *after* startup
# succeeds. Everything under it works: core.jar is accepted, dexopt produces an
# optimised copy, and libjavacore's ~45 register_*() natives bind. The only
# thing left to prove is that it can actually execute bytecode.
#
# The class deliberately touches the layers that were hardest to get building,
# each in its own try/catch so one failure does not hide the rest:
#   - String/StringBuilder      -> core Java + the dex verifier
#   - HashMap                   -> generics, hashing, java.util
#   - Math.sqrt                 -> fdlibm
#   - toUpperCase, isLetter     -> ICU4C via com.ibm.icu4jni
#   - System.getProperty        -> the VM's own property table
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JAVA_HOME/bin/javac"
BUILD="${ANDROID3DS_ROOT}"/build
# core.jar holds a classes.dex, which javac cannot read. build_core_jar.sh also
# leaves the pre-dex .class files in classes.jar -- that is the bootclasspath.
CORE="$BUILD/core/classes.jar"
DX="$BUILD/dx/dx"
OUT="$BUILD/hello"
# Deliberately NOT the shipping rootfs_overlay.  This smoketest did its job on
# 2026-08-03 -- it proved Dalvik executes real bytecode on hardware -- but the
# artifact it left in /system/framework has no pre-baked odex, so
# PackageManagerService dexopts it on every boot, installd fails to open the
# output, and PMS then prunes the whole app half of /data/dalvik-cache because
# it believes a dexopt happened.  That cost is paid on every boot forever and
# buys nothing: nothing in init.rc or any .rc/.xml/.sh references hello.jar.
# The jar lands in its own fakeroot now.  To run the smoketest again, copy it
# onto the card by hand and take the dexopt cost deliberately.
OV="$OUT/fakeroot"

rm -rf "$OUT"; mkdir -p "$OUT/src" "$OUT/classes"

cat > "$OUT/src/Hello.java" <<'EOF'
public class Hello {
    static void ok(String what, Object value) {
        System.out.println("hello: " + what + " -> " + value);
    }

    static void section(String what, Runnable body) {
        try {
            body.run();
        } catch (Throwable t) {
            System.out.println("hello: " + what + " FAILED: " + t);
        }
    }

    public static void main(String[] args) {
        System.out.println("hello: dalvik is executing java bytecode");

        section("string", new Runnable() { public void run() {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 5; i++) sb.append(i).append(',');
            ok("StringBuilder", sb.toString());
            ok("substring", "android3ds".substring(0, 7));
        }});

        section("util", new Runnable() { public void run() {
            java.util.HashMap<String, Integer> m =
                    new java.util.HashMap<String, Integer>();
            m.put("a", 1);
            m.put("b", 2);
            ok("HashMap", m.get("a") + "," + m.get("b"));
            java.util.ArrayList<String> l = new java.util.ArrayList<String>();
            l.add("x"); l.add("y");
            ok("ArrayList", l.toString());
        }});

        // The 2026-08-03 boot printed
        //     Math.sqrt(144) -> 01.6033822739252712
        // which is wrong twice over: the value should be 12, and no correctly
        // formatted double ever starts "01.". Math.cos(0) -> 1.0 was fine, so
        // the fault is isolated to either fdlibm's sqrt or the double->String
        // path. Print the raw bits and an integer cast as well: those go
        // nowhere near the formatter, so if they read 12 the arithmetic is
        // fine and the bug is in RealToString; if they do not, it is fdlibm.
        section("fdlibm", new Runnable() { public void run() {
            double s = Math.sqrt(144.0);
            ok("Math.sqrt(144) as double", Double.valueOf(s));
            ok("Math.sqrt(144) as long", Long.valueOf((long) s));
            ok("Math.sqrt(144) raw bits", Long.toHexString(
                    Double.doubleToLongBits(s)));
            ok("  (12.0 raw bits should be)", Long.toHexString(
                    Double.doubleToLongBits(12.0)));
            ok("Math.cos(0)", Double.valueOf(Math.cos(0.0)));
            ok("toString(12.0)", Double.toString(12.0));
            ok("toString(0.5)", Double.toString(0.5));
            ok("toString(1234.5)", Double.toString(1234.5));
            ok("String.format decimals", String.format(
                    java.util.Locale.US, "%.1f/%.1f",
                    new Object[] { Float.valueOf(12.25f), Float.valueOf(0.5f) }));
        }});

        section("icu", new Runnable() { public void run() {
            ok("toUpperCase", "android3ds".toUpperCase());
            ok("Character.isLetter('x')", Boolean.valueOf(Character.isLetter('x')));
        }});

        section("vm", new Runnable() { public void run() {
            ok("java.vm.version", System.getProperty("java.vm.version"));
            ok("os.arch", System.getProperty("os.arch"));
        }});

        System.out.println("hello: OK");
    }
}
EOF

echo "  JAVAC Hello.java"
# Same targeting as core.jar: Java 6 bytecode, and core.jar is the *only*
# bootclasspath -- there is no host rt.jar in this world.
"$JAVAC" -source 6 -target 6 -nowarn \
    -bootclasspath "$CORE" \
    -d "$OUT/classes" "$OUT/src/Hello.java" 2>&1 | grep -v "^Note:" || true

ls "$OUT/classes"

echo "  DX    hello.jar"
"$DX" --dex --output="$OUT/hello.jar" "$OUT/classes"

mkdir -p "$OV/system/framework"
cp "$OUT/hello.jar" "$OV/system/framework/hello.jar"
chmod 644 "$OV/system/framework/hello.jar"

ls -la "$OUT/hello.jar" "$OV/system/framework/hello.jar"
echo "  classes in the dex:"
unzip -l "$OUT/hello.jar"
