#!/usr/bin/env python3
"""Build the AOSP Eclair WebKit engine from the captured Android make graph.

The old Android build core and arm-eabi-4.4 prebuilt toolchain are not part of
this repository.  ``webkit_commands.sh`` is the deterministic ``make -n``
command graph captured from the matching Eclair tree; this driver applies the
small Android3DS toolchain substitutions in one reviewable place and executes
the result from the canonical source root.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "scripts" / "webkit_commands.sh"
GENERATED = ROOT / "build" / "webkit_driver" / "commands.sh"
STATIC_ARCHIVE = ROOT / "build" / "webkit_intermediates" / "libwebcore.a"
LIBXML2_ARCHIVE = ROOT / "build" / "libxml2_webkit" / "libxml2.a"
REGISTRATION_OBJECT = (
    ROOT
    / "build"
    / "webkit_intermediates"
    / "WebKit/android/jni/WebCoreJniRegistration.o"
)
# WebCoreJniOnLoad.o was archived here while the thirteen JNI
# registrations still hung off JNI_OnLoad.  It defines nothing else, and
# that JNI_OnLoad is a second definition of the one in
# libjavacore.a(sql__sqlite_jni.o), so a build that finds the object left
# over from before WebCoreJniRegistration.cpp existed evicts it rather
# than leaving a duplicate symbol one -u flag away from breaking the link.
STALE_MEMBER = "WebCoreJniOnLoad.o"
LOG = ROOT / "build_webkit.log"
AR = (
    ROOT
    / "toolchain"
    / "armv6-eabihf--glibc--stable-2025.08-1"
    / "bin"
    / "arm-buildroot-linux-gnueabihf-ar"
)


COMPILE_OUTPUT = re.compile(
    r" -o (build/webkit_intermediates/\S+\.o) (\S+)$"
)


# Puts back the `__inline` gperf stopped emitting after 3.0.  Anchored on the
# return-type line, which gperf writes on its own directly above the function
# name and which appears exactly once in the output.  A string comparison, not
# a regex, so the `*` needs no quoting through two layers of shell.
INLINE_LOOKUP = (
    "awk '"
    "BEGIN { done = 0 } "
    'done == 0 && $0 == "const struct Entity *" { '
    'print "#ifdef __GNUC__"; print "__inline"; '
    'print "#ifdef __GNUC_STDC_INLINE__"; '
    'print "__attribute__ ((__gnu_inline__))"; '
    'print "#endif"; print "#endif"; done = 1 } '
    "{ print }'"
)


# N3DS_WEBKIT_SK_DEBUG: the captured graph compiles every WebKit TU with
# -DSK_RELEASE, as AOSP did -- but there NDEBUG was global, so Skia itself was
# release too.  Here AndroidConfig.h deliberately leaves NDEBUG undefined, so
# libskia.a, libandroid_runtime and bootanimation are all SK_DEBUG, and under
# SK_DEBUG several Skia classes grow debug-only members (SkString::fStr,
# SkTDArray::fData, SkBitmap's two lock counters, SkShader::fInSession,
# SkAutoTArray::fCount).  WebKit therefore laid out every one of those objects
# smaller than the Skia code that constructs and validates them: on hardware,
# 2026-09-30, SkString::validate() failed `fStr == c_str()` inside
# WebViewCoreThread and sk_throw() wrote 0xbbadbeef.  WebKit joins the rest of
# the tree rather than the other way round, which would mean rebuilding Skia
# and every proven consumer of it.  WebKit's own NDEBUG stays as captured.
SK_RELEASE_FLAG = " -DSK_RELEASE "
SK_DEBUG_FLAG = " -DSK_DEBUG "
# N3DS_WEBKIT_HARD_FLOAT: every captured compile carries Eclair's global
# -msoft-float.  The 2009 arm-eabi toolchain had no hard-float ABI, so there
# it only meant "no VFP instructions"; on this arm-buildroot-linux-gnueabihf
# GCC it selects -mfloat-abi=soft, a different calling convention from the
# rest of the tree.  WebKit then passed every SkScalar to Skia in r1/r2 while
# Skia read s0/s1, and read every float Skia returned from r0: on 2026-09-30
# (#322) PictureSet::draw's canvas->translate(0, 0) arrived as (240, 3.7),
# SkPaint::measureText() came back as junk, and every page drew shifted and
# without text -- the "pages don't render" of #321 and #322.  app_process
# links with --no-warn-mismatch, so the linker never said so.  Dropping the
# flag makes WebKit use the toolchain's hard-float default like everything
# else; the four scalar-FP JNI entries already carry pcs("aapcs").
SOFT_FLOAT_FLAG = " -msoft-float"
FLAGS_STAMP = ROOT / "build" / "webkit_intermediates" / "N3DS_FLAGS"
FLAGS_STAMP_TEXT = ("N3DS_WEBKIT_SK_DEBUG N3DS_WEBKIT_UB_FLAGS "
                    "N3DS_STL_BYVALUE_COMPARATOR N3DS_WEBKIT_HARD_FLOAT "
                    "N3DS_WEBKIT_QUIET_NOTIMPL\n")
# N3DS_WEBKIT_QUIET_NOTIMPL (#326): notImplemented() printed to stderr, which
# app_process sends to the top-screen console.  NotImplemented.h is a header,
# so like the STL fix the stamp forces the clean rebuild that reaches every
# file using it.
NOT_IMPLEMENTED_H = (ROOT / "third_party" / "webkit" / "WebCore" / "platform"
                     / "NotImplemented.h")
# N3DS_STL_BYVALUE_COMPARATOR: WebKit/android/stl/algorithm is a header, and
# an incremental build keys on .cpp mtimes, so the stamp forces the clean
# rebuild that recompiles every user of the fixed stable_sort overload.
STL_ALGORITHM = ROOT / "third_party" / "webkit" / "WebKit" / "android" / "stl" / "algorithm"
# N3DS_WEBKIT_UB_FLAGS: the compiler wrappers must keep GCC 14 from
# optimising on assumptions the 2009 sources never made (see webkit_gxx.sh).
WRAPPER_FLAGS = {
    ROOT / "scripts" / "webkit_gxx.sh": (
        "-fno-delete-null-pointer-checks", "-fno-lifetime-dse", "-fwrapv"),
    ROOT / "scripts" / "webkit_gcc.sh": (
        "-fno-delete-null-pointer-checks", "-fwrapv"),
}

# N3DS_WEBKIT_PARALLEL: the graph is ~1170 independent compiles run one at a
# time.  With --jobs N each compile+dependency-copy pair runs in the
# background, at most N at once; every other command (generators, ar) first
# waits for all of them, so anything that consumes an object still sees it.
# Background failures cannot trip `set -e`, so they leave a marker instead.
PARALLEL_PRELUDE = (
    'N3DS_FAIL=build/webkit_driver/compile.failed',
    'rm -f "$N3DS_FAIL"',
    'n3ds_throttle() { while [ "$(jobs -rp | wc -l)" -ge "$N3DS_JOBS" ]; '
    'do wait -n || true; done; }',
    'n3ds_barrier() { wait; if [ -e "$N3DS_FAIL" ]; then '
    'echo "build_webkit: a parallel compile failed; see the log above" >&2; '
    'exit 1; fi; }',
)


def background_compile(compile_line: str, dependency_line: str) -> list[str]:
    return [
        "n3ds_throttle",
        "{ ( %s ) && ( %s ); } || : > \"$N3DS_FAIL\" &"
        % (compile_line, dependency_line),
    ]


def render_commands(source: str, incremental: bool, jobs: int = 1) -> str:
    gxx = ROOT / "scripts" / "webkit_gxx.sh"
    gcc = ROOT / "scripts" / "webkit_gcc.sh"
    lines = source.splitlines()
    rendered: list[str] = []
    registration_compile: str | None = None
    parallel = jobs > 1
    index = 0
    while index < len(lines):
        line = lines[index].replace(SK_RELEASE_FLAG, SK_DEBUG_FLAG).replace(
            SOFT_FLOAT_FLAG, "")
        if parallel and index == 1:
            # Right after the shebang, before the graph's own `set -e`.
            rendered.append("N3DS_JOBS=%d" % jobs)
            rendered.extend(PARALLEL_PRELUDE)
        if line.startswith("GXX="):
            line = f'GXX="{gxx}"'
        elif line.startswith("GCC="):
            line = f'GCC="{gcc}"'
        elif line.startswith("AR="):
            line = f'AR="{AR}"'
        elif "prebuilt/linux-x86/toolchain/arm-eabi-4.4.0/bin/arm-eabi-ar" in line:
            line = line.replace(
                "prebuilt/linux-x86/toolchain/arm-eabi-4.4.0/bin/arm-eabi-ar",
                '"$AR"',
            )
        elif "prebuilt/linux-x86/flex/flex-2.5.4a" in line:
            line = line.replace("prebuilt/linux-x86/flex/flex-2.5.4a", "flex")
        elif (line.startswith("gperf ") and " > " in line and
              line.endswith("/HTMLEntityNames.c")):
            # HTMLEntityNames.c is #include'd as source by HTMLTokenizer.cpp
            # and by PreloadScanner.cpp -- deliberately, with the comment "we
            # are getting two copies of the data.  However, this way the code
            # gets inlined."  That only holds because gperf up to 3.0 emitted
            # the lookup function as __inline; 3.3 emits it plain, so the two
            # copies became two external definitions of findEntity() inside
            # one archive and the link failed.  Put the old marker back.
            #
            # Reproducing gperf 3.0's guard exactly, rather than writing
            # `static`, keeps the standalone HTMLEntityNames.o compile
            # unchanged: that one is C, where __GNUC_STDC_INLINE__ is defined
            # and selects gnu_inline semantics, so it still emits the symbol.
            # In the two C++ includers the bare __inline gives the definition
            # vague linkage and the linker folds them.
            target = line.rsplit(" > ", 1)[1]
            line = "\n".join((
                line,
                "%s %s > %s.inline" % (INLINE_LOOKUP, target, target),
                "mv %s.inline %s" % (target, target),
            ))
        elif (line.startswith("cat build/webkit_intermediates/") and
              ".hpp >> " in line and line.endswith("Grammar.h")):
            # The captured graph builds Grammar.h as "include guard + bison's
            # -d header + #endif".  Bison 2.x emitted no function prototypes
            # there; 3.8 emits `int cssyyparse (void* parser);`, and
            # CSSParser.cpp includes this header from inside namespace WebCore
            # to get the token enum.  That would declare WebCore::cssyyparse
            # and leave every call site after the include needing a symbol
            # CSSGrammar.cpp never defines -- it defines the global one that
            # CSSParser.cpp already declared at file scope.  Strip the line.
            header, target = line[len("cat "):].split(" >> ", 1)
            line = "sed '/^int [a-z]*yyparse /d' %s >> %s" % (header, target)
        elif (line.startswith("rm -f build/webkit_intermediates/") and
              line.endswith("Grammar.hpp")):
            # Bison 3.8 makes the generated .cpp include this .hpp.  Eclair's
            # captured graph folded the old tool's header into Grammar.h and
            # deleted the intermediate name, which now breaks compilation.
            line = f'test -s "{line[len("rm -f "):]}"'
        output = COMPILE_OUTPUT.search(line)
        if (output and output.group(1).endswith("WebCoreJni.o") and
                output.group(2).endswith("WebCoreJni.cpp")):
            registration_compile = line.replace(
                "WebCoreJni.o", "WebCoreJniRegistration.o"
            ).replace("WebCoreJni.cpp", "WebCoreJniRegistration.cpp")
        dependency_line = (
            lines[index + 1] if output and index + 1 < len(lines) else ""
        )
        if (output and (incremental or parallel) and
                dependency_line.startswith("cp ") and ".d " in dependency_line):
            body = (background_compile(line, dependency_line) if parallel
                    else [line, dependency_line])
            if incremental:
                rendered.append(
                    f'if [ ! -s "{output.group(1)}" ] || '
                    f'[ "{output.group(2)}" -nt "{output.group(1)}" ]; then'
                )
                rendered.extend("  " + step for step in body)
                rendered.append("fi")
            else:
                rendered.extend(body)
            index += 2
            continue
        if parallel and index > 0 and line.strip() and not line.startswith("mkdir "):
            rendered.append("n3ds_barrier")
        rendered.append(line)
        index += 1
    if parallel:
        rendered.append("n3ds_barrier")
    if registration_compile is None:
        raise ValueError("captured WebKit graph has no WebCoreJni compile template")
    registration_output = (
        "build/webkit_intermediates/WebKit/android/jni/WebCoreJniRegistration.o"
    )
    registration_source = (
        "third_party/webkit/WebKit/android/jni/WebCoreJniRegistration.cpp"
    )
    rendered.extend((
        f'if [ ! -s "{registration_output}" ] || '
        f'[ "{registration_source}" -nt "{registration_output}" ]; then',
        "  " + registration_compile,
        "fi",
        f'"$AR" rcs build/webkit_intermediates/libwebcore.a "{registration_output}"',
    ))
    return "\n".join(rendered) + "\n"


def soft_float_members(archive: Path) -> list[str]:
    """N3DS_WEBKIT_HARD_FLOAT: compiler-made members not on the VFP ABI.

    GCC writes Tag_ABI_enum_size into every C/C++ object, and under the
    hard-float ABI also Tag_ABI_VFP_args: VFP registers.  Hand-written
    assembly carries neither tag, so it is not counted.
    """
    readelf = AR.with_name(AR.name[:-len("ar")] + "readelf")
    out = subprocess.check_output(
        [str(readelf), "-A", str(archive)], text=True,
        stderr=subprocess.DEVNULL)
    soft: list[str] = []
    member, compiled, vfp = None, False, False
    for line in out.splitlines() + ["File: <end>"]:
        if line.startswith("File: "):
            if member is not None and compiled and not vfp:
                soft.append(member)
            member, compiled, vfp = line[len("File: "):], False, False
        elif "Tag_ABI_enum_size" in line:
            compiled = True
        elif "Tag_ABI_VFP_args: VFP registers" in line:
            vfp = True
    return soft


def require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"build_webkit: required file is missing: {path}")


def parse_jobs(argv: list[str]) -> int:
    for index, arg in enumerate(argv):
        if arg.startswith("--jobs="):
            return max(1, int(arg.split("=", 1)[1]))
        if arg in ("--jobs", "-j") and index + 1 < len(argv):
            return max(1, int(argv[index + 1]))
    return 1


def main() -> int:
    incremental = "--clean" not in sys.argv[1:]
    jobs = parse_jobs(sys.argv[1:])
    # N3DS_WEBKIT_SK_DEBUG: an incremental build only recompiles sources
    # newer than their objects, so a flag change alone would rebuild nothing
    # and leave SK_RELEASE objects in the archive.  The stamp records which
    # Skia mode the intermediates were built for.
    if incremental and (
            not FLAGS_STAMP.is_file() or
            FLAGS_STAMP.read_text(encoding="utf-8") != FLAGS_STAMP_TEXT):
        print("build_webkit: intermediates predate " + FLAGS_STAMP_TEXT.strip()
              + "; rebuilding clean")
        incremental = False
    for wrapper, flags in WRAPPER_FLAGS.items():
        require_file(wrapper)
        text = wrapper.read_text(encoding="utf-8")
        missing = [flag for flag in flags if flag not in text]
        if missing:
            raise SystemExit(
                f"build_webkit: {wrapper.name} lacks {' '.join(missing)} -- "
                "GCC would delete Skia's safeRef() NULL test (the #316 "
                "Browser crash)"
            )
    require_file(STL_ALGORITHM)
    if "N3DS_STL_BYVALUE_COMPARATOR" not in STL_ALGORITHM.read_text(
            encoding="utf-8", errors="replace"):
        raise SystemExit(
            "build_webkit: WebKit/android/stl/algorithm still casts by-value "
            "comparators to by-reference (the #317 compareZIndex crash)"
        )
    require_file(NOT_IMPLEMENTED_H)
    if "N3DS_WEBKIT_QUIET_NOTIMPL" not in NOT_IMPLEMENTED_H.read_text(
            encoding="utf-8", errors="replace"):
        raise SystemExit(
            "build_webkit: NotImplemented.h still prints notImplemented() to "
            "stderr (the top-screen setCursor lines)"
        )
    require_file(COMMANDS)
    require_file(ROOT / "third_party" / "webkit" / "Android.jsc.mk")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "patch_webkit_modern_toolchain.py"),
            str(ROOT / "third_party" / "webkit"),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "build_libxml2_webkit.sh")],
        cwd=ROOT,
        check=True,
    )
    require_file(LIBXML2_ARCHIVE)
    if not incremental:
        shutil.rmtree(ROOT / "build" / "webkit_intermediates", ignore_errors=True)
    GENERATED.parent.mkdir(parents=True, exist_ok=True)
    GENERATED.write_text(
        render_commands(COMMANDS.read_text(), incremental=incremental,
                        jobs=jobs),
        encoding="utf-8",
    )
    GENERATED.chmod(GENERATED.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    with LOG.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            ["bash", str(GENERATED)],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    if completed.returncode:
        lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        errors = [line for line in lines if "error:" in line.lower()][-20:]
        print(f"build_webkit: failed; errors and tail from {LOG}", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        for line in lines[-60:]:
            print(line, file=sys.stderr)
        return completed.returncode
    require_file(STATIC_ARCHIVE)
    require_file(REGISTRATION_OBJECT)
    members = subprocess.check_output(
        [str(AR), "t", str(STATIC_ARCHIVE)], text=True
    ).splitlines()
    if "WebCoreJniRegistration.o" not in members:
        raise SystemExit(
            "build_webkit: static archive lacks WebCoreJniRegistration.o"
        )
    # N3DS_WEBKIT_SK_DEBUG: prove the objects, not just the command line.
    # SkToU8/SkToU16 are out-of-line functions only under SK_DEBUG (macros
    # otherwise), so an SK_RELEASE build of WebKit never references them.
    undefined = subprocess.check_output(
        [str(AR.with_name(AR.name[:-len("ar")] + "nm")), "-u",
         str(STATIC_ARCHIVE)],
        text=True, stderr=subprocess.DEVNULL,
    )
    if not re.search(r"\b_Z6SkToU8j\b|\b_Z7SkToU16j\b", undefined):
        raise SystemExit(
            "build_webkit: libwebcore.a references no SK_DEBUG-only Skia "
            "helper -- WebKit was built SK_RELEASE against an SK_DEBUG "
            "libskia.a, which mislays SkString/SkBitmap/SkTDArray"
        )
    # N3DS_STL_BYVALUE_COMPARATOR: compareZIndex takes RenderLayer* by value,
    # so the merge sort instantiated for it must take the comparator the same
    # way.  The broken header produced only the RenderLayer* const& flavour.
    defined = subprocess.check_output(
        [str(AR.with_name(AR.name[:-len("ar")] + "nm")), "-C",
         "--defined-only", str(STATIC_ARCHIVE)],
        text=True, stderr=subprocess.DEVNULL,
    )
    zorder_sorts = [line for line in defined.splitlines()
                    if "stable_sort<WebCore::RenderLayer*>" in line]
    if not zorder_sorts or any("RenderLayer* const&" in line
                               for line in zorder_sorts):
        raise SystemExit(
            "build_webkit: stable_sort<RenderLayer*> is missing or still calls "
            "compareZIndex through a by-reference type:\n  "
            + "\n  ".join(zorder_sorts)
        )
    # N3DS_WEBKIT_HARD_FLOAT: app_process links with --no-warn-mismatch, so
    # nothing downstream would notice a soft-float object coming back.
    for archive in (STATIC_ARCHIVE, LIBXML2_ARCHIVE):
        soft = soft_float_members(archive)
        if soft:
            raise SystemExit(
                f"build_webkit: {len(soft)} member(s) of {archive.name} use "
                "the soft-float calling convention; every SkScalar crossing "
                "into hard-float Skia would be read from the wrong "
                "registers:\n  " + "\n  ".join(soft[:10]))
    FLAGS_STAMP.write_text(FLAGS_STAMP_TEXT, encoding="utf-8")
    if STALE_MEMBER in members:
        subprocess.run([str(AR), "d", str(STATIC_ARCHIVE), STALE_MEMBER], check=True)
        print(f"build_webkit: evicted stale {STALE_MEMBER} from the archive")
    subprocess.run(["file", str(STATIC_ARCHIVE)], check=True)
    print(f"build_webkit: static engine archive ready: {STATIC_ARCHIVE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
