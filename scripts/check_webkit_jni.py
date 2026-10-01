#!/usr/bin/env python3
"""Check every WebKit <-> framework JNI lookup against the compiled dex.

WebKit (third_party/webkit, linked into app_process as libwebcore.a) is a
slightly later Android revision than third_party/frameworks/base.  Each JNI
lookup the engine makes by name -- GetMethodID, GetStaticMethodID,
GetFieldID, GetStaticFieldID, FindClass, the GetJMethod() wrappers, the
callJNIMethod<T>(obj, "name", "sig") helpers, and every JNINativeMethod table
handed to jniRegisterNativeMethods -- is a contract with a Java class that
only fails at run time:

  * a bad JNINativeMethod entry fails RegisterNatives for the whole class in
    the zygote ("Unable to find decl for native ..."), so zygote never starts;
  * a bad GetMethodID leaves NoSuchMethodError pending on whatever thread made
    the lookup, which is how the Browser died in BrowserFrame.nativeCreateFrame
    on "showRect" -- and every JNI call made after that with the exception
    still pending misbehaves (DeleteLocalRef warnings, null results);
  * a Java `native` method nobody registers is an UnsatisfiedLinkError the
    first time it is called: app_process is static, there is no library for
    dvmResolveNativeMethod to dlsym a Java_... symbol from.

So this runs the C preprocessor over exactly the sources build_webkit.py
compiles (the captured command graph, so #if ENABLE(...) and the string
macros resolve the way the real compile resolves them), pulls every lookup
out with its class resolved, and applies Dalvik's own lookup rules
(dalvik/vm/Jni.c) to the class_defs in core.jar + framework.jar:

  GetMethodID        virtual methods up the superclass chain, else a direct
                     (private/<init>) method of the class itself; never static
  GetStaticMethodID  direct methods up the superclass chain; must be static
  GetFieldID         instance fields up the superclass chain
  GetStaticFieldID   static fields of the class itself only (dvmFindStaticField)
  RegisterNatives    direct, then virtual, methods of the class itself; must be
                     ACC_NATIVE

and the reverse: every ACC_NATIVE method of every class WebKit registers, and
of every android/webkit/* class, must be covered by a registered entry.

Usage: check_webkit_jni.py [--framework JAR_OR_DEX] [--core JAR_OR_DEX]
                           [--inventory] [--keep-preprocessed DIR]
Defaults check build/framework_jar/classes.dex (what build_framework_jar.sh
just produced) against build/core/classes.dex.  Exit status 1 on any
mismatch.
"""

import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMANDS = os.path.join(ROOT, "scripts", "webkit_commands.sh")
GXX = os.path.join(ROOT, "scripts", "webkit_gxx.sh")
GCC = os.path.join(ROOT, "scripts", "webkit_gcc.sh")
WEBKIT_PREFIX = "third_party/webkit/"
REGISTRATION = "third_party/webkit/WebKit/android/jni/WebCoreJniRegistration.cpp"

DEFAULT_FRAMEWORK = os.path.join(ROOT, "build", "framework_jar", "classes.dex")
DEFAULT_CORE = os.path.join(ROOT, "build", "core", "classes.dex")

# Only translation units that can name a Java member are preprocessed.  The
# list is filtered from the compiled set, so a file build_webkit.py stops
# compiling drops out of the check, and a new compiled file that mentions any
# of these tokens is picked up without editing this script.
JNI_TOKENS = re.compile(
    r"\b(GetMethodID|GetStaticMethodID|GetFieldID|GetStaticFieldID|FindClass|"
    r"GetJMethod|callJNIMethod|callJNIStaticMethod|jniRegisterNativeMethods|"
    r"RegisterNatives|registerNativeMethods)\b")

ACC_STATIC = 0x0008
ACC_NATIVE = 0x0100
ACC_INTERFACE = 0x0200

# What an object passed to GetObjectClass(), or a jclass that arrives as a
# function parameter, actually is.  Keyed by (source basename, expression);
# a value of None means the class is genuinely dynamic (the JavaScript <->
# Java bridge reflecting on arbitrary objects) and the lookup is reported,
# not checked.  An unresolved expression that is NOT listed here is an error,
# so new lookups cannot slip past unexamined.
OBJECT_CLASSES = {
    ("WebViewCore.cpp", "javaWebViewCore"): "Landroid/webkit/WebViewCore;",
    ("JavaBridge.cpp", "obj"): "Landroid/webkit/JWebCoreJavaBridge;",
    ("WebCoreFrameBridge.cpp", "obj"): "Landroid/webkit/BrowserFrame;",
    # FieldIds(JNIEnv*, jclass clazz), constructed by register_websettings()
    # from FindClass("android/webkit/WebSettings").
    ("WebSettings.cpp", "clazz"): "Landroid/webkit/WebSettings;",
    # JavaScript <-> Java bridge reflection (jni_class/jni_runtime/
    # jni_instance): the receiver's class is fixed by the JDK API used.
    ("jni_class.cpp", "anInstance"): "Ljava/lang/Object;",
    ("jni_class.cpp", "aClass"): "Ljava/lang/Class;",
    ("jni_runtime.cpp", "aField"): "Ljava/lang/reflect/Field;",
    ("jni_runtime.cpp", "fieldType"): "Ljava/lang/Class;",
    ("jni_runtime.cpp", "aMethod"): "Ljava/lang/reflect/Method;",
    ("jni_runtime.cpp", "returnType"): "Ljava/lang/Class;",
    ("jni_runtime.cpp", "aParameter"): "Ljava/lang/Class;",
    ("jni_instance.cpp", "_instance->_instance"): "Ljava/lang/Object;",
    ("jni_runtime.cpp", "fieldJInstance"): None,
    ("jni_utility.cpp", "obj"): None,
}
# Same receiver expression, different receiver class per member.
MEMBER_CLASSES = {
    ("jni_instance.cpp", "_instance->_instance", "doubleValue"): "Ljava/lang/Number;",
    ("jni_instance.cpp", "_instance->_instance", "booleanValue"): "Ljava/lang/Boolean;",
}


# ---------------------------------------------------------------- dex model

def uleb128(buf, off):
    result = 0
    shift = 0
    while True:
        b = buf[off]
        off += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, off
        shift += 7


class ClassInfo(object):
    __slots__ = ("desc", "flags", "sup", "ifaces", "direct", "virtual",
                 "sfields", "ifields", "origin")

    def __init__(self, desc, flags, sup, ifaces, origin):
        self.desc = desc
        self.flags = flags
        self.sup = sup
        self.ifaces = ifaces
        self.direct = {}
        self.virtual = {}
        self.sfields = {}
        self.ifields = {}
        self.origin = origin


def read_dex_bytes(path):
    if path.endswith(".dex"):
        with open(path, "rb") as f:
            return f.read()
    with zipfile.ZipFile(path) as z:
        return z.read("classes.dex")


def parse_dex(path):
    d = read_dex_bytes(path)
    if d[:4] != b"dex\n":
        raise SystemExit("%s: not a dex file" % path)
    (_ss, str_off, ts, type_off, _ps, proto_off, _fs, field_off, _ms,
     meth_off, cs, cdef_off) = struct.unpack_from("<12I", d, 56)
    strings = {}

    def string(i):
        s = strings.get(i)
        if s is None:
            off = struct.unpack_from("<I", d, str_off + i * 4)[0]
            _n, off = uleb128(d, off)
            s = d[off:d.index(b"\0", off)].decode("utf-8", "replace")
            strings[i] = s
        return s

    def typ(i):
        return string(struct.unpack_from("<I", d, type_off + i * 4)[0])

    def proto(i):
        _shorty, ret, params = struct.unpack_from("<III", d, proto_off + i * 12)
        sig = "("
        if params:
            n = struct.unpack_from("<I", d, params)[0]
            for k in range(n):
                sig += typ(struct.unpack_from("<H", d, params + 4 + k * 2)[0])
        return sig + ")" + typ(ret)

    def method(i):
        c, p, n = struct.unpack_from("<HHI", d, meth_off + i * 8)
        return string(n), proto(p)

    def field(i):
        c, t, n = struct.unpack_from("<HHI", d, field_off + i * 8)
        return string(n), typ(t)

    classes = {}
    origin = os.path.basename(path)
    for i in range(cs):
        (cidx, flags, sidx, ioff, _src, _ann, data_off, _sv) = \
            struct.unpack_from("<8I", d, cdef_off + i * 32)
        ifaces = []
        if ioff:
            n = struct.unpack_from("<I", d, ioff)[0]
            ifaces = [typ(struct.unpack_from("<H", d, ioff + 4 + k * 2)[0])
                      for k in range(n)]
        info = ClassInfo(typ(cidx), flags,
                         None if sidx == 0xFFFFFFFF else typ(sidx),
                         ifaces, origin)
        if data_off:
            off = data_off
            nsf, off = uleb128(d, off)
            nif, off = uleb128(d, off)
            ndm, off = uleb128(d, off)
            nvm, off = uleb128(d, off)
            for count, table in ((nsf, info.sfields), (nif, info.ifields)):
                idx = 0
                for _ in range(count):
                    delta, off = uleb128(d, off)
                    acc, off = uleb128(d, off)
                    idx += delta
                    table[field(idx)] = acc
            for count, table in ((ndm, info.direct), (nvm, info.virtual)):
                idx = 0
                for _ in range(count):
                    delta, off = uleb128(d, off)
                    acc, off = uleb128(d, off)
                    _code, off = uleb128(d, off)
                    idx += delta
                    table[method(idx)] = acc
        classes.setdefault(info.desc, info)
    return classes


class Hierarchy(object):
    def __init__(self, classes):
        self.c = classes

    def chain(self, desc):
        seen = set()
        while desc and desc not in seen:
            seen.add(desc)
            info = self.c.get(desc)
            if info is None:
                return
            yield info
            desc = info.sup

    # Each returns (flags, owning class) or None, mirroring dalvik/vm/Jni.c.
    def get_method_id(self, desc, name, sig):
        for info in self.chain(desc):
            if (name, sig) in info.virtual:
                return info.virtual[(name, sig)], info.desc
        info = self.c.get(desc)
        if info and (name, sig) in info.direct:
            return info.direct[(name, sig)], info.desc
        # Dalvik puts interface methods an abstract class does not implement
        # into its vtable as miranda methods.
        for info in self.chain(desc):
            for iface in self.all_ifaces(info.desc):
                ii = self.c.get(iface)
                if ii and (name, sig) in ii.virtual:
                    return ii.virtual[(name, sig)], ii.desc
        return None

    def all_ifaces(self, desc, seen=None):
        if seen is None:
            seen = set()
        info = self.c.get(desc)
        if info is None:
            return seen
        for i in info.ifaces:
            if i not in seen:
                seen.add(i)
                self.all_ifaces(i, seen)
        return seen

    def get_static_method_id(self, desc, name, sig):
        for info in self.chain(desc):
            if (name, sig) in info.direct:
                return info.direct[(name, sig)], info.desc
        return None

    def get_field_id(self, desc, name, sig):
        for info in self.chain(desc):
            if (name, sig) in info.ifields:
                return info.ifields[(name, sig)], info.desc
        return None

    def get_static_field_id(self, desc, name, sig):
        info = self.c.get(desc)
        if info and (name, sig) in info.sfields:
            return info.sfields[(name, sig)], info.desc
        return None

    def register(self, desc, name, sig):
        info = self.c.get(desc)
        if info is None:
            return None
        if (name, sig) in info.direct:
            return info.direct[(name, sig)], desc
        if (name, sig) in info.virtual:
            return info.virtual[(name, sig)], desc
        return None

    def same_name(self, desc, name, kinds):
        out = []
        for info in self.chain(desc):
            for kind in kinds:
                for (n, s), acc in sorted(getattr(info, kind).items()):
                    if n == name:
                        out.append("%s%s %s in %s" % (
                            "static " if acc & ACC_STATIC else "",
                            "native" if acc & ACC_NATIVE else kind,
                            s, info.desc))
        return out


# ------------------------------------------------------ source preprocessing

def compiled_sources():
    """(source, compile line) for every .cpp build_webkit.py compiles."""
    out = []
    template = None
    pat = re.compile(r" -o (build/webkit_intermediates/\S+\.o) (\S+)$")
    with open(COMMANDS, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = pat.search(line)
            if not m or not m.group(2).startswith(WEBKIT_PREFIX):
                continue
            if not m.group(2).endswith((".cpp", ".c")):
                continue
            out.append((m.group(2), line))
            if m.group(2).endswith("/WebCoreJni.cpp"):
                template = line
    if template is None:
        raise SystemExit("webkit_commands.sh has no WebCoreJni.cpp compile")
    # build_webkit.py appends WebCoreJniRegistration.cpp with WebCoreJni's
    # flags; do the same.
    out.append((REGISTRATION, template.replace(
        "WebCoreJni.o", "WebCoreJniRegistration.o").replace(
        "WebCoreJni.cpp", "WebCoreJniRegistration.cpp")))
    return out


def preprocess(src, line, outdir):
    dest = os.path.join(outdir, src.replace("/", "__") + ".ii")
    m = re.search(r" -o (\S+\.o) (\S+)$", line)
    cmd = line[:m.start()] + " -E -o " + dest + " " + m.group(2)
    cmd = cmd.replace(" -MD ", " ").replace(" -MD", "")
    env = dict(os.environ)
    env["GXX"] = GXX
    env["GCC"] = GCC
    env.setdefault("LC_ALL", "C")
    r = subprocess.run(["bash", "-c", cmd], cwd=ROOT, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    if r.returncode != 0:
        raise SystemExit("preprocessing %s failed:\n%s" % (src, r.stderr[-3000:]))
    return dest


LINEMARK = re.compile(r'^# (\d+) "([^"]*)"')


class Unit(object):
    """A preprocessed translation unit, reduced to the lines that came from
    WebKit's own sources, with an offset -> (file, line) map."""

    def __init__(self, src, ii_path):
        self.src = src
        self.base = os.path.basename(src)
        texts = []
        self.starts = []
        self.where = []
        pos = 0
        cur_file, cur_line = src, 1
        with open(ii_path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                m = LINEMARK.match(raw)
                if m:
                    cur_line = int(m.group(1))
                    cur_file = os.path.normpath(m.group(2))
                    continue
                if cur_file.startswith(WEBKIT_PREFIX):
                    self.starts.append(pos)
                    self.where.append((cur_file, cur_line))
                    texts.append(raw)
                    pos += len(raw)
                cur_line += 1
        self.text = "".join(texts)
        self.depth, self.opener = brace_map(self.text)

    def locate(self, off):
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        f, l = self.where[lo] if self.where else (self.src, 0)
        return "%s:%d" % (f[len(WEBKIT_PREFIX):], l)

    def in_source_file(self, off):
        lo = self.locate(off)
        return lo.startswith(self.src[len(WEBKIT_PREFIX):] + ":")


def brace_map(text):
    """Per-offset brace depth, and for each '{' offset its parent '{'."""
    depth = [0] * (len(text) + 1)
    opener = {}
    stack = []
    i = 0
    n = len(text)
    d = 0
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            q = c
            depth[i] = d
            i += 1
            while i < n and text[i] != q:
                if text[i] == "\\":
                    depth[i] = d
                    i += 1
                depth[i] = d
                i += 1
            if i < n:
                depth[i] = d
            i += 1
            continue
        if c == "{":
            opener[i] = stack[-1] if stack else None
            stack.append(i)
            d += 1
        elif c == "}":
            if stack:
                stack.pop()
            d -= 1
        depth[i] = d
        i += 1
    depth[n] = d
    return depth, opener


def function_block(unit, off):
    """(start, end) offsets of the function body enclosing `off`, or None."""
    text = unit.text
    # innermost '{' enclosing off
    i = off
    d = unit.depth[off]
    target = d
    blocks = []
    while i > 0 and target > 0:
        i -= 1
        if text[i] == "{" and unit.depth[i] == target:
            blocks.append(i)
            target -= 1
        elif text[i] == "}" and False:
            pass
    # outermost block whose header ends with ')' (optionally const/throw())
    # is the function body; namespace/class/struct/extern bodies are not.
    for b in reversed(blocks):
        head = text[max(0, b - 400):b].rstrip()
        head = re.sub(r"\bconst$", "", head).rstrip()
        if head.endswith(")"):
            end = b
            depth = 0
            while end < len(text):
                if text[end] == "{":
                    depth += 1
                elif text[end] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                end += 1
            return b, end
    return None


def function_name(unit, off):
    blk = function_block(unit, off)
    if blk is None:
        return "<file scope>"
    head = unit.text[max(0, blk[0] - 600):blk[0]]
    # strip a constructor initialiser list
    names = re.findall(r"([A-Za-z_][\w:~]*)\s*\([^;{}]*\)\s*(?:const\s*)?(?::[^;{}]*)?$",
                       head.strip())
    if names:
        return names[-1]
    m = re.findall(r"([A-Za-z_][\w:~]*)\s*\(", head)
    return m[-1] if m else "<function>"


# --------------------------------------------------------- call extraction

STRLIT = re.compile(r'\s*((?:"(?:[^"\\]|\\.)*"\s*)+)$', re.S)


def literal(arg):
    """Concatenated value of an argument made only of string literals."""
    m = STRLIT.match(arg)
    if not m:
        return None
    return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))


def split_args(text, open_paren):
    """Top-level comma-separated args of the call whose '(' is at open_paren."""
    args = []
    depth = 0
    cur = []
    i = open_paren
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\\":
                    j += 1
                j += 1
            cur.append(text[i:j + 1])
            i = j + 1
            continue
        if c in "([{":
            depth += 1
            if depth == 1 and c == "(":
                i += 1
                continue
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                args.append("".join(cur).strip())
                return args, i
        elif c == "," and depth == 1:
            args.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    return args, n


def strip_casts(expr):
    expr = expr.strip()
    while True:
        m = re.match(r"^\(\s*(?:const\s+)?\w+\s*\*?\s*\)\s*(.*)$", expr, re.S)
        if not m:
            break
        expr = m.group(1).strip()
    while expr.startswith("(") and expr.endswith(")"):
        inner, _ = split_args(expr, 0)
        if len(inner) == 1 and inner[0] == expr[1:-1].strip():
            expr = inner[0]
        else:
            break
    return expr


CALL = re.compile(
    r"(?<![\w.])(?:(?:env|_env|mEnv|m_env|\(\*env\))\s*->\s*|JSC::Bindings::|)"
    r"\b(GetMethodID|GetStaticMethodID|GetFieldID|GetStaticFieldID|GetJMethod|"
    r"FindClass|callJNIMethod|callJNIStaticMethod|jniRegisterNativeMethods|"
    r"RegisterNatives)\s*(?:<[^<>()]*>)?\s*\(")


class Lookup(object):
    def __init__(self, kind, cls, name, sig, where, func, note=""):
        self.kind = kind
        self.cls = cls
        self.name = name
        self.sig = sig
        self.where = where
        self.func = func
        self.note = note


def resolve_string(unit, expr):
    expr = strip_casts(expr)
    v = literal(expr)
    if v is not None:
        return v
    if re.match(r"^[A-Za-z_]\w*$", expr):
        m = None
        for m in re.finditer(
                r"\b%s\s*(?:\[\s*\d*\s*\])?\s*=\s*((?:\"(?:[^\"\\]|\\.)*\"\s*)+)[;,]"
                % re.escape(expr), unit.text):
            pass
        if m:
            return literal(m.group(1))
    return None


def to_desc(internal):
    if internal.startswith("["):
        return internal
    return "L%s;" % internal


def resolve_class(unit, expr, off, member=None, depth=0):
    """-> (descriptor | None, how).  descriptor None + how 'dynamic' means a
    documented dynamic receiver; how starting with 'UNRESOLVED' is an error."""
    expr = strip_casts(expr)
    key = (unit.base, expr)
    if member and (unit.base, expr, member) in MEMBER_CLASSES:
        return MEMBER_CLASSES[(unit.base, expr, member)], "annotated"
    if depth > 4:
        return None, "UNRESOLVED (recursion) %s" % expr
    m = re.match(r"^(?:env\s*->\s*|\(\*env\)\s*->\s*)?FindClass\s*\((.*)\)$", expr, re.S)
    if m:
        args, _ = split_args(expr, expr.index("("))
        name = resolve_string(unit, args[-1])
        if name is None:
            return None, "UNRESOLVED FindClass(%s)" % args[-1]
        return to_desc(name), "FindClass"
    m = re.match(r"^(?:env\s*->\s*)?GetObjectClass\s*\((.*)\)$", expr, re.S)
    if m:
        obj = strip_casts(m.group(1))
        if (unit.base, obj) in OBJECT_CLASSES:
            v = OBJECT_CLASSES[(unit.base, obj)]
            return v, "annotated" if v else "dynamic"
        return None, "UNRESOLVED GetObjectClass(%s)" % obj
    m = re.match(r"^(?:env\s*->\s*)?New(?:Global|Weak(?:Global)?)Ref\s*\((.*)\)$", expr, re.S)
    if m:
        return resolve_class(unit, m.group(1), off, member, depth + 1)
    if not re.match(r"^[A-Za-z_][\w:]*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)*$", expr):
        return None, "UNRESOLVED expression %s" % expr
    if key in OBJECT_CLASSES and OBJECT_CLASSES[key] is None:
        return None, "dynamic"
    # nearest assignment inside the enclosing function, before the use
    pat = re.compile(r"(?<![\w>.:])%s\s*=(?!=)\s*([^;]+);" %
                     re.escape(expr).replace(r"\ ", r"\s*"))
    blk = function_block(unit, off)
    if blk:
        best = None
        for m in pat.finditer(unit.text, blk[0], off):
            best = m
        if best:
            r, how = resolve_class(unit, best.group(1), best.start(), member,
                                   depth + 1)
            # A local assigned from something opaque (a reflection call's
            # result, an array element) falls back to its annotation.
            if r is None and how.startswith("UNRESOLVED") and key in OBJECT_CLASSES:
                v = OBJECT_CLASSES[key]
                return v, "annotated" if v else "dynamic"
            return r, how
    if key in OBJECT_CLASSES:
        v = OBJECT_CLASSES[key]
        return v, "annotated" if v else "dynamic"
    # file-scope variable assigned somewhere in this source file
    found = set()
    for m in pat.finditer(unit.text):
        if not unit.in_source_file(m.start()):
            continue
        r, how = resolve_class(unit, m.group(1), m.start(), member, depth + 1)
        if r:
            found.add(r)
    if len(found) == 1:
        return found.pop(), "global"
    if len(found) > 1:
        return None, "UNRESOLVED ambiguous %s -> %s" % (expr, sorted(found))
    return None, "UNRESOLVED %s" % expr


def extract(unit):
    lookups = []
    registrations = []
    dynamic = []
    tables = {}
    for m in re.finditer(
            r"JNINativeMethod\s+(\w+)\s*\[\s*\]\s*=\s*\{", unit.text):
        body_start = m.end() - 1
        depth = 0
        i = body_start
        while i < len(unit.text):
            if unit.text[i] == "{":
                depth += 1
            elif unit.text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = unit.text[body_start:i + 1]
        entries = []
        for e in re.finditer(
                r'\{\s*((?:"(?:[^"\\]|\\.)*"\s*)+),\s*((?:"(?:[^"\\]|\\.)*"\s*)+),',
                body):
            entries.append((literal(e.group(1)), literal(e.group(2)),
                            unit.locate(body_start + e.start())))
        tables[m.group(1)] = entries

    for m in CALL.finditer(unit.text):
        if not unit.in_source_file(m.start()):
            continue
        fn = m.group(1)
        args, _end = split_args(unit.text, m.end() - 1)
        where = unit.locate(m.start())
        func = function_name(unit, m.start())
        # skip the helper definitions themselves
        head = unit.text[max(0, m.start() - 40):m.start()]
        if re.search(r"(jmethodID|jvalue|T|jclass|int)\s*$", head) and \
                any(a.startswith(("JNIEnv", "jobject", "jclass", "const char"))
                    for a in args):
            continue
        if fn == "FindClass":
            name = resolve_string(unit, args[-1])
            if name is None:
                dynamic.append((where, func, "FindClass(%s)" % args[-1]))
            else:
                lookups.append(Lookup("FindClass", to_desc(name), None, None,
                                      where, func))
            continue
        if fn in ("jniRegisterNativeMethods", "RegisterNatives"):
            if fn == "jniRegisterNativeMethods":
                cls_arg, table = args[1], strip_casts(args[2])
                cname = resolve_string(unit, cls_arg)
                cls = to_desc(cname) if cname else None
                how = "literal" if cls else "UNRESOLVED %s" % cls_arg
            else:
                cls, how = resolve_class(unit, args[-3], m.start())
                table = strip_casts(args[-2])
            registrations.append((cls, how, table, where, func))
            continue
        if fn == "GetJMethod":
            if len(args) != 4:
                continue
            clazz, name_a, sig_a = args[1], args[2], args[3]
            kind = "GetMethodID"
        elif fn in ("callJNIMethod", "callJNIStaticMethod"):
            if len(args) < 3:
                continue
            clazz, name_a, sig_a = args[0], args[1], args[2]
            kind = "callJNIMethod" if fn == "callJNIMethod" else "GetStaticMethodID"
        else:
            if len(args) == 4:
                args = args[1:]
            if len(args) != 3:
                continue
            clazz, name_a, sig_a = args
            kind = fn
        name = resolve_string(unit, name_a)
        sig = resolve_string(unit, sig_a)
        if name is None or sig is None:
            dynamic.append((where, func, "%s(%s)" % (fn, ", ".join(args))))
            continue
        if kind == "callJNIMethod":
            cls, how = resolve_class(unit, clazz, m.start(), member=name)
            kind = "GetMethodID"
        else:
            cls, how = resolve_class(unit, clazz, m.start(), member=name)
        lookups.append(Lookup(kind, cls, name, sig, where, func, how))
    return lookups, registrations, tables, dynamic


# ------------------------------------------------------------------- check

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--framework", default=DEFAULT_FRAMEWORK)
    ap.add_argument("--core", default=DEFAULT_CORE)
    ap.add_argument("--inventory", action="store_true",
                    help="print every lookup, not only the problems")
    ap.add_argument("--keep-preprocessed", metavar="DIR")
    opts = ap.parse_args()

    classes = {}
    for p in (opts.core, opts.framework):
        if not os.path.exists(p):
            raise SystemExit("missing %s" % p)
        for k, v in parse_dex(p).items():
            classes.setdefault(k, v)
    hier = Hierarchy(classes)
    print("dex: %d classes from %s + %s" % (
        len(classes), os.path.relpath(opts.core, ROOT),
        os.path.relpath(opts.framework, ROOT)))

    srcs = []
    for src, line in compiled_sources():
        try:
            with open(os.path.join(ROOT, src), encoding="utf-8",
                      errors="replace") as f:
                if JNI_TOKENS.search(f.read()):
                    srcs.append((src, line))
        except IOError:
            raise SystemExit("compiled source missing: %s" % src)
    outdir = opts.keep_preprocessed or tempfile.mkdtemp(prefix="webkit_jni_")
    os.makedirs(outdir, exist_ok=True)

    lookups = []
    registrations = []
    tables = {}
    dynamic = []
    try:
        for src, line in srcs:
            unit = Unit(src, preprocess(src, line, outdir))
            l, r, t, d = extract(unit)
            lookups += l
            registrations += [(c, h, (unit.base, tb), w, f) for c, h, tb, w, f in r]
            for k, v in t.items():
                tables[(unit.base, k)] = v
            dynamic += d
    finally:
        if not opts.keep_preprocessed:
            shutil.rmtree(outdir, ignore_errors=True)
    print("sources: %d compiled WebKit translation units name Java members"
          % len(srcs))

    problems = []

    def problem(msg):
        problems.append(msg)

    # --- by-name lookups ------------------------------------------------
    checked = 0
    for lk in lookups:
        if lk.cls is None:
            if lk.note == "dynamic":
                dynamic.append((lk.where, lk.func, "%s(?, %s, %s)" % (
                    lk.kind, lk.name, lk.sig)))
            else:
                problem("UNRESOLVED  %s %s %s  [%s in %s]  %s" % (
                    lk.kind, lk.name, lk.sig, lk.where, lk.func, lk.note))
            continue
        checked += 1
        if lk.cls not in classes:
            problem("NOCLASS     %s  (%s %s%s)  [%s in %s]" % (
                lk.cls, lk.kind, lk.name or "", lk.sig or "", lk.where, lk.func))
            continue
        if lk.kind == "FindClass":
            res, ok, why = True, True, ""
        elif lk.kind == "GetMethodID":
            res = hier.get_method_id(lk.cls, lk.name, lk.sig)
            ok = res is not None and not res[0] & ACC_STATIC
            why = "is static" if res else "no such method"
            kinds = ("virtual", "direct")
        elif lk.kind == "GetStaticMethodID":
            res = hier.get_static_method_id(lk.cls, lk.name, lk.sig)
            ok = res is not None and res[0] & ACC_STATIC
            why = "not static" if res else "no such static method"
            kinds = ("direct", "virtual")
        elif lk.kind == "GetFieldID":
            res = hier.get_field_id(lk.cls, lk.name, lk.sig)
            ok = res is not None
            why = "no such instance field"
            kinds = ("ifields", "sfields")
        elif lk.kind == "GetStaticFieldID":
            res = hier.get_static_field_id(lk.cls, lk.name, lk.sig)
            ok = res is not None
            why = "no such static field in the class itself"
            kinds = ("sfields", "ifields")
        if opts.inventory:
            print("  %-4s %-17s %s %s %s  [%s in %s]" % (
                "ok" if ok else "BAD", lk.kind, lk.cls,
                lk.name or "", lk.sig or "", lk.where, lk.func))
        if not ok:
            have = hier.same_name(lk.cls, lk.name, kinds) or ["nothing named %s" % lk.name]
            problem("%-11s %s.%s %s -- %s  [%s in %s]\n              has: %s" % (
                "MISMATCH", lk.cls, lk.name, lk.sig, why, lk.where, lk.func,
                "\n                   ".join(have)))

    # --- native registrations -------------------------------------------
    registered = {}
    reg_checked = 0
    for cls, how, tkey, where, func in registrations:
        if cls is None:
            problem("UNRESOLVED  registration of table %s  [%s in %s] %s" % (
                tkey[1], where, func, how))
            continue
        entries = tables.get(tkey)
        if entries is None:
            problem("NOTABLE     %s registered from unknown table %s  [%s]" % (
                cls, tkey[1], where))
            continue
        if cls not in classes:
            problem("NOCLASS     %s  (RegisterNatives %s)  [%s in %s]" % (
                cls, tkey[1], where, func))
            continue
        for name, sig, ewhere in entries:
            reg_checked += 1
            registered.setdefault(cls, set()).add((name, sig))
            res = hier.register(cls, name, sig)
            ok = res is not None and res[0] & ACC_NATIVE
            if opts.inventory:
                print("  %-4s %-17s %s %s %s  [%s via %s]" % (
                    "ok" if ok else "BAD", "RegisterNatives", cls, name, sig,
                    ewhere, where))
            if not ok:
                have = [h for h in hier.same_name(cls, name, ("direct", "virtual"))
                        if h.endswith(" in " + cls)] or ["nothing named %s" % name]
                problem("%-11s %s.%s %s -- %s  [%s, registered at %s]\n"
                        "              has: %s" % (
                            "NATIVE", cls, name, sig,
                            "not native" if res else
                            "no method of this descriptor in the class itself "
                            "(fails RegisterNatives for the WHOLE class)",
                            ewhere, where, "\n                   ".join(have)))

    # --- reverse: Java natives nobody registers --------------------------
    reverse_classes = set(registered)
    reverse_classes.update(c for c in classes if c.startswith("Landroid/webkit/"))
    java_natives = 0
    for cls in sorted(reverse_classes):
        info = classes.get(cls)
        if info is None:
            continue
        for table in (info.direct, info.virtual):
            for (name, sig), acc in sorted(table.items()):
                if not acc & ACC_NATIVE:
                    continue
                java_natives += 1
                if (name, sig) not in registered.get(cls, ()):
                    problem("UNREGISTERED %s.%s %s -- declared native, no "
                            "WebKit table registers it (UnsatisfiedLinkError "
                            "on first call)" % (cls, name, sig))

    if dynamic:
        print("")
        print("dynamic lookups (receiver class decided at run time, not checkable):")
        for where, func, what in dynamic:
            print("  %s in %s: %s" % (where, func, what))

    print("")
    print("checked %d by-name lookups and %d native registrations "
          "(%d classes registered); %d Java native methods in those classes "
          "and android/webkit/*" % (checked, reg_checked, len(registered),
                                    java_natives))
    if problems:
        print("%d PROBLEM(S):" % len(problems))
        for p in problems:
            print("  " + p)
        return 1
    print("webkit JNI boundary: ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
