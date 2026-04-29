"""Shared paths, helpers, and merge harnesses for the merge-engine tests."""

import io
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

def _merge(lat_scale=1.0, lat_baseline=0, jp_scale=1.0, jp_baseline=0,
           lat_wght=400, lat_opsz=14, jp_wght=400, output_weight=None,
           output_upm=None):
    """Run a TTF Inter-subset + TTF Noto-subset merge and return the TTFont."""
    out = tempfile.mktemp(suffix=".ttf")
    output = {"familyName": "Test"}
    if output_weight is not None:
        output["weight"] = output_weight
    if output_upm is not None:
        output["upm"] = output_upm
    config = {
        "subFont": {
            "path": EN_VAR,
            "scale": lat_scale,
            "baselineOffset": lat_baseline,
            "axes": [
                {"tag": "opsz", "currentValue": lat_opsz},
                {"tag": "wght", "currentValue": lat_wght},
            ],
        },
        "baseFont": {
            "path": JP_VAR,
            "scale": jp_scale,
            "baselineOffset": jp_baseline,
            "axes": [{"tag": "wght", "currentValue": jp_wght}],
        },
        "output": output,
        "export": {"path": {"font": out}},
    }
    mf.merge_fonts(config)
    font = TTFont(out)
    os.remove(out)
    return font


def _merge_with_meta(output_family="TestMeta", output_copyright="",
                     output_ps_name=None, output_version=None, app_version=None,
                     output_manufacturer=None, output_manufacturer_url=None,
                     output_trademark=None):
    """Run merge with metadata options and return the TTFont."""
    out = tempfile.mktemp(suffix=".ttf")
    output = {
        "familyName": output_family,
        "copyright": output_copyright,
    }
    if output_manufacturer is not None:
        output["manufacturer"] = output_manufacturer
    if output_manufacturer_url is not None:
        output["manufacturerURL"] = output_manufacturer_url
    if output_trademark is not None:
        output["trademark"] = output_trademark
    if output_ps_name is not None:
        output["postScriptName"] = output_ps_name
    if output_version is not None:
        output["version"] = output_version
    config = {
        "subFont": {
            "path": EN_VAR,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [
                {"tag": "opsz", "currentValue": 14},
                {"tag": "wght", "currentValue": 400},
            ],
        },
        "baseFont": {
            "path": JP_VAR,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [{"tag": "wght", "currentValue": 400}],
        },
        "output": output,
        "export": {"path": {"font": out}},
    }
    if app_version is not None:
        config["appVersion"] = app_version
    mf.merge_fonts(config)
    font = TTFont(out)
    for f in (out, out.replace(".ttf", ".woff2")):
        if os.path.exists(f):
            os.remove(f)
    return font


def _merge_otf_jp(**kwargs):
    """Run merge with the CFF CID Japanese subset as base."""
    if not os.path.exists(JP_OTF):
        pytest.skip("NotoSansCJKjp-subset.otf not found")
    out = tempfile.mktemp(suffix=".otf")
    config = {
        "subFont": {
            "path": EN_CFF,
            "scale": kwargs.get("lat_scale", 1.0),
            "baselineOffset": kwargs.get("lat_baseline", 0),
            "axes": [],
        },
        "baseFont": {
            "path": JP_OTF,
            "scale": kwargs.get("jp_scale", 1.0),
            "baselineOffset": kwargs.get("jp_baseline", 0),
            "axes": [],
        },
        "output": {"familyName": "TestOTF"},
        "export": {"path": {"font": out}},
    }
    mf.merge_fonts(config)
    font = TTFont(out)
    os.remove(out)
    return font


_MERGE_CFF_CACHE: dict = {}


def _merge_cff_to_cff(lat_scale=1.0, lat_baseline=0):
    """Merge Inter (CFF) into Noto CJK (CFF base) — CFF→CFF all the way.

    The CID merge is expensive, so the result is memoised by
    ``(lat_scale, lat_baseline)`` across the whole test session. Tests
    should treat the returned font as read-only.
    """
    key = (lat_scale, lat_baseline)
    if key in _MERGE_CFF_CACHE:
        return _MERGE_CFF_CACHE[key]
    out = tempfile.mktemp(suffix=".otf")
    config = {
        "subFont": {
            "path": EN_CFF,
            "scale": lat_scale,
            "baselineOffset": lat_baseline,
            "axes": [],
        },
        "baseFont": {
            "path": JP_OTF,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [],
        },
        "output": {"familyName": "TestHint"},
        "export": {"path": {"font": out}},
    }
    mf.merge_fonts(config)
    # Load into memory so the on-disk artefacts can go away immediately.
    with open(out, "rb") as fp:
        data = fp.read()
    os.remove(out)
    woff2 = out.replace(".otf", ".woff2")
    if os.path.exists(woff2):
        os.remove(woff2)
    font = TTFont(io.BytesIO(data))
    _MERGE_CFF_CACHE[key] = font
    return font


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
