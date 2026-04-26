"""
Regenerate the test-suite font subsets from their full counterparts.

The full fonts in python/tests/fonts/ are too large for fast tests:
    InterVariable.ttf            ~880 KB
    Inter-Regular.otf            ~610 KB
    NotoSansJP-VariableFont.ttf  ~9.1 MB
    NotoSansCJKjp-Regular.otf    ~16 MB

This script slices each one down to the same curated codepoint set so
that every TTF/OTF subset committed to the repo can be re-derived from
the upstream sources at any time. Keeping coverage identical across all
four subsets also avoids non-cmap-mapped Latin glyphs leaking into a CFF
CID merge — fontTools' charset format 0 encoder requires every glyph
name to be ``cid#####`` after the merge, which only holds when the
Latin source has nothing to add beyond what the JP base already covers.

Run:
    python3 python/tests/generate_test_subsets.py
"""

import os
import sys

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont


FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# Curated coverage shared by all four subsets. Chosen for tests, not for
# real-world rendering: a hand-picked slice of printable ASCII plus a few
# Hiragana and CJK ideographs is enough to exercise every code path in
# the merge engine without bloating the test data.
_ASCII = " !()*+,-./0123456789:;=?ABCDEFGHIJKLMNOPQRSTUVWXYZ[]abcdefghijklmnopqrstuvwxyz{}"
_HIRAGANA = "あいうえおかきくけこ"
_CJK = "京字東植混漢"
CODEPOINTS = sorted({ord(c) for c in _ASCII + _HIRAGANA + _CJK})


# (source, destination, drop_layout) for each subset to regenerate.
SUBSETS = [
    (
        os.path.join(FONTS, "Inter-4.1", "InterVariable.ttf"),
        os.path.join(FONTS, "Inter-4.1", "Inter-subset.ttf"),
        False,
    ),
    (
        os.path.join(FONTS, "Inter-4.1", "Inter-Regular.otf"),
        os.path.join(FONTS, "Inter-4.1", "Inter-subset.otf"),
        # The CFF CID merge cannot accommodate non-cmap-mapped Latin
        # glyph alternates (their non-CID names break charset format 0),
        # so the Inter CFF subset drops layout features entirely.
        True,
    ),
    (
        os.path.join(FONTS, "Noto_Sans_JP", "NotoSansJP-VariableFont_wght.ttf"),
        os.path.join(FONTS, "Noto_Sans_JP", "NotoSansJP-subset.ttf"),
        False,
    ),
    (
        os.path.join(FONTS, "NotoSansCJKjp", "NotoSansCJKjp-Regular.otf"),
        os.path.join(FONTS, "NotoSansCJKjp", "NotoSansCJKjp-subset.otf"),
        False,
    ),
]


def _subset(src: str, dst: str, drop_layout: bool) -> tuple[int, int]:
    font = TTFont(src)
    options = Options()
    options.layout_features = [] if drop_layout else ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_outline = True
    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=CODEPOINTS)
    subsetter.subset(font)
    font.save(dst)
    return os.path.getsize(dst), len(font.getGlyphOrder())


def main() -> int:
    print(f"codepoints: {len(CODEPOINTS)} ({len(_ASCII)} ASCII + "
          f"{len(_HIRAGANA)} Hiragana + {len(_CJK)} CJK)")
    missing = [src for src, _, _ in SUBSETS if not os.path.exists(src)]
    if missing:
        for m in missing:
            print(f"error: {m} not found", file=sys.stderr)
        return 1
    for src, dst, drop_layout in SUBSETS:
        size, glyphs = _subset(src, dst, drop_layout)
        rel = os.path.relpath(dst, FONTS)
        print(f"  wrote fonts/{rel}  ({size:,} bytes, {glyphs} glyphs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
