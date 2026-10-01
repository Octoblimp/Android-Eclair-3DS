#!/usr/bin/env python3
"""Compile an AOSP LatinIME word list into the Eclair (android-2.0) binary
trie that third_party/latinime/dictionary/src/dictionary.cpp reads.

AOSP Eclair and Froyo only ever shipped a 34-byte stub res/raw/main.dict (the
single word "Android"); the real dictionaries lived in a vendor tree.  Jelly
Bean published Google's frequency lists (dictionaries/en_us_wordlist.xml,
Apache 2.0, 0..255 frequencies -- the same one-byte scale this format uses),
so build the trie from that.

Format (dictionary.h / dictionary.cpp, no header, big-endian):
  node   := count:u8  child[count]
  child  := char  flags_addr  [freq:u8 if terminal]
  char   := u8 (< 0xFF)  |  0xFF hi:u8 lo:u8
  flags_addr := 0x80 terminal | 0x40 has-children | addr[21:16]  (+2 bytes addr[15:0])
                (a single byte when there are no children)
Addresses are absolute byte offsets of the child node; 22 bits -> 4 MB max.

N3DS_LATINIME_REAL_DICT
"""
import argparse
import gzip
import re
import sys

DROP_FLAGS = {"offensive", "nonword", "babytalk", "n", "e"}
MAX_WORD = 47          # BinaryDictionary.MAX_WORD_LENGTH 48 incl. terminator
ADDRESS_MAX = 0x3FFFFF


def read_words(path, min_freq):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        text = f.read()
    best = {}
    pat = re.compile(r'<w f="(\d+)"(?: flags="([^"]*)")?[^>]*>([^<]+)</w>')
    for m in pat.finditer(text):
        freq, flags, word = int(m.group(1)), m.group(2) or "", m.group(3)
        word = (word.replace("&amp;", "&").replace("&apos;", "'")
                    .replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">"))
        if freq < min_freq or flags in DROP_FLAGS:
            continue
        if not word or len(word) > MAX_WORD or any(ord(c) > 0xFFFF for c in word):
            continue
        freq = min(freq, 255)
        if best.get(word, -1) < freq:
            best[word] = freq
    return best


class Node(object):
    __slots__ = ("children", "freq", "offset", "size")

    def __init__(self):
        self.children = {}
        self.freq = None
        self.offset = 0
        self.size = 0


def build_trie(words):
    root = Node()
    # Insert most frequent first so each node's children come out in roughly
    # descending frequency order (dict preserves insertion order).
    for word, freq in sorted(words.items(), key=lambda kv: (-kv[1], kv[0])):
        n = root
        for c in word:
            nxt = n.children.get(c)
            if nxt is None:
                nxt = n.children[c] = Node()
            n = nxt
        n.freq = freq
    return root


def char_len(c):
    return 1 if ord(c) < 0xFF else 3


def layout(root):
    """Depth-first pre-order: a node block, then each child's subtree.
    Entry sizes depend only on has-children/terminal, so every offset is
    known in one pass (no relaxation)."""
    order = []
    stack = [root]
    while stack:
        n = stack.pop()
        if len(n.children) > 255:
            raise SystemExit("node with %d children (> 255)" % len(n.children))
        size = 1
        for c, ch in n.children.items():
            size += char_len(c) + (3 if ch.children else 1) + (1 if ch.freq is not None else 0)
        n.size = size
        order.append(n)
        kids = [ch for ch in n.children.values() if ch.children]
        stack.extend(reversed(kids))
    off = 0
    for n in order:
        n.offset = off
        off += n.size
    if off - 1 > ADDRESS_MAX:
        raise SystemExit("dictionary is %d bytes, over the 22-bit address space" % off)
    return order, off


def serialise(order, total):
    out = bytearray(total)
    for n in order:
        p = n.offset
        out[p] = len(n.children)
        p += 1
        for c, ch in n.children.items():
            o = ord(c)
            if o < 0xFF:
                out[p] = o
                p += 1
            else:
                out[p] = 0xFF
                out[p + 1] = (o >> 8) & 0xFF
                out[p + 2] = o & 0xFF
                p += 3
            flags = 0x80 if ch.freq is not None else 0
            if ch.children:
                a = ch.offset
                assert 0 < a <= ADDRESS_MAX
                out[p] = flags | 0x40 | ((a >> 16) & 0x3F)
                out[p + 1] = (a >> 8) & 0xFF
                out[p + 2] = a & 0xFF
                p += 3
            else:
                out[p] = flags
                p += 1
            if ch.freq is not None:
                out[p] = ch.freq
                p += 1
        assert p == n.offset + n.size
    return bytes(out)


# --- independent reader, mirroring dictionary.cpp, used as a self-check ----
def _child_iter(d, pos):
    count = d[pos]
    pos += 1
    for _ in range(count):
        c = d[pos]
        pos += 1
        if c == 0xFF:
            c = (d[pos] << 8) | d[pos + 1]
            pos += 2
        term = (d[pos] & 0x80) != 0
        if d[pos] & 0x40:
            addr = ((d[pos] & 0x3F) << 16) | (d[pos + 1] << 8) | d[pos + 2]
            pos += 3
        else:
            addr = 0
            pos += 1
        freq = None
        if term:
            freq = d[pos]
            pos += 1
        yield chr(c), term, addr, freq


def lookup(d, word):
    pos = 0
    for i, ch in enumerate(word):
        for c, term, addr, freq in _child_iter(d, pos):
            if c == ch:
                if i == len(word) - 1:
                    return freq if term else None
                if not addr:
                    return None
                pos = addr
                break
        else:
            return None
    return None


def walk(d, pos=0, prefix=""):
    for c, term, addr, freq in _child_iter(d, pos):
        if term:
            yield prefix + c, freq
        if addr:
            for x in walk(d, addr, prefix + c):
                yield x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wordlist")
    ap.add_argument("out")
    ap.add_argument("--min-freq", type=int, default=30)
    a = ap.parse_args()
    sys.setrecursionlimit(10000)

    words = read_words(a.wordlist, a.min_freq)
    order, total = layout(build_trie(words))
    data = serialise(order, total)

    # Self-check: every word reads back with its frequency, and nothing else.
    got = dict(walk(data))
    if got != words:
        missing = [w for w in words if got.get(w) != words[w]][:10]
        extra = [w for w in got if w not in words][:10]
        raise SystemExit("self-check failed: missing/wrong %r extra %r" % (missing, extra))
    for w in ("the", "hello", "keyboard", "don't", "January", "website"):
        if w in words and lookup(data, w) != words[w]:
            raise SystemExit("lookup(%r) failed" % w)

    with open(a.out, "wb") as f:
        f.write(data)
    print("make_latinime_dict: %d words, %d nodes, %d bytes -> %s (N3DS_LATINIME_REAL_DICT)"
          % (len(words), len(order), len(data), a.out))


if __name__ == "__main__":
    main()
