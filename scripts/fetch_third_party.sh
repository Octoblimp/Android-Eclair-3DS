#!/bin/bash
# Recreate the third_party/ checkouts this repository carries only as patches.
#
# patches/MANIFEST.tsv names, for each tree, the upstream repository and the
# exact commit the port is based on (the Linux kernel, arm9linuxfw and
# firm_linux_loader from linux-3ds; bionic, dalvik, frameworks/base and the
# other projects from AOSP Eclair). Each is fetched at that commit and
# patches/<name>.diff is applied on top as working-tree changes.
#
# The diffs are text only. Binary files they leave out are listed in
# patches/BINARIES.tsv: Nintendo firmware is user-supplied (README, Firmware),
# and the rest are build outputs and media that the build scripts regenerate
# and the release zip carries.
#
#   scripts/fetch_third_party.sh                 # every tree
#   scripts/fetch_third_party.sh third_party/linux
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/patches/MANIFEST.tsv"
ONLY="${1:-}"

test -f "$MANIFEST" || { echo "FATAL: $MANIFEST not found" >&2; exit 1; }

# Every field is non-empty ("-" for none): `read` collapses consecutive tabs.
tail -n +2 "$MANIFEST" | while IFS="$(printf '\t')" read -r path url base branch patch _text _bin; do
    [ -n "$ONLY" ] && [ "$path" != "$ONLY" ] && continue
    [ "$branch" = - ] && branch=""
    dest="$ROOT/$path"
    if [ -e "$dest/.git" ]; then
        echo "skip $path (already checked out)"
        continue
    fi
    echo "=== $path at ${base:0:12} from $url"
    mkdir -p "$dest"
    git -C "$dest" init -q
    git -C "$dest" remote add origin "$url"
    if ! git -C "$dest" fetch -q --depth 1 origin "$base"; then
        # A server that refuses a bare commit id: fetch the branch and look.
        echo "  fetch by commit id refused; fetching ${branch:-all branches}"
        if [ -n "$branch" ]; then
            git -C "$dest" fetch -q origin "$branch"
        else
            git -C "$dest" fetch -q origin
        fi
        git -C "$dest" cat-file -e "$base^{commit}" || {
            echo "FATAL: commit $base is not on $url" >&2
            exit 1
        }
    fi
    git -C "$dest" -c advice.detachedHead=false checkout -q "$base"
    if [ "$patch" != "-" ]; then
        git -C "$dest" apply --whitespace=nowarn "$ROOT/patches/$patch"
        echo "  applied patches/$patch"
    fi
    if [ "$path" = third_party/linux ] && [ -f "$ROOT/patches/linux.config" ]; then
        # build_kernel.sh builds with the tree's .config as it stands.
        cp "$ROOT/patches/linux.config" "$dest/.config"
        echo "  installed patches/linux.config as .config"
    fi
done
echo "done. Next: README, Firmware, then Building."
