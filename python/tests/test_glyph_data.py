"""Tests for outlines, metrics, hint info, and layout features after merge."""

import os
import tempfile

import pytest

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from conftest import (
    EN_CFF, EN_FULL, EN_VAR, JP_FULL_VAR, JP_OTF, JP_OTF_FULL,
    JP_STATIC, JP_VAR, KAISEI, PLAYWRITE, TIKTOK_SANS,
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
# Latin kerning preservation when JP base ships its own Latin kerning
# ---------------------------------------------------------------------------

class TestLatinKernPreservation:
    """Latin pair kerning must equal the source even when the JP base
    (e.g. Noto Sans JP) ships its own Latin kerning for the same pairs.

    Uses TikTok Sans (UPM=1000) as the Latin source so kern values share a
    UPM with Noto Sans JP — any change in the merged value reflects a real
    GPOS bug, not UPM rounding.
    """

    def _merge_tiktok_noto(self):
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {
                "path": TIKTOK_SANS,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": JP_STATIC,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "output": {"familyName": "TestKernPreserve", "upm": 1000},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        font = TTFont(out)
        os.remove(out)
        for ext in (".woff2",):
            sib = out.replace(".ttf", ext)
            if os.path.exists(sib):
                os.remove(sib)
        return font

    def _sum_kern(self, font, glyph1, glyph2):
        """Sum every kern XAdvance applied to a (g1, g2) pair across all
        kern lookups — mirroring how a shaper stacks adjustments when the
        same tag points at multiple lookups."""
        gpos = font["GPOS"].table
        total = 0
        seen = False
        for fr in gpos.FeatureList.FeatureRecord:
            if fr.FeatureTag != "kern":
                continue
            for li in fr.Feature.LookupListIndex:
                lk = gpos.LookupList.Lookup[li]
                for st in lk.SubTable:
                    ext = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
                    cov = getattr(ext, "Coverage", None)
                    if not cov or isinstance(cov, list):
                        continue
                    if glyph1 not in (cov.glyphs or []):
                        continue
                    if ext.Format == 1 and hasattr(ext, "PairSet"):
                        idx = cov.glyphs.index(glyph1)
                        for pvr in ext.PairSet[idx].PairValueRecord:
                            if pvr.SecondGlyph == glyph2:
                                v = pvr.Value1.XAdvance if pvr.Value1 else 0
                                if v:
                                    seen = True
                                    total += v
                    if ext.Format == 2 and hasattr(ext, "ClassDef1"):
                        c1 = ext.ClassDef1.classDefs.get(glyph1, 0)
                        c2 = ext.ClassDef2.classDefs.get(glyph2, 0)
                        val = ext.Class1Record[c1].Class2Record[c2]
                        v = val.Value1.XAdvance if val.Value1 else 0
                        if v:
                            seen = True
                            total += v
        return total if seen else None

    def _script_feature_indices(self, font, table_tag, script_tag, feature_tag):
        table = font[table_tag].table
        for sr in table.ScriptList.ScriptRecord:
            if sr.ScriptTag != script_tag or not sr.Script.DefaultLangSys:
                continue
            return [
                fi for fi in sr.Script.DefaultLangSys.FeatureIndex
                if table.FeatureList.FeatureRecord[fi].FeatureTag == feature_tag
            ]
        return []

    def _feature_has_pair_kern(self, font, feature_index, glyph1, glyph2):
        gpos = font["GPOS"].table
        feature = gpos.FeatureList.FeatureRecord[feature_index].Feature
        for li in feature.LookupListIndex:
            lk = gpos.LookupList.Lookup[li]
            for st in lk.SubTable:
                ext = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
                cov = getattr(ext, "Coverage", None)
                if not cov or isinstance(cov, list) or glyph1 not in (cov.glyphs or []):
                    continue
                if ext.Format == 1 and hasattr(ext, "PairSet"):
                    idx = cov.glyphs.index(glyph1)
                    for pvr in ext.PairSet[idx].PairValueRecord:
                        if pvr.SecondGlyph == glyph2:
                            return True
                if ext.Format == 2 and hasattr(ext, "ClassDef1"):
                    c1 = ext.ClassDef1.classDefs.get(glyph1, 0)
                    c2 = ext.ClassDef2.classDefs.get(glyph2, 0)
                    val = ext.Class1Record[c1].Class2Record[c2]
                    if val.Value1 and val.Value1.XAdvance:
                        return True
        return False

    # Pairs sampled from TikTok Sans across category x category, biased
    # toward pairs where Noto Sans JP defines a *different* value (so the
    # bug actually manifests for these inputs without the fix).
    KERN_PAIRS = [
        # uppercase – uppercase
        ("A", "T"), ("A", "V"), ("A", "W"), ("A", "Y"),
        ("L", "T"), ("L", "V"), ("L", "W"), ("L", "Y"),
        ("F", "J"), ("P", "J"),
        # uppercase – lowercase  ← the user-reported "Tokyo" / "Type" cases
        ("T", "o"), ("T", "y"), ("T", "s"), ("T", "e"), ("T", "a"),
        ("Y", "e"), ("Y", "a"), ("V", "e"), ("W", "a"), ("K", "o"),
        # lowercase – uppercase
        ("a", "T"), ("e", "T"), ("o", "T"), ("h", "T"), ("n", "T"),
        # lowercase – lowercase
        ("r", "e"), ("r", "c"), ("r", "o"), ("f", "o"), ("k", "o"),
        # punctuation / symbols
        ("T", "period"), ("T", "comma"), ("V", "comma"),
        ("L", "quoteright"),
        # digits
        ("seven", "one"),
    ]

    @pytest.fixture(scope="class")
    def merged_font(self):
        return self._merge_tiktok_noto()

    @pytest.fixture(scope="class")
    def src_font(self):
        return TTFont(TIKTOK_SANS)

    @pytest.mark.parametrize("g1,g2", KERN_PAIRS)
    def test_kern_pair_matches_source(self, src_font, merged_font, g1, g2):
        """Every sampled Latin kern pair must match TikTok's source value
        (no JP overlay stacking onto the Latin font's pair value)."""
        src_kern = self._sum_kern(src_font, g1, g2)
        merged_kern = self._sum_kern(merged_font, g1, g2)
        assert src_kern is not None, (
            f"TikTok source defines no {g1}+{g2} kern; pick a different sample."
        )
        assert merged_kern == src_kern, (
            f"{g1}+{g2} kern changed after merge: "
            f"source={src_kern}, merged={merged_kern}"
        )

    def test_latn_script_has_single_kern_feature(self, merged_font):
        """`latn` should expose exactly one kern feature record.

        HarfBuzz only applies the first auto-enabled GPOS feature for a
        duplicated tag under a LangSys. If both JP and Latin `kern`
        features survive under `latn`, the JP one shadows the Latin one and
        Latin pair kerning disappears in shaping even though the lookup
        exists in the table.
        """
        indices = self._script_feature_indices(merged_font, "GPOS", "latn", "kern")
        assert len(indices) == 1, (
            f"latn script should expose exactly one kern feature, got {indices}"
        )
        assert self._feature_has_pair_kern(merged_font, indices[0], "T", "o"), (
            "latn script's sole kern feature should carry the Latin T+o pair"
        )

    ADVANCE_GLYPHS = [
        # uppercase
        "A", "B", "K", "L", "T", "V", "W", "Y",
        # lowercase
        "a", "e", "f", "g", "i", "k", "n", "o", "r", "s", "t", "y",
        # digits
        "zero", "one", "five", "seven",
        # punctuation / symbols
        "period", "comma", "hyphen", "parenleft", "quoteright",
    ]

    @pytest.mark.parametrize("glyph", ADVANCE_GLYPHS)
    def test_latin_advance_width_preserved(self, src_font, merged_font, glyph):
        """Advance widths for Latin glyphs match the source — no SinglePos
        from the JP base shifts them sideways. Look the merged glyph up via
        cmap because cross-codepoint name collisions (e.g. base reuses
        ``hyphen`` for U+2011 too) auto-rename the sub-font copy."""
        src_cmap_rev = {g: cp for cp, g in src_font.getBestCmap().items()}
        cp = src_cmap_rev.get(glyph)
        assert cp is not None, f"{glyph} not in source cmap"
        merged_glyph = merged_font.getBestCmap().get(cp)
        assert merged_glyph is not None, (
            f"U+{cp:04X} ({glyph}) missing from merged cmap"
        )
        assert merged_font["hmtx"].metrics[merged_glyph] == src_font["hmtx"].metrics[glyph], (
            f"hmtx for U+{cp:04X} changed: "
            f"source[{glyph}]={src_font['hmtx'].metrics[glyph]}, "
            f"merged[{merged_glyph}]={merged_font['hmtx'].metrics[merged_glyph]}"
        )

    def test_jp_pairpos_strips_latin_first_glyph(self, src_font, merged_font):
        """JP-origin PairPos lookups no longer cover 'T' in first position.

        The JP base ships PairPos subtables that include 'T' in their first-
        glyph Coverage (Noto Sans JP has Latin-Latin kerning baked in). The
        merge engine must strip those entries so JP's kern doesn't stack on
        top of the Latin font's own pair values. We match JP-origin
        subtables by their oversized Coverage (Noto's mixed kern lookup is
        far larger than any TikTok subtable).
        """
        # Largest TikTok PairPos subtable sets the "this is Latin-origin"
        # cutoff. Anything bigger in the merged font that still covers 'T'
        # came from the JP base.
        max_lat_cov = 0
        src_gpos = src_font["GPOS"].table
        for lk in src_gpos.LookupList.Lookup:
            for st in lk.SubTable:
                ext = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
                cov = getattr(ext, "Coverage", None)
                if not cov or isinstance(cov, list):
                    continue
                if not (hasattr(ext, "PairSet") or hasattr(ext, "Class1Record")):
                    continue
                if cov.glyphs:
                    max_lat_cov = max(max_lat_cov, len(cov.glyphs))

        gpos = merged_font["GPOS"].table
        offending = []
        for li, lk in enumerate(gpos.LookupList.Lookup):
            for sti, st in enumerate(lk.SubTable):
                ext = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
                cov = getattr(ext, "Coverage", None)
                if not cov or isinstance(cov, list):
                    continue
                if not (hasattr(ext, "PairSet") or hasattr(ext, "Class1Record")):
                    continue
                if "T" not in (cov.glyphs or []):
                    continue
                if len(cov.glyphs) <= max_lat_cov:
                    continue  # Latin-origin subtable, fine
                offending.append((li, sti, len(cov.glyphs)))
        assert not offending, (
            "JP-origin PairPos still covers 'T' in first position "
            f"(kerning would stack): {offending}"
        )



# ---------------------------------------------------------------------------
# Latin ligature preservation when JP base ships Latin-input ligatures
# ---------------------------------------------------------------------------

class TestLatinLigaturePreservation:
    """Pan-CJK base fonts (Noto Sans JP, Source Han Sans) pack Latin-input
    ligatures into ``dlig`` / ``liga`` lookups that emit CJK compatibility
    square symbols (e.g. ``n+s → ㎱`` U+33B1, ``S+v → ㎜``). With dlig
    enabled in Illustrator / InDesign, those rules fire on plain Latin
    text — typing "Sans" produces "Sa㎱". The merge engine must strip
    those Latin-input entries so the Latin font owns its own ligature
    decisions; cross-script ligatures stay reachable.
    """

    SAMPLE_TEXT = ("Sans", "Tokyo", "Type", "AT",
                   # Pairs explicitly known to trigger Noto Sans JP's
                   # square-symbol dlig if the base lookup leaks through:
                   "ns",   # → ㎱ U+33B1
                   "Sv",   # → ㎜ U+33DC
                   "Am",   # → ㏟ U+33DF
                   "AU",   # → ㍳ U+3373
                   "Bq",   # → ㏃ U+33C3
                   "nA",   # → ㎁ U+3381
                   "er",   # → ㌕ U+32CD prefix
                   "rad")

    @pytest.fixture(scope="class")
    def merged_font_path(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("liga") / "merged.ttf"
        config = {
            "subFont": {
                "path": TIKTOK_SANS,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": JP_STATIC,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "output": {"familyName": "TestLigaPreserve", "upm": 1000},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    def _shape(self, font_path, text, features=None):
        """Return the glyph-name sequence produced by HarfBuzz."""
        try:
            import uharfbuzz as hb
        except ImportError:
            pytest.skip("uharfbuzz not installed")
        with open(font_path, "rb") as f:
            data = f.read()
        face = hb.Face(data)
        font = hb.Font(face)
        order = TTFont(font_path).getGlyphOrder()
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(font, buf, features or {})
        return [order[g.codepoint] for g in buf.glyph_infos]

    @pytest.mark.parametrize("text", SAMPLE_TEXT)
    def test_dlig_does_not_emit_cjk_square_symbol(self, merged_font_path, text):
        """With dlig enabled, plain Latin input must not collapse into
        CJK compatibility square symbols (the JP-side ligature trap)."""
        shaped = self._shape(merged_font_path, text, {"dlig": True})
        # CJK compatibility square symbols live in U+3200-33FF. Their
        # fontTools glyph names are typically "uniXXXX" or similar; the
        # robust check is "no glyph name should look like a CJK uni-symbol
        # (uni32xx / uni33xx)".
        offending = [g for g in shaped
                     if g.startswith("uni32") or g.startswith("uni33")]
        assert not offending, (
            f"dlig on {text!r} hit a JP-side square symbol: shaped={shaped}"
        )

    @pytest.mark.parametrize("text", SAMPLE_TEXT)
    def test_dlig_matches_latin_solo(self, merged_font_path, text):
        """Merged font's dlig output for Latin text must equal the Latin
        font's own dlig output (which is "no substitution" for TikTok
        Sans, since it doesn't ship dlig)."""
        merged = self._shape(merged_font_path, text, {"dlig": True})
        solo = self._shape(TIKTOK_SANS, text, {"dlig": True})
        assert merged == solo, (
            f"dlig on {text!r}: merged={merged} vs Latin solo={solo}"
        )

    def test_latn_ccmp_matches_latin_solo(self, merged_font_path):
        """`ccmp` substitutions on Latin combining marks must reach the
        Latin font's `.case` rules.

        Pan-CJK fonts ship their own `ccmp` lookup under `latn`, and
        HarfBuzz lets the first duplicate-tag record win for `ccmp`
        the same way it does for `kern` (verified via `hb-shape`
        --trace). Without dedupe, `gravecomb -> gravecomb.case` and
        similar Latin-side rules never fire and case-sensitive
        combining marks regress to their default form.
        """
        for text in ("M̀", "Ê̄", "À̂",
                     "İ", "T́"):
            merged = self._shape(merged_font_path, text)
            solo = self._shape(TIKTOK_SANS, text)
            assert merged == solo, (
                f"ccmp shaping for {text!r} differs: "
                f"merged={merged}, solo={solo}"
            )

    def test_latn_script_has_single_ccmp_feature(self, merged_font_path):
        """`latn` should expose exactly one `ccmp` feature record."""
        merged = TTFont(merged_font_path)
        gsub = merged["GSUB"].table
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != "latn" or not sr.Script.DefaultLangSys:
                continue
            ccmp = [
                fi for fi in sr.Script.DefaultLangSys.FeatureIndex
                if gsub.FeatureList.FeatureRecord[fi].FeatureTag == "ccmp"
            ]
            assert len(ccmp) == 1, (
                f"latn DefaultLangSys ccmp records: {ccmp}"
            )
            return
        pytest.fail("merged font has no latn script in GSUB")

    def test_jp_only_explicit_latin_script_keeps_ccmp(self, merged_font_path):
        """Per-LangSys dedupe: explicit Latin scripts that the Latin font
        doesn't define keep their JP-side `ccmp` intact.

        TikTok Sans has no `grek` script, but Noto Sans JP does. The
        dedupe rule must not drop JP `grek` `ccmp` just because the tag
        also exists under Latin's `latn` — otherwise Greek text loses
        its combining-mark composition entirely.
        """
        merged = TTFont(merged_font_path)
        gsub = merged["GSUB"].table
        seen = False
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != "grek" or not sr.Script.DefaultLangSys:
                continue
            seen = True
            ccmp = [
                fi for fi in sr.Script.DefaultLangSys.FeatureIndex
                if gsub.FeatureList.FeatureRecord[fi].FeatureTag == "ccmp"
            ]
            assert ccmp, (
                "grek DefaultLangSys lost its JP-side ccmp (per-LangSys "
                "dedupe regression)"
            )
        assert seen, "merged font has no grek script in GSUB"

    def test_jp_dlig_lookup_no_latin_only_entry(self, merged_font_path):
        """Structurally: no surviving GSUB ligature subtable should hold
        an entry whose every input glyph is in the Latin font."""
        merged = TTFont(merged_font_path)
        lat_glyphs = set(TTFont(TIKTOK_SANS).getGlyphOrder())
        gsub = merged["GSUB"].table
        offending = []
        for li, lk in enumerate(gsub.LookupList.Lookup):
            for sti, st in enumerate(lk.SubTable):
                ext = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
                ligs = getattr(ext, "ligatures", None)
                if not ligs:
                    continue
                for first, lig_list in ligs.items():
                    for lig in lig_list or ():
                        comp = getattr(lig, "Component", None) or []
                        inputs = [first, *comp]
                        if all(g in lat_glyphs for g in inputs):
                            # Tolerate Latin-origin lookups (sub font's
                            # own dlig). Use the lookup's overall glyph
                            # set: a lookup whose every referenced glyph
                            # is Latin came from the sub font.
                            all_in_lookup = mf._collect_lookup_glyphs(lk)
                            if all(g in lat_glyphs for g in all_in_lookup):
                                continue
                            offending.append(
                                (li, sti, first, list(comp), lig.LigGlyph)
                            )
        assert not offending, (
            "Base-side LigatureSubst still holds Latin-only entries: "
            f"{offending[:5]}"
        )



# ---------------------------------------------------------------------------
# Latin digit / single-input substitution preservation
# ---------------------------------------------------------------------------

class TestLatinSingleSubstPreservation:
    """Pan-CJK base fonts (Noto Sans JP, Noto Sans CJK JP) ship Latin-script
    `locl`, `aalt`, `fwid`, `hwid` lookups that map Latin digit / letter
    glyphs to base-font alternates. After cross-codepoint glyph rename
    (#20) the lookups are classified `mixed` instead of `latin` and survive
    the merge — so plain ``0123456789`` shaped under ``latn/en`` shapes to
    base-font digits instead of the Latin font's. The merge engine must
    strip those Latin-input single-glyph substitutions so the Latin font
    owns its own digit / letter decisions; cross-script entries on JP
    glyphs (e.g. ``vert`` / ``vrt2``) stay reachable.
    """

    DIGITS = "0123456789"

    @pytest.fixture(scope="class")
    def inter_merged_path(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("digit_inter") / "merged.ttf"
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
            "output": {"familyName": "TestDigitInter"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    @pytest.fixture(scope="class")
    def tiktok_merged_path(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("digit_tiktok") / "merged.ttf"
        config = {
            "subFont": {
                "path": TIKTOK_SANS,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "TestDigitTikTok", "upm": 1000},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    def _shape(self, font_path, text, features=None,
               script="latn", language="en"):
        try:
            import uharfbuzz as hb
        except ImportError:
            pytest.skip("uharfbuzz not installed")
        with open(font_path, "rb") as f:
            data = f.read()
        face = hb.Face(data)
        font = hb.Font(face)
        order = TTFont(font_path).getGlyphOrder()
        buf = hb.Buffer()
        buf.add_str(text)
        buf.script = script
        buf.language = language
        buf.guess_segment_properties()
        hb.shape(font, buf, features or {})
        return [order[g.codepoint] for g in buf.glyph_infos]

    # Glyph indices the issue calls out as known-bad base-font digit
    # outputs in the JP subset (lookups 1/4/5 in ``NotoSansJP-subset.ttf``
    # before the fix). Any of these appearing for plain ``0123456789``
    # under ``latn/en`` means base-side substitutions leaked through.
    BASE_DIGIT_LEAKS = frozenset(
        {f"glyph{n:05d}" for n in range(225, 235)}     # fwid digits
        | {f"glyph{n:05d}" for n in range(320, 330)}   # hwid digits
    )

    @pytest.mark.parametrize("features,reason", [
        (None, "default shaping"),
        ({"tnum": True}, "tnum=1"),
        ({"fwid": True}, "fwid=1"),
        ({"hwid": True}, "hwid=1"),
        ({"aalt": True}, "aalt=1"),
        ({"locl": True}, "locl=1"),
    ])
    def test_inter_latn_digits_no_base_leak(
            self, inter_merged_path, features, reason):
        """Inter + Noto Sans JP: digits shaped under ``latn/en`` (with or
        without ``tnum`` / ``fwid`` / ``hwid`` / ``aalt`` / ``locl``) must
        not produce any base-font full-width / half-width digit glyph.

        Pre-fix this would shape ``0`` to ``glyph00225`` (base fwid) or
        ``glyph00320`` (base hwid) under several feature combinations.
        """
        shaped = self._shape(inter_merged_path, self.DIGITS, features)
        leaked = [g for g in shaped if g in self.BASE_DIGIT_LEAKS]
        assert not leaked, (
            f"{reason} on Inter+NotoSansJP leaked base digit glyphs: "
            f"{leaked} (full shape: {shaped})"
        )

    def test_inter_latn_digits_default_are_inter(self, inter_merged_path):
        """Default ``latn/en`` shaping must reach Inter's literal ``zero``,
        ``one``, …, ``nine`` glyph names — not any base-font alternate.
        """
        shaped = self._shape(inter_merged_path, self.DIGITS)
        expected = ["zero", "one", "two", "three", "four", "five",
                    "six", "seven", "eight", "nine"]
        assert shaped == expected, f"merged default shaping: {shaped}"

    def test_inter_latn_tnum_reaches_inter_tabular(self, inter_merged_path):
        """``tnum=1`` on Inter + Noto Sans JP must reach Inter's tabular
        figures (``zero.tf``..``nine.tf`` in the unsubset font, renamed
        to ``glyph00080``..``glyph00089`` in this subset). Pre-fix,
        base-side `locl` (or `aalt` / `fwid`) rewrote the digits to
        base-font glyphs *before* Inter's `tnum` ran, so Inter's `tnum`
        silently no-op'd, leaving merged tnum identical to merged default.

        Compare merged tnum vs Inter solo tnum, normalizing the ``.lat``
        suffix the merge engine appends when an Inter glyph name collides
        with a base-font glyph (Inter's ``glyph00081`` collides with Noto
        Sans JP's, so it becomes ``glyph00081.lat``).
        """
        merged_default = self._shape(inter_merged_path, self.DIGITS)
        merged_tnum = self._shape(inter_merged_path, self.DIGITS,
                                  {"tnum": True})
        solo_tnum = self._shape(EN_VAR, self.DIGITS, {"tnum": True})

        def normalize(g):
            return g[:-4] if g.endswith(".lat") else g

        assert merged_tnum != merged_default, (
            f"tnum=1 silently no-op'd — Inter's tnum did not reach the "
            f"buffer (default={merged_default} tnum={merged_tnum})"
        )
        assert [normalize(g) for g in merged_tnum] == solo_tnum, (
            f"merged tnum={merged_tnum} (normalized: "
            f"{[normalize(g) for g in merged_tnum]}) "
            f"!= Inter solo tnum={solo_tnum}"
        )

    def test_tiktok_latn_digits_no_base_leak(self, tiktok_merged_path):
        """Non-Inter regression: TikTok Sans + Noto Sans JP digits under
        ``latn/en`` (default and ``tnum=1``) must not leak base digit
        glyphs."""
        for features, label in [(None, "default"), ({"tnum": True}, "tnum")]:
            shaped = self._shape(tiktok_merged_path, self.DIGITS, features)
            leaked = [g for g in shaped if g in self.BASE_DIGIT_LEAKS]
            assert not leaked, (
                f"TikTok {label} leaked base digit glyphs: {leaked} "
                f"(full shape: {shaped})"
            )

    def test_tiktok_latn_digits_default_match_solo(self, tiktok_merged_path):
        """TikTok Sans default ``latn/en`` digit shaping must equal solo
        — TikTok and Noto Sans JP share no digit glyph names that get
        rename-suffixed in this subset, so a direct equality check works.
        """
        merged = self._shape(tiktok_merged_path, self.DIGITS)
        solo = self._shape(TIKTOK_SANS, self.DIGITS)
        assert merged == solo, (
            f"TikTok default: merged={merged} vs solo={solo}"
        )

    def test_no_latin_input_in_base_singlesubst(self, inter_merged_path):
        """Structural: no surviving base-side Type 1 / Type 3 subtable
        should map a Latin-owned digit (``zero``..``nine``) to a base-font
        glyph. The bug: Noto Sans JP `locl` (Type 1 SingleSubst) and `aalt`
        (Type 3 AlternateSubst) keep mappings like ``zero -> glyph00225``
        on Latin-input names that the Latin font now owns.

        Latin-origin lookups (the sub-font's own `locl` / `aalt` / `tnum`)
        are tolerated — digits are legitimate Latin sources for those —
        so the test only flags subtables whose outputs include glyphs the
        Latin font does *not* know about, identifying the rule as
        base-side.
        """
        merged = TTFont(inter_merged_path)
        # Latin-owned merged glyph names — anything named in Inter solo
        # plus the rename-suffix variants the merge engine introduces on
        # name collisions. We only need a *superset* here: false negatives
        # in this set would mistakenly clear a Latin output, preventing
        # the lookup from registering as base-side; false positives are
        # harmless. Keep the set conservative.
        lat_solo = set(TTFont(EN_VAR).getGlyphOrder())
        merged_glyphs = set(merged.getGlyphOrder())
        lat_owned = {g for g in merged_glyphs
                     if g in lat_solo or g.endswith(".lat")
                     or g.rsplit(".", 1)[0] in lat_solo}
        digit_inputs = {"zero", "one", "two", "three", "four",
                        "five", "six", "seven", "eight", "nine"}
        gsub = merged["GSUB"].table
        offending = []
        for li, lk in enumerate(gsub.LookupList.Lookup):
            for sti, st in enumerate(lk.SubTable):
                ext = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
                for attr in ("mapping", "alternates"):
                    data = getattr(ext, attr, None)
                    if not data:
                        continue
                    # Output set for this subtable. If at least one output
                    # is a glyph the Latin font does not own, the
                    # subtable is base-side.
                    outs = set()
                    for v in data.values():
                        if isinstance(v, (list, tuple)):
                            outs.update(v)
                        else:
                            outs.add(v)
                    if outs and outs.issubset(lat_owned):
                        continue  # Latin-origin subtable
                    for src in data:
                        if src in digit_inputs:
                            offending.append(
                                (li, sti, attr, src, data[src]))
        assert not offending, (
            "Base-side Type 1/3 GSUB still maps Latin digit inputs "
            f"to base-font outputs: {offending[:10]}"
        )


# ---------------------------------------------------------------------------
# CID base font: digit substitution leakage (NotoSansCJKjp-style)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.exists(JP_OTF),
    reason="NotoSansCJKjp-subset.otf not present",
)
class TestCidBaseDigitNoLeak:
    """CID base fonts (NotoSansCJKjp / Source Han Sans) reference Latin
    digits by CID name (e.g. ``cid00017`` for U+0030). Inter's `zero`
    glyph is renamed to ``cid00017`` during cmap-driven copy, so the
    base GSUB rules ``cid00017 -> cid63153`` (`locl`), ``cid00017 ->
    cid59062`` (`fwid`) etc. all fire on the Latin design unless the
    merge engine strips them. This test pins the regression for #23 on
    the CID/CFF path — the bare TTF subset path uses semantic glyph
    names and doesn't catch this CID-specific failure mode.
    """

    DIGITS = "0123456789"

    @pytest.fixture(scope="class")
    def merged_path(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("digit_cid") / "merged.otf"
        config = {
            "subFont": {
                "path": EN_CFF,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": JP_OTF,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "output": {"familyName": "TestDigitCid"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    def _shape(self, font_path, text, features=None):
        try:
            import uharfbuzz as hb
        except ImportError:
            pytest.skip("uharfbuzz not installed")
        with open(font_path, "rb") as f:
            data = f.read()
        face = hb.Face(data)
        font = hb.Font(face)
        order = TTFont(font_path).getGlyphOrder()
        buf = hb.Buffer()
        buf.add_str(text)
        buf.script = "latn"
        buf.language = "en"
        buf.guess_segment_properties()
        hb.shape(font, buf, features or {})
        return [order[g.codepoint] for g in buf.glyph_infos]

    @pytest.mark.parametrize("features,reason", [
        (None, "default"),
        ({"locl": True}, "locl=1"),
        ({"tnum": True}, "tnum=1"),
        ({"fwid": True}, "fwid=1"),
        ({"hwid": True}, "hwid=1"),
        ({"aalt": True}, "aalt=1"),
    ])
    def test_cid_digits_no_base_alternate_leak(
            self, merged_path, features, reason):
        """For each feature combination, the merged font's digit shaping
        under ``latn/en`` must produce stable CID digit names — not the
        base font's full-width / half-width / locl alternate CIDs.

        The merged Latin digits live at ``cid00017``..``cid00026``. The
        bug case from the issue: base ``locl`` rewrites those to
        ``cid63153``..``cid63162`` (and similar large-CID alternates).
        After the fix, no entry in the base GSUB should map any of
        ``cid00017``..``cid00026`` to a different CID, so all six feature
        combinations shape to the same merged digit CIDs.
        """
        shaped = self._shape(merged_path, self.DIGITS, features)
        latin_cids = {f"cid{n:05d}" for n in range(17, 27)}  # cid00017..00026
        unexpected = [g for g in shaped if g not in latin_cids]
        assert not unexpected, (
            f"{reason} on Inter+NotoSansCJKjp leaked non-Latin CIDs: "
            f"{unexpected} (full shape: {shaped})"
        )

    def test_cid_locl_lookup_stripped_for_latin_cids(self, merged_path):
        """Structural: no surviving base-side Type 1 / Type 3 subtable
        should keep ``cid00017``..``cid00026`` as a source key. Those CID
        names are now Latin-owned (Inter's digit glyphs sit there) and
        any base-side rewrite is the bug from #23."""
        merged = TTFont(merged_path)
        latin_cids = {f"cid{n:05d}" for n in range(17, 27)}
        gsub = merged["GSUB"].table
        offending = []
        for li, lk in enumerate(gsub.LookupList.Lookup):
            for sti, st in enumerate(lk.SubTable):
                ext = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
                for attr in ("mapping", "alternates"):
                    data = getattr(ext, attr, None)
                    if not data:
                        continue
                    for src in data:
                        if src in latin_cids:
                            offending.append(
                                (li, sti, attr, src, data[src]))
        assert not offending, (
            "Base-side Type 1/3 GSUB still maps Latin CID digits "
            f"(cid00017..cid00026) to alternates: {offending[:10]}"
        )


# ---------------------------------------------------------------------------
# CID base font: budget-path digit leak (full NotoSansCJKjp-Regular.otf)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.exists(JP_OTF_FULL),
    reason="NotoSansCJKjp-Regular.otf not present",
)
class TestCidBudgetPathDigitNoLeak:
    """The 65535-glyph budget fallback path (`merge_feature_tables(None,
    ...)`) used to skip base-side Latin-source stripping entirely because
    `lat_glyph_names` was empty there. Result: full NotoSansCJKjp-Regular
    + Inter shaped ``0123456789`` to ``cid63153..cid63162`` (locl
    alternates). This test pins the regression on the actual budget path
    by merging the unsubsetted Noto Sans CJK JP. It's slow (~10–30 s),
    so it's class-scoped and only runs when the full font fixture is
    available.
    """

    DIGITS = "0123456789"

    @pytest.fixture(scope="class")
    def merged_path(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("digit_cid_budget") / "merged.otf"
        config = {
            "subFont": {
                "path": EN_CFF,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": JP_OTF_FULL,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "output": {"familyName": "TestDigitCidBudget"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    def _shape(self, font_path, text, features=None):
        try:
            import uharfbuzz as hb
        except ImportError:
            pytest.skip("uharfbuzz not installed")
        with open(font_path, "rb") as f:
            data = f.read()
        face = hb.Face(data)
        font = hb.Font(face)
        order = TTFont(font_path).getGlyphOrder()
        buf = hb.Buffer()
        buf.add_str(text)
        buf.script = "latn"
        buf.language = "en"
        buf.guess_segment_properties()
        hb.shape(font, buf, features or {})
        return [order[g.codepoint] for g in buf.glyph_infos]

    def test_full_cid_default_digits_are_latin(self, merged_path):
        """Default ``latn/en`` digit shaping on the full NotoSansCJKjp
        merge must reach Latin-owned CID slots, not base ``cidNNNN``
        alternates with names that hint at vertical / fullwidth /
        locl variants (cid63153..cid63162 for Noto Sans CJK locl).
        """
        shaped = self._shape(merged_path, self.DIGITS)
        leak_cids = {f"cid{n:05d}" for n in range(63153, 63163)}
        leaked = [g for g in shaped if g in leak_cids]
        assert not leaked, (
            f"Default latn/en digits leaked Noto CJK locl alternates: "
            f"{leaked} (full shape: {shaped})"
        )

    def test_full_cid_tnum_digits_no_leak(self, merged_path):
        """``tnum=1`` on the full CJK budget path must also avoid the
        locl leak. ``tnum`` is the visible trigger from the issue
        report: it makes the leak observable even when default shaping
        looks right by accident."""
        shaped = self._shape(merged_path, self.DIGITS, {"tnum": True})
        leak_cids = {f"cid{n:05d}" for n in range(63153, 63163)}
        leaked = [g for g in shaped if g in leak_cids]
        assert not leaked, (
            f"tnum=1 latn/en leaked Noto CJK locl alternates: "
            f"{leaked} (full shape: {shaped})"
        )


# ---------------------------------------------------------------------------
# Inter dlig chain-context preservation (the rf / fi / ff family)
# ---------------------------------------------------------------------------

class TestInterDligChainContext:
    """Inter implements its `dlig` ligature family (`fi → f.i + i`,
    `rf → r + f.1`, `ff → f + f.1`, …) via a Type 6 ChainContextSubst
    lookup, not Type 4 LigatureSubst. Without the duplicate-tag dedupe
    of `dlig` under `latn`, the merged LangSys carries both JP-side and
    Latin-side `dlig` records and HarfBuzz only fires the first (JP)
    record — so Inter's chain-context substitutions never reach the
    buffer and merged shaping diverges from Inter solo.
    """

    DLIG_INPUTS = ("fi", "fl", "ff", "ffi", "ffl", "rf", "tt")

    @pytest.fixture(scope="class")
    def merged_font_path(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("inter_dlig") / "merged.ttf"
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
            "output": {"familyName": "TestInterDlig"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    def _shape(self, font_path, text, features=None):
        try:
            import uharfbuzz as hb
        except ImportError:
            pytest.skip("uharfbuzz not installed")
        with open(font_path, "rb") as f:
            data = f.read()
        face = hb.Face(data)
        font = hb.Font(face)
        order = TTFont(font_path).getGlyphOrder()
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(font, buf, features or {})
        return [order[g.codepoint] for g in buf.glyph_infos]

    @pytest.mark.parametrize("text", DLIG_INPUTS)
    def test_dlig_chain_context_matches_inter_solo(self, merged_font_path, text):
        """Each dlig input must shape identically to Inter solo."""
        merged = self._shape(merged_font_path, text, {"dlig": True})
        solo = self._shape(EN_VAR, text, {"dlig": True})
        assert merged == solo, (
            f"dlig on {text!r}: merged={merged}, solo={solo}"
        )

    def test_latn_script_has_single_dlig_feature(self, merged_font_path):
        """`latn` should expose exactly one `dlig` feature record."""
        merged = TTFont(merged_font_path)
        gsub = merged["GSUB"].table
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != "latn" or not sr.Script.DefaultLangSys:
                continue
            dlig = [
                fi for fi in sr.Script.DefaultLangSys.FeatureIndex
                if gsub.FeatureList.FeatureRecord[fi].FeatureTag == "dlig"
            ]
            assert len(dlig) == 1, (
                f"latn DefaultLangSys dlig records: {dlig}"
            )
            return
        pytest.fail("merged font has no latn script in GSUB")



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
        """CJK kern stays direct PairPos and accessible from DFLT script."""
        if not os.path.exists(JP_FULL_VAR) or not os.path.exists(EN_FULL):
            pytest.skip("Full Inter or Noto Sans JP variable fixture not found")
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {
                "path": EN_FULL,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [
                    {"tag": "opsz", "currentValue": 14},
                    {"tag": "wght", "currentValue": 400},
                ],
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

        def kern_feature_indices(script_tag):
            indices = set()
            for sr in gpos.ScriptList.ScriptRecord:
                if sr.ScriptTag == script_tag and sr.Script.DefaultLangSys:
                    for fi in sr.Script.DefaultLangSys.FeatureIndex:
                        if gpos.FeatureList.FeatureRecord[fi].FeatureTag == "kern":
                            indices.add(fi)
            return indices

        # Match Noto's source shape: scripts share one kern feature record.
        dflt_kern_feat_indices = kern_feature_indices("DFLT")
        assert dflt_kern_feat_indices, "DFLT script should have kern features"
        assert len(dflt_kern_feat_indices) == 1, (
            "DFLT should expose a single kern feature so Adobe apps do not "
            f"skip the base CJK kern path: {dflt_kern_feat_indices}"
        )
        for script_tag in ("hani", "kana", "latn"):
            assert kern_feature_indices(script_tag) == dflt_kern_feat_indices, (
                f"{script_tag} should share the same merged kern feature as DFLT"
            )

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
                            assert lookup.LookupType == 2, (
                                "CJK kern PairPos should stay direct LookupType 2 "
                                "for Adobe compatibility"
                            )
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

    def test_base_only_upm_scales_unmapped_glyphs(self):
        out = tempfile.mktemp(suffix=".ttf")
        base_cfg = {
            "path": JP_VAR,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [{"tag": "wght", "currentValue": 400}],
        }
        config = {
            "subFont": None,
            "baseFont": base_cfg,
            "output": {"familyName": "Test", "upm": 2000},
            "export": {"path": {"font": out}},
        }

        source = TTFont(JP_VAR)
        source = mf._instantiate_if_variable(source, base_cfg, "Test source")
        source_cmap_names = set((source.getBestCmap() or {}).values())
        gname = None
        source_bounds = None
        for candidate in source.getGlyphOrder():
            if candidate == ".notdef" or candidate in source_cmap_names:
                continue
            if candidate not in source["hmtx"].metrics:
                continue
            bounds = _get_bounds(source, candidate)
            if bounds is None:
                continue
            gname = candidate
            source_bounds = bounds
            break

        assert gname is not None, "fixture should contain an unmapped outline glyph"
        source_hmtx = source["hmtx"].metrics[gname]
        source_vmtx = None
        if "vmtx" in source and gname in source["vmtx"].metrics:
            source_vmtx = source["vmtx"].metrics[gname]

        m = None
        try:
            mf.merge_fonts(config)
            m = TTFont(out)
            ratio = 2000 / source["head"].unitsPerEm

            assert m["head"].unitsPerEm == 2000
            assert m["hmtx"].metrics[gname] == (
                int(round(source_hmtx[0] * ratio)),
                int(round(source_hmtx[1] * ratio)),
            )
            if source_vmtx is not None:
                assert m["vmtx"].metrics[gname] == (
                    int(round(source_vmtx[0] * ratio)),
                    int(round(source_vmtx[1] * ratio)),
                )

            expected_bounds = tuple(int(round(v * ratio)) for v in source_bounds)
            actual_bounds = _get_bounds(m, gname)
            assert actual_bounds is not None
            for actual, expected in zip(actual_bounds, expected_bounds):
                assert abs(actual - expected) <= 2
        finally:
            source.close()
            if m is not None:
                m.close()
            for path in (out, out.replace(".ttf", ".woff2")):
                if os.path.exists(path):
                    os.remove(path)

    def test_cff_subfont_upm_scaling_is_not_applied_twice(self):
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {
                "path": EN_CFF,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "Test", "upm": 2000},
            "export": {"path": {"font": out}},
        }

        sub = TTFont(EN_CFF)
        m = None
        try:
            mf.merge_fonts(config)
            m = TTFont(out)
            merged_gname = m.getBestCmap()[0x0048]
            sub_gname = sub.getBestCmap()[0x0048]
            ratio = 2000 / sub["head"].unitsPerEm
            expected_hmtx = (
                int(round(sub["hmtx"].metrics[sub_gname][0] * ratio)),
                int(round(sub["hmtx"].metrics[sub_gname][1] * ratio)),
            )
            assert m["hmtx"].metrics[merged_gname] == expected_hmtx
        finally:
            sub.close()
            if m is not None:
                m.close()
            for path in (out, out.replace(".ttf", ".woff2")):
                if os.path.exists(path):
                    os.remove(path)



# ---------------------------------------------------------------------------
# TrueType hinting normalization (Issue #17)
# ---------------------------------------------------------------------------

class TestHintingNormalization:
    """Merged TTF output is published unhinted.

    Mixing glyph bytecode from one source with the font-wide ``fpgm`` /
    ``prep`` / ``cvt `` of another source is unsafe: function indices,
    storage slots, and CVT entries are source-specific. The previous
    behavior left hint state from the base font in the output while the
    sub font's glyph programs survived alongside it, so the output looked
    bytecode-hinted to renderers without actually moving any points. The
    merge engine now strips bytecode hinting entirely and lets the
    platform autohinter handle small sizes; ``gasp`` is left in place
    because it controls smoothing strategy, not bytecode execution.
    """

    @pytest.fixture(autouse=True)
    def _load_base_tables(self):
        """Load instantiated JP base font for comparison."""
        from fontTools.varLib.instancer import instantiateVariableFont
        jp = TTFont(JP_VAR)
        self.jp = instantiateVariableFont(jp, {"wght": 400})

    def test_fpgm_dropped(self):
        """fpgm is dropped from merged TTF output."""
        m = _merge()
        assert "fpgm" not in m, "fpgm should be stripped from merged TTF"

    def test_prep_dropped(self):
        """prep is dropped from merged TTF output."""
        m = _merge()
        assert "prep" not in m, "prep should be stripped from merged TTF"

    def test_cvt_dropped(self):
        """cvt is dropped from merged TTF output."""
        m = _merge()
        assert "cvt " not in m, "cvt should be stripped from merged TTF"

    def test_gasp_table_survives_merge(self):
        """gasp is preserved (smoothing hint, not bytecode)."""
        if "gasp" not in self.jp:
            pytest.skip("Base font has no gasp table")
        m = _merge()
        assert "gasp" in m, "gasp table lost during merge"
        assert m["gasp"].gaspRange == self.jp["gasp"].gaspRange, \
            "gasp ranges differ from base font"

    def test_glyph_programs_cleared(self):
        """Every glyph in the merged TTF has an empty bytecode program."""
        m = _merge(lat_scale=1.5)
        glyf = m["glyf"]
        for gname in m.getGlyphOrder():
            try:
                g = glyf[gname]
            except KeyError:
                continue
            program = getattr(g, "program", None)
            if program is None:
                continue
            assert len(program.bytecode) == 0, \
                f"Glyph '{gname}' still carries {len(program.bytecode)} bytes of bytecode"

    def test_maxp_hinting_fields_zeroed(self):
        """maxp v1 hint counters are normalized in unhinted output."""
        m = _merge()
        maxp = m["maxp"]
        assert maxp.maxZones == 1, "maxp.maxZones must be 1 for unhinted TrueType output"
        for attr in (
            "maxTwilightPoints",
            "maxStorage",
            "maxFunctionDefs",
            "maxInstructionDefs",
            "maxStackElements",
            "maxSizeOfInstructions",
        ):
            if hasattr(maxp, attr):
                assert getattr(maxp, attr) == 0, \
                    f"maxp.{attr} = {getattr(maxp, attr)}, expected 0 for unhinted output"

    def test_round_trip_loads_clean(self):
        """Saved-then-reloaded TTF still has every glyph accessible."""
        m = _merge(lat_scale=1.5)
        out = tempfile.mktemp(suffix=".ttf")
        try:
            m.save(out)
            reloaded = TTFont(out)
            glyf = reloaded["glyf"]
            for gname in reloaded.getGlyphOrder():
                _ = glyf[gname]
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_hinted_sub_font_gets_normalized(self):
        """Hinted sub font + base merge still yields unhinted output (Issue #17)."""
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {
                "path": TIKTOK_SANS,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "TestHintNormalize"},
            "export": {"path": {"font": out}},
        }
        try:
            mf.merge_fonts(config)
            m = TTFont(out)
            try:
                # Bytecode tables: fully removed.
                assert "fpgm" not in m
                assert "prep" not in m
                assert "cvt " not in m
                # Sub font's Latin glyphs: bytecode stripped despite the
                # original carrying e.g. 29 bytes on 'A'. This was the core
                # issue — glyph bytecode survived without its companion
                # fpgm/prep/cvt and silently did nothing.
                glyf = m["glyf"]
                for gname in ("A", "zero"):
                    if gname in glyf.glyphOrder:
                        program = getattr(glyf[gname], "program", None)
                        if program is not None:
                            assert len(program.bytecode) == 0, \
                                f"Sub-font hinted glyph '{gname}' must have bytecode cleared"
                # maxp counters reset.
                maxp = m["maxp"]
                assert maxp.maxZones == 1
                for attr in ("maxFunctionDefs", "maxStorage",
                             "maxSizeOfInstructions"):
                    if hasattr(maxp, attr):
                        assert getattr(maxp, attr) == 0
            finally:
                m.close()
        finally:
            if os.path.exists(out):
                os.remove(out)
            woff2 = out.replace(".ttf", ".woff2")
            if os.path.exists(woff2):
                os.remove(woff2)

    def test_ttfautohint_policy_requires_tool(self, monkeypatch):
        """Explicit ttfautohint mode fails clearly when the tool is absent."""
        monkeypatch.setattr(mf.shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError, match="ttfautohint was not found"):
            mf._apply_ttfautohint("/tmp/nonexistent.ttf")

    def test_ttfautohint_policy_replaces_output(self, monkeypatch):
        """ttfautohint mode writes a temp output, then replaces the final TTF."""
        calls = []
        out = tempfile.mktemp(suffix=".ttf")
        tmp = f"{out}.ttfautohint.tmp"
        try:
            with open(out, "wb") as f:
                f.write(b"before")

            def fake_run(args, check, stdout, stderr):
                calls.append((args, check, stdout, stderr))
                assert args[1] == out
                assert args[2] == tmp
                with open(args[2], "wb") as f:
                    f.write(b"after")

            monkeypatch.setattr(mf.shutil, "which", lambda name: "/usr/bin/ttfautohint")
            monkeypatch.setattr(mf.subprocess, "run", fake_run)

            mf._apply_ttfautohint(out)

            assert calls
            with open(out, "rb") as f:
                assert f.read() == b"after"
            assert not os.path.exists(tmp)
        finally:
            for p in (out, tmp):
                if os.path.exists(p):
                    os.remove(p)



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

    def test_replaced_glyphs_preserve_base_vertical_metrics(self):
        """Replaced glyphs must keep their original base vmtx rows.

        If a copied or duplicated glyph misses vmtx, the later consistency
        pass backfills topSideBearing=0, which moves the glyph too high in
        vertical text.
        """
        m = self._merge()
        base = TTFont(JP_STATIC)
        try:
            cmap = m.getBestCmap()
            base_cmap = base.getBestCmap()
            for cp in (
                0x0020, 0x002D, 0x00A0, 0x02BB, 0x0399, 0x2003,
                0x2011, 0x2012, 0x2013, 0x2018, 0x2026, 0x24EA,
                0x30FB, 0xFF40,
            ):
                merged_glyph = cmap.get(cp)
                base_glyph = base_cmap.get(cp)
                assert merged_glyph is not None, f"U+{cp:04X} missing"
                assert base_glyph is not None, f"U+{cp:04X} missing in base"
                assert m["vmtx"].metrics[merged_glyph] == (
                    base["vmtx"].metrics[base_glyph]
                )
        finally:
            base.close()

    @staticmethod
    def _single_sub_mapping_for_feature(font, feature_tag):
        if "GSUB" not in font:
            return {}
        table = font["GSUB"].table
        if not table.FeatureList or not table.LookupList:
            return {}
        result = {}
        for feature_record in table.FeatureList.FeatureRecord:
            if feature_record.FeatureTag != feature_tag:
                continue
            for lookup_index in feature_record.Feature.LookupListIndex:
                lookup = table.LookupList.Lookup[lookup_index]
                if lookup.LookupType != 1:
                    continue
                for subtable in lookup.SubTable:
                    st = (subtable.ExtSubTable
                          if hasattr(subtable, "ExtSubTable") else subtable)
                    mapping = getattr(st, "mapping", None)
                    if mapping:
                        result.update(mapping)
        return result

    def test_renamed_replacements_preserve_vertical_substitution(self):
        """Renamed replacement glyphs should stay reachable from vert/vrt2."""
        m = self._merge()
        base = TTFont(JP_STATIC)
        try:
            cmap = m.getBestCmap()
            base_cmap = base.getBestCmap()
            merged_glyph = cmap[0x2026]
            base_glyph = base_cmap[0x2026]
            assert merged_glyph != base_glyph

            for tag in ("vert", "vrt2"):
                base_mapping = self._single_sub_mapping_for_feature(base, tag)
                merged_mapping = self._single_sub_mapping_for_feature(m, tag)
                assert base_mapping.get(base_glyph) is not None
                assert merged_mapping.get(merged_glyph) == (
                    base_mapping[base_glyph]
                )
        finally:
            base.close()




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
# Named LangSys default fallback (Issue #12)
# ---------------------------------------------------------------------------

class TestNamedLangSysDefaultFallback:
    """Named LangSys records must preserve the other side's default features.

    If the merged font creates `latn/JAN` from the JP base but the Latin sub
    font only has `latn/dflt`, HarfBuzz selects `latn/JAN` for Japanese text
    and never consults `latn/dflt`. The named record therefore needs the
    Latin default feature set folded in.
    """

    @staticmethod
    def _gsub_feature_tags(font, script_tag, lang_sys_tag=None):
        gsub = font["GSUB"].table
        features = gsub.FeatureList.FeatureRecord
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != script_tag:
                continue
            if lang_sys_tag is None:
                lang_sys = sr.Script.DefaultLangSys
            else:
                lang_sys = None
                for lsr in (sr.Script.LangSysRecord or []):
                    if lsr.LangSysTag == lang_sys_tag:
                        lang_sys = lsr.LangSys
                        break
            if lang_sys is None:
                pytest.fail(f"{script_tag}/{lang_sys_tag or 'dflt'} missing")
            return {
                features[i].FeatureTag
                for i in (lang_sys.FeatureIndex or [])
            }
        pytest.fail(f"{script_tag} script missing")

    def test_latn_jan_keeps_latin_default_features(self):
        """Noto's `latn/JAN` must not shadow Inter's `latn/dflt` GSUB."""
        m = _merge()
        tags = self._gsub_feature_tags(m, "latn", "JAN ")

        assert {"calt", "case", "frac", "tnum", "ss01", "zero"} <= tags
        assert "locl" in tags

    def test_latin_named_langsys_keeps_jp_default_features(self):
        """The fallback is symmetric when only the Latin side has a locale."""
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {
                "path": TIKTOK_SANS,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "TestNamedLangSys"},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        m = TTFont(out)
        os.remove(out)

        tags = self._gsub_feature_tags(m, "latn", "CAT ")
        assert "calt" in tags
        assert "fwid" in tags


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
