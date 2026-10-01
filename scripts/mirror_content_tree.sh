#!/bin/bash
# Copy one content/<name> app source tree from the WSL repo to the Windows
# tree, then prove the two are byte-identical.
#
# There are two content/ trees and they are used for different things: the
# build scripts read the Windows one (that is where find_script() and the
# older build_*.sh hard-code), while only $ANDROID3DS_ROOT/content is
# tracked by a repo that can be pushed.  A change made in one tree and not the
# other is either a build reading stale source or a change that never gets
# committed, and neither failure announces itself.  The WSL tree is the source
# of truth here because it is the one that can be reviewed.
#
# Usage: mirror_content_tree.sh mictest [othername ...]
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
WIN="${ANDROID3DS_WIN}/content"

test $# -gt 0 || { echo "usage: $(basename "$0") <app> [app ...]" >&2; exit 1; }

for name in "$@"; do
    src="$ROOT/content/$name"
    test -d "$src" || { echo "mirror_content_tree: no such tree $src" >&2; exit 1; }
    mkdir -p "$WIN"
    rm -rf "${WIN:?}/$name"
    cp -a "$src" "$WIN/$name"
    # cp -a onto DrvFs cannot preserve modes, so compare content only.
    diff -r "$src" "$WIN/$name"
    echo "mirrored $name: $(find "$src" -type f | wc -l) files, trees identical"
done
