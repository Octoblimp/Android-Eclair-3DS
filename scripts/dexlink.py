#!/usr/bin/env python3
"""Link-check the shipped dex files against each other.

A class or method that a dex references but that nothing on the bootclasspath
defines does not fail at install time and does not fail at launch.  It fails
the first time the one code path that touches it runs, as NoClassDefFoundError
or NoSuchMethodError -- an uncaught exception, so RuntimeInit kills the process
with no signal, which is exactly what dmesg showed when the Browser died:
"binder: undelivered transaction, process died" and nothing else.

So: parse each dex's type_ids / method_ids (what it *references*) against the
class_defs of the whole bootclasspath (what is *defined*), resolving methods
up the superclass and interface chain the way the verifier does.

Usage: dexlink.py <apk-or-jar-to-check> [more ...]
Classpath is core.jar + framework.jar + services.jar + the file itself.
"""
import os
import struct
import sys
import zipfile

HOME = os.path.expanduser("~/android3ds")
FW = os.path.join(
    HOME, "third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/framework")
CLASSPATH = [os.path.join(FW, n) for n in
             ("core.jar", "framework.jar", "services.jar")]


def uleb128(buf, off):
    result = 0
    shift = 0
    while True:
        b = buf[off]
        off += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, off
        shift += 7


class Dex(object):
    def __init__(self, data, name):
        self.name = name
        self.d = data
        if bytes(data[:4]) != b"dex\n":
            raise ValueError("%s: not a dex" % name)
        (self.string_ids_size, self.string_ids_off,
         self.type_ids_size, self.type_ids_off,
         self.proto_ids_size, self.proto_ids_off,
         self.field_ids_size, self.field_ids_off,
         self.method_ids_size, self.method_ids_off,
         self.class_defs_size, self.class_defs_off) = struct.unpack_from(
            "<12I", data, 56)
        self._str = {}
        self._ty = {}
        self._pr = {}

    def string(self, idx):
        s = self._str.get(idx)
        if s is None:
            off = struct.unpack_from("<I", self.d,
                                     self.string_ids_off + idx * 4)[0]
            _n, off = uleb128(self.d, off)
            end = self.d.index(b"\0", off)
            s = self.d[off:end].decode("utf-8", "replace")
            self._str[idx] = s
        return s

    def type(self, idx):
        t = self._ty.get(idx)
        if t is None:
            t = self.string(struct.unpack_from(
                "<I", self.d, self.type_ids_off + idx * 4)[0])
            self._ty[idx] = t
        return t

    def proto(self, idx):
        p = self._pr.get(idx)
        if p is None:
            _shorty, ret, params_off = struct.unpack_from(
                "<III", self.d, self.proto_ids_off + idx * 12)
            sig = "("
            if params_off:
                n = struct.unpack_from("<I", self.d, params_off)[0]
                for k in range(n):
                    t = struct.unpack_from("<H", self.d,
                                           params_off + 4 + k * 2)[0]
                    sig += self.type(t)
            p = sig + ")" + self.type(ret)
            self._pr[idx] = p
        return p

    def method(self, idx):
        cls, proto, name = struct.unpack_from(
            "<HHI", self.d, self.method_ids_off + idx * 8)
        return self.type(cls), self.string(name), self.proto(proto)

    def referenced_types(self):
        return set(self.type(i) for i in range(self.type_ids_size))

    def referenced_methods(self):
        return set(self.method(i) for i in range(self.method_ids_size))

    def hierarchy(self):
        """class descriptor -> (super or None, [interfaces], set(name+proto))"""
        out = {}
        for i in range(self.class_defs_size):
            (class_idx, _flags, sup_idx, ifaces_off, _src, _ann,
             class_data_off, _static) = struct.unpack_from(
                "<8I", self.d, self.class_defs_off + i * 32)
            name = self.type(class_idx)
            sup = None if sup_idx == 0xFFFFFFFF else self.type(sup_idx)
            ifaces = []
            if ifaces_off:
                n = struct.unpack_from("<I", self.d, ifaces_off)[0]
                for k in range(n):
                    ifaces.append(self.type(struct.unpack_from(
                        "<H", self.d, ifaces_off + 4 + k * 2)[0]))
            own = set()
            if class_data_off:
                off = class_data_off
                nsf, off = uleb128(self.d, off)
                nif, off = uleb128(self.d, off)
                ndm, off = uleb128(self.d, off)
                nvm, off = uleb128(self.d, off)
                for _ in range(nsf + nif):
                    _i, off = uleb128(self.d, off)
                    _a, off = uleb128(self.d, off)
                for count in (ndm, nvm):
                    midx = 0
                    for _ in range(count):
                        delta, off = uleb128(self.d, off)
                        _a, off = uleb128(self.d, off)
                        _c, off = uleb128(self.d, off)
                        midx += delta
                        _c2, nm, pr = self.method(midx)
                        own.add((nm, pr))
            out[name] = (sup, ifaces, own)
        return out


def load(path):
    if not os.path.exists(path):
        return None
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".dex")]
        if not names:
            return None
        return Dex(bytearray(z.read(names[0])), os.path.basename(path))


def resolves(hier, cls, name, proto, seen=None):
    if seen is None:
        seen = set()
    if cls in seen:
        return False
    seen.add(cls)
    ent = hier.get(cls)
    if ent is None:
        return False
    sup, ifaces, own = ent
    if (name, proto) in own:
        return True
    if sup and resolves(hier, sup, name, proto, seen):
        return True
    for i in ifaces:
        if resolves(hier, i, name, proto, seen):
            return True
    return False


def main():
    targets = sys.argv[1:]
    if not targets:
        sys.stderr.write("usage: dexlink.py <apk-or-jar> ...\n")
        return 2

    base = {}
    loaded = []
    for p in CLASSPATH:
        d = load(p)
        if d is None:
            sys.stderr.write("classpath: %s has no dex\n" % p)
            return 2
        base.update(d.hierarchy())
        loaded.append(d.name)
    print("classpath: %d classes from %s" % (len(base), ", ".join(loaded)))

    rc = 0
    for t in targets:
        d = load(t)
        if d is None:
            print("%s: no dex, skipped" % t)
            continue
        hier = dict(base)
        own = d.hierarchy()
        hier.update(own)

        print("")
        print("=== %s: %d classes, %d types referenced, %d methods referenced"
              % (os.path.basename(t), len(own), d.type_ids_size,
                 d.method_ids_size))

        missing_cls = sorted(ty for ty in d.referenced_types()
                             if ty.lstrip("[").startswith("L")
                             and ty.lstrip("[") not in hier)
        if missing_cls:
            rc = 1
            print("  MISSING CLASSES (%d) -- NoClassDefFoundError waiting to "
                  "happen:" % len(missing_cls))
            for m in missing_cls:
                print("    %s" % m)
        else:
            print("  classes: all %d referenced types resolve"
                  % d.type_ids_size)

        missing_m = []
        for cls, name, proto in d.referenced_methods():
            if cls.startswith("["):
                continue
            if cls not in hier:
                continue          # already reported above
            if resolves(hier, cls, name, proto):
                continue
            missing_m.append((cls, name, proto))
        if missing_m:
            rc = 1
            print("  MISSING METHODS (%d) -- NoSuchMethodError waiting to "
                  "happen:" % len(missing_m))
            for cls, name, proto in sorted(missing_m):
                print("    %s.%s%s" % (cls, name, proto))
        else:
            print("  methods: all %d referenced methods resolve"
                  % d.method_ids_size)
    return rc


if __name__ == "__main__":
    sys.exit(main())
