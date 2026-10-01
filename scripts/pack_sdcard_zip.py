#!/usr/bin/env python3
"""Pack sdcard/ into the flashable sdcard.zip, then verify the archive.

Deliberately uses python3's zipfile rather than the `zip` command. The
`zip` binary is not installed in this WSL image, and on 2026-09-10 a
respin that shelled out to it died with exit 127. Nothing checked the
status, so the old archive stayed in place and every subsequent "new
build" flashed identical bytes (md5 1ff0364ece373c42fe4dcb210bf90cdd,
unchanged since 2026-09-09). The verify pass at the bottom re-reads the
finished archive and compares it to the tree it was built from, so a
silent no-op is no longer possible.
"""
import os, sys, zipfile, time

root, staging, out = sys.argv[1], sys.argv[2], sys.argv[3]

files, dirs = [], []
for dirpath, dirnames, filenames in os.walk(staging):
    dirnames.sort()
    rel = os.path.relpath(dirpath, staging).replace(os.sep, '/')
    if rel != '.':
        dirs.append(rel)
    for fn in sorted(filenames):
        full = os.path.join(dirpath, fn)
        if os.path.islink(full):
            print("ERROR: symlink in staging tree: %s" % full); sys.exit(1)
        files.append(os.path.relpath(full, staging).replace(os.sep, '/'))
files.sort(); dirs.sort()

# The archive must extract straight onto the SD card root, so every path is
# relative to sdcard/ -- never to the project root. Until 2026-09-11 they were
# relative to the project root, so every entry carried an "sdcard/" prefix and
# extracting at the card root wrote SD:/sdcard/linux/..., a branch the
# bootloader never reads. SD:/linux/ kept the build from 2026-09-09 and every
# "reflash" after that changed nothing on the device (the running image mapped
# a 494009-byte services.jar long after staging had moved to 493903).
EXPECTED_TOPS = ["linux", "luma"]

def check_layout(paths, what):
    tops = sorted({p.split("/")[0] for p in paths})
    if tops != EXPECTED_TOPS:
        print("   BAD LAYOUT (%s): top-level entries %s, expected %s"
              % (what, tops, EXPECTED_TOPS))
        return False
    return True

if not check_layout(files, "staging tree"):
    sys.exit(1)

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for rel in dirs:
        st = os.stat(os.path.join(staging, rel))
        zi = zipfile.ZipInfo(rel + '/', time.localtime(st.st_mtime)[:6])
        zi.external_attr = (st.st_mode & 0xFFFF) << 16 | 0x10
        zf.writestr(zi, b'')
    for rel in files:
        full = os.path.join(staging, rel)
        st = os.stat(full)
        zi = zipfile.ZipInfo(rel, time.localtime(st.st_mtime)[:6])
        zi.external_attr = (st.st_mode & 0xFFFF) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        with open(full, 'rb') as fh:
            zf.writestr(zi, fh.read())

print("   packed %d files, %d dirs, %d bytes" % (len(files), len(dirs), os.path.getsize(out)))

# --- verify: re-read the finished archive against the staging tree ---
bad = 0
with zipfile.ZipFile(out) as zf:
    if zf.testzip() is not None:
        print("   CRC FAILURE in archive"); sys.exit(1)
    names = set(n for n in zf.namelist() if not n.endswith('/'))
    for rel in files:
        if rel not in names:
            print("   MISSING FROM ZIP: %s" % rel); bad += 1; continue
        with open(os.path.join(staging, rel), 'rb') as fh:
            if zf.read(rel) != fh.read():
                print("   CONTENT MISMATCH: %s" % rel); bad += 1
    if not check_layout(names, "finished archive"):
        bad += 1
    for extra in sorted(names - set(files)):
        print("   UNEXPECTED ENTRY: %s" % extra); bad += 1
if bad:
    print("   %d of %d files failed verification" % (bad, len(files))); sys.exit(1)
print("   all %d files verified byte-for-byte against staging" % len(files))
