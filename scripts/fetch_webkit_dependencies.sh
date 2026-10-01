#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LIBXML2="$ROOT/third_party/libxml2"
LIBXML2_COMMIT=60a4c356ee9ce5e9ccb23347c0381f0436192691
LIBXML2_URL=https://android.googlesource.com/platform/external/libxml2

if [ ! -d "$LIBXML2/.git" ]; then
    test ! -e "$LIBXML2" || {
        echo "fetch_webkit_dependencies: non-git path already exists: $LIBXML2" >&2
        exit 1
    }
    git clone --filter=blob:none --no-checkout "$LIBXML2_URL" "$LIBXML2"
fi

git -C "$LIBXML2" fetch --depth=1 origin "$LIBXML2_COMMIT"
git -C "$LIBXML2" checkout --detach "$LIBXML2_COMMIT"
actual=$(git -C "$LIBXML2" rev-parse HEAD)
test "$actual" = "$LIBXML2_COMMIT" || {
    echo "fetch_webkit_dependencies: libxml2 identity mismatch: $actual" >&2
    exit 1
}
echo "fetch_webkit_dependencies: libxml2 $actual"
