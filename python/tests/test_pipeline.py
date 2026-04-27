"""Tests for merge pipeline edge cases and output packaging."""

import json
import os
import tempfile

import pytest

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from conftest import EN_FULL, EN_VAR, FONTS, JP_OTF_FULL, JP_VAR, _merge_otf_jp

import merge_fonts as mf


SHIPPORI = os.path.join(FONTS, "Shippori_Mincho", "ShipporiMincho-Regular.ttf")


# ---------------------------------------------------------------------------
# CID Japanese font (CFF base, OTF output)
# ---------------------------------------------------------------------------

class TestCIDJapaneseFont:
    """Merge tests with CID-keyed CFF (JP OTF) base font."""

    def test_merge_succeeds(self):
        """Merge with CID-keyed JP font completes without error."""
        m = _merge_otf_jp()
        # CFF base stays CFF after merge; TT base stays TT. Either outline
        # table is acceptable as long as one is present.
        assert "CFF " in m or "glyf" in m
        assert m.sfntVersion in ("OTTO", "\x00\x01\x00\x00"), \
            f"sfntVersion should be CFF or TrueType, got {repr(m.sfntVersion)}"

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
        """Japanese glyph has a valid outline in the merged font."""
        m = _merge_otf_jp()
        cmap = m.getBestCmap()
        a_glyph = cmap.get(0x3042)  # あ
        assert a_glyph is not None, "U+3042 (あ) not in cmap"
        gs = m.getGlyphSet()
        bp = BoundsPen(gs)
        gs[a_glyph].draw(bp)
        bounds = bp.bounds
        assert bounds is not None, "Glyph あ has no outline in the merged font"

    def test_hmtx_complete_otf(self):
        """All glyphs have hmtx metrics."""
        m = _merge_otf_jp()
        hmtx = m["hmtx"]
        order = m.getGlyphOrder()
        missing = [g for g in order if g not in hmtx.metrics]
        assert len(missing) == 0, f"Glyphs missing from hmtx: {missing[:10]}"



# ---------------------------------------------------------------------------
# ChainContext Format 2 ClassDef rename (Issue #8 — i.numr crash)
# ---------------------------------------------------------------------------

class TestChainContextClassDefRename:
    """Regression for the i.numr crash. When a Latin glyph is renamed via
    cmap-based remap (e.g. Inter `i.numr` → Shippori `uniE0A5`), every
    place that references the old name in GSUB/GPOS must be rewritten —
    including the BacktrackClassDef / InputClassDef / LookAheadClassDef
    triple inside ChainContextSubst Format 2 lookups.
    """

    def test_inter_full_into_shippori_does_not_crash(self):
        """Inter Variable + Shippori Mincho merge round-trips through save."""
        if not os.path.exists(SHIPPORI):
            pytest.skip("Shippori Mincho not available")
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {"path": EN_FULL, "scale": 1.0,
                        "baselineOffset": 0,
                        "axes": [{"tag": "opsz", "currentValue": 14},
                                 {"tag": "wght", "currentValue": 400}]},
            "baseFont": {"path": SHIPPORI, "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
            "output": {"familyName": "TestChain"},
            "export": {"path": {"font": out}},
        }
        try:
            mf.merge_fonts(config)
            assert os.path.exists(out)
            # Reload to verify the saved font is parseable too.
            TTFont(out)
        finally:
            for p in (out, out.replace(".ttf", ".woff2")):
                if os.path.exists(p):
                    os.remove(p)


# ---------------------------------------------------------------------------
# Base-only merge (no Latin sub)
# ---------------------------------------------------------------------------

class TestBaseOnly:
    """Verify that base-font-only merge (no Latin) works correctly."""

    def _merge_base_only(self):
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "baseFont": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "BaseOnly"},
            "export": {"path": {"font": out}},
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
            "output": {"familyName": "TestWoff2"},
            "export": {"path": {"font": out, "woff2": woff2_path}},
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
            "baseFont": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "BaseOnlyWoff2"},
            "export": {"path": {"font": out, "woff2": woff2_path}},
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

@pytest.mark.skipif(
    not os.path.exists(JP_OTF_FULL),
    reason="NotoSansCJKjp-Regular.otf not in python/tests/fonts/NotoSansCJKjp/",
)
class TestLargeCIDFont:
    """Verify merge of a 65535-glyph CID font with a Latin font."""

    def _merge_large(self):
        out = tempfile.mktemp(suffix=".otf")
        config = {
            "subFont": {
                "path": EN_VAR,
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
            "output": {"familyName": "LargeCIDTest"},
            "export": {"path": {"font": out}},
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
# Utility helpers (detect_sfnt_ext, compute_style_name, prepare_output_dir)
# ---------------------------------------------------------------------------

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
            target = os.path.join(d, "TestFont")
            result = mf.prepare_output_dir(target, overwrite=False)
            assert os.path.isdir(result)
            assert result == target

    def test_overwrite_false_raises(self):
        with tempfile.TemporaryDirectory() as d:
            existing = os.path.join(d, "Existing")
            os.makedirs(existing)
            with pytest.raises(FileExistsError):
                mf.prepare_output_dir(existing, overwrite=False)

    def test_overwrite_true_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            existing = os.path.join(d, "Existing")
            os.makedirs(existing)
            marker = os.path.join(existing, "old.txt")
            open(marker, "w").close()
            result = mf.prepare_output_dir(existing, overwrite=True)
            assert os.path.isdir(result)
            assert not os.path.exists(marker)


# ---------------------------------------------------------------------------
# Output packaging (TestPackageFonts / TestPackageOptions)
# ---------------------------------------------------------------------------

class TestPackageFonts:

    def _export(self, overwrite=False):
        d = tempfile.mkdtemp()
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
                "familyName": "TestFont",
                "weight": 400,
                "italic": False,
                "width": 5,
            },
            "export": {
                "package": {
                    "dir": os.path.join(d, "TestFont-Regular"),
                    "overwrite": overwrite,
                },
            },
        }
        manifest = mf.package_fonts(config)
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
            assert "Built with OFL Font Baker" in content
        import shutil
        shutil.rmtree(d)

    def test_overwrite_false_blocks_duplicate(self):
        d, _ = self._export()
        with pytest.raises(FileExistsError):
            config = {
                "subFont": {
                    "path": EN_VAR, "scale": 1.0, "baselineOffset": 0,
                    "axes": [{"tag": "opsz", "currentValue": 14}, {"tag": "wght", "currentValue": 400}],
                },
                "baseFont": {
                    "path": JP_VAR, "scale": 1.0, "baselineOffset": 0,
                    "axes": [{"tag": "wght", "currentValue": 400}],
                },
                "output": {"familyName": "TestFont"},
                "export": {
                    "package": {
                        "dir": os.path.join(d, "TestFont-Regular"),
                        "overwrite": False,
                    },
                },
            }
            mf.package_fonts(config)
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


class TestPackageOptions:

    def _base_config(self, tmpdir):
        return {
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
                "familyName": "TestFont",
                "weight": 400,
                "italic": False,
                "width": 5,
            },
            "export": {
                "package": {
                    "dir": os.path.join(tmpdir, "TestFont-Regular"),
                    "overwrite": False,
                },
            },
        }

    def test_bundle_input_fonts(self):
        import shutil
        d = tempfile.mkdtemp()
        config = self._base_config(d)
        config["export"]["package"]["bundleInputFonts"] = True
        manifest = mf.package_fonts(config)
        pkg_dir = os.path.join(d, "TestFont-Regular")
        source_dir = os.path.join(pkg_dir, "source")
        assert os.path.isdir(source_dir)
        assert os.path.isfile(os.path.join(source_dir, os.path.basename(EN_VAR)))
        assert os.path.isfile(os.path.join(source_dir, os.path.basename(JP_VAR)))
        with open(manifest["configPath"]) as f:
            export_cfg = json.load(f)
        assert export_cfg["baseFont"]["path"].startswith("./source/")
        assert export_cfg["subFont"]["path"].startswith("./source/")
        shutil.rmtree(d)

    def test_default_options(self):
        opts = mf.resolve_package_options({})
        assert opts == {
            "overwrite": False,
            "bundleInputFonts": False,
        }

    def test_font_format_auto_uses_base_ext(self):
        import shutil
        d = tempfile.mkdtemp()
        config = self._base_config(d)
        manifest = mf.package_fonts(config)
        assert manifest["fontPath"].endswith(".ttf")
        shutil.rmtree(d)
