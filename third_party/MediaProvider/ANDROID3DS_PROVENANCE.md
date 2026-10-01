# MediaProvider source provenance

Official AOSP `platform/packages/providers/MediaProvider`, fetched 2026-09-30
from https://android.googlesource.com/platform/packages/providers/MediaProvider
at `android-2.0_r1`, commit `f432080cd4db6693806f4d54b52a35665d9884d7`.

Matches the canonical Android framework tag. Original sources and license
headers remain intact. `scripts/build_media_provider.sh` changes only its
disposable build copy: it removes the MediaScannerReceiver and
MediaScannerService declarations from the manifest and makes
`getCompressedAlbumArt()` survive the missing native MediaScanner (this image
has no libmedia_jni, so any scan would kill android.process.media). It signs
the APK with the same certificate as Camera.apk, because both declare the
`android.media` shared user ID. This provides the `media` content provider the
stock Camera app saves photos into and its gallery reads back.
