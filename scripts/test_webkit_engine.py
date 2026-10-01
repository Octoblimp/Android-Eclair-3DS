#!/usr/bin/env python3
"""Release-contract checks for restoring the real Eclair WebKit engine."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    candidate = ROOT / path
    assert candidate.is_file(), f"missing {path}"
    return candidate.read_text(encoding="utf-8")


driver = text("scripts/build_webkit.py")
launcher = text("scripts/build_webkit.sh")
framework = text("scripts/build_framework_jar.sh")
browser = text("scripts/build_browser.sh")
verifier = text("scripts/verify_release_artifacts.sh")

assert len(launcher) < 4096, "WebKit launcher must stay reviewable"
assert "build_webkit.py" in launcher
assert "webkit_commands.sh" in driver
assert "webkit_gxx.sh" in driver
assert "libwebcore.so" in driver, "driver must build/stage the JNI shared engine"

assert 'core/java/android/webkit' not in framework, (
    "framework build still excludes android.webkit"
)
assert "android/net/http/RequestQueue.java" not in framework, (
    "framework build still excludes WebKit's HTTP backend"
)
assert "n3ds_src" not in browser, "Browser still compiles the basic renderer"
assert "AndroidManifest.n3ds.xml" not in browser, "Browser still uses minimal manifest"
assert "libwebcore.so" in verifier, "release verifier does not require native WebKit"
assert "still requires the unported WebKit runtime" not in verifier

print("webkit_engine: PASS")
