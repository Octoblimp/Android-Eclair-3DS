#!/usr/bin/env python3
"""Apply bounded compatibility fixes for building Eclair WebKit with GCC 14.

The generated bindings header only forward-declares ``JSNode`` at the helper
definition, so modern GCC cannot prove the old implicit JSNode* -> JSCell*
conversion.  The object is a JSCell-derived wrapper by construction; make the
historical representation conversion explicit without changing ownership or
runtime behavior.
"""

from __future__ import annotations

import argparse
from pathlib import Path


DOM_RELATIVE = Path("WebCore/bindings/js/JSDOMBinding.h")
DOM_OLD = """        if (JSNode* wrapper = getCachedDOMNodeWrapper(node->document(), node))
            return wrapper;
        return createDOMNodeWrapper<WrapperClass>(exec, globalObject, node);
"""
DOM_NEW = """        if (JSNode* wrapper = getCachedDOMNodeWrapper(node->document(), node))
            return JSC::JSValue(reinterpret_cast<JSC::JSCell*>(wrapper));
        return JSC::JSValue(reinterpret_cast<JSC::JSCell*>(
            createDOMNodeWrapper<WrapperClass>(exec, globalObject, node)));
"""
FONT_RELATIVE = Path("WebCore/css/CSSFontSelector.cpp")
FONT_OLD = """        std::stable_sort(candidateFontFaces.begin(), candidateFontFaces.end(), compareFontFaces);
"""
FONT_NEW = """        std::stable_sort<CSSFontFace>(candidateFontFaces.begin(), candidateFontFaces.end(), compareFontFaces);
"""
RANGE_RELATIVE = Path("WebCore/dom/Range.cpp")
RANGE_OLD = """    // Not strictly legal C++, but in practice this can happen, and this check works
    // fine with GCC to detect such cases and return false rather than crashing.
    if (!&a || !&b)
        return false;
"""
RANGE_NEW = """    // References cannot legally be null. Modern GCC diagnoses the historical
    // null-reference extension as an always-false comparison under -Werror=address.
"""
RENDER_LAYER_RELATIVE = Path("WebCore/rendering/RenderLayer.cpp")
RENDER_LAYER_OLD = """    if (m_posZOrderList)
        std::stable_sort(m_posZOrderList->begin(), m_posZOrderList->end(), compareZIndex);

    if (m_negZOrderList)
        std::stable_sort(m_negZOrderList->begin(), m_negZOrderList->end(), compareZIndex);
"""
RENDER_LAYER_NEW = """    if (m_posZOrderList)
        std::stable_sort<RenderLayer*>(m_posZOrderList->begin(), m_posZOrderList->end(), compareZIndex);

    if (m_negZOrderList)
        std::stable_sort<RenderLayer*>(m_negZOrderList->begin(), m_negZOrderList->end(), compareZIndex);
"""
FIND_CANVAS_RELATIVE = Path("WebKit/android/nav/FindCanvas.cpp")
FIND_CANVAS_OLD = "GlyphSet::GlyphSet& GlyphSet::operator=(GlyphSet& src) {"
FIND_CANVAS_NEW = "GlyphSet& GlyphSet::operator=(GlyphSet& src) {"
JSC_ERROR_DECL_OLD = "int jscyyerror(const char*);"
JSC_ERROR_DECL_NEW = "int jscyyerror(void*, void*, const char*);"
JSC_ERROR_BODY_OLD = "int yyerror(const char *)"
JSC_ERROR_BODY_NEW = "int yyerror(void*, void*, const char *)"
CSS_ERROR_OLD = "static inline int cssyyerror(const char*)"
CSS_ERROR_NEW = "static inline int cssyyerror(void*, const char*)"
XPATH_ERROR_OLD = "static void xpathyyerror(const char*) { }"
XPATH_ERROR_NEW = "static void xpathyyerror(void*, const char*) { }"
JSC_GRAMMAR_RELATIVE = Path("JavaScriptCore/parser/Grammar.y")
JSC_GRAMMAR_OLD = """#define YYPARSE_PARAM globalPtr
#define YYLEX_PARAM globalPtr
"""
JSC_GRAMMAR_NEW = """/* N3DS_MODERN_BISON_PARAMS */
"""
CSS_GRAMMAR_RELATIVE = Path("WebCore/css/CSSGrammar.y")
CSS_GRAMMAR_OLD = """// FIXME: Replace with %parse-param { CSSParser* parser } once we can depend on bison 2.x
#define YYPARSE_PARAM parser
#define YYLEX_PARAM parser
"""
CSS_GRAMMAR_NEW = """/* N3DS_MODERN_BISON_PARAMS */
"""
XPATH_GRAMMAR_RELATIVE = Path("WebCore/xml/XPathGrammar.y")
XPATH_GRAMMAR_OLD = """#define YYPARSE_PARAM parserParameter
#define PARSER static_cast<Parser*>(parserParameter)
"""
XPATH_GRAMMAR_NEW = """/* N3DS_MODERN_BISON_PARAMS */
#define PARSER static_cast<Parser*>(parserParameter)
"""
JSC_PARAM_MOVE_OLD = """%parse-param { void* globalPtr }
%lex-param { void* globalPtr }
"""
JSC_PARAM_MOVE_NEW = """/* N3DS_MODERN_BISON_PARAMS */
"""
JSC_DECLARATION_OLD = """%pure_parser

%{
"""
JSC_DECLARATION_NEW = """%pure_parser
%parse-param { void* globalPtr }
%lex-param { void* globalPtr }

%{
"""
CSS_PARAM_MOVE_OLD = """%parse-param { void* parser }
%lex-param { void* parser }
"""
CSS_PARAM_MOVE_NEW = """/* N3DS_MODERN_BISON_PARAMS */
"""
CSS_DECLARATION_OLD = """%}

%pure_parser
"""
CSS_DECLARATION_NEW = """%}

%pure_parser
%parse-param { void* parser }
%lex-param { void* parser }
"""
XPATH_PARAM_MOVE_OLD = """%parse-param { void* parserParameter }
#define PARSER static_cast<Parser*>(parserParameter)
"""
XPATH_PARAM_MOVE_NEW = """/* N3DS_MODERN_BISON_PARAMS */
#define PARSER static_cast<Parser*>(parserParameter)
"""
XPATH_DECLARATION_OLD = """%}

%pure_parser

%union
"""
XPATH_DECLARATION_NEW = """%}

%pure_parser
%parse-param { void* parserParameter }

%union
"""

PATCHES = (
    (DOM_RELATIVE, DOM_OLD, DOM_NEW),
    (FONT_RELATIVE, FONT_OLD, FONT_NEW),
    (RANGE_RELATIVE, RANGE_OLD, RANGE_NEW),
    (RENDER_LAYER_RELATIVE, RENDER_LAYER_OLD, RENDER_LAYER_NEW),
    (FIND_CANVAS_RELATIVE, FIND_CANVAS_OLD, FIND_CANVAS_NEW),
    (JSC_GRAMMAR_RELATIVE, JSC_ERROR_DECL_OLD, JSC_ERROR_DECL_NEW),
    (JSC_GRAMMAR_RELATIVE, JSC_ERROR_BODY_OLD, JSC_ERROR_BODY_NEW),
    (CSS_GRAMMAR_RELATIVE, CSS_ERROR_OLD, CSS_ERROR_NEW),
    (XPATH_GRAMMAR_RELATIVE, XPATH_ERROR_OLD, XPATH_ERROR_NEW),
    (JSC_GRAMMAR_RELATIVE, JSC_GRAMMAR_OLD, JSC_GRAMMAR_NEW),
    (CSS_GRAMMAR_RELATIVE, CSS_GRAMMAR_OLD, CSS_GRAMMAR_NEW),
    (XPATH_GRAMMAR_RELATIVE, XPATH_GRAMMAR_OLD, XPATH_GRAMMAR_NEW),
)


def replace_exact(source: str, old: str, new: str, target: Path) -> tuple[str, bool]:
    old_count = source.count(old)
    # Several compatibility replacements intentionally retain the old text as
    # part of the expanded new block.  Recognize that form before counting the
    # embedded old anchor.  Conversely, FindCanvas's corrected return type is
    # a substring of the broken spelling, so that case must still replace old.
    if old in new and new in source:
        return source, False
    if old_count == 1:
        return source.replace(old, new), True
    if old_count > 1:
        label = old.splitlines()[0]
        raise SystemExit(
            f"webkit modern-toolchain patch anchor duplicated ({label}): {target}"
        )
    if new in source:
        return source, False
    label = old.splitlines()[0]
    raise SystemExit(
        f"webkit modern-toolchain patch anchor mismatch ({label}): {target}"
    )


def normalize_grammar_parameters(
    source: str, parameters: tuple[str, ...], target: Path
) -> tuple[str, bool]:
    """Place exactly one Bison parameter block after one `%pure_parser`."""
    lines = [
        line
        for line in source.splitlines()
        if not line.startswith("%parse-param ") and not line.startswith("%lex-param ")
    ]
    pure_indexes = [index for index, line in enumerate(lines) if line == "%pure_parser"]
    if len(pure_indexes) != 1:
        raise SystemExit(
            f"webkit grammar expected one %pure_parser, found {len(pure_indexes)}: {target}"
        )
    insert_at = pure_indexes[0] + 1
    lines[insert_at:insert_at] = list(parameters)
    normalized = "\n".join(lines) + "\n"
    return normalized, normalized != source


def patch(root: Path) -> bool:
    changed = False
    for relative, old, new in PATCHES:
        target = root / relative
        source = target.read_text(encoding="utf-8")
        source, replaced = replace_exact(source, old, new, target)
        if replaced:
            target.write_text(source, encoding="utf-8")
            changed = True
    grammars = (
        (JSC_GRAMMAR_RELATIVE,
         ("%parse-param { void* globalPtr }", "%lex-param { void* globalPtr }")),
        (CSS_GRAMMAR_RELATIVE,
         ("%parse-param { void* parser }", "%lex-param { void* parser }")),
        (XPATH_GRAMMAR_RELATIVE, ("%parse-param { void* parserParameter }",)),
    )
    for relative, parameters in grammars:
        target = root / relative
        source = target.read_text(encoding="utf-8")
        source, normalized = normalize_grammar_parameters(source, parameters, target)
        if normalized:
            target.write_text(source, encoding="utf-8")
            changed = True
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path("third_party/webkit"),
        help="WebKit source root",
    )
    args = parser.parse_args()
    changed = patch(args.root.resolve())
    print("webkit_modern_toolchain: " + ("patched" if changed else "already patched"))


if __name__ == "__main__":
    main()
