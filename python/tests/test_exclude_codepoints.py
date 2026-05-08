"""Tests for subFont.excludeCodepoints and glyph-name collision rename
(issue #20).

Two distinct mechanisms covered here:

1. ``subFont.excludeCodepoints`` — caller-supplied list of codepoints that
   must remain sourced from baseFont. Filters the sub-font cmap before merge.

2. Cross-codepoint glyph-name collision auto-rename — when sub and base
   share a glyph name but the codepoints don't match (e.g. Inter
   ``uni25CE`` for U+0298 vs Noto ``uni25CE`` for U+25CE), the sub-font
   glyph is renamed (``uni25CE.sub``) so the base outline at its codepoint
   stays intact.
"""

import os
import tempfile

import pytest

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph

from conftest import (EN_CFF, EN_FULL, EN_VAR,
                      JP_OTF, JP_STATIC, JP_VAR, TIKTOK_SANS, _get_bounds)

import merge_fonts as mf


# ---------------------------------------------------------------------------
# parse_codepoint_list helper
# ---------------------------------------------------------------------------

class TestParseCodepointList:
    """Unit tests for the ``parse_codepoint_list`` helper."""

    def test_empty_returns_empty_set(self):
        assert mf.parse_codepoint_list(None) == set()
        assert mf.parse_codepoint_list([]) == set()

    def test_single_codepoint_string(self):
        assert mf.parse_codepoint_list(["U+2460"]) == {0x2460}

    def test_lowercase_hex(self):
        assert mf.parse_codepoint_list(["U+abcd"]) == {0xABCD}

    def test_codepoint_range(self):
        assert mf.parse_codepoint_list(["U+2460-U+2462"]) == {0x2460, 0x2461, 0x2462}

    def test_integer_form(self):
        assert mf.parse_codepoint_list([0x2460]) == {0x2460}

    def test_mixed_forms(self):
        result = mf.parse_codepoint_list(["U+203B", "U+2460-U+2462", 0x25CE])
        assert result == {0x203B, 0x2460, 0x2461, 0x2462, 0x25CE}

    def test_whitespace_tolerated(self):
        assert mf.parse_codepoint_list([" U+2460 "]) == {0x2460}

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError, match="Invalid codepoint"):
            mf.parse_codepoint_list(["U+ZZZZ"])

    def test_missing_prefix_raises(self):
        with pytest.raises(ValueError, match="Invalid codepoint"):
            mf.parse_codepoint_list(["2460"])

    def test_range_reverse_raises(self):
        with pytest.raises(ValueError, match="end < start"):
            mf.parse_codepoint_list(["U+2462-U+2460"])

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            mf.parse_codepoint_list([-1])
        with pytest.raises(ValueError, match="out of range"):
            mf.parse_codepoint_list([0x110000])

    def test_bool_rejected(self):
        with pytest.raises(ValueError, match="Invalid codepoint"):
            mf.parse_codepoint_list([True])

    def test_non_list_rejected(self):
        with pytest.raises(ValueError, match="must be a list"):
            mf.parse_codepoint_list("U+2460")


# ---------------------------------------------------------------------------
# subFont.excludeCodepoints (end-to-end merge)
# ---------------------------------------------------------------------------

def _merge_with_exclude(exclude_codepoints):
    """Run a TTF Inter + TTF Noto merge with exclude_codepoints applied."""
    if not os.path.exists(EN_FULL) or not os.path.exists(JP_STATIC):
        pytest.skip("Full Inter / Noto Sans JP fonts not found")
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
            "excludeCodepoints": exclude_codepoints,
        },
        "baseFont": {
            "path": JP_STATIC,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [],
        },
        "output": {"familyName": "TestExclude"},
        "export": {"path": {"font": out}},
    }
    mf.merge_fonts(config)
    font = TTFont(out)
    os.remove(out)
    return font


def _base_advance(codepoint):
    """Look up the base font's advance width at ``codepoint`` (Noto Sans JP)."""
    base = TTFont(JP_STATIC)
    g = base.getBestCmap().get(codepoint)
    aw = base["hmtx"].metrics[g][0] if g else None
    base.close()
    return aw


class TestExcludeCodepoints:
    """End-to-end: ``subFont.excludeCodepoints`` keeps the base outline at
    the listed codepoints while the rest of the sub font merges normally.

    Stable signal used in these tests: advance width. Inter at 2048 UPM
    scaled to Noto's 1000 UPM produces a different aw than Noto's native
    aw at every shared codepoint we touch, so an aw match against the
    base font is a reliable "base outline preserved" check.
    """

    def test_excluded_single_keeps_base_glyph(self):
        """U+2460 (①) excluded — must keep Noto's advance width."""
        merged = _merge_with_exclude(["U+2460"])
        cmap = merged.getBestCmap()
        glyph = cmap.get(0x2460)
        assert glyph is not None, "U+2460 missing from merged cmap"
        merged_aw = merged["hmtx"].metrics[glyph][0]
        base_aw = _base_advance(0x2460)
        assert merged_aw == base_aw, (
            f"U+2460 advance {merged_aw} != base {base_aw} — exclusion did not preserve base"
        )

    def test_excluded_range_keeps_base_glyphs(self):
        """U+2460-U+2469 excluded as a range — every base glyph preserved."""
        merged = _merge_with_exclude(["U+2460-U+2469"])
        cmap = merged.getBestCmap()
        for cp in range(0x2460, 0x246A):
            glyph = cmap.get(cp)
            assert glyph is not None, f"U+{cp:04X} missing from merged cmap"
            merged_aw = merged["hmtx"].metrics[glyph][0]
            base_aw = _base_advance(cp)
            assert merged_aw == base_aw, (
                f"U+{cp:04X} aw {merged_aw} != base {base_aw} — range exclusion failed"
            )

    def test_excluded_integer_form_works(self):
        """Integer codepoint form is accepted."""
        merged = _merge_with_exclude([0x2460])
        cmap = merged.getBestCmap()
        glyph = cmap.get(0x2460)
        merged_aw = merged["hmtx"].metrics[glyph][0]
        assert merged_aw == _base_advance(0x2460), (
            "Integer-form exclusion did not preserve base glyph"
        )

    def test_non_excluded_codepoint_still_merged(self):
        """U+0041 (A) is NOT in excludeCodepoints — Inter must still win."""
        merged = _merge_with_exclude(["U+2460"])
        cmap = merged.getBestCmap()
        glyph_a = cmap.get(0x0041)
        assert glyph_a is not None
        merged_aw = merged["hmtx"].metrics[glyph_a][0]
        # Inter's "A" advance differs from Noto's "A" — confirm we did NOT
        # accidentally fall back to base for unrelated codepoints.
        base_a_aw = _base_advance(0x0041)
        assert merged_aw != base_a_aw, (
            f"U+0041 aw {merged_aw} == base {base_a_aw} — exclusion was over-broad"
        )

    def test_empty_list_is_no_op(self):
        """Empty/missing excludeCodepoints behaves like the previous merge."""
        merged_empty = _merge_with_exclude([])
        merged_none = _merge_with_exclude(None)
        # Both should produce a valid font; smoke check that U+0041 merged.
        for m in (merged_empty, merged_none):
            cmap = m.getBestCmap()
            assert cmap.get(0x0041) is not None

    def test_invalid_value_raises(self):
        """A malformed entry raises during merge before any output is written."""
        if not os.path.exists(EN_FULL) or not os.path.exists(JP_STATIC):
            pytest.skip("Full Inter / Noto Sans JP fonts not found")
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
                "excludeCodepoints": ["bogus"],
            },
            "baseFont": {
                "path": JP_STATIC,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "output": {"familyName": "TestExcludeBad"},
            "export": {"path": {"font": out}},
        }
        with pytest.raises(ValueError, match="Invalid codepoint"):
            mf.merge_fonts(config)
        # No partial output should be left behind.
        if os.path.exists(out):
            os.remove(out)


# ---------------------------------------------------------------------------
# Glyph-name collision auto-rename (cross-codepoint)
# ---------------------------------------------------------------------------

class TestGlyphNameCollisionRename:
    """When sub and base share a glyph name but reach it from different
    codepoints, the sub glyph is renamed so the base outline at the
    "stranded" codepoint stays intact.

    Concrete case: Inter encodes U+0298 (ʘ, Latin bilabial click) as glyph
    ``uni25CE``. Noto Sans JP uses the same glyph name ``uni25CE`` for
    U+25CE (◎, bullseye). Without the rename, copying Inter's ``uni25CE``
    would silently overwrite Noto's bullseye, so U+25CE would render as the
    Latin click.
    """

    @staticmethod
    def _merge():
        if not os.path.exists(EN_FULL) or not os.path.exists(JP_STATIC):
            pytest.skip("Full Inter / Noto Sans JP fonts not found")
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
                "path": JP_STATIC,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "output": {"familyName": "TestCollision"},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        font = TTFont(out)
        os.remove(out)
        return font

    def test_disjoint_codepoints_preserve_base_outline(self):
        """U+25CE (Noto's ◎ bullseye) keeps a near-em-square width even
        though Inter's ``uni25CE`` glyph (encoded at U+0298) was copied."""
        merged = self._merge()
        cmap = merged.getBestCmap()
        glyph_25ce = cmap.get(0x25CE)
        assert glyph_25ce is not None, "U+25CE missing from merged cmap"
        bounds = _get_bounds(merged, glyph_25ce)
        assert bounds is not None
        width = bounds[2] - bounds[0]
        # Noto's bullseye fills the em (~1000); Inter's ʘ at U+0298 is small.
        assert width > 750, (
            f"U+25CE width {width} — base bullseye was overwritten by sub-font click"
        )

    def test_disjoint_codepoints_sub_glyph_renamed(self):
        """U+0298 (ʘ) maps to a renamed sub-font glyph (``.sub`` suffix),
        not the original ``uni25CE``."""
        merged = self._merge()
        cmap = merged.getBestCmap()
        glyph_0298 = cmap.get(0x0298)
        assert glyph_0298 is not None, "U+0298 missing from merged cmap"
        assert glyph_0298 != cmap.get(0x25CE), (
            "U+0298 and U+25CE share a glyph name — rename did not run"
        )
        assert glyph_0298.endswith(".sub") or ".sub" in glyph_0298, (
            f"sub-font glyph at U+0298 should carry .sub suffix, got {glyph_0298!r}"
        )

    def test_disjoint_codepoints_sub_glyph_has_latin_outline(self):
        """The renamed sub glyph still carries Inter's Latin click outline."""
        merged = self._merge()
        cmap = merged.getBestCmap()
        glyph_0298 = cmap.get(0x0298)
        bounds = _get_bounds(merged, glyph_0298)
        assert bounds is not None
        width = bounds[2] - bounds[0]
        # Inter's U+0298 click is small (Latin lowercase scale, ~500-600).
        assert width < 750, (
            f"U+0298 width {width} suggests base outline — sub-font copy missing"
        )

    def test_overlap_codepoints_protect_collateral(self):
        """U+3000 (CJK ideographic space) shares the glyph ``uni2003`` with
        Inter's em space at U+2003. The ideographic space at U+3000 must
        stay at base width (full em ~1000), not Inter's em-space width."""
        merged = self._merge()
        cmap = merged.getBestCmap()
        glyph_3000 = cmap.get(0x3000)
        assert glyph_3000 is not None, "U+3000 missing from merged cmap"
        aw = merged["hmtx"].metrics[glyph_3000][0]
        # Noto's U+3000 is full em (1000). A regression where Inter's em
        # space (also 1000 in Inter's UPM) bleeds in would only shift if
        # the UPMs differ — the more reliable signal is glyph identity:
        # glyph_3000 should NOT equal glyph_2003 after the rename.
        glyph_2003 = cmap.get(0x2003)
        assert glyph_3000 != glyph_2003, (
            "U+3000 and U+2003 should resolve to distinct glyphs after merge"
        )
        assert aw >= 900, f"U+3000 advance {aw} too narrow — base outline lost"

    def test_warning_emitted_on_collision(self, capsys):
        """A stderr warning is emitted for each detected collision."""
        if not os.path.exists(EN_FULL) or not os.path.exists(JP_STATIC):
            pytest.skip("Full Inter / Noto Sans JP fonts not found")
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
                "path": JP_STATIC,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "output": {"familyName": "TestWarn"},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        if os.path.exists(out):
            os.remove(out)
        captured = capsys.readouterr()
        assert "glyph name collision" in captured.err, (
            "stderr should warn about at least one cross-codepoint collision; "
            f"got: {captured.err!r}"
        )
        # The U+25CE case must specifically be reported.
        assert "uni25CE" in captured.err


# ---------------------------------------------------------------------------
# excludeCodepoints + collision rename interaction
# ---------------------------------------------------------------------------

class TestExcludeAndCollisionInteraction:
    """Integer-form ``excludeCodepoints`` plus a colliding glyph name run
    through both code paths in one merge — the excluded codepoint must
    keep the base outline AND the unrelated cross-codepoint collision
    must still trigger the ``.sub`` rename."""

    def test_integer_exclude_with_collision_rename(self):
        """Exclude U+0298 (integer form) — Inter no longer cmaps it, so
        the cross-codepoint collision for ``uni25CE`` disappears AND the
        base bullseye at U+25CE stays intact regardless."""
        if not os.path.exists(EN_FULL) or not os.path.exists(JP_STATIC):
            pytest.skip("Full Inter / Noto Sans JP fonts not found")
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
                # Mix integer + range to confirm both forms feed the
                # collision-detection pass after filtering.
                "excludeCodepoints": [0x0298, "U+2460-U+2462"],
            },
            "baseFont": {
                "path": JP_STATIC,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "output": {"familyName": "TestExcludeCollision"},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        merged = TTFont(out)
        os.remove(out)
        cmap = merged.getBestCmap()

        # Excluded integer codepoint: U+0298 must point at the base font's
        # glyph (Noto doesn't even cmap U+0298 in the static, so post-merge
        # cmap should be missing or pointing at .notdef-equivalent).
        assert cmap.get(0x0298) is None or cmap.get(0x0298) == ".notdef", (
            f"U+0298 was excluded but cmap still has {cmap.get(0x0298)!r}"
        )

        # Excluded range members keep base advance widths.
        for cp in (0x2460, 0x2461, 0x2462):
            base = TTFont(JP_STATIC)
            base_aw = base["hmtx"].metrics[base.getBestCmap()[cp]][0]
            base.close()
            merged_aw = merged["hmtx"].metrics[cmap[cp]][0]
            assert merged_aw == base_aw, (
                f"U+{cp:04X} aw {merged_aw} != base {base_aw} — "
                "range exclusion did not preserve base"
            )

        # Cross-codepoint collisions still detected for OTHER glyph names
        # (e.g. ``uni2003`` / U+3000). The integer exclusion only removes
        # U+0298 from sub cmap; it does not disable the rename pass.
        assert cmap.get(0x3000) != cmap.get(0x2003), (
            "U+3000 and U+2003 should resolve to distinct glyphs even when "
            "an unrelated codepoint is excluded"
        )


# ---------------------------------------------------------------------------
# CID-keyed CFF base + collision rename smoke test
# ---------------------------------------------------------------------------

class TestCIDBaseWithCollision:
    """Sanity: the collision pass must not crash when the base is a CID-
    keyed CFF font (Noto Sans CJK OTF). CID fonts use ``cidNNNNN`` glyph
    names so cross-codepoint name collisions are vanishingly rare in
    practice, but the code path still needs to handle the case where the
    sub font has its own postscript-style glyph names (``A``, ``space``,
    ``uni25CE``) — none of which appear in the CID glyph list — and run
    cleanly through the rename loop."""

    def test_cid_base_merge_succeeds(self):
        """CID Noto + Inter CFF merge runs without error and produces
        a font that contains both Latin and CJK glyphs."""
        if not os.path.exists(EN_CFF) or not os.path.exists(JP_OTF):
            pytest.skip("Inter CFF / NotoSansCJKjp OTF not found")
        out = tempfile.mktemp(suffix=".otf")
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
            "output": {"familyName": "TestCIDCollision"},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        merged = TTFont(out)
        os.remove(out)
        cmap = merged.getBestCmap()
        assert cmap.get(0x0041) is not None, "Latin A missing"
        assert cmap.get(0x3042) is not None, "あ missing"


# ---------------------------------------------------------------------------
# `.sub2` dedup path
# ---------------------------------------------------------------------------

def _make_sub_font_with_preexisting_sub_glyph(out_path: str):
    """Save a copy of TikTok Sans with an extra glyph named ``space.sub``
    — so the rename allocator must fall back to ``.sub2``.

    A static TTF source is used because variable fonts carry a ``gvar``
    table whose ``glyphCount`` must match the glyph order; appending a
    glyph would require regenerating ``gvar`` deltas.
    """
    src = TTFont(TIKTOK_SANS)
    glyf = src["glyf"]
    glyf["space.sub"] = TTGlyph()  # empty outline
    src["hmtx"].metrics["space.sub"] = (500, 0)
    src.setGlyphOrder(list(glyf.glyphOrder))
    src.save(out_path)
    src.close()


class TestExportConfigRoundTrip:
    """``build_export_config`` must persist ``subFont.excludeCodepoints``
    so a packaged export round-trips through ExportConfig.json. Without
    this, re-running the saved config would silently lose the protected
    codepoints and the sub font would overwrite the base again on the
    next merge."""

    def test_unit_roundtrip_preserves_exclude_codepoints(self):
        """Direct call to ``build_export_config`` keeps the list as-is."""
        config = {
            "subFont": {
                "path": "/tmp/sub.ttf",
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
                "excludeCodepoints": ["U+2460-U+24FF", 0x203B],
            },
            "baseFont": {
                "path": "/tmp/base.ttf",
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "output": {"familyName": "TestRoundtrip"},
        }
        result = mf.build_export_config(config)
        assert result["subFont"]["excludeCodepoints"] == [
            "U+2460-U+24FF", 0x203B,
        ]
        # The list must be JSON-serialisable as written.
        import json
        json.dumps(result)

    def test_unit_no_exclude_omits_field(self):
        """Absent or empty list does not pollute the output config."""
        config = {
            "subFont": {"path": "/tmp/sub.ttf", "scale": 1.0,
                        "baselineOffset": 0, "axes": []},
            "baseFont": {"path": "/tmp/base.ttf", "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
        }
        result = mf.build_export_config(config)
        assert "excludeCodepoints" not in result["subFont"]

        config["subFont"]["excludeCodepoints"] = []
        result = mf.build_export_config(config)
        assert "excludeCodepoints" not in result["subFont"]

    def test_unit_baseFont_does_not_get_exclude(self):
        """Only the sub-font entry gets ``excludeCodepoints`` — even if
        a user accidentally puts the field on baseFont, it should not
        round-trip and confuse downstream tooling."""
        config = {
            "subFont": {"path": "/tmp/sub.ttf", "scale": 1.0,
                        "baselineOffset": 0, "axes": []},
            "baseFont": {"path": "/tmp/base.ttf", "scale": 1.0,
                         "baselineOffset": 0, "axes": [],
                         "excludeCodepoints": ["U+2460"]},
        }
        result = mf.build_export_config(config)
        assert "excludeCodepoints" not in result["baseFont"]

    def test_package_export_persists_exclude_codepoints(self):
        """End-to-end: package_fonts writes ExportConfig.json with the
        list intact, so re-loading it reproduces the same merge."""
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "subFont": {
                    "path": EN_VAR,
                    "familyName": "Inter",
                    "styleName": "Regular",
                    "scale": 1.0,
                    "baselineOffset": 0,
                    "axes": [
                        {"tag": "opsz", "currentValue": 14},
                        {"tag": "wght", "currentValue": 400},
                    ],
                    "excludeCodepoints": ["U+2460-U+24FF", "U+203B"],
                },
                "baseFont": {
                    "path": JP_VAR,
                    "familyName": "Noto Sans JP",
                    "styleName": "Regular",
                    "scale": 1.0,
                    "baselineOffset": 0,
                    "axes": [{"tag": "wght", "currentValue": 400}],
                },
                "output": {
                    "familyName": "TestExcludeRT",
                    "weight": 400, "italic": False, "width": 5,
                },
                "export": {
                    "package": {
                        "dir": os.path.join(tmpdir, "TestExcludeRT-Regular"),
                        "overwrite": False,
                        # ExportConfig.json is only written when input
                        # fonts are bundled, which is also the realistic
                        # round-trip scenario for this test.
                        "bundleInputFonts": True,
                    },
                },
            }
            manifest = mf.package_fonts(config)
            with open(manifest["configPath"]) as f:
                exported = json.load(f)
            assert exported["subFont"]["excludeCodepoints"] == [
                "U+2460-U+24FF", "U+203B",
            ], (
                "ExportConfig.json must persist excludeCodepoints so "
                "re-running the saved config reproduces the merge"
            )


class TestSubSuffixDedup:
    """When the sub font already contains the natural rename target
    (``space.sub``), the allocator must fall back to ``space.sub2`` so the
    pre-existing sub-font glyph isn't silently overwritten by the renamed
    copy of ``space``."""

    def test_dedup_picks_sub2_when_sub_already_taken(self):
        """A sub font carrying its own ``space.sub`` makes the rename
        allocator pick ``space.sub2``; the pre-existing ``space.sub``
        survives in the merged font."""
        if not os.path.exists(TIKTOK_SANS) or not os.path.exists(JP_STATIC):
            pytest.skip("TikTok Sans / Noto Sans JP not found")
        with tempfile.TemporaryDirectory() as tmpdir:
            sub_path = os.path.join(tmpdir, "tiktok_with_sub.ttf")
            _make_sub_font_with_preexisting_sub_glyph(sub_path)
            out = os.path.join(tmpdir, "merged.ttf")
            config = {
                "subFont": {
                    "path": sub_path,
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
                "output": {"familyName": "TestSub2"},
                "export": {"path": {"font": out}},
            }
            mf.merge_fonts(config)
            merged = TTFont(out)
            cmap = merged.getBestCmap()
            # The space glyph at U+0020 must use ``.sub2`` because
            # ``space.sub`` was already present in the sub font.
            glyph_at_20 = cmap.get(0x0020)
            assert glyph_at_20 == "space.sub2", (
                f"U+0020 mapped to {glyph_at_20!r}; expected 'space.sub2' "
                "(allocator should have skipped the pre-existing 'space.sub')"
            )
            # The pre-existing ``space.sub`` must still exist in the merged
            # glyph order, not be overwritten by the rename.
            order = set(merged.getGlyphOrder())
            assert "space.sub" in order, (
                "pre-existing 'space.sub' was removed by the rename"
            )
            assert "space.sub2" in order, (
                "rename target 'space.sub2' missing from glyph order"
            )
