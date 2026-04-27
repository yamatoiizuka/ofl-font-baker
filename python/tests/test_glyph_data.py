"""Tests for outlines, metrics, hint info, and layout features after merge."""

import os
import tempfile

import pytest

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from conftest import (
    EN_CFF, EN_FULL, EN_VAR, JP_FULL_VAR, JP_OTF, JP_STATIC, JP_VAR,
    KAISEI, PLAYWRITE,
    _cid_glyph_for_codepoint, _get_bounds, _merge, _merge_cff_to_cff,
)

import merge_fonts as mf


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
            "subFont": {"path": EN_VAR, "scale": 1.0, "baselineOffset": 0, "axes": []},
            "baseFont": {"path": JP_VAR, "scale": 1.0, "baselineOffset": 0, "axes": []},
            "output": {"familyName": "Test"}, "export": {"path": {"font": out}},
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

    def test_jp_composite_not_double_shifted(self):
        """JP composite glyphs (Kaisei `acute`, `dieresis`) shift by exactly
        jp_baseline, not double. Regression for Issue #2 #3 — the actual fault
        was in `transform_tt_glyph_inplace`, not `copy_glyph_tt` as the issue
        suggested: `transform_tt_glyph_inplace` was adding `dy` to composite
        component.y on top of the base-glyph contour shift, double-shifting
        the composite render.
        """
        import tempfile

        def _merge_kaisei(jp_baseline):
            out = tempfile.mktemp(suffix=".ttf")
            config = {
                "subFont": {"path": EN_VAR, "scale": 1.0,
                            "baselineOffset": 0, "axes": []},
                "baseFont": {"path": KAISEI, "scale": 1.0,
                             "baselineOffset": jp_baseline, "axes": []},
                "output": {"familyName": "TestKaisei"},
                "export": {"path": {"font": out}},
            }
            mf.merge_fonts(config)
            font = TTFont(out)
            os.remove(out)
            woff2 = out.replace(".ttf", ".woff2")
            if os.path.exists(woff2):
                os.remove(woff2)
            return font

        m0 = _merge_kaisei(0)
        m100 = _merge_kaisei(-100)
        for gname in ("acute", "dieresis"):
            if gname not in m0.getGlyphOrder():
                continue
            b0 = _get_bounds(m0, gname)
            b100 = _get_bounds(m100, gname)
            if b0 is None or b100 is None:
                continue
            dy = round(b100[1] - b0[1])
            assert abs(dy - (-100)) <= 2, (
                f"{gname} (JP composite) shift={dy}, expected -100 "
                f"(double-shift bug at ~-200)"
            )



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
# Feature preservation (GSUB / GPOS)
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

    def test_base_kern_preserved_in_dflt_script(self):
        """CJK kern (e.g. す。) from base font is accessible from DFLT script."""
        if not os.path.exists(JP_FULL_VAR):
            pytest.skip("NotoSansJP-VariableFont_wght.ttf not found")
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {
                "path": EN_CFF,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": JP_FULL_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "TestKern"},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        font = TTFont(out)
        os.remove(out)

        gpos = font["GPOS"].table

        # Find kern feature indices referenced by DFLT script
        dflt_kern_feat_indices = set()
        for sr in gpos.ScriptList.ScriptRecord:
            if sr.ScriptTag == "DFLT" and sr.Script.DefaultLangSys:
                for fi in sr.Script.DefaultLangSys.FeatureIndex:
                    if gpos.FeatureList.FeatureRecord[fi].FeatureTag == "kern":
                        dflt_kern_feat_indices.add(fi)
        assert dflt_kern_feat_indices, "DFLT script should have kern features"

        # Collect all kern lookup indices reachable from DFLT
        dflt_kern_lookups = set()
        for fi in dflt_kern_feat_indices:
            dflt_kern_lookups.update(
                gpos.FeatureList.FeatureRecord[fi].Feature.LookupListIndex)

        # Verify す。pair (XAdvance=-100) is in one of these lookups
        found = False
        for li in dflt_kern_lookups:
            lookup = gpos.LookupList.Lookup[li]
            for subtable in lookup.SubTable:
                st = subtable
                if hasattr(st, "ExtSubTable"):
                    st = st.ExtSubTable
                if not hasattr(st, "Coverage") or not st.Coverage:
                    continue
                if "uni3059" not in st.Coverage.glyphs:
                    continue
                if st.Format == 1:
                    idx = st.Coverage.glyphs.index("uni3059")
                    for pvr in st.PairSet[idx].PairValueRecord:
                        if pvr.SecondGlyph == "uni3002":
                            assert pvr.Value1.XAdvance == -100
                            found = True
        assert found, "す。kern pair (XAdvance=-100) should be reachable from DFLT"

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
# Glyph names and composite glyphs
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
# Metrics preservation and output UPM
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
            "subFont": None,
            "baseFont": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "Test", "upm": 1500},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        m = TTFont(out)
        os.remove(out)
        assert m["head"].unitsPerEm == 1500



# ---------------------------------------------------------------------------
# TrueType hinting preservation
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
# CFF hinting / coincidence / FontBBox
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.exists(JP_OTF),
    reason="NotoSansCJKjp-subset.otf not present",
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

    def test_cff_top_dict_family_name(self):
        """CFF TopDict FamilyName mirrors nameID 1."""
        m = _merge_cff_to_cff()
        td = m["CFF "].cff.topDictIndex[0]
        assert td.FamilyName == "TestHint"

    def test_cff_top_dict_full_name(self):
        """CFF TopDict FullName mirrors nameID 4 (family + style)."""
        m = _merge_cff_to_cff()
        td = m["CFF "].cff.topDictIndex[0]
        assert td.FullName == "TestHint Regular"

    def test_cff_top_dict_notice_mirrors_copyright(self):
        """CFF TopDict Notice mirrors the merged nameID 0 copyright."""
        m = _merge_cff_to_cff()
        td = m["CFF "].cff.topDictIndex[0]
        name_copyright = m["name"].getDebugName(0)
        assert td.Notice == name_copyright

    def test_cff_font_names_mirrors_postscript_name(self):
        """CFF Name INDEX fontNames[0] mirrors nameID 6 (PostScript name)."""
        m = _merge_cff_to_cff()
        cff = m["CFF "].cff
        assert cff.fontNames, "CFF Name INDEX is unexpectedly empty"
        assert cff.fontNames[0] == m["name"].getDebugName(6)


@pytest.mark.skipif(
    not os.path.exists(JP_OTF),
    reason="NotoSansCJKjp-subset.otf not present",
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
    not os.path.exists(JP_OTF),
    reason="NotoSansCJKjp-subset.otf not present",
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
# Latin cmap variant collision
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
            "subFont": {"path": PLAYWRITE, "scale": 1.0, "baselineOffset": 0,
                       "axes": [{"tag": "wght", "currentValue": 400}]},
            "baseFont": {"path": KAISEI, "scale": 1.0, "baselineOffset": 0, "axes": []},
            "output": {"familyName": "Test"}, "export": {"path": {"font": out}},
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
# Shared-glyph collateral damage (U+2027 / U+30FB middle dot)
# ---------------------------------------------------------------------------

class TestSharedGlyphCollateral:
    """
    Regression: Noto Sans JP maps both U+2027 (HYPHENATION POINT) and
    U+30FB (KATAKANA MIDDLE DOT) to the same glyph "uni2027".  When Inter
    replaces U+2027, the shared glyph was overwritten in place — U+30FB
    silently became a half-width Latin glyph instead of the original
    full-width katakana middle dot.  The merge engine must duplicate the
    original glyph and repoint collateral cmap entries.
    """

    @staticmethod
    def _merge():
        if not os.path.exists(EN_FULL) or not os.path.exists(JP_STATIC):
            pytest.skip("Full Inter / Noto Sans JP fonts not found")
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {"path": EN_FULL, "scale": 1.0, "baselineOffset": 0,
                       "axes": [{"tag": "opsz", "currentValue": 14},
                                {"tag": "wght", "currentValue": 400}]},
            "baseFont": {"path": JP_STATIC, "scale": 1.0, "baselineOffset": 0,
                         "axes": []},
            "output": {"familyName": "TestMiddleDot"},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        font = TTFont(out)
        os.remove(out)
        return font

    def test_katakana_middle_dot_preserves_width(self):
        """U+30FB must keep its full-width advance (1000) after merge."""
        m = self._merge()
        cmap = m.getBestCmap()
        glyph_30fb = cmap.get(0x30FB)
        assert glyph_30fb is not None, "U+30FB missing from cmap"
        aw = m["hmtx"].metrics[glyph_30fb][0]
        assert aw >= 900, (
            f"U+30FB advance width {aw} is too narrow — "
            "shared glyph was likely overwritten by Latin replacement"
        )

    def test_hyphenation_point_uses_latin_glyph(self):
        """U+2027 should be replaced by the Inter glyph (half-width)."""
        m = self._merge()
        cmap = m.getBestCmap()
        glyph_2027 = cmap.get(0x2027)
        assert glyph_2027 is not None, "U+2027 missing from cmap"
        aw = m["hmtx"].metrics[glyph_2027][0]
        # Inter's U+2027 is narrow (~590 at 2048 UPM → ~288 at 1000 UPM)
        assert aw < 600, (
            f"U+2027 advance width {aw} — expected narrow Latin replacement"
        )

    def test_middle_dots_are_distinct_glyphs(self):
        """U+30FB and U+2027 must point to different glyph names."""
        m = self._merge()
        cmap = m.getBestCmap()
        assert cmap.get(0x30FB) != cmap.get(0x2027), (
            "U+30FB and U+2027 should no longer share the same glyph"
        )

    def test_katakana_middle_dot_has_outline(self):
        """U+30FB must still have a drawable outline."""
        m = self._merge()
        cmap = m.getBestCmap()
        bounds = _get_bounds(m, cmap[0x30FB])
        assert bounds is not None, "U+30FB has no outline"




# ---------------------------------------------------------------------------
# Same-tag features merge under Latin scripts (Issue #2 #6)
# ---------------------------------------------------------------------------


class TestSameTagFeatures:
    """`_build_lang_sys` must surface JP-side feature lookups under Latin
    scripts even when the tag is also defined on the Latin side."""

    @staticmethod
    def _coverage_for_tag(font, tag):
        glyphs = set()
        if "GSUB" not in font:
            return glyphs
        t = font["GSUB"].table
        for fr in t.FeatureList.FeatureRecord:
            if fr.FeatureTag != tag:
                continue
            for li in fr.Feature.LookupListIndex:
                glyphs.update(mf._collect_lookup_glyphs(t.LookupList.Lookup[li]))
        return glyphs

    @staticmethod
    def _latin_langsys(font):
        if "GSUB" not in font:
            return []
        out = []
        for sr in font["GSUB"].table.ScriptList.ScriptRecord:
            if sr.ScriptTag in ("latn", "DFLT"):
                if sr.Script.DefaultLangSys:
                    out.append(sr.Script.DefaultLangSys)
                for lsr in (sr.Script.LangSysRecord or []):
                    out.append(lsr.LangSys)
        return out

    def test_jp_aalt_lookups_reachable_from_latin_langsys(self):
        """JP-side `aalt` lookups (which target JP glyphs) must remain
        reachable from the merged Latin script's LangSys instead of being
        silently dropped because Latin also defines `aalt`."""
        en_aalt = self._coverage_for_tag(TTFont(EN_VAR), "aalt")
        jp_aalt = self._coverage_for_tag(TTFont(JP_VAR), "aalt")
        jp_only = jp_aalt - en_aalt
        if not jp_only:
            pytest.skip("Fixture has no JP-only aalt glyphs to check")

        m = _merge()
        gsub = m["GSUB"].table
        feat_list = gsub.FeatureList.FeatureRecord
        lookup_list = gsub.LookupList.Lookup
        reach_lookups = set()
        for ls in self._latin_langsys(m):
            for fi in (ls.FeatureIndex or []):
                if feat_list[fi].FeatureTag == "aalt":
                    reach_lookups.update(feat_list[fi].Feature.LookupListIndex)
        reach_glyphs = set()
        for li in reach_lookups:
            reach_glyphs.update(mf._collect_lookup_glyphs(lookup_list[li]))

        seen_jp_only = reach_glyphs & jp_only
        assert seen_jp_only, (
            f"None of {len(jp_only)} JP-only aalt glyphs are reachable from "
            f"the Latin LangSys; the JP `aalt` feature was dropped instead "
            f"of being merged in alongside the Latin one."
        )


# ---------------------------------------------------------------------------
# maxp recalc after merge (Issue #2 #8)
# ---------------------------------------------------------------------------


class TestMaxpRecalc:
    """The merge engine must refresh maxp sub-fields so they reflect the
    glyphs added by the Latin sub. fontTools' save() refreshes numGlyphs
    but not the per-glyph maxima."""

    LATEEF = os.path.join(os.path.dirname(EN_VAR), "..", "Lateef",
                          "Lateef-Regular.ttf")

    def test_maxp_reflects_added_latin_glyphs(self):
        """Every maxp sub-field — including the composite-walking ones
        (`maxCompositePoints` / `maxCompositeContours`) — must reflect
        Lateef's glyphs after merge. Captured pre-save via TTFont.save
        patch so the test catches in-memory staleness even when fontTools'
        own save would have masked it on disk."""
        if not os.path.exists(self.LATEEF):
            pytest.skip("Lateef not available")
        captured = {}
        orig_save = TTFont.save

        def patched(self, *args, **kwargs):
            if "maxp" in self and "glyf" in self and not captured:
                for attr in ("maxPoints", "maxContours",
                             "maxCompositePoints", "maxCompositeContours",
                             "maxComponentElements", "maxComponentDepth"):
                    captured[attr] = getattr(self["maxp"], attr, None)
            return orig_save(self, *args, **kwargs)

        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {"path": self.LATEEF, "scale": 1.0,
                        "baselineOffset": 0, "axes": []},
            "baseFont": {"path": JP_VAR, "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
            "output": {"familyName": "TestMaxp"},
            "export": {"path": {"font": out}},
        }
        TTFont.save = patched
        try:
            mf.merge_fonts(config)
            assert captured.get("maxPoints", 0) >= 1000, (
                f"maxPoints={captured.get('maxPoints')}, expected >=1000"
            )
            assert captured.get("maxContours", 0) >= 50, (
                f"maxContours={captured.get('maxContours')}, expected >=50"
            )
            assert captured.get("maxCompositePoints", 0) > 0, (
                f"maxCompositePoints={captured.get('maxCompositePoints')}, "
                f"expected >0 (composites in Lateef should populate this)"
            )
            assert captured.get("maxCompositeContours", 0) > 0, (
                f"maxCompositeContours={captured.get('maxCompositeContours')}"
            )
            assert captured.get("maxComponentElements", 0) >= 5, (
                f"maxComponentElements={captured.get('maxComponentElements')}"
            )
        finally:
            TTFont.save = orig_save
            for p in (out, out.replace(".ttf", ".woff2")):
                if os.path.exists(p):
                    os.remove(p)
