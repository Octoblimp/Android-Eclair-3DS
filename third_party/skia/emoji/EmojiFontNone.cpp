/*
 * Copyright 2009, The Android Open Source Project
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *  * Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *  * Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
 * EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL APPLE COMPUTER, INC. OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 * PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 * OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/*  EmojiFont with no emoji font behind it.
 *
 *  emoji/EmojiFont.cpp is the real thing, and it cannot be built here: it
 *  includes EmojiFactory.h, the carrier PUA factory interface from
 *  frameworks/opt/emoji, which was never fetched.  (gmoji_pua_table.h sits
 *  next to this file, but it is only the codepoint list -- every glyph behind
 *  it comes from the factory.)  EmojiFont.cpp's own answer to a missing
 *  factory is already written down -- get_emoji_factory()
 *  returns NULL when no implementation is installed, IsAvailable() reports
 *  false, and every caller in WebCore is guarded on IsAvailable() before it
 *  asks for a glyph.  This file is that path and only that path, so the four
 *  entry points resolve and text renders through the ordinary font stack.
 *
 *  It is not a stub standing in for work that is owed.  Restoring real emoji
 *  means fetching frameworks/opt/emoji and building emoji/EmojiFont.cpp
 *  instead of this file; nothing else here would change.
 */

#include "EmojiFont.h"

class SkCanvas;
class SkPaint;

namespace android {

bool EmojiFont::IsAvailable() {
    return false;
}

uint16_t EmojiFont::UnicharToGlyph(int32_t) {
    /*  0 means "no matching emoji form".  Since no glyph ID this returns can
        ever be >= kGlyphBase, IsEmojiGlyph() -- which is inline in the header
        and so is not ours to answer -- stays false for every glyph, and the
        two functions below are unreachable in practice.
     */
    return 0;
}

SkScalar EmojiFont::GetAdvanceWidth(uint16_t, const SkPaint&) {
    return 0;
}

void EmojiFont::Draw(SkCanvas*, uint16_t, SkScalar, SkScalar, const SkPaint&) {
}

}
