"""Build fix: this toolchain's host g++ can't build kernel GCC plugins.

arch/arm/Kconfig unconditionally does 'select HAVE_GCC_PLUGINS' -- that's
just ARM architecturally claiming the plugin infrastructure is supported,
not a real probe of whether the build machine's g++ can actually compile
one. This toolchain's plugin headers (system.h) pull in <gmp.h> and
require -std=gnu++11, neither of which this g++ install provides, so any
config that touches GCC_PLUGINS (e.g. STACKPROTECTOR_PER_TASK, which is
implemented as an ARM-specific gcc plugin) fails at
scripts/gcc-plugins/arm_ssp_per_task_plugin.so with a hard compile error,
not a soft/skippable one.

Also: 'make oldconfig'/whatever syncconfig path 'make zImage' invokes
re-derives GCC_PLUGINS to its Kconfig default (y, since HAVE_GCC_PLUGINS
is unconditionally selected) on every single sync, ignoring an explicit
"# CONFIG_GCC_PLUGINS is not set" written into .config by hand or via
scripts/config --disable -- so disabling it in .config doesn't stick.
Removing the select is what actually makes it stick, since then
HAVE_GCC_PLUGINS itself is never true and GCC_PLUGINS has no way to
become visible/selectable regardless of what .config says.
"""
from a3ds_paths import A3DS_ROOT

path = f"{A3DS_ROOT}/third_party/linux/arch/arm/Kconfig"

with open(path) as f:
    c = f.read()

old = "\tselect HAVE_GCC_PLUGINS\n"
n = c.count(old)
assert n == 1, f"expected exactly 1 match, found {n}"

new = (
    "\t# select HAVE_GCC_PLUGINS -- disabled: this toolchain's host g++\n"
    "\t# can't build kernel GCC plugins (missing gmp.h / -std=gnu++11 in\n"
    "\t# its plugin headers), so anything that pulls in GCC_PLUGINS (e.g.\n"
    "\t# STACKPROTECTOR_PER_TASK) fails scripts/gcc-plugins/*.so with a\n"
    "\t# hard compile error, not a soft skip.\n"
)

c = c.replace(old, new)
with open(path, "w") as f:
    f.write(c)
print("OK")
