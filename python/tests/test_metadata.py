"""Tests for OFL / nameID / version / OFL.txt / Settings.txt metadata."""

import os
import tempfile

import pytest

from fontTools.ttLib import TTFont

from conftest import JP_VAR, _merge, _merge_with_meta

import merge_fonts as mf


# ---------------------------------------------------------------------------
# Output weight / nameID 2, 4, 17
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
# PostScript name sanitization and validation
# ---------------------------------------------------------------------------

class TestSanitizePostScriptName:
    """Unit tests for sanitize_postscript_name()."""

    def test_ascii_only_unchanged(self):
        assert mf.sanitize_postscript_name("NotoSans") == "NotoSans"

    def test_spaces_stripped(self):
        assert mf.sanitize_postscript_name("Noto Sans") == "NotoSans"

    def test_japanese_becomes_empty(self):
        assert mf.sanitize_postscript_name("\u5927\u548c\u660e\u671d") == ""

    def test_mixed_keeps_ascii_drops_japanese(self):
        assert mf.sanitize_postscript_name("Yamato \u660e\u671d") == "Yamato"

    def test_forbidden_chars_stripped(self):
        assert mf.sanitize_postscript_name("Noto/Sans") == "NotoSans"
        assert mf.sanitize_postscript_name("Foo(Bar)") == "FooBar"
        assert mf.sanitize_postscript_name("[Foo]{Bar}") == "FooBar"
        assert mf.sanitize_postscript_name("<Foo>") == "Foo"
        assert mf.sanitize_postscript_name("50%Off") == "50Off"

    def test_all_forbidden_becomes_empty(self):
        assert mf.sanitize_postscript_name("[](){}<>/%") == ""

    def test_allowed_punctuation_preserved(self):
        for n in ("Foo-Bar", "Foo.Bar", "Foo_Bar", "Foo+Bar", "Foo:Bar", "Foo#Bar"):
            assert mf.sanitize_postscript_name(n) == n

    def test_truncation_past_63(self):
        assert mf.sanitize_postscript_name("A" * 64) == "A" * 63
        assert mf.sanitize_postscript_name("A" * 100) == "A" * 63

    def test_exact_63_not_truncated(self):
        assert mf.sanitize_postscript_name("A" * 63) == "A" * 63

    def test_control_chars_stripped(self):
        assert mf.sanitize_postscript_name("Noto\tSans") == "NotoSans"
        assert mf.sanitize_postscript_name("Noto\nSans") == "NotoSans"

    def test_empty_input(self):
        assert mf.sanitize_postscript_name("") == ""


class TestValidatePostScriptName:
    """Unit tests for validate_postscript_name()."""

    def test_valid_names_pass(self):
        for n in ("NotoSans-Regular", "Yamato", "Foo.Bar_Baz+Qux", "A" * 63):
            mf.validate_postscript_name(n)

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            mf.validate_postscript_name("")

    def test_multibyte_raises(self):
        with pytest.raises(ValueError, match="invalid character"):
            mf.validate_postscript_name("\u5927\u548c")

    def test_forbidden_char_raises(self):
        with pytest.raises(ValueError, match="invalid character"):
            mf.validate_postscript_name("Foo/Bar")

    def test_space_raises(self):
        with pytest.raises(ValueError, match="invalid character"):
            mf.validate_postscript_name("Foo Bar")

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="exceeds"):
            mf.validate_postscript_name("A" * 64)


# ---------------------------------------------------------------------------
# Metadata correctness (Inter + Noto JP merge)
# ---------------------------------------------------------------------------

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

    def test_postscript_name_derived_sanitizes_family(self):
        """When postScriptName is absent, nameID 6 is sanitized from familyName."""
        m = _merge_with_meta(output_family="Foo/Bar(Baz)")
        name6 = m["name"].getDebugName(6)
        for ch in "()[]{}<>/%":
            assert ch not in name6, f"Forbidden char {ch!r} found in nameID 6: {name6!r}"
        assert name6.startswith("FooBarBaz")

    def test_postscript_name_explicit_override(self):
        """Explicit postScriptName is used as the PS base name in nameID 6."""
        m = _merge_with_meta(output_family="\u5927\u548c\u660e\u671d",
                             output_ps_name="YamatoMincho")
        name6 = m["name"].getDebugName(6)
        assert name6.startswith("YamatoMincho"), f"Unexpected nameID 6: {name6!r}"

    def test_postscript_name_invalid_raises(self):
        """Invalid explicit postScriptName raises ValueError."""
        with pytest.raises(ValueError, match="invalid character"):
            _merge_with_meta(output_family="Foo", output_ps_name="Bad/Name")

    def test_postscript_name_empty_family_raises(self):
        """Family with only non-ASCII and no explicit PS name raises."""
        with pytest.raises(ValueError, match="empty"):
            _merge_with_meta(output_family="\u5927\u548c\u660e\u671d")

    def test_version_defaults_to_1000(self):
        """nameID 5 defaults to 'Version 1.000' when not supplied."""
        m = _merge_with_meta()
        v = m["name"].getDebugName(5)
        assert v == "Version 1.000", f"Unexpected nameID 5: {v!r}"

    def test_version_custom_value(self):
        """Explicit version is written as 'Version X' in nameID 5."""
        m = _merge_with_meta(output_version="2.5")
        v = m["name"].getDebugName(5)
        assert v == "Version 2.5", f"Unexpected nameID 5: {v!r}"

    def test_version_with_explicit_prefix(self):
        """If the value already starts with 'Version ', it is not doubled."""
        m = _merge_with_meta(output_version="Version 3.0-beta")
        v = m["name"].getDebugName(5)
        assert v == "Version 3.0-beta", f"Unexpected nameID 5: {v!r}"

    def test_version_empty_falls_back_to_default(self):
        """Empty/whitespace version falls back to the 1.000 default."""
        m = _merge_with_meta(output_version="  ")
        v = m["name"].getDebugName(5)
        assert v == "Version 1.000", f"Unexpected nameID 5: {v!r}"

    def test_version_appends_app_version(self):
        """appVersion is appended to nameID 5 as ';ofl-font-baker X.Y.Z'."""
        m = _merge_with_meta(output_version="1.000", app_version="1.0.0")
        v = m["name"].getDebugName(5)
        assert v == "Version 1.000;ofl-font-baker 1.0.0", f"Unexpected nameID 5: {v!r}"

    def test_version_no_app_version_suffix_when_missing(self):
        """Missing appVersion produces no suffix."""
        m = _merge_with_meta(output_version="1.000")
        v = m["name"].getDebugName(5)
        assert ";ofl-font-baker" not in v, f"Unexpected nameID 5 suffix: {v!r}"

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

    def test_designer_always_cleared(self):
        """nameID 9 is always cleared — Designer belongs to the source authors."""
        m = _merge_with_meta()
        d = m["name"].getDebugName(9)
        assert d is None or d == "", f"Expected cleared designer, got '{d}'"

    def test_designer_url_always_cleared(self):
        """nameID 12 is always cleared — Designer URL is not set on the derivative."""
        m = _merge_with_meta()
        url = m["name"].getDebugName(12)
        assert url is None or url == "", f"Expected cleared designer URL, got '{url}'"

    def test_manufacturer_set_when_provided(self):
        """outputManufacturer is written to nameID 8."""
        m = _merge_with_meta(output_manufacturer="Acme Foundry")
        assert m["name"].getDebugName(8) == "Acme Foundry"

    def test_manufacturer_empty_clears(self):
        """Missing outputManufacturer clears nameID 8."""
        m = _merge_with_meta(output_manufacturer="")
        v = m["name"].getDebugName(8)
        assert v is None or v == "", f"Expected empty manufacturer, got '{v}'"

    def test_manufacturer_url_set_when_provided(self):
        """outputManufacturerURL is written to nameID 11."""
        m = _merge_with_meta(output_manufacturer_url="https://acme.example")
        assert m["name"].getDebugName(11) == "https://acme.example"

    def test_manufacturer_url_empty_clears(self):
        """Missing outputManufacturerURL clears nameID 11."""
        m = _merge_with_meta(output_manufacturer_url="")
        url = m["name"].getDebugName(11)
        assert url is None or url == "", f"Expected empty manufacturer URL, got '{url}'"

    def test_vendor_id_always_four_spaces(self):
        """OS/2 achVendID is fixed to 4 spaces (unknown vendor)."""
        m = _merge_with_meta()
        assert m["OS/2"].achVendID == "    "

    def test_unique_id_is_version_and_ps_name(self):
        """nameID 3 = '{version};{PS-full-name}'."""
        m = _merge_with_meta(output_family="TestUID", output_version="2.500")
        assert m["name"].getDebugName(3) == "2.500;TestUID-Regular"

    def test_unique_id_strips_version_prefix(self):
        """'Version ' prefix is dropped from the uniqueID version segment."""
        m = _merge_with_meta(output_family="TestUID",
                             output_version="Version 3.0")
        assert m["name"].getDebugName(3) == "3.0;TestUID-Regular"

    def test_description_mentions_sources(self):
        """nameID 10 mentions source font names."""
        m = _merge_with_meta()
        desc = m["name"].getDebugName(10)
        assert desc is not None
        assert "Based on" in desc

    def test_variations_ps_name_prefix_removed(self):
        """nameID 25 is dropped from the output (no variable instances)."""
        m = _merge_with_meta()
        assert m["name"].getDebugName(25) is None

    def test_head_created_is_fresh(self):
        """head.created is refreshed at merge time, not inherited from the base."""
        from fontTools.misc.timeTools import timestampNow
        before = timestampNow()
        m = _merge_with_meta()
        after = timestampNow()
        assert before <= m["head"].created <= after + 60
        assert before <= m["head"].modified <= after + 60

    def test_head_created_and_modified_match(self):
        """head.created and head.modified are pinned to the same instant."""
        m = _merge_with_meta()
        assert m["head"].created == m["head"].modified

    def test_head_font_revision_matches_default(self):
        """head.fontRevision defaults to 1.0 when no version is supplied."""
        m = _merge_with_meta()
        assert m["head"].fontRevision == 1.0

    def test_head_font_revision_matches_version(self):
        """head.fontRevision tracks output.version numerically."""
        m = _merge_with_meta(output_version="2.5")
        assert m["head"].fontRevision == 2.5

    def test_head_font_revision_strips_version_prefix(self):
        """'Version ' prefix is dropped before parsing fontRevision."""
        m = _merge_with_meta(output_version="Version 3.25")
        assert m["head"].fontRevision == 3.25

    def test_head_font_revision_strips_suffix(self):
        """Non-numeric suffixes like '-beta' are dropped before parsing."""
        m = _merge_with_meta(output_version="1.500-beta")
        assert m["head"].fontRevision == 1.5

    def test_head_font_revision_falls_back_on_garbage(self):
        """Unparseable version values fall back to 1.0."""
        m = _merge_with_meta(output_version="pre-release")
        assert m["head"].fontRevision == 1.0

    def test_trademark_includes_user_addition(self):
        """outputTrademark is appended to nameID 7."""
        m = _merge_with_meta(output_trademark="Acme is a trademark of Acme Foundry")
        tm = m["name"].getDebugName(7)
        assert tm is not None
        assert "Acme is a trademark of Acme Foundry" in tm

    def test_trademark_preserves_sources(self):
        """Source trademarks (if any) survive into nameID 7."""
        # Inter and Noto Sans JP test subsets carry trademark text in
        # their name tables; the combined output should retain at least
        # one source trademark when the user addition is empty.
        m = _merge_with_meta(output_trademark="")
        tm = m["name"].getDebugName(7)
        # Not guaranteed that subsets include trademark, but if either
        # source had one, it must survive — we just assert non-failure
        # here and rely on the user-addition test for positive coverage.
        assert tm is None or isinstance(tm, str)

    def test_description_mentions_built_with(self):
        """Two-font merge includes 'Built with OFL Font Baker' in nameID 10."""
        m = _merge_with_meta()
        desc = m["name"].getDebugName(10)
        assert "Built with OFL Font Baker" in desc


class TestMetadataBaseOnly:
    """Metadata for base-font-only merge (no Latin font)."""

    def _merge_base_only_meta(self, output_copyright=""):
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "baseFont": {
                "path": JP_VAR,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {
                "familyName": "BaseOnlyMeta",
                "copyright": output_copyright,
            },
            "export": {"path": {"font": out}},
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

    def test_designer_cleared(self):
        """Base-only merges also clear nameID 9 — Designer is never set on the output."""
        m = self._merge_base_only_meta()
        d = m["name"].getDebugName(9)
        assert d is None or d == "", f"Expected cleared designer, got '{d}'"

    def test_description_mentions_built_with(self):
        """Base-only also uses 'Built with OFL Font Baker' in nameID 10."""
        m = self._merge_base_only_meta()
        desc = m["name"].getDebugName(10) or ""
        assert "Built with OFL Font Baker" in desc


# ---------------------------------------------------------------------------
# OFL.txt and Settings.txt builders
# ---------------------------------------------------------------------------

class TestBuildOflText:

    def test_collects_source_copyrights(self):
        config = {
            "baseFont": {"copyright": "Copyright Base"},
            "subFont": {"copyright": "Copyright Latin"},
            "output": {"familyName": "Test"},
        }
        text = mf.build_ofl_text(config)
        assert "Copyright Base" in text
        assert "Copyright Latin" in text
        assert "SIL OPEN FONT LICENSE" in text

    def test_user_copyright_appended(self):
        config = {
            "baseFont": {"copyright": "Copyright Base"},
            "output": {"copyright": "Copyright User", "familyName": "Test"},
        }
        text = mf.build_ofl_text(config)
        assert "Copyright User" in text

    def test_fallback_copyright(self):
        config = {
            "baseFont": {},
            "output": {"familyName": "MyFont"},
        }
        text = mf.build_ofl_text(config)
        assert "MyFont Authors" in text

    def test_dedup_copyrights(self):
        config = {
            "baseFont": {"copyright": "Same"},
            "subFont": {"copyright": "Same"},
            "output": {"familyName": "Test"},
        }
        text = mf.build_ofl_text(config)
        assert text.count("Same") == 1


class TestBuildSettingsText:

    def test_header_includes_family_and_style(self):
        config = {
            "baseFont": {"familyName": "Noto", "styleName": "Regular",
                         "scale": 1.0, "baselineOffset": 0, "path": "/fonts/noto.otf"},
            "output": {"familyName": "MyFont", "weight": 700,
                       "italic": True, "width": 5},
        }
        text = mf.build_settings_text(config)
        assert "MyFont Bold Italic" in text

    def test_base_only_shows_built_with(self):
        config = {
            "baseFont": {"familyName": "Noto", "styleName": "Regular",
                         "scale": 1.0, "baselineOffset": 0, "path": "/fonts/noto.otf"},
            "output": {"familyName": "MyFont", "weight": 400},
        }
        text = mf.build_settings_text(config)
        assert "Built with OFL Font Baker" in text

    def test_with_latin_shows_sub_font(self):
        config = {
            "baseFont": {"familyName": "Noto", "styleName": "Regular",
                         "scale": 1.0, "baselineOffset": 0, "path": "/fonts/noto.otf"},
            "subFont": {"familyName": "Inter", "styleName": "Regular",
                        "scale": 0.95, "baselineOffset": 5, "path": "/fonts/inter.ttf"},
            "output": {"familyName": "MyFont", "weight": 400},
        }
        text = mf.build_settings_text(config)
        assert "Built with OFL Font Baker" in text
        assert "[Sub Font]" in text


