"""Shared paths, helpers, and merge harnesses for the merge-engine tests."""

import io
import json
import os
import sys
import tempfile

import pytest

# Put the python/ directory on sys.path so `import merge_fonts` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

import merge_fonts as mf

# Silence merge progress output during tests.
mf.progress = lambda *a: None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FONTS = os.path.join(os.path.dirname(__file__), "fonts")

# Latin sources. The "_FULL" variants are only needed by the few tests
# that exercise large-coverage edge cases — see TestLargeCIDFont and
# TestSharedGlyphCollateral.
EN_VAR = os.path.join(FONTS, "Inter-4.1", "Inter-subset.ttf")
EN_FULL = os.path.join(FONTS, "Inter-4.1", "InterVariable.ttf")
EN_CFF = os.path.join(FONTS, "Inter-4.1", "Inter-subset.otf")
EN_CFF_FULL = os.path.join(FONTS, "Inter-4.1", "Inter-Regular.otf")

# Japanese bases.
JP_VAR = os.path.join(FONTS, "Noto_Sans_JP", "NotoSansJP-subset.ttf")
JP_FULL_VAR = os.path.join(FONTS, "Noto_Sans_JP", "NotoSansJP-VariableFont_wght.ttf")
JP_STATIC = os.path.join(FONTS, "Noto_Sans_JP", "NotoSansJP-Regular.ttf")
JP_OTF = os.path.join(FONTS, "NotoSansCJKjp", "NotoSansCJKjp-subset.otf")
JP_OTF_FULL = os.path.join(FONTS, "NotoSansCJKjp", "NotoSansCJKjp-Regular.otf")

# Other typefaces used by single-purpose tests.
PLAYWRITE = os.path.join(FONTS, "Playwrite_IE", "PlaywriteIE-VariableFont_wght.ttf")
KAISEI = os.path.join(FONTS, "Kaisei_Decol", "KaiseiDecol-Regular.ttf")
# UPM-stable Latin source for kerning preservation tests (UPM = 1000, same
# as Noto Sans JP, so changes to kern values cannot be hidden behind UPM
# scaling artifacts).
TIKTOK_SANS = os.path.join(FONTS, "TikTok_Sans", "static", "TikTokSans-Regular.ttf")


# ---------------------------------------------------------------------------
# Merge harnesses
# ---------------------------------------------------------------------------

# Merges are by far the slowest part of the suite and many tests inspect the
# same configuration, so outputs are memoised (as bytes) per config for the
# whole session. Every call still gets its own TTFont, so tests may mutate it.
_MERGE_CACHE: dict = {}


def _source(path, scale=1.0, baseline=0, axes=()):
    """Build a font-source config entry; ``axes`` is ``(tag, value)`` pairs."""
    return {
        "path": path,
        "scale": scale,
        "baselineOffset": baseline,
        "axes": [{"tag": tag, "currentValue": value} for tag, value in axes],
    }


def _run_merge(config, suffix):
    """Merge ``config`` (without its export section) and return a fresh TTFont."""
    key = json.dumps(config, sort_keys=True)
    data = _MERGE_CACHE.get(key)
    if data is None:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "merged" + suffix)
            mf.merge_fonts({**config, "export": {"path": {"font": out}}})
            with open(out, "rb") as fp:
                data = fp.read()
        _MERGE_CACHE[key] = data
    return TTFont(io.BytesIO(data))


def _merge(lat_scale=1.0, lat_baseline=0, jp_scale=1.0, jp_baseline=0,
           lat_wght=400, lat_opsz=14, jp_wght=400, output_weight=None,
           output_upm=None):
    """Run a TTF Inter-subset + TTF Noto-subset merge and return the TTFont."""
    output = {"familyName": "Test"}
    if output_weight is not None:
        output["weight"] = output_weight
    if output_upm is not None:
        output["upm"] = output_upm
    return _run_merge({
        "subFont": _source(EN_VAR, lat_scale, lat_baseline,
                           [("opsz", lat_opsz), ("wght", lat_wght)]),
        "baseFont": _source(JP_VAR, jp_scale, jp_baseline, [("wght", jp_wght)]),
        "output": output,
    }, ".ttf")


def _merge_with_meta(output_family="TestMeta", output_copyright="",
                     output_ps_name=None, output_version=None, app_version=None,
                     output_manufacturer=None, output_manufacturer_url=None,
                     output_trademark=None):
    """Run merge with metadata options and return the TTFont."""
    output = {"familyName": output_family, "copyright": output_copyright}
    optional = {
        "manufacturer": output_manufacturer,
        "manufacturerURL": output_manufacturer_url,
        "trademark": output_trademark,
        "postScriptName": output_ps_name,
        "version": output_version,
    }
    output.update({k: v for k, v in optional.items() if v is not None})
    config = {
        "subFont": _source(EN_VAR, axes=[("opsz", 14), ("wght", 400)]),
        "baseFont": _source(JP_VAR, axes=[("wght", 400)]),
        "output": output,
    }
    if app_version is not None:
        config["appVersion"] = app_version
    return _run_merge(config, ".ttf")


def _merge_otf_jp(lat_scale=1.0, lat_baseline=0, jp_scale=1.0, jp_baseline=0):
    """Run merge with the CFF CID Japanese subset as base."""
    if not os.path.exists(JP_OTF):
        pytest.skip("NotoSansCJKjp-subset.otf not found")
    return _run_merge({
        "subFont": _source(EN_CFF, lat_scale, lat_baseline),
        "baseFont": _source(JP_OTF, jp_scale, jp_baseline),
        "output": {"familyName": "TestOTF"},
    }, ".otf")


def _merge_cff_to_cff(lat_scale=1.0, lat_baseline=0):
    """Merge Inter (CFF) into Noto CJK (CFF base) — CFF→CFF all the way."""
    return _run_merge({
        "subFont": _source(EN_CFF, lat_scale, lat_baseline),
        "baseFont": _source(JP_OTF),
        "output": {"familyName": "TestHint"},
    }, ".otf")


def _merge_full(exclude_codepoints=None):
    """Merge full Inter (variable TTF) into static Noto Sans JP.

    Shared by the glyph-name collision, shared-glyph collateral and
    excludeCodepoints suites, which all need full-coverage sources.
    """
    if not os.path.exists(EN_FULL) or not os.path.exists(JP_STATIC):
        pytest.skip("Full Inter / Noto Sans JP fonts not found")
    sub = _source(EN_FULL, axes=[("opsz", 14), ("wght", 400)])
    if exclude_codepoints is not None:
        sub["excludeCodepoints"] = exclude_codepoints
    return _run_merge({
        "subFont": sub,
        "baseFont": _source(JP_STATIC),
        "output": {"familyName": "TestFull"},
    }, ".ttf")


# ---------------------------------------------------------------------------
# Glyph helpers
# ---------------------------------------------------------------------------

def _get_bounds(font, glyph_name):
    """Return (xMin, yMin, xMax, yMax) for a glyph (handles composites)."""
    gs = font.getGlyphSet()
    bp = BoundsPen(gs)
    gs[glyph_name].draw(bp)
    return bp.bounds


def _cid_glyph_for_codepoint(font, codepoint):
    """Look up a CID glyph name from the cmap (CID fonts use cid#####)."""
    for table in font["cmap"].tables:
        if codepoint in table.cmap:
            return table.cmap[codepoint]
    raise KeyError(f"U+{codepoint:04X} not found in cmap")
