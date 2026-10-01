#!/usr/bin/env python3
"""Idempotence and fail-closed checks for each WebKit compatibility edit."""

from pathlib import Path

from patch_webkit_modern_toolchain import (
    PATCHES,
    normalize_grammar_parameters,
    replace_exact,
)
from build_webkit import render_commands


root = Path(__file__).resolve().parents[1]
for wrapper in ("webkit_gxx.sh", "webkit_gcc.sh"):
    wrapper_text = (root / "scripts" / wrapper).read_text(encoding="utf-8")
    assert "third_party/libhardware/include" in wrapper_text


for index, (_relative, old, new) in enumerate(PATCHES):
    target = Path("fixture") / str(index)
    original = "prefix\n" + old + "suffix\n"
    patched, changed = replace_exact(original, old, new, target)
    assert changed is True
    assert patched == original.replace(old, new)
    repeated, changed = replace_exact(patched, old, new, target)
    assert changed is False
    assert repeated == patched

try:
    replace_exact("unexpected source\n", "required anchor\n", "fixed\n", Path("bad"))
except SystemExit as error:
    assert "anchor mismatch" in str(error)
else:
    raise AssertionError("unknown WebKit source must fail closed")

grammar = "%parse-param { void* old }\n%lex-param { void* old }\n%pure_parser\n\n%{\n"
parameters = ("%parse-param { void* parser }", "%lex-param { void* parser }")
normalized, changed = normalize_grammar_parameters(grammar, parameters, Path("grammar"))
assert changed is True
assert normalized.count("%pure_parser") == 1
assert normalized.count(parameters[0]) == 1
assert normalized.count(parameters[1]) == 1
assert normalized.index("%pure_parser") < normalized.index(parameters[0])
repeated, changed = normalize_grammar_parameters(normalized, parameters, Path("grammar"))
assert changed is False
assert repeated == normalized

rendered = render_commands(
    "rm -f build/webkit_intermediates/WebCore/CSSGrammar.hpp\n"
    '"$GXX" -MD -o build/webkit_intermediates/WebKit/android/jni/WebCoreJni.o '
    "third_party/webkit/WebKit/android/jni/WebCoreJni.cpp\n",
    incremental=True,
)
assert 'test -s "build/webkit_intermediates/WebCore/CSSGrammar.hpp"' in rendered
assert "rm -f" not in rendered
assert "WebCoreJniOnLoad.o" in rendered
assert "WebCoreJniOnLoad.cpp" in rendered

print("webkit_modern_toolchain: PASS")
