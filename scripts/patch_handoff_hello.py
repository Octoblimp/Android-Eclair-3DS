#!/usr/bin/env python3
"""HANDOFF: the hello.jar dexopt failure, and the stale services.jar lines.

Two separate things in one 09-12 04:48 logcat that look alike and are not.
The hello.jar failure is structural and recurs every boot; the services.jar
dep-signature mismatches are from a capture taken seven hours before the
dexpreopt rebuild that fixed them.  Writing both down together so the next
session does not spend its first hour chasing the dead one.
"""
from a3ds_paths import A3DS_ROOT
import io

PATH = f"{A3DS_ROOT}/HANDOFF.md"

doc = io.open(PATH, encoding="utf-8").read()
orig = doc

# ------------------------------------------------------------- header ---
old = """**Current flashable:** `sdcard.zip`, 59,371,688 bytes, md5 `bbe04b74626dc52df2c083c936ad60a1`

That zip carries both halves of the current work: the DSP audio evidence
probes (§3.13) and the camera control-bit walk (§3.14). One flash, both
captures.
"""
new = """**Current flashable:** `sdcard.zip`, 59,368,882 bytes, md5 `5709f20727c5cbb112fc959e203b7d2e`

That zip carries both halves of the current work: the DSP audio evidence
probes (§3.13) and the camera control-bit walk (§3.14). One flash, both
captures. It is also the first zip without `hello.jar` (§3.15), so it holds
185 files rather than 186.
"""
assert old in doc, "header anchor missing"
doc = doc.replace(old, new, 1)

# ---------------------------------------------------------- section 3.15 ---
section = """## 3.15 hello.jar: a dexopt failure on every boot, removed -- and what it really cost

The 09-12 04:48 logcat carries exactly one hard error:

    E/installd(161): dexopt cannot open
    '/data/dalvik-cache/system@framework@hello.jar@classes.dex' for output

The mechanism, read out of the real source rather than assumed
(`third_party/frameworks/base/services/java/com/android/server/PackageManagerService.java`,
lines 428-545):

* PMS lists `/system/framework` and dexopts every `.apk`/`.jar` there that
  `DexFile.isDexOptNeeded()` calls stale. `framework-res.apk` is skipped by
  name. `core.jar`, `framework.jar` and `services.jar` are handled by the
  bootclasspath loop above it, which adds them to `libFiles`, and the directory
  loop skips anything already in that set. **`hello.jar` is the only file in
  that directory that reaches the dexopt call.**
* It has no pre-baked entry in `sdcard/linux/android/data/dalvik-cache/` --
  that directory holds exactly the three real jars -- so `isDexOptNeeded` is
  true every boot.
* `mInstaller.dexopt()` fails, and `didDexOpt = true` is set on the next line
  with no check of the return value.
* `didDexOpt` then deletes every `data@app@*` and `data@app-private@*` entry
  from `/data/dalvik-cache`.

`mNoDexOpt` is a red herring here: `Running ENG build: no pre-dexopt` on line
103 of the same capture only sets `SCAN_NO_DEX` for the `/system/app` scan. It
does not gate this loop, which is why the error appears despite it.

The failure cannot heal, so all of that runs on every boot, forever.

### What it actually cost, stated honestly

Less than the paragraph above makes it sound, and the difference matters.

The two log lines are **35 ms** apart, so this was never a boot-time problem.
And the prune found nothing to prune: there is not one `Pruning dalvik file`
line in the capture, because this build has no `/data/app` directory at all.

What it really was is a permanent error in every log -- the kind that costs
attention on every future capture -- and a live tripwire. The first app ever
installed to `/data` would silently lose its optimised dex on every boot after
the one that installed it, and the cause would be a jar that has nothing to do
with it.

### Why installd's open() fails is still unexplained

installd's source is not in this tree; the string `for output` appears nowhere
in it. That half is unproven and stays unproven. It did not need solving:
nothing in `init.rc` or in any `.rc`, `.sh` or `.xml` references `hello.jar`,
and only `scripts/build_hello_dex.sh` produces it, which no other script
invokes. It is the Dalvik smoketest from 2026-08-03 and it did its job then --
it proved the VM executes real bytecode on hardware.

### What was changed

Deleted from **both** staging sources: `rootfs_overlay/system/framework/` and
`output/target/system/framework/`. Buildroot's target directory is additive, so
deleting from the overlay alone would have left the file in the image. The
sync's `--delete` then took it off both cards.

`build_hello_dex.sh` now installs to `build/hello/fakeroot` instead of the
shipping overlay, **in both copies of the script** -- `find_script()` prefers
the Windows one, so a WSL-only fix is a fix that never runs. Re-running the
smoketest can no longer put the file back on the card. The `build/*smoke*` and
`scratch/bootsim` fakeroots keep their copies; those never ship.

No gate referenced `hello.jar` and none hardcodes a file count, so nothing had
to be repaired. `verify_release_artifacts.sh`: ALL OK.

### The services.jar dep-signature lines in that same capture are stale

`DexOpt: mismatch dep signature for
'/data/dalvik-cache/system@framework@services.jar@classes.dex'` appears seven
times in the same log, with `source file mod time mismatch` lines beside it.
**Do not chase it from this capture.** The capture is 09-12 **04:48**; the
staged `system@framework@services.jar@classes.dex` is dated 09-12 **12:09**.
The capture predates the dexpreopt rebuild by about seven hours, so those lines
describe a card state that no longer exists. `jar_dexdep.py` reports every
bundled odex `source/deps=current` against current staging.

If those lines reappear in a capture taken *after* a flash of md5
`5709f20727c5cbb112fc959e203b7d2e`, that is a real defect worth a session. From
this capture it is noise, and it looks exactly like the hello.jar error sitting
forty lines above it, which is the trap.

"""

anchor = "## 4. Known blocked\n"
assert anchor in doc, "section 4 anchor missing"
assert "3.15 hello.jar" not in doc, "3.15 already present"
doc = doc.replace(anchor, section + anchor, 1)

assert doc != orig, "unchanged"
io.open(PATH, "w", encoding="utf-8", newline="\n").write(doc)
print("patched " + PATH)
