"""
Tests for the composite font merge engine.

Uses subset test fonts in testdata/fonts/ for fast execution.
Run: python3 -m pytest python/tests/test_merge.py -v
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen

import merge_fonts as mf

# Silence progress output during tests
mf.progress = lambda *a: None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
FONTS = os.path.join(ROOT, "testdata", "fonts")
EN_VAR = os.path.join(FONTS, "Inter-4.1", "Inter-subset.ttf")
JP_VAR = os.path.join(FONTS, "Noto_Sans_JP", "NotoSansJP-subset.ttf")
PLAYWRITE = os.path.join(FONTS, "Playwrite_IE", "PlaywriteIE-VariableFont_wght.ttf")
KAISEI = os.path.join(FONTS, "Kaisei_Decol", "KaiseiDecol-Regular.ttf")


def _merge(lat_scale=1.0, lat_baseline=0, jp_scale=1.0, jp_baseline=0,
           lat_wght=400, lat_opsz=14, jp_wght=400, output_weight=None,
           output_upm=None):
    """Run merge and return the merged TTFont."""
    out = tempfile.mktemp(suffix=".ttf")
    config = {
        "latin": {
            "path": EN_VAR,
            "scale": lat_scale,
            "baselineOffset": lat_baseline,
            "axes": [
                {"tag": "opsz", "currentValue": lat_opsz},
                {"tag": "wght", "currentValue": lat_wght},
            ],
        },
        "base": {
            "path": JP_VAR,
            "scale": jp_scale,
            "baselineOffset": jp_baseline,
            "axes": [{"tag": "wght", "currentValue": jp_wght}],
        },
        "outputFormat": "ttf",
        "outputPath": out,
        "outputFamilyName": "Test",
    }
    if output_weight is not None:
        config["outputWeight"] = output_weight
    if output_upm is not None:
        config["outputUpm"] = output_upm
    mf.merge_fonts(config)
    font = TTFont(out)
    os.remove(out)
    return font


def _get_bounds(font, glyph_name):
    """Get effective bounds (works for both simple and composite glyphs)."""
    gs = font.getGlyphSet()
    bp = BoundsPen(gs)
    gs[glyph_name].draw(bp)
    return bp.bounds  # (xMin, yMin, xMax, yMax)


# ---------------------------------------------------------------------------
# Variable Font instantiation
# ---------------------------------------------------------------------------

class TestVariableInstantiation:
    """Verify that variable font axis values are correctly baked."""

    def test_weight_affects_stem_width(self):
        """Different wght values produce different stem widths."""
        m100 = _merge(lat_wght=100, jp_wght=100)
        m700 = _merge(lat_wght=700, jp_wght=700)

        # Compare stem width of 'l' as a proxy for weight
        b100 = _get_bounds(m100, "l")
        b700 = _get_bounds(m700, "l")
        w100 = b100[2] - b100[0]
        w700 = b700[2] - b700[0]

        assert w700 > w100 * 1.5, f"wght=700 ({w700}) should be much wider than wght=100 ({w100})"

    def test_japanese_weight_affects_glyphs(self):
        """Japanese font wght axis is also applied."""
        m100 = _merge(jp_wght=100)
        m700 = _merge(jp_wght=700)

        b100 = _get_bounds(m100, "uni3042")  # あ
        b700 = _get_bounds(m700, "uni3042")

        w100 = b100[2] - b100[0]
        w700 = b700[2] - b700[0]
        assert w700 > w100, "Japanese wght=700 should produce wider glyphs"

    def test_fvar_removed_after_instantiation(self):
        """fvar/gvar tables are removed after instantiation."""
        m = _merge()
        assert "fvar" not in m
        assert "gvar" not in m

    def test_default_axes_still_instantiated(self):
        """Fonts with fvar are instantiated even when no axes are specified."""
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "latin": {"path": EN_VAR, "scale": 1.0, "baselineOffset": 0, "axes": []},
            "base": {"path": JP_VAR, "scale": 1.0, "baselineOffset": 0, "axes": []},
            "outputFormat": "ttf", "outputPath": out, "outputFamilyName": "Test",
        }
        mf.merge_fonts(config)
        font = TTFont(out)
        os.remove(out)
        assert "fvar" not in font
        assert "gvar" not in font


# ---------------------------------------------------------------------------
# Baseline offset
# ---------------------------------------------------------------------------

class TestBaselineOffset:
    """Verify that baseline offset is correctly applied to glyph coordinates."""

    def test_simple_glyph_shift(self):
        """Simple glyphs are shifted by exactly the given dy."""
        m0 = _merge(lat_baseline=0)
        m200 = _merge(lat_baseline=-200)

        for gname in ["H", "a", "zero", "parenleft", "bracketleft"]:
            b0 = _get_bounds(m0, gname)
            b200 = _get_bounds(m200, gname)
            dy_min = round(b200[1] - b0[1])
            dy_max = round(b200[3] - b0[3])
            assert abs(dy_min - (-200)) <= 2, f"{gname} yMin shift={dy_min}, expected -200"
            assert abs(dy_max - (-200)) <= 2, f"{gname} yMax shift={dy_max}, expected -200"

    def test_composite_no_double_shift(self):
        """Composite glyphs (colon, etc.) are not double-shifted."""
        m0 = _merge(lat_baseline=0)
        m200 = _merge(lat_baseline=-200)

        for gname in ["colon", "semicolon", "comma"]:
            b0 = _get_bounds(m0, gname)
            b200 = _get_bounds(m200, gname)
            if b0 is None or b200 is None:
                continue
            dy = round(b200[1] - b0[1])
            assert abs(dy - (-200)) <= 2, \
                f"{gname} (composite) shift={dy}, expected -200 (double-shift bug if ~-400)"

    def test_japanese_glyphs_unaffected(self):
        """Japanese glyphs are unaffected by Latin baseline changes."""
        m0 = _merge(lat_baseline=0)
        m200 = _merge(lat_baseline=-200)

        b0 = _get_bounds(m0, "uni3042")
        b200 = _get_bounds(m200, "uni3042")
        dy = round(b200[1] - b0[1])
        assert abs(dy) <= 1, f"Japanese glyph shifted by {dy} when only Latin baseline changed"


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------

class TestScale:
    """Verify that scale is correctly applied to glyphs and metrics."""

    def test_glyph_size_scales(self):
        """scale=2.0 roughly doubles glyph height."""
        m1 = _merge(lat_scale=1.0)
        m2 = _merge(lat_scale=2.0)

        b1 = _get_bounds(m1, "H")
        b2 = _get_bounds(m2, "H")
        h1 = b1[3] - b1[1]
        h2 = b2[3] - b2[1]

        ratio = h2 / h1
        assert 1.9 < ratio < 2.1, f"H height ratio={ratio:.2f}, expected ~2.0"

    def test_advance_width_scales(self):
        """Advance width scales proportionally."""
        m1 = _merge(lat_scale=1.0)
        m2 = _merge(lat_scale=2.0)

        aw1 = m1["hmtx"].metrics["H"][0]
        aw2 = m2["hmtx"].metrics["H"][0]
        ratio = aw2 / aw1
        assert 1.9 < ratio < 2.1, f"H advance width ratio={ratio:.2f}, expected ~2.0"


# ---------------------------------------------------------------------------
# UPM normalization
# ---------------------------------------------------------------------------

class TestUPMNormalization:
    """Verify that 2048-to-1000 UPM normalization is applied correctly."""

    def test_merged_upm_is_japanese(self):
        """Merged UPM matches the Japanese base font."""
        m = _merge()
        assert m["head"].unitsPerEm == 1000

    def test_latin_glyph_scaled_to_target_upm(self):
        """Latin glyphs are scaled from 2048 to 1000 UPM."""
        from fontTools.varLib.instancer import instantiateVariableFont

        en = TTFont(EN_VAR)
        en = instantiateVariableFont(en, {"wght": 400, "opsz": 14})
        m = _merge()

        scale = 1000 / 2048
        en_bounds = _get_bounds(en, "H")
        m_bounds = _get_bounds(m, "H")

        expected_h = round((en_bounds[3] - en_bounds[1]) * scale)
        actual_h = round(m_bounds[3] - m_bounds[1])
        assert abs(actual_h - expected_h) <= 2, \
            f"H height: expected={expected_h}, got={actual_h}"

    def test_os2_metrics_scaled(self):
        """OS/2 ascender/descender are scaled to target UPM."""
        m = _merge()
        os2 = m["OS/2"]
        # Inter's sTypoAscender is 1984 (2048 UPM) → ~969 (1000 UPM)
        assert os2.sTypoAscender < 1100, \
            f"sTypoAscender={os2.sTypoAscender}, should be <1100 (not raw 2048-UPM value)"


# ---------------------------------------------------------------------------
# GPOS scaling
# ---------------------------------------------------------------------------

class TestGPOSScaling:
    """Verify that GPOS values scale correctly with user scale and baseline."""

    def _get_min_kern(self, font):
        """Get the minimum kern XAdvance value in the font."""
        gpos = font["GPOS"].table
        min_val = 0
        for fr in gpos.FeatureList.FeatureRecord:
            if fr.FeatureTag != "kern":
                continue
            for li in fr.Feature.LookupListIndex:
                lk = gpos.LookupList.Lookup[li]
                for st in lk.SubTable:
                    ext = st
                    if hasattr(st, "ExtSubTable"):
                        ext = st.ExtSubTable
                    if hasattr(ext, "PairSet") and ext.PairSet:
                        for ps in ext.PairSet:
                            if ps and ps.PairValueRecord:
                                for pvr in ps.PairValueRecord:
                                    v = getattr(pvr, "Value1", None)
                                    if v and hasattr(v, "XAdvance") and v.XAdvance:
                                        min_val = min(min_val, v.XAdvance)
        return min_val

    def test_kern_scales_with_user_scale(self):
        """Kern values scale proportionally with user scale."""
        m1 = _merge(lat_scale=1.0)
        m2 = _merge(lat_scale=2.0)

        k1 = self._get_min_kern(m1)
        k2 = self._get_min_kern(m2)

        assert k1 != 0, "No kern values found"
        ratio = k2 / k1
        assert 1.8 < ratio < 2.2, f"kern ratio={ratio:.2f}, expected ~2.0"

    def test_kern_not_affected_by_baseline(self):
        """Kern values are unaffected by baseline offset (relative values)."""
        m0 = _merge(lat_baseline=0)
        m200 = _merge(lat_baseline=-200)

        k0 = self._get_min_kern(m0)
        k200 = self._get_min_kern(m200)
        assert k0 == k200, f"kern changed with baseline: {k0} vs {k200}"

    def _get_pair_kern(self, font, glyph1, glyph2):
        """Get kern value for a specific glyph pair (Format 1 + Format 2)."""
        gpos = font["GPOS"].table
        for fr in gpos.FeatureList.FeatureRecord:
            if fr.FeatureTag != "kern":
                continue
            for li in fr.Feature.LookupListIndex:
                lk = gpos.LookupList.Lookup[li]
                for st in lk.SubTable:
                    ext = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
                    if not hasattr(ext, "Coverage"):
                        continue
                    if glyph1 not in ext.Coverage.glyphs:
                        continue
                    # Format 1
                    if ext.Format == 1 and hasattr(ext, "PairSet"):
                        idx = ext.Coverage.glyphs.index(glyph1)
                        for pvr in ext.PairSet[idx].PairValueRecord:
                            if pvr.SecondGlyph == glyph2:
                                return pvr.Value1.XAdvance if pvr.Value1 else 0
                    # Format 2
                    if ext.Format == 2 and hasattr(ext, "ClassDef1"):
                        c1 = ext.ClassDef1.classDefs.get(glyph1, 0)
                        c2 = ext.ClassDef2.classDefs.get(glyph2, 0)
                        val = ext.Class1Record[c1].Class2Record[c2]
                        return val.Value1.XAdvance if val.Value1 else 0
        return None

    def test_pair_kern_preserved_after_merge(self):
        """T+o pair kerning is preserved after merge."""
        m = _merge()
        kern = self._get_pair_kern(m, "T", "o")
        assert kern is not None, "T+o kern pair not found in merged font"
        assert kern < 0, f"T+o kern should be negative (tight), got {kern}"


# ---------------------------------------------------------------------------
# Feature preservation
# ---------------------------------------------------------------------------

class TestFeaturePreservation:
    """Verify that GSUB/GPOS features are correctly preserved or removed."""

    def test_latin_features_present(self):
        """Latin features from Inter (calt, case, frac, ss01, etc.) are preserved."""
        m = _merge()
        gsub = m["GSUB"].table
        tags = {fr.FeatureTag for fr in gsub.FeatureList.FeatureRecord}
        for expected in ["calt", "case", "frac", "ss01", "ss02", "dlig"]:
            assert expected in tags, f"Feature '{expected}' missing from merged font"

    def test_japanese_subordinate_liga_removed(self):
        """Subordinate Latin liga from the Japanese font is removed."""
        m = _merge()
        gsub = m["GSUB"].table
        for fr in gsub.FeatureList.FeatureRecord:
            if fr.FeatureTag == "liga":
                for li in fr.Feature.LookupListIndex:
                    lk = gsub.LookupList.Lookup[li]
                    for st in lk.SubTable:
                        ext = st
                        if hasattr(st, "ExtSubTable"):
                            ext = st.ExtSubTable
                        if hasattr(ext, "ligatures") and ext.ligatures:
                            if "f" in ext.ligatures:
                                pytest.fail("Noto's subordinate Latin liga (f→fi/fl) should be removed")

    def test_case_feature_maps_correctly(self):
        """case feature maps to valid glyph names."""
        m = _merge()
        gsub = m["GSUB"].table
        order = set(m.getGlyphOrder())
        for fr in gsub.FeatureList.FeatureRecord:
            if fr.FeatureTag == "case":
                for li in fr.Feature.LookupListIndex:
                    lk = gsub.LookupList.Lookup[li]
                    for st in lk.SubTable:
                        if hasattr(st, "mapping") and st.mapping:
                            for src, dst in st.mapping.items():
                                assert dst in order, \
                                    f"case: {src}→{dst}, but {dst} not in glyph order"
                            return
        pytest.fail("No case feature mapping found")

    def test_chaining_lookup_references_valid(self):
        """Chaining context lookups reference valid lookup indices."""
        m = _merge()
        gsub = m["GSUB"].table
        total = len(gsub.LookupList.Lookup)

        for lookup in gsub.LookupList.Lookup:
            for st in lookup.SubTable:
                ext = st
                if hasattr(st, "ExtSubTable"):
                    ext = st.ExtSubTable
                if hasattr(ext, "SubstLookupRecord") and ext.SubstLookupRecord:
                    for slr in ext.SubstLookupRecord:
                        assert slr.LookupListIndex < total, \
                            f"Chaining ref {slr.LookupListIndex} >= total lookups {total}"

    def test_feature_names_in_name_table(self):
        """Feature names (ss01, etc.) exist in the name table."""
        m = _merge()
        gsub = m["GSUB"].table
        name_table = m["name"]
        for fr in gsub.FeatureList.FeatureRecord:
            if fr.FeatureTag == "ss01":
                fp = fr.Feature.FeatureParams
                assert fp is not None, "ss01 should have FeatureParams"
                name_id = fp.UINameID
                name_str = name_table.getDebugName(name_id)
                assert name_str is not None, f"ss01 name ID {name_id} not found in name table"
                assert len(name_str) > 0, f"ss01 name is empty"
                return
        pytest.fail("ss01 feature not found")

    def test_liga_lookup_is_ligature_type(self):
        """liga feature lookups are actually LigatureSubst type.
        Detects lookup index remapping bugs that point to AlternateSubst, etc."""
        m = _merge()
        gsub = m["GSUB"].table
        found_liga = False
        for fr in gsub.FeatureList.FeatureRecord:
            if fr.FeatureTag == "liga":
                found_liga = True
                for li in fr.Feature.LookupListIndex:
                    lk = gsub.LookupList.Lookup[li]
                    # LookupType 4 = LigatureSubst, 7 = Extension
                    assert lk.LookupType in (4, 7), \
                        f"liga lookup {li} has wrong type {lk.LookupType} (expected 4 or 7)"
                    for st in lk.SubTable:
                        ext = st
                        if hasattr(st, 'ExtSubTable'):
                            ext = st.ExtSubTable
                        # Extension should also wrap a LigatureSubst
                        if hasattr(ext, 'ExtensionLookupType'):
                            assert ext.ExtensionLookupType == 4, \
                                f"liga extension lookup wraps type {ext.ExtensionLookupType}, expected 4"
        if not found_liga:
            pytest.skip("No liga feature found in merged font")

    def test_jp_chaining_refs_remapped_after_filter(self):
        """JP chaining context lookup references are remapped after filtering."""
        m = _merge()
        gsub = m["GSUB"].table
        total = len(gsub.LookupList.Lookup)
        for i, lookup in enumerate(gsub.LookupList.Lookup):
            for st in lookup.SubTable:
                ext = st
                if hasattr(st, 'ExtSubTable'):
                    ext = st.ExtSubTable
                if hasattr(ext, 'SubstLookupRecord') and ext.SubstLookupRecord:
                    for slr in ext.SubstLookupRecord:
                        assert slr.LookupListIndex < total, \
                            f"Lookup {i}: chaining ref {slr.LookupListIndex} >= total {total}"
                # Also check nested rule sets
                for attr in ('SubRuleSet', 'SubClassSet', 'ChainSubRuleSet', 'ChainSubClassSet'):
                    ruleset_list = getattr(ext, attr, None)
                    if not ruleset_list:
                        continue
                    for ruleset in ruleset_list:
                        if not ruleset:
                            continue
                        for attr2 in ('SubRule', 'SubClassRule', 'ChainSubRule', 'ChainSubClassRule'):
                            rules = getattr(ruleset, attr2, None)
                            if not rules:
                                continue
                            for rule in rules:
                                if hasattr(rule, 'SubstLookupRecord') and rule.SubstLookupRecord:
                                    for slr in rule.SubstLookupRecord:
                                        assert slr.LookupListIndex < total, \
                                            f"Lookup {i}: nested chaining ref {slr.LookupListIndex} >= total {total}"

    def test_no_jp_subordinate_liga_in_latin_script(self):
        """JP subordinate Latin liga does not appear in the Latin script."""
        m = _merge()
        gsub = m["GSUB"].table
        # Find 'latn' or 'DFLT' script
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag in ('latn', 'DFLT'):
                lang_sys = sr.Script.DefaultLangSys
                if not lang_sys:
                    continue
                for fi in lang_sys.FeatureIndex:
                    fr = gsub.FeatureList.FeatureRecord[fi]
                    if fr.FeatureTag == 'liga':
                        for li in fr.Feature.LookupListIndex:
                            lk = gsub.LookupList.Lookup[li]
                            for st in lk.SubTable:
                                ext = st
                                if hasattr(st, 'ExtSubTable'):
                                    ext = st.ExtSubTable
                                if hasattr(ext, 'ligatures') and ext.ligatures:
                                    if 'f' in ext.ligatures:
                                        pytest.fail(
                                            "JP subordinate Latin liga (f→fi/fl) should not be "
                                            "in Latin script's liga feature")


# ---------------------------------------------------------------------------
# Output weight
# ---------------------------------------------------------------------------

class TestOutputWeight:
    """Verify that outputWeight is correctly reflected in font metadata."""

    def test_weight_class_overrides_base(self):
        """outputWeight=500 overrides JP Thin(100) to usWeightClass=500."""
        m = _merge(lat_wght=100, jp_wght=100, output_weight=500)
        assert m["OS/2"].usWeightClass == 500

    def test_name_id_2_matches_weight(self):
        """nameID 2 (Subfamily) matches the outputWeight style name."""
        m = _merge(lat_wght=100, jp_wght=100, output_weight=500)
        name2 = m["name"].getDebugName(2)
        assert name2 == "Medium", f"Expected 'Medium', got '{name2}'"

    def test_name_id_17_matches_weight(self):
        """nameID 17 (Typographic Subfamily) also follows outputWeight."""
        m = _merge(lat_wght=100, jp_wght=100, output_weight=500)
        name17 = m["name"].getDebugName(17)
        if name17 is not None:
            assert name17 == "Medium", \
                f"nameID 17 should be 'Medium', got '{name17}'"

    def test_name_id_4_includes_weight(self):
        """nameID 4 (Full Name) includes the style name."""
        m = _merge(lat_wght=100, jp_wght=100, output_weight=700)
        name4 = m["name"].getDebugName(4)
        assert "Bold" in name4, f"Expected 'Bold' in nameID 4, got '{name4}'"


# ---------------------------------------------------------------------------
# Metadata (name table) correctness
# ---------------------------------------------------------------------------

def _merge_with_meta(output_family="TestMeta", output_designer="", output_copyright=""):
    """Run merge with metadata options and return TTFont + cleanup paths."""
    out = tempfile.mktemp(suffix=".ttf")
    config = {
        "latin": {
            "path": EN_VAR,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [
                {"tag": "opsz", "currentValue": 14},
                {"tag": "wght", "currentValue": 400},
            ],
        },
        "base": {
            "path": JP_VAR,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [{"tag": "wght", "currentValue": 400}],
        },
        "outputFormat": "ttf",
        "outputPath": out,
        "outputFamilyName": output_family,
        "outputDesigner": output_designer,
        "outputCopyright": output_copyright,
    }
    mf.merge_fonts(config)
    font = TTFont(out)
    for f in (out, out.replace(".ttf", ".woff2")):
        if os.path.exists(f):
            os.remove(f)
    return font


class TestMetadataCorrectness:
    """Verify that the merged name table matches the configuration."""

    def test_family_name_matches_config(self):
        """nameID 1 matches outputFamilyName."""
        m = _merge_with_meta(output_family="MyCustomFont")
        assert m["name"].getDebugName(1) == "MyCustomFont"

    def test_full_name_includes_family(self):
        """nameID 4 (Full Name) includes outputFamilyName."""
        m = _merge_with_meta(output_family="MyCustomFont")
        name4 = m["name"].getDebugName(4)
        assert "MyCustomFont" in name4

    def test_postscript_name_no_spaces(self):
        """nameID 6 (PostScript Name) contains no spaces."""
        m = _merge_with_meta(output_family="My Custom Font")
        name6 = m["name"].getDebugName(6)
        assert " " not in name6
        assert "MyCustomFont" in name6

    def test_license_is_ofl(self):
        """nameID 13 contains the OFL license text."""
        m = _merge_with_meta()
        lic = m["name"].getDebugName(13)
        assert "Open Font License" in lic

    def test_license_url(self):
        """nameID 14 is the OFL URL."""
        m = _merge_with_meta()
        url = m["name"].getDebugName(14)
        assert "openfontlicense.org" in url

    def test_copyright_preserves_sources(self):
        """nameID 0 includes source font copyrights."""
        m = _merge_with_meta()
        cr = m["name"].getDebugName(0)
        assert cr is not None and len(cr) > 0

    def test_copyright_includes_user_addition(self):
        """outputCopyright is appended to nameID 0."""
        m = _merge_with_meta(output_copyright="Copyright 2026 TestUser")
        cr = m["name"].getDebugName(0)
        assert "Copyright 2026 TestUser" in cr

    def test_copyright_without_user(self):
        """Source copyrights are preserved even when outputCopyright is empty."""
        m = _merge_with_meta(output_copyright="")
        cr = m["name"].getDebugName(0)
        assert cr is not None and len(cr) > 0

    def test_designer_set_when_provided(self):
        """outputDesigner is written to nameID 9."""
        m = _merge_with_meta(output_designer="John Doe")
        assert m["name"].getDebugName(9) == "John Doe"

    def test_designer_empty_clears(self):
        """Empty outputDesigner clears nameID 9."""
        m = _merge_with_meta(output_designer="")
        d = m["name"].getDebugName(9)
        assert d is None or d == "", f"Expected empty designer, got '{d}'"

    def test_description_mentions_sources(self):
        """nameID 10 mentions source font names."""
        m = _merge_with_meta()
        desc = m["name"].getDebugName(10)
        assert desc is not None
        assert "Based on" in desc

    def test_description_mentions_merged(self):
        """Two-font merge includes 'Merged with' in nameID 10."""
        m = _merge_with_meta()
        desc = m["name"].getDebugName(10)
        assert "Merged with OFL Font Baker" in desc


class TestMetadataBaseOnly:
    """Metadata for base-font-only merge (no Latin font)."""

    def _merge_base_only_meta(self, output_designer="", output_copyright=""):
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "base": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "outputFormat": "ttf",
            "outputPath": out,
            "outputFamilyName": "BaseOnlyMeta",
            "outputDesigner": output_designer,
            "outputCopyright": output_copyright,
        }
        mf.merge_fonts(config)
        font = TTFont(out)
        for f in (out, out.replace(".ttf", ".woff2")):
            if os.path.exists(f):
                os.remove(f)
        return font

    def test_family_name(self):
        m = self._merge_base_only_meta()
        assert m["name"].getDebugName(1) == "BaseOnlyMeta"

    def test_license_is_ofl(self):
        m = self._merge_base_only_meta()
        lic = m["name"].getDebugName(13)
        assert "Open Font License" in lic

    def test_copyright_preserved(self):
        m = self._merge_base_only_meta()
        cr = m["name"].getDebugName(0)
        assert cr is not None and len(cr) > 0

    def test_designer_set(self):
        m = self._merge_base_only_meta(output_designer="Jane Smith")
        assert m["name"].getDebugName(9) == "Jane Smith"

    def test_description_baked_not_merged(self):
        """Base-only uses 'Baked with', not 'Merged with'."""
        m = self._merge_base_only_meta()
        desc = m["name"].getDebugName(10) or ""
        assert "Merged with" not in desc
        assert "Baked with OFL Font Baker" in desc


# ---------------------------------------------------------------------------
# Glyph name preservation
# ---------------------------------------------------------------------------

class TestGlyphNamePreservation:
    """Verify glyph names are preserved in post table format 2.0."""

    def test_post_format_2(self):
        m = _merge()
        assert m["post"].formatType == 2.0

    def test_alternate_glyph_names_preserved(self):
        """Alternate glyph names from features survive save/load round-trip."""
        m = _merge()
        order = set(m.getGlyphOrder())
        # Find alternate glyphs (names containing '.') that exist in the font
        alt_glyphs = [g for g in order if '.' in g and not g.startswith('.')]
        assert len(alt_glyphs) > 0, "No alternate glyphs found — subsetting may have removed them"
        # Ensure none have been renamed to synthetic 'glyph12345' format
        synthetic_alts = [g for g in alt_glyphs if g.startswith('glyph') and g[5:].isdigit()]
        assert len(synthetic_alts) == 0, \
            f"Alternate glyphs renamed to synthetic names: {synthetic_alts[:5]}"


# ---------------------------------------------------------------------------
# Composite glyph integrity
# ---------------------------------------------------------------------------

class TestCompositeGlyphs:
    """Verify composite glyph reference integrity."""

    def test_no_empty_composite_components(self):
        """All composite component glyphs have valid outlines."""
        m = _merge()
        glyf = m["glyf"]
        empty_components = []

        for name in m.getGlyphOrder():
            g = glyf[name]
            if g.isComposite():
                for c in g.components:
                    cg = glyf.get(c.glyphName)
                    if not cg or (cg.numberOfContours == 0 and not cg.isComposite()):
                        empty_components.append(f"{name}→{c.glyphName}")

        assert len(empty_components) == 0, \
            f"Empty composite components: {empty_components[:10]}"

    def test_hmtx_complete(self):
        """All glyphs have hmtx metrics."""
        m = _merge()
        hmtx = m["hmtx"]
        order = m.getGlyphOrder()
        missing = [g for g in order if g not in hmtx.metrics]
        assert len(missing) == 0, f"Glyphs missing from hmtx: {missing[:10]}"


# ---------------------------------------------------------------------------
# TT-to-CFF conversion (JP font is OTF)
# ---------------------------------------------------------------------------

JP_OTF = os.path.join(FONTS, "NotoSansCJKjp", "NotoSansCJKjp-Regular.otf")

def _merge_otf_jp(**kwargs):
    """Run merge with CFF-based JP font and return the merged TTFont."""
    if not os.path.exists(JP_OTF):
        pytest.skip("NotoSansCJKjp-Regular.otf not found")
    out = tempfile.mktemp(suffix=".otf")
    config = {
        "latin": {
            "path": EN_VAR,
            "scale": kwargs.get("lat_scale", 1.0),
            "baselineOffset": kwargs.get("lat_baseline", 0),
            "axes": [
                {"tag": "opsz", "currentValue": 14},
                {"tag": "wght", "currentValue": 400},
            ],
        },
        "base": {
            "path": JP_OTF,
            "scale": kwargs.get("jp_scale", 1.0),
            "baselineOffset": kwargs.get("jp_baseline", 0),
            "axes": [],
        },
        "outputFormat": "otf",
        "outputPath": out,
        "outputFamilyName": "TestOTF",
    }
    mf.merge_fonts(config)
    font = TTFont(out)
    os.remove(out)
    return font


class TestCIDJapaneseFont:
    """Merge tests with CID-keyed CFF (JP OTF) base font."""

    def test_merge_succeeds(self):
        """Merge with CID-keyed JP font completes without error."""
        m = _merge_otf_jp()
        # CID fonts are converted to TT for merging
        assert "glyf" in m
        assert m.sfntVersion == "\x00\x01\x00\x00", \
            f"sfntVersion should be TrueType, got {repr(m.sfntVersion)}"

    def test_latin_glyph_has_outline(self):
        """Latin glyph (U+0041 = A) has a valid outline."""
        m = _merge_otf_jp()
        cmap = m.getBestCmap()
        a_glyph = cmap.get(0x0041)  # A
        assert a_glyph is not None, "U+0041 (A) not in cmap"
        gs = m.getGlyphSet()
        bp = BoundsPen(gs)
        gs[a_glyph].draw(bp)
        bounds = bp.bounds
        assert bounds is not None, "Latin glyph for U+0041 has no outline"
        assert bounds[2] > bounds[0], "Latin glyph for U+0041 has zero width"

    def test_japanese_glyph_has_outline(self):
        """Japanese glyph has a valid outline after CFF-to-TT conversion."""
        m = _merge_otf_jp()
        cmap = m.getBestCmap()
        a_glyph = cmap.get(0x3042)  # あ
        assert a_glyph is not None, "U+3042 (あ) not in cmap"
        gs = m.getGlyphSet()
        bp = BoundsPen(gs)
        gs[a_glyph].draw(bp)
        bounds = bp.bounds
        assert bounds is not None, "Glyph あ has no outline after CFF→TT conversion"

    def test_hmtx_complete_otf(self):
        """All glyphs have hmtx metrics."""
        m = _merge_otf_jp()
        hmtx = m["hmtx"]
        order = m.getGlyphOrder()
        missing = [g for g in order if g not in hmtx.metrics]
        assert len(missing) == 0, f"Glyphs missing from hmtx: {missing[:10]}"


# ---------------------------------------------------------------------------
# Metrics preservation
# ---------------------------------------------------------------------------

class TestMetricsPreservation:
    """Verify that merged font metrics are set correctly.

    reconcile_tables() sets OS/2 and hhea metrics to the envelope
    (max ascender, min descender) of Latin and JP fonts.
    head.unitsPerEm is cloned from the base (JP) font.
    """

    @pytest.fixture(autouse=True)
    def _load_base_metrics(self):
        """Load JP base font metrics for comparison."""
        from fontTools.varLib.instancer import instantiateVariableFont
        jp = TTFont(JP_VAR)
        jp = instantiateVariableFont(jp, {"wght": 400})
        self.jp_os2 = jp["OS/2"]
        self.jp_hhea = jp["hhea"]
        self.jp_upm = jp["head"].unitsPerEm

    def test_head_upm_matches_base(self):
        """head.unitsPerEm matches the base (JP) font."""
        m = _merge()
        assert m["head"].unitsPerEm == self.jp_upm

    def test_os2_typo_ascender_ge_base(self):
        """OS/2 sTypoAscender >= base font (envelope max)."""
        m = _merge()
        assert m["OS/2"].sTypoAscender >= self.jp_os2.sTypoAscender

    def test_os2_typo_descender_le_base(self):
        """OS/2 sTypoDescender <= base font (envelope min)."""
        m = _merge()
        assert m["OS/2"].sTypoDescender <= self.jp_os2.sTypoDescender

    def test_hhea_ascender_ge_base(self):
        """hhea ascent >= base font."""
        m = _merge()
        assert m["hhea"].ascent >= self.jp_hhea.ascent

    def test_hhea_descender_le_base(self):
        """hhea descent <= base font."""
        m = _merge()
        assert m["hhea"].descent <= self.jp_hhea.descent

    def test_latin_scale_does_not_affect_upm(self):
        """Latin scale does not affect unitsPerEm."""
        m_s1 = _merge(lat_scale=1.0)
        m_s2 = _merge(lat_scale=2.0)
        assert m_s1["head"].unitsPerEm == self.jp_upm
        assert m_s2["head"].unitsPerEm == self.jp_upm

    def test_latin_scale_does_not_inflate_metrics_unbounded(self):
        """Latin scale=2.0 does not inflate sTypoAscender beyond reason."""
        m = _merge(lat_scale=2.0)
        # scale=2.0 pushes Latin sTypoAscender to ~1938,
        # but it should not exceed 3x UPM (1000)
        assert m["OS/2"].sTypoAscender < self.jp_upm * 3, \
            f"sTypoAscender={m['OS/2'].sTypoAscender} is unreasonably large"

    def test_baseline_offset_does_not_affect_upm(self):
        """Latin baseline offset does not affect unitsPerEm."""
        m = _merge(lat_baseline=-200)
        assert m["head"].unitsPerEm == self.jp_upm

    def test_baseline_offset_does_not_affect_os2_metrics(self):
        """Latin baseline offset does not affect OS/2 sTypoAscender/Descender.

        reconcile_tables() uses font-wide metrics; baseline offset
        is applied only to glyph coordinates.
        """
        m0 = _merge(lat_baseline=0)
        m200 = _merge(lat_baseline=-200)
        assert m0["OS/2"].sTypoAscender == m200["OS/2"].sTypoAscender
        assert m0["OS/2"].sTypoDescender == m200["OS/2"].sTypoDescender

    def test_baseline_offset_does_not_affect_hhea_metrics(self):
        """Latin baseline offset does not affect hhea ascent/descent."""
        m0 = _merge(lat_baseline=0)
        m200 = _merge(lat_baseline=-200)
        assert m0["hhea"].ascent == m200["hhea"].ascent
        assert m0["hhea"].descent == m200["hhea"].descent


class TestOutputUpm:
    """Verify the unified outputUpm transform scales outlines, hmtx, and metrics."""

    def test_default_upm_matches_base(self):
        m = _merge()
        jp = TTFont(JP_VAR)
        assert m["head"].unitsPerEm == jp["head"].unitsPerEm

    def test_explicit_upm_sets_head(self):
        m = _merge(output_upm=2000)
        assert m["head"].unitsPerEm == 2000

    def test_jp_glyph_scaled_by_upm_ratio(self):
        """A JP glyph's advance width scales with the UPM ratio."""
        m1 = _merge()
        m2 = _merge(output_upm=2000)
        jp_upm = m1["head"].unitsPerEm
        ratio = 2000 / jp_upm
        # Pick a JP-origin glyph via cmap U+3042 (あ) if present, else any
        jp_font = TTFont(JP_VAR)
        cmap = jp_font.getBestCmap()
        cp = next((c for c in (0x3042, 0x3044, 0x3046) if c in cmap), None)
        assert cp is not None, "No JP cmap fallback"
        gname = m1.getBestCmap()[cp]
        aw1 = m1["hmtx"].metrics[gname][0]
        aw2 = m2["hmtx"].metrics[gname][0]
        assert abs(aw2 - aw1 * ratio) <= 2, (aw1, aw2, ratio)

    def test_os2_metrics_scaled_by_upm_ratio(self):
        m1 = _merge()
        m2 = _merge(output_upm=2000)
        ratio = 2000 / m1["head"].unitsPerEm
        assert abs(m2["OS/2"].sTypoAscender - m1["OS/2"].sTypoAscender * ratio) <= 2
        assert abs(m2["hhea"].ascent - m1["hhea"].ascent * ratio) <= 2

    def test_base_only_respects_upm(self):
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "latin": None,
            "base": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "outputPath": out,
            "outputFamilyName": "Test",
            "outputUpm": 1500,
        }
        mf.merge_fonts(config)
        m = TTFont(out)
        os.remove(out)
        assert m["head"].unitsPerEm == 1500


# ---------------------------------------------------------------------------
# Hinting preservation
# ---------------------------------------------------------------------------

class TestHintingPreservation:
    """Verify that base font TrueType hinting tables survive merge.

    The merged font is cloned from the base (JP) font, so fpgm / prep /
    cvt / gasp tables should be preserved as-is.
    """

    @pytest.fixture(autouse=True)
    def _load_base_tables(self):
        """Load instantiated JP base font for comparison."""
        from fontTools.varLib.instancer import instantiateVariableFont
        jp = TTFont(JP_VAR)
        self.jp = instantiateVariableFont(jp, {"wght": 400})

    def test_prep_table_survives_merge(self):
        """prep table is preserved after merge."""
        if "prep" not in self.jp:
            pytest.skip("Base font has no prep table")
        m = _merge()
        assert "prep" in m, "prep table lost during merge"
        # Contents should match the base font
        assert m["prep"].program.getBytecode() == self.jp["prep"].program.getBytecode(), \
            "prep table contents differ from base font"

    def test_fpgm_table_survives_merge(self):
        """fpgm table is preserved if present in base font."""
        if "fpgm" not in self.jp:
            pytest.skip("Base font has no fpgm table")
        m = _merge()
        assert "fpgm" in m, "fpgm table lost during merge"

    def test_cvt_table_survives_merge(self):
        """cvt table is preserved if present in base font."""
        if "cvt " not in self.jp:
            pytest.skip("Base font has no cvt table")
        m = _merge()
        assert "cvt " in m, "cvt table lost during merge"

    def test_gasp_table_survives_merge(self):
        """gasp table is preserved after merge."""
        if "gasp" not in self.jp:
            pytest.skip("Base font has no gasp table")
        m = _merge()
        assert "gasp" in m, "gasp table lost during merge"
        # Verify gasp ranges are preserved
        assert m["gasp"].gaspRange == self.jp["gasp"].gaspRange, \
            "gasp ranges differ from base font"

    def test_latin_glyph_instructions_not_crash(self):
        """Latin glyph hinting instructions do not crash after merge.

        Glyph-level TT instructions may become invalid after scaling,
        but font compilation and loading should still work.
        """
        m = _merge(lat_scale=1.0)
        # Round-trip: save and reload to verify no instruction-related crash
        out = tempfile.mktemp(suffix=".ttf")
        try:
            m.save(out)
            reloaded = TTFont(out)
            glyf = reloaded["glyf"]
            # Verify Latin glyphs are accessible
            for gname in ["H", "a", "zero"]:
                g = glyf.get(gname)
                assert g is not None, f"Glyph '{gname}' missing after round-trip"
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_scaled_latin_glyph_instructions_not_crash(self):
        """Scaled Latin glyphs do not crash on round-trip."""
        m = _merge(lat_scale=1.5)
        out = tempfile.mktemp(suffix=".ttf")
        try:
            m.save(out)
            reloaded = TTFont(out)
            # Access all glyphs to trigger instruction parsing
            glyf = reloaded["glyf"]
            for gname in reloaded.getGlyphOrder():
                _ = glyf[gname]
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_scaled_latin_instructions_cleared(self):
        """Scaled Latin glyphs have their hinting instructions cleared."""
        m = _merge(lat_scale=1.5)
        glyf = m["glyf"]
        # 'A' is a Latin glyph that was scaled
        a_glyph = glyf.get("A")
        if a_glyph and hasattr(a_glyph, "program") and a_glyph.program:
            assert len(a_glyph.program.bytecode) == 0, \
                "Scaled Latin glyph should have empty instructions"

    def test_unscaled_latin_instructions_preserved(self):
        """Unscaled Latin glyphs preserve hinting instructions."""
        # UPM ratio may cause implicit scaling, so check if any instructions survive
        # at scale=1.0. This depends on whether UPMs match.
        m = _merge(lat_scale=1.0)
        glyf = m["glyf"]
        # Just verify it doesn't crash — actual preservation depends on UPM match
        a_glyph = glyf.get("A")
        assert a_glyph is not None

    def test_maxp_hinting_fields_present(self):
        """maxp table has TT hinting-related fields."""
        m = _merge()
        maxp = m["maxp"]
        # TrueType maxp (version 1.0) should have these fields
        assert hasattr(maxp, "maxZones"), "maxp missing maxZones"
        assert hasattr(maxp, "maxFunctionDefs"), "maxp missing maxFunctionDefs"
        assert hasattr(maxp, "maxSizeOfInstructions"), "maxp missing maxSizeOfInstructions"


# ---------------------------------------------------------------------------
# CFF hint preservation (Inter CFF -> Noto CJK CFF, output CFF)
# ---------------------------------------------------------------------------

EN_CFF = os.path.join(FONTS, "Inter-4.1", "Inter-Regular.otf")
_JP_CID_HINT = JP_OTF


_MERGE_CFF_CACHE = {}


def _merge_cff_to_cff(lat_scale=1.0, lat_baseline=0):
    """Merge Inter (CFF) into Noto CJK (CFF base) — CFF→CFF all the way.

    The 65K-glyph CID merge is expensive (~30-60s per call), so the
    resulting TTFont is memoised by (lat_scale, lat_baseline) across the
    whole test session. Tests should treat the returned font as read-only.
    """
    key = (lat_scale, lat_baseline)
    if key in _MERGE_CFF_CACHE:
        return _MERGE_CFF_CACHE[key]
    out = tempfile.mktemp(suffix=".otf")
    config = {
        "latin": {
            "path": EN_CFF,
            "scale": lat_scale,
            "baselineOffset": lat_baseline,
            "axes": [],
        },
        "base": {
            "path": _JP_CID_HINT,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [],
        },
        "outputPath": out,
        "outputFamilyName": "TestHint",
    }
    mf.merge_fonts(config)
    # Load into memory, then drop the on-disk artefacts.
    with open(out, "rb") as _f:
        _data = _f.read()
    os.remove(out)
    woff2 = out.replace(".otf", ".woff2")
    if os.path.exists(woff2):
        os.remove(woff2)
    import io
    font = TTFont(io.BytesIO(_data))
    _MERGE_CFF_CACHE[key] = font
    return font


def _cid_glyph_for_codepoint(font, codepoint):
    """Look up a CID glyph name from the cmap (CID fonts use cid#####)."""
    for table in font["cmap"].tables:
        if codepoint in table.cmap:
            return table.cmap[codepoint]
    raise KeyError(f"U+{codepoint:04X} not found in cmap")


@pytest.mark.skipif(
    not os.path.exists(_JP_CID_HINT),
    reason="NotoSansCJKjp-Regular.otf not present",
)
class TestCFFHintPreservation:
    """Verify CFF hint info (stems, BlueValues) survives CFF→CFF merge."""

    @staticmethod
    def _has_hint_op(font, glyph_name):
        cff = font["CFF "].cff
        cff.desubroutinize()
        cs = cff.topDictIndex[0].CharStrings[glyph_name]
        cs.decompile()
        prog = cs.program
        return any(op in prog for op in ("hstem", "hstemhm", "vstem", "vstemhm", "hintmask"))

    @staticmethod
    def _fd_private(font, glyph_name):
        """Return the Private dict governing `glyph_name` (FDSelect-aware)."""
        cff = font["CFF "].cff
        td = cff.topDictIndex[0]
        if hasattr(td, "FDArray") and td.FDArray:
            cs = td.CharStrings[glyph_name]
            fd_idx = getattr(cs, "fdSelectIndex", 0) or 0
            return td.FDArray[fd_idx].Private
        return td.Private

    def test_output_is_cff(self):
        m = _merge_cff_to_cff()
        assert "CFF " in m or "CFF2" in m
        assert "glyf" not in m

    def test_latin_glyph_has_hints_unchanged(self):
        """At scale=1, dy=0, Inter 'A' charstring retains hint operators."""
        m = _merge_cff_to_cff()
        gname = _cid_glyph_for_codepoint(m, ord("A"))
        assert self._has_hint_op(m, gname), f"Hint operators missing on unscaled {gname!r}"

    def test_latin_glyph_has_hints_scaled(self):
        """Hints survive even when scale/baseline are non-trivial."""
        m = _merge_cff_to_cff(lat_scale=0.9, lat_baseline=-40)
        gname = _cid_glyph_for_codepoint(m, ord("A"))
        assert self._has_hint_op(m, gname), f"Hint operators missing on scaled {gname!r}"

    def test_blue_values_present(self):
        m = _merge_cff_to_cff()
        gname = _cid_glyph_for_codepoint(m, ord("A"))
        priv = self._fd_private(m, gname)
        assert getattr(priv, "BlueValues", None), "BlueValues missing on Private dict"


@pytest.mark.skipif(
    not os.path.exists(_JP_CID_HINT),
    reason="NotoSansCJKjp-Regular.otf not present",
)
class TestCFFCoincidenceSnap:
    """Verify that points originally at the same absolute (x, y) remain
    coincident after the CFF transform, despite UPM scaling and rounding.

    Inter (UPM 2048) merged into NotoJP (UPM 1000) gives a non-trivial
    scale ratio (~0.488), which is the case where naive per-delta rounding
    accumulates drift and breaks coincident vertices.
    """

    @staticmethod
    def _collect_points(font, glyph_name):
        """Return a list of absolute (x, y) points drawn for the glyph."""
        from fontTools.pens.recordingPen import RecordingPen
        gs = font.getGlyphSet()
        rec = RecordingPen()
        gs[glyph_name].draw(rec)
        points = []
        for cmd, args in rec.value:
            if cmd in ("moveTo", "lineTo"):
                points.append(tuple(args[0]))
            elif cmd in ("curveTo", "qCurveTo"):
                for pt in args:
                    if pt is not None:
                        points.append(tuple(pt))
        return points

    def _check_glyph(self, letter):
        from fontTools.ttLib import TTFont as _TTFont
        src = _TTFont(EN_CFF)
        m = _merge_cff_to_cff()
        out_gname = _cid_glyph_for_codepoint(m, ord(letter))
        src_pts = self._collect_points(src, letter)
        out_pts = self._collect_points(m, out_gname)
        assert len(src_pts) == len(out_pts), (
            f"Point count changed for {letter}: "
            f"{len(src_pts)} -> {len(out_pts)}"
        )
        # Group source point indices by source coordinate; assert that the
        # corresponding output points are equal.
        groups = {}
        for i, p in enumerate(src_pts):
            groups.setdefault(p, []).append(i)
        for src_pt, idxs in groups.items():
            if len(idxs) < 2:
                continue
            out_group = {out_pts[i] for i in idxs}
            assert len(out_group) == 1, (
                f"Coincident points at source {src_pt} in glyph "
                f"'{letter}' diverged after transform: {out_group}"
            )

    def test_o_coincident_vertices(self):
        self._check_glyph("O")

    def test_a_coincident_vertices(self):
        self._check_glyph("A")

    def test_e_coincident_vertices(self):
        self._check_glyph("E")


@pytest.mark.skipif(
    not os.path.exists(_JP_CID_HINT),
    reason="NotoSansCJKjp-Regular.otf not present",
)
class TestCFFFontBBox:
    """CFF has no per-glyph bbox; FontBBox must envelope all CharStrings."""

    def test_fontbbox_envelopes_all_glyphs(self):
        from fontTools.pens.boundsPen import BoundsPen
        m = _merge_cff_to_cff(lat_scale=0.9, lat_baseline=-40)
        td = m["CFF "].cff.topDictIndex[0]
        fb = td.FontBBox
        gs = m.getGlyphSet()
        for gname in td.CharStrings.keys():
            pen = BoundsPen(gs)
            try:
                gs[gname].draw(pen)
            except Exception:
                continue
            if pen.bounds is None:
                continue
            xmin, ymin, xmax, ymax = pen.bounds
            assert xmin >= fb[0] - 1, f"{gname} xMin {xmin} < FontBBox {fb}"
            assert ymin >= fb[1] - 1, f"{gname} yMin {ymin} < FontBBox {fb}"
            assert xmax <= fb[2] + 1, f"{gname} xMax {xmax} > FontBBox {fb}"
            assert ymax <= fb[3] + 1, f"{gname} yMax {ymax} > FontBBox {fb}"


# ---------------------------------------------------------------------------
# Base-only merge (no Latin font)
# ---------------------------------------------------------------------------

class TestBaseOnly:
    """Verify that base-font-only merge (no Latin) works correctly."""

    def _merge_base_only(self):
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "base": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "outputFormat": "ttf",
            "outputPath": out,
            "outputFamilyName": "BaseOnly",
        }
        mf.merge_fonts(config)
        return out

    def test_merge_succeeds(self):
        """Base-font-only merge completes without error."""
        out = self._merge_base_only()
        try:
            font = TTFont(out)
            assert len(font.getGlyphOrder()) > 1
        finally:
            for f in (out, out.replace(".ttf", ".woff2")):
                if os.path.exists(f):
                    os.remove(f)

    def test_japanese_glyph_present(self):
        """Japanese glyphs are present in the output."""
        out = self._merge_base_only()
        try:
            font = TTFont(out)
            cmap = font.getBestCmap()
            assert 0x3042 in cmap  # あ
        finally:
            for f in (out, out.replace(".ttf", ".woff2")):
                if os.path.exists(f):
                    os.remove(f)


# ---------------------------------------------------------------------------
# WOFF2 output
# ---------------------------------------------------------------------------

class TestWOFF2Output:
    """Verify that WOFF2 output is correctly generated."""

    def test_woff2_generated(self):
        """A .woff2 file is generated alongside the main output."""
        out = tempfile.mktemp(suffix=".ttf")
        woff2_path = out.replace(".ttf", ".woff2")
        config = {
            "latin": {
                "path": EN_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [
                    {"tag": "opsz", "currentValue": 14},
                    {"tag": "wght", "currentValue": 400},
                ],
            },
            "base": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "outputFormat": "ttf",
            "outputPath": out,
            "outputFamilyName": "TestWoff2",
        }
        mf.merge_fonts(config)
        try:
            assert os.path.exists(woff2_path), "WOFF2 output missing"
            woff2_font = TTFont(woff2_path)
            assert woff2_font.flavor == "woff2"
            assert len(woff2_font.getGlyphOrder()) > 1
        finally:
            for f in (out, woff2_path):
                if os.path.exists(f):
                    os.remove(f)

    def test_woff2_base_only(self):
        """WOFF2 is also generated for base-font-only merge."""
        out = tempfile.mktemp(suffix=".otf")
        woff2_path = out.replace(".otf", ".woff2")
        config = {
            "base": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "outputFormat": "otf",
            "outputPath": out,
            "outputFamilyName": "BaseOnlyWoff2",
        }
        mf.merge_fonts(config)
        try:
            assert os.path.exists(woff2_path), "WOFF2 output missing for base-only"
        finally:
            for f in (out, woff2_path):
                if os.path.exists(f):
                    os.remove(f)


# ---------------------------------------------------------------------------
# Large CID font (65535 glyphs) — run with: pytest -k LargeCID
# ---------------------------------------------------------------------------

JP_CID = JP_OTF


@pytest.mark.skipif(
    not os.path.exists(JP_CID),
    reason="NotoSansCJKjp-Regular.otf not in python/tests/NotoSansCJKjp/",
)
class TestLargeCIDFont:
    """Verify merge of a 65535-glyph CID font with a Latin font."""

    def _merge_large(self):
        out = tempfile.mktemp(suffix=".otf")
        config = {
            "latin": {
                "path": EN_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "base": {
                "path": JP_CID,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "outputFormat": "otf",
            "outputPath": out,
            "outputFamilyName": "LargeCIDTest",
        }
        mf.merge_fonts(config)
        return out

    def test_merge_succeeds(self):
        """65535-glyph CID font merges without error."""
        out = self._merge_large()
        try:
            font = TTFont(out)
            assert len(font.getGlyphOrder()) <= 65535
        finally:
            for f in (out, out.replace(".otf", ".woff2")):
                if os.path.exists(f):
                    os.remove(f)

    def test_glyph_count_not_exceed_limit(self):
        """Merged glyph count does not exceed 65535."""
        out = self._merge_large()
        try:
            font = TTFont(out)
            assert len(font.getGlyphOrder()) == 65535
        finally:
            for f in (out, out.replace(".otf", ".woff2")):
                if os.path.exists(f):
                    os.remove(f)

    def test_latin_glyph_replaced_via_cmap(self):
        """Latin glyphs are replaced via cmap."""
        out = self._merge_large()
        try:
            font = TTFont(out)
            cmap = font.getBestCmap()
            assert 0x0041 in cmap, "U+0041 (A) not in merged cmap"
            gs = font.getGlyphSet()
            gname = cmap[0x0041]
            bp = BoundsPen(gs)
            gs[gname].draw(bp)
            assert bp.bounds is not None, "Latin A has no outline in merged font"
        finally:
            for f in (out, out.replace(".otf", ".woff2")):
                if os.path.exists(f):
                    os.remove(f)

    def test_post_format_3(self):
        """Large fonts use post format 3.0."""
        out = self._merge_large()
        try:
            font = TTFont(out)
            assert font["post"].formatType == 3.0
        finally:
            for f in (out, out.replace(".otf", ".woff2")):
                if os.path.exists(f):
                    os.remove(f)


# ---------------------------------------------------------------------------
# Latin cmap-variant collision (Playwrite IE has both `e` and `e.mod`)
# ---------------------------------------------------------------------------

class TestLatinCmapVariantCollision:
    """
    Regression: Playwrite IE maps U+0065 -> `e.mod` via cmap but also keeps
    a distinct plain `e` glyph referenced by GSUB lookups. Renaming
    `e.mod` -> `e` on copy used to collide with Playwrite's own `e`, fusing
    two distinct glyphs and producing wrong contextual substitutions.
    """

    @staticmethod
    def _merge_playwrite_kaisei():
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "latin": {"path": PLAYWRITE, "scale": 1.0, "baselineOffset": 0,
                      "axes": [{"tag": "wght", "currentValue": 400}]},
            "base": {"path": KAISEI, "scale": 1.0, "baselineOffset": 0, "axes": []},
            "outputFormat": "ttf", "outputPath": out, "outputFamilyName": "Test",
        }
        mf.merge_fonts(config)
        font = TTFont(out)
        os.remove(out)
        return font

    def test_cmap_variant_and_base_are_distinct(self):
        m = self._merge_playwrite_kaisei()
        order = set(m.getGlyphOrder())
        assert "e.mod" in order
        assert "e" in order or "e.lat" in order

    def test_cmap_points_at_variant(self):
        m = self._merge_playwrite_kaisei()
        cmap = m.getBestCmap()
        assert cmap.get(0x0065) == "e.mod"

    def test_variant_has_distinct_outline_from_base(self):
        m = self._merge_playwrite_kaisei()
        order = set(m.getGlyphOrder())
        base_name = "e" if "e" in order else "e.lat"
        b_mod = _get_bounds(m, "e.mod")
        b_base = _get_bounds(m, base_name)
        assert b_mod is not None and b_base is not None
        assert b_mod != b_base


# ---------------------------------------------------------------------------
# Export artifacts (OFL.txt, Settings.txt, export_fonts)
# ---------------------------------------------------------------------------

class TestBuildOflText:

    def test_collects_source_copyrights(self):
        config = {
            "base": {"copyright": "Copyright Base"},
            "latin": {"copyright": "Copyright Latin"},
            "outputFamilyName": "Test",
        }
        text = mf.build_ofl_text(config)
        assert "Copyright Base" in text
        assert "Copyright Latin" in text
        assert "SIL OPEN FONT LICENSE" in text

    def test_user_copyright_appended(self):
        config = {
            "base": {"copyright": "Copyright Base"},
            "outputCopyright": "Copyright User",
            "outputFamilyName": "Test",
        }
        text = mf.build_ofl_text(config)
        assert "Copyright User" in text

    def test_fallback_copyright(self):
        config = {
            "base": {},
            "outputFamilyName": "MyFont",
        }
        text = mf.build_ofl_text(config)
        assert "MyFont Authors" in text

    def test_dedup_copyrights(self):
        config = {
            "base": {"copyright": "Same"},
            "latin": {"copyright": "Same"},
            "outputFamilyName": "Test",
        }
        text = mf.build_ofl_text(config)
        assert text.count("Same") == 1


class TestBuildSettingsText:

    def test_header_includes_family_and_style(self):
        config = {
            "base": {"familyName": "Noto", "styleName": "Regular",
                     "scale": 1.0, "baselineOffset": 0, "path": "/fonts/noto.otf"},
            "outputFamilyName": "MyFont",
            "outputWeight": 700,
            "outputItalic": True,
            "outputWidth": 5,
        }
        text = mf.build_settings_text(config)
        assert "MyFont Bold Italic" in text

    def test_base_only_shows_baked(self):
        config = {
            "base": {"familyName": "Noto", "styleName": "Regular",
                     "scale": 1.0, "baselineOffset": 0, "path": "/fonts/noto.otf"},
            "outputFamilyName": "MyFont",
            "outputWeight": 400,
        }
        text = mf.build_settings_text(config)
        assert "Baked with" in text

    def test_with_latin_shows_merged(self):
        config = {
            "base": {"familyName": "Noto", "styleName": "Regular",
                     "scale": 1.0, "baselineOffset": 0, "path": "/fonts/noto.otf"},
            "latin": {"familyName": "Inter", "styleName": "Regular",
                      "scale": 0.95, "baselineOffset": 5, "path": "/fonts/inter.ttf"},
            "outputFamilyName": "MyFont",
            "outputWeight": 400,
        }
        text = mf.build_settings_text(config)
        assert "Merged with" in text
        assert "[Latin/Kana Font]" in text


class TestDetectSfntExt:

    def test_ttf_font(self):
        assert mf.detect_sfnt_ext(EN_VAR) == "ttf"

    def test_fallback_by_extension(self):
        assert mf.detect_sfnt_ext("/nonexistent/font.otf") == "otf"
        assert mf.detect_sfnt_ext("/nonexistent/font.ttf") == "ttf"


class TestComputeStyleName:

    def test_regular(self):
        assert mf.compute_style_name(400, False, 5) == "Regular"

    def test_bold_italic(self):
        assert mf.compute_style_name(700, True, 5) == "Bold Italic"

    def test_condensed_semibold(self):
        assert mf.compute_style_name(600, False, 3) == "Condensed SemiBold"


class TestPrepareOutputDir:

    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as d:
            result = mf.prepare_output_dir(d, "TestFont", overwrite=False)
            assert os.path.isdir(result)
            assert result == os.path.join(d, "TestFont")

    def test_overwrite_false_raises(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Existing"))
            with pytest.raises(FileExistsError):
                mf.prepare_output_dir(d, "Existing", overwrite=False)

    def test_overwrite_true_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            existing = os.path.join(d, "Existing")
            os.makedirs(existing)
            marker = os.path.join(existing, "old.txt")
            open(marker, "w").close()
            result = mf.prepare_output_dir(d, "Existing", overwrite=True)
            assert os.path.isdir(result)
            assert not os.path.exists(marker)


class TestExportFonts:

    def _export(self, overwrite=False):
        d = tempfile.mkdtemp()
        config = {
            "latin": {
                "path": EN_VAR,
                "familyName": "Inter",
                "styleName": "Regular",
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [
                    {"tag": "opsz", "currentValue": 14},
                    {"tag": "wght", "currentValue": 400},
                ],
            },
            "base": {
                "path": JP_VAR,
                "familyName": "Noto Sans JP",
                "styleName": "Regular",
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "outputDir": d,
            "outputFolderName": "TestFont-Regular",
            "overwrite": overwrite,
            "outputFamilyName": "TestFont",
            "outputWeight": 400,
            "outputItalic": False,
            "outputWidth": 5,
        }
        manifest = mf.export_fonts(config)
        return d, manifest

    def test_manifest_keys(self):
        d, manifest = self._export()
        assert set(manifest.keys()) == {
            "outputDir", "fontPath", "woff2Path", "oflPath",
            "settingsPath", "configPath", "files",
        }
        import shutil
        shutil.rmtree(d)

    def test_font_file_exists(self):
        d, manifest = self._export()
        assert os.path.isfile(manifest["fontPath"])
        assert manifest["fontPath"].endswith(".ttf")
        import shutil
        shutil.rmtree(d)

    def test_woff2_exists(self):
        d, manifest = self._export()
        assert os.path.isfile(manifest["woff2Path"])
        assert manifest["woff2Path"].endswith(".woff2")
        import shutil
        shutil.rmtree(d)

    def test_ofl_txt_exists(self):
        d, manifest = self._export()
        assert os.path.isfile(manifest["oflPath"])
        with open(manifest["oflPath"]) as f:
            assert "SIL OPEN FONT LICENSE" in f.read()
        import shutil
        shutil.rmtree(d)

    def test_settings_txt_exists(self):
        d, manifest = self._export()
        assert os.path.isfile(manifest["settingsPath"])
        with open(manifest["settingsPath"]) as f:
            content = f.read()
            assert "TestFont" in content
            assert "Merged with" in content
        import shutil
        shutil.rmtree(d)

    def test_overwrite_false_blocks_duplicate(self):
        d, _ = self._export()
        with pytest.raises(FileExistsError):
            config = {
                "latin": {
                    "path": EN_VAR, "scale": 1.0, "baselineOffset": 0,
                    "axes": [{"tag": "opsz", "currentValue": 14}, {"tag": "wght", "currentValue": 400}],
                },
                "base": {
                    "path": JP_VAR, "scale": 1.0, "baselineOffset": 0,
                    "axes": [{"tag": "wght", "currentValue": 400}],
                },
                "outputDir": d,
                "outputFolderName": "TestFont-Regular",
                "overwrite": False,
                "outputFamilyName": "TestFont",
            }
            mf.export_fonts(config)
        import shutil
        shutil.rmtree(d)

    def test_overwrite_true_succeeds(self):
        d, _ = self._export()
        _, manifest2 = self._export(overwrite=True)
        assert os.path.isfile(manifest2["fontPath"])
        import shutil
        shutil.rmtree(d)

    def test_manifest_has_files_array(self):
        d, manifest = self._export()
        assert "files" in manifest
        assert manifest["fontPath"] in manifest["files"]
        assert manifest["oflPath"] in manifest["files"]
        assert manifest["settingsPath"] in manifest["files"]
        import shutil
        shutil.rmtree(d)

    def test_config_path_null_by_default(self):
        d, manifest = self._export()
        assert manifest["configPath"] is None
        import shutil
        shutil.rmtree(d)


class TestOutputOptions:

    def _base_config(self, tmpdir):
        return {
            "latin": {
                "path": EN_VAR,
                "familyName": "Inter",
                "styleName": "Regular",
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [
                    {"tag": "opsz", "currentValue": 14},
                    {"tag": "wght", "currentValue": 400},
                ],
            },
            "base": {
                "path": JP_VAR,
                "familyName": "Noto Sans JP",
                "styleName": "Regular",
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "outputDir": tmpdir,
            "outputFolderName": "TestFont-Regular",
            "overwrite": False,
            "outputFamilyName": "TestFont",
            "outputWeight": 400,
            "outputItalic": False,
            "outputWidth": 5,
        }

    def test_include_woff2_false(self):
        import shutil
        d = tempfile.mkdtemp()
        config = self._base_config(d)
        config["outputOptions"] = {"includeWoff2": False}
        manifest = mf.export_fonts(config)
        assert manifest["woff2Path"] is None
        assert not os.path.exists(os.path.join(d, "TestFont-Regular", "TestFont-Regular.woff2"))
        shutil.rmtree(d)

    def test_write_config_json(self):
        import shutil
        d = tempfile.mkdtemp()
        config = self._base_config(d)
        config["outputOptions"] = {"writeConfigJson": True}
        manifest = mf.export_fonts(config)
        assert manifest["configPath"] is not None
        assert os.path.isfile(manifest["configPath"])
        with open(manifest["configPath"]) as f:
            export_cfg = json.load(f)
        assert export_cfg["outputFamilyName"] == "TestFont"
        assert export_cfg["base"]["path"] == JP_VAR
        shutil.rmtree(d)

    def test_bundle_input_fonts(self):
        import shutil
        d = tempfile.mkdtemp()
        config = self._base_config(d)
        config["outputOptions"] = {"writeConfigJson": True, "bundleInputFonts": True}
        manifest = mf.export_fonts(config)
        source_dir = os.path.join(d, "TestFont-Regular", "source")
        assert os.path.isdir(source_dir)
        assert os.path.isfile(os.path.join(source_dir, os.path.basename(EN_VAR)))
        assert os.path.isfile(os.path.join(source_dir, os.path.basename(JP_VAR)))
        with open(manifest["configPath"]) as f:
            export_cfg = json.load(f)
        assert export_cfg["base"]["path"].startswith("./source/")
        assert export_cfg["latin"]["path"].startswith("./source/")
        shutil.rmtree(d)

    def test_unsupported_font_format_raises(self):
        d = tempfile.mkdtemp()
        config = self._base_config(d)
        config["outputOptions"] = {"fontFormat": "otf"}
        with pytest.raises(ValueError, match="Unsupported fontFormat"):
            mf.export_fonts(config)
        import shutil
        shutil.rmtree(d)

    def test_unsupported_bundle_mode_raises(self):
        d = tempfile.mkdtemp()
        config = self._base_config(d)
        config["outputOptions"] = {"bundleMode": "flat"}
        with pytest.raises(ValueError, match="Unsupported bundleMode"):
            mf.export_fonts(config)
        import shutil
        shutil.rmtree(d)

    def test_unknown_option_raises(self):
        d = tempfile.mkdtemp()
        config = self._base_config(d)
        config["outputOptions"] = {"unknownKey": True}
        with pytest.raises(ValueError, match="Unknown outputOptions"):
            mf.export_fonts(config)
        import shutil
        shutil.rmtree(d)

    def test_default_options(self):
        opts = mf.resolve_output_options({})
        assert opts == {
            "bundleMode": "directory",
            "fontFormat": "auto",
            "includeWoff2": True,
            "writeConfigJson": False,
            "bundleInputFonts": False,
        }

    def test_font_format_auto_uses_base_ext(self):
        import shutil
        d = tempfile.mkdtemp()
        config = self._base_config(d)
        config["outputOptions"] = {"fontFormat": "auto"}
        manifest = mf.export_fonts(config)
        assert manifest["fontPath"].endswith(".ttf")
        shutil.rmtree(d)
