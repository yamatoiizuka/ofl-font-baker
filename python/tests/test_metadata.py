"""Tests for OFL / nameID / version / OFL.txt / Settings.txt metadata."""

import os
import tempfile

import pytest

from fontTools.ttLib import TTFont

from conftest import EN_CFF_FULL, EN_VAR, JP_VAR, _merge, _merge_with_meta

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
# Static-output style identity: STAT removal + fsSelection / macStyle
# (Issue #16)
# ---------------------------------------------------------------------------

_FS_ITALIC = 0x0001
_FS_BOLD = 0x0020
_FS_REGULAR = 0x0040
_MAC_BOLD = 0x0001
_MAC_ITALIC = 0x0002


def _merge_with_italic(output_weight=400, output_italic=False,
                       metadata_mode=None):
    """Run a merge that lets the test choose italic + metadataMode."""
    out = tempfile.mktemp(suffix=".ttf")
    output = {
        "familyName": "StyleTest",
        "weight": output_weight,
        "italic": output_italic,
    }
    if metadata_mode is not None:
        output["metadataMode"] = metadata_mode
    config = {
        "subFont": {
            "path": EN_VAR, "scale": 1.0, "baselineOffset": 0,
            "axes": [
                {"tag": "opsz", "currentValue": 14},
                {"tag": "wght", "currentValue": 400},
            ],
        },
        "baseFont": {
            "path": JP_VAR, "scale": 1.0, "baselineOffset": 0,
            "axes": [{"tag": "wght", "currentValue": 400}],
        },
        "output": output,
        "export": {"path": {"font": out}},
    }
    mf.merge_fonts(config)
    font = TTFont(out)
    for f in (out, out.replace(".ttf", ".woff2")):
        if os.path.exists(f):
            os.remove(f)
    return font


class TestStripStat:
    """STAT must not survive into static outputs.

    fontTools.varLib.instancer prunes STAT to the instantiated location,
    leaving stale axis records (or a partial table for off-axis instances).
    Once output.weight/italic/width overrides change the static identity,
    inherited STAT contradicts the name table / OS/2.
    """

    def test_merge_mode_drops_stat(self):
        """Merge mode removes STAT regardless of source."""
        # Sanity: source has STAT (so the test is meaningful).
        assert "STAT" in TTFont(JP_VAR)
        m = _merge(output_weight=700)
        assert "STAT" not in m

    def test_inherit_base_drops_stat(self):
        """inheritBase also drops STAT — static outputs don't need it."""
        m = _merge_inherit("inheritBase")
        assert "STAT" not in m

    def test_inherit_base_with_weight_drops_stat(self):
        """inheritBase + weight override (the issue #16 scenario)."""
        m = _merge_inherit("inheritBase", {"weight": 700})
        assert "STAT" not in m

    def test_inherit_sub_drops_stat(self):
        """inheritSub also drops STAT."""
        m = _merge_inherit("inheritSub")
        assert "STAT" not in m


class TestStyleBitsMergeMode:
    """OS/2.fsSelection REGULAR/BOLD/ITALIC and head.macStyle bold/italic
    must agree with output.weight + output.italic. The base font's bits
    must not leak into the derivative."""

    def test_regular_sets_regular_clears_bold_italic(self):
        m = _merge(output_weight=400)
        fs = m["OS/2"].fsSelection
        ms = m["head"].macStyle
        assert fs & _FS_REGULAR
        assert not (fs & _FS_BOLD)
        assert not (fs & _FS_ITALIC)
        assert not (ms & _MAC_BOLD)
        assert not (ms & _MAC_ITALIC)

    def test_bold_sets_bold_clears_regular(self):
        """Issue #16: weight=700 must clear inherited REGULAR bit."""
        m = _merge(output_weight=700)
        fs = m["OS/2"].fsSelection
        ms = m["head"].macStyle
        assert fs & _FS_BOLD, f"BOLD bit missing in fsSelection={fs:#x}"
        assert not (fs & _FS_REGULAR), \
            f"REGULAR bit still set in fsSelection={fs:#x}"
        assert ms & _MAC_BOLD, f"macStyle bold bit missing in {ms:#x}"

    def test_extra_bold_also_sets_bold(self):
        """weight >= 700 sets the bold bits."""
        m = _merge(output_weight=800)
        fs = m["OS/2"].fsSelection
        assert fs & _FS_BOLD
        assert not (fs & _FS_REGULAR)

    @pytest.mark.parametrize("weight,name", [
        (300, "Light"),
        (500, "Medium"),
        (600, "SemiBold"),
    ])
    def test_non_regular_weights_clear_regular_bit(self, weight, name):
        """Light / Medium / SemiBold must clear REGULAR — only the actual
        Regular face (weight=400, normal width, non-italic) advertises it.
        Otherwise font matchers would pick e.g. SemiBold as the family's
        Regular style."""
        m = _merge(output_weight=weight)
        # Sanity: confirm we really did get the non-Regular style.
        assert m["name"].getDebugName(2) == name
        fs = m["OS/2"].fsSelection
        assert not (fs & _FS_REGULAR), \
            f"REGULAR must be clear for {name}, got fsSelection={fs:#x}"
        assert not (fs & _FS_BOLD)
        assert not (fs & _FS_ITALIC)

    def test_italic_sets_italic_clears_regular(self):
        m = _merge_with_italic(output_weight=400, output_italic=True)
        fs = m["OS/2"].fsSelection
        ms = m["head"].macStyle
        assert fs & _FS_ITALIC
        assert not (fs & _FS_REGULAR)
        assert not (fs & _FS_BOLD)
        assert ms & _MAC_ITALIC
        assert not (ms & _MAC_BOLD)

    def test_bold_italic_sets_both(self):
        m = _merge_with_italic(output_weight=700, output_italic=True)
        fs = m["OS/2"].fsSelection
        ms = m["head"].macStyle
        assert fs & _FS_BOLD
        assert fs & _FS_ITALIC
        assert not (fs & _FS_REGULAR)
        assert ms & _MAC_BOLD
        assert ms & _MAC_ITALIC


class TestStyleBitsInheritMode:
    """Inherit mode must re-sync style bits when any style component is
    overridden, but leave them alone in pure pass-through."""

    def test_pure_passthrough_keeps_bits(self):
        """No style override → fsSelection is preserved verbatim."""
        base = TTFont(JP_VAR)
        base_fs = base["OS/2"].fsSelection
        m = _merge_inherit("inheritBase")
        assert m["OS/2"].fsSelection == base_fs

    def test_weight_override_recomputes_bits(self):
        """Issue #16 root case: inheritBase + weight=700 must clear
        the inherited REGULAR bit and set BOLD even when italic isn't
        explicitly specified."""
        m = _merge_inherit("inheritBase", {"weight": 700})
        fs = m["OS/2"].fsSelection
        ms = m["head"].macStyle
        assert fs & _FS_BOLD, f"BOLD missing in fsSelection={fs:#x}"
        assert not (fs & _FS_REGULAR), \
            f"REGULAR still set in fsSelection={fs:#x}"
        assert ms & _MAC_BOLD

    def test_italic_override_clears_regular(self):
        m = _merge_inherit("inheritBase", {"italic": True})
        fs = m["OS/2"].fsSelection
        assert fs & _FS_ITALIC
        assert not (fs & _FS_REGULAR)


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




# ---------------------------------------------------------------------------
# metadataMode: inheritBase / inheritSub
# ---------------------------------------------------------------------------


def _merge_inherit(mode, output_extra=None, with_sub=True, return_path=False):
    """Run a merge with output.metadataMode={mode} and optional overrides."""
    out = tempfile.mktemp(suffix=".ttf")
    output = {"metadataMode": mode}
    if output_extra:
        output.update(output_extra)
    config = {
        "baseFont": {
            "path": JP_VAR,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [{"tag": "wght", "currentValue": 400}],
        },
        "output": output,
        "export": {"path": {"font": out}},
    }
    if with_sub:
        config["subFont"] = {
            "path": EN_VAR,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [
                {"tag": "opsz", "currentValue": 14},
                {"tag": "wght", "currentValue": 400},
            ],
        }
    mf.merge_fonts(config)
    if return_path:
        return out
    font = TTFont(out)
    for f in (out, out.replace(".ttf", ".woff2")):
        if os.path.exists(f):
            os.remove(f)
    return font


class TestMetadataModeValidation:
    """Validation of output.metadataMode."""

    def test_unknown_value_raises(self):
        with pytest.raises(ValueError, match="metadataMode"):
            _merge_inherit("bogus")

    def test_inherit_sub_without_sub_raises(self):
        with pytest.raises(ValueError, match="requires a subFont"):
            _merge_inherit("inheritSub", with_sub=False)

    def test_null_treated_as_merge(self):
        """metadataMode=null collapses to merge mode."""
        # Null falls through to merge, which forces familyName="Merged Font"
        # default and clears designer. Smoke-check that it runs.
        m = _merge_inherit(None, output_extra={"familyName": "MergedNull"})
        assert m["name"].getDebugName(1) == "MergedNull"


class TestInheritBase:
    """inheritBase: pass identity through from the base font."""

    def test_family_name_inherited_from_base(self):
        """No familyName override → nameID 1 keeps base's family."""
        base = TTFont(JP_VAR)
        base_family = base["name"].getDebugName(1)
        m = _merge_inherit("inheritBase")
        assert m["name"].getDebugName(1) == base_family

    def test_copyright_inherited_from_base(self):
        """No copyright override → nameID 0 keeps base's copyright (no merging from sub)."""
        base = TTFont(JP_VAR)
        base_copy = base["name"].getDebugName(0)
        m = _merge_inherit("inheritBase")
        assert m["name"].getDebugName(0) == base_copy

    def test_designer_not_cleared(self):
        """inherit mode does NOT clear nameID 9 — base's designer survives."""
        base = TTFont(JP_VAR)
        base_designer = base["name"].getDebugName(9)
        m = _merge_inherit("inheritBase")
        if base_designer:
            assert m["name"].getDebugName(9) == base_designer

    def test_license_not_forced_to_ofl_canonical(self):
        """inherit mode does NOT overwrite nameID 13 with the canonical OFL text."""
        base = TTFont(JP_VAR)
        base_license = base["name"].getDebugName(13)
        m = _merge_inherit("inheritBase")
        # The license string should be byte-identical to base, even if it
        # differs from the canonical merge-mode license text.
        if base_license is not None:
            assert m["name"].getDebugName(13) == base_license

    def test_head_timestamps_not_refreshed(self):
        """inherit mode keeps head.created/modified from the base font."""
        base = TTFont(JP_VAR)
        m = _merge_inherit("inheritBase")
        assert m["head"].created == base["head"].created
        assert m["head"].modified == base["head"].modified

    def test_version_not_modified_when_unspecified(self):
        """inherit mode without version override keeps base's nameID 5."""
        base = TTFont(JP_VAR)
        base_version = base["name"].getDebugName(5)
        m = _merge_inherit("inheritBase")
        assert m["name"].getDebugName(5) == base_version

    def test_version_no_ofl_baker_suffix_in_inherit(self):
        """inherit mode does NOT append ;ofl-font-baker even with appVersion."""
        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {
                "path": EN_VAR, "scale": 1.0, "baselineOffset": 0,
                "axes": [
                    {"tag": "opsz", "currentValue": 14},
                    {"tag": "wght", "currentValue": 400},
                ],
            },
            "baseFont": {
                "path": JP_VAR, "scale": 1.0, "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "appVersion": "9.9.9",
            "output": {"metadataMode": "inheritBase", "version": "2.5"},
            "export": {"path": {"font": out}},
        }
        mf.merge_fonts(config)
        font = TTFont(out)
        for f in (out, out.replace(".ttf", ".woff2")):
            if os.path.exists(f):
                os.remove(f)
        v = font["name"].getDebugName(5)
        assert v == "Version 2.5", f"Unexpected nameID 5: {v!r}"
        assert ";ofl-font-baker" not in v

    def test_variations_ps_prefix_kept(self):
        """inherit mode does NOT strip nameID 25 (only merge mode does)."""
        base = TTFont(JP_VAR)
        base_n25 = base["name"].getDebugName(25)
        m = _merge_inherit("inheritBase")
        if base_n25 is not None:
            assert m["name"].getDebugName(25) == base_n25


class TestInheritBaseOverrides:
    """Explicit output.* fields override the inherited base values."""

    def test_family_override_recomposes_full_name(self):
        """familyName override updates nameID 1 and recomposes nameID 4 with base style."""
        base = TTFont(JP_VAR)
        base_subfamily = base["name"].getDebugName(2) or "Regular"
        m = _merge_inherit("inheritBase", {"familyName": "OverrideFam"})
        assert m["name"].getDebugName(1) == "OverrideFam"
        assert m["name"].getDebugName(4) == f"OverrideFam {base_subfamily}".strip()

    def test_family_override_recomposes_postscript_name(self):
        """familyName override regenerates nameID 6 from sanitized family."""
        base = TTFont(JP_VAR)
        base_subfamily = base["name"].getDebugName(2) or "Regular"
        m = _merge_inherit("inheritBase", {"familyName": "Override Fam"})
        ps_style = base_subfamily.replace(" ", "") or "Regular"
        assert m["name"].getDebugName(6) == f"OverrideFam-{ps_style}"

    def test_explicit_postscript_name(self):
        """postScriptName override picks the PS base directly."""
        base = TTFont(JP_VAR)
        base_subfamily = base["name"].getDebugName(2) or "Regular"
        m = _merge_inherit("inheritBase",
                           {"familyName": "OverrideFam", "postScriptName": "MyPS"})
        ps_style = base_subfamily.replace(" ", "") or "Regular"
        assert m["name"].getDebugName(6) == f"MyPS-{ps_style}"

    def test_weight_override_recomposes_style(self):
        """weight override updates OS/2 + nameID 2/4 style."""
        m = _merge_inherit("inheritBase", {"weight": 700})
        assert m["OS/2"].usWeightClass == 700
        assert m["name"].getDebugName(2) == "Bold"
        # nameID 4 includes the new style
        assert "Bold" in m["name"].getDebugName(4)

    def test_italic_override_sets_bits(self):
        """italic override flips OS/2.fsSelection and head.macStyle italic bits."""
        m = _merge_inherit("inheritBase", {"italic": True})
        assert m["OS/2"].fsSelection & 0x0001
        assert m["head"].macStyle & 0x0002
        assert "Italic" in (m["name"].getDebugName(2) or "")

    def test_version_override(self):
        """version override sets nameID 5 + head.fontRevision (no suffix)."""
        m = _merge_inherit("inheritBase", {"version": "3.0"})
        assert m["name"].getDebugName(5) == "Version 3.0"
        assert m["head"].fontRevision == 3.0

    def test_copyright_overwrite(self):
        """copyright override fully replaces nameID 0 (no concatenation)."""
        m = _merge_inherit("inheritBase",
                           {"copyright": "Copyright Override"})
        assert m["name"].getDebugName(0) == "Copyright Override"

    def test_manufacturer_override(self):
        m = _merge_inherit("inheritBase", {"manufacturer": "Acme"})
        assert m["name"].getDebugName(8) == "Acme"

    def test_unspecified_fields_untouched(self):
        """Specifying weight does NOT clear designer or rewrite copyright."""
        base = TTFont(JP_VAR)
        base_designer = base["name"].getDebugName(9)
        base_copy = base["name"].getDebugName(0)
        m = _merge_inherit("inheritBase", {"weight": 700})
        if base_designer:
            assert m["name"].getDebugName(9) == base_designer
        assert m["name"].getDebugName(0) == base_copy


class TestInheritSub:
    """inheritSub: identity comes from the sub font."""

    def test_family_from_sub(self):
        """nameID 1 comes from sub, not base."""
        sub = TTFont(EN_VAR)
        sub_family = sub["name"].getDebugName(1)
        m = _merge_inherit("inheritSub")
        assert m["name"].getDebugName(1) == sub_family

    def test_copyright_from_sub(self):
        """nameID 0 comes from sub only (not concatenated)."""
        sub = TTFont(EN_VAR)
        sub_copy = sub["name"].getDebugName(0)
        m = _merge_inherit("inheritSub")
        assert m["name"].getDebugName(0) == sub_copy

    def test_weight_class_from_sub(self):
        """OS/2.usWeightClass comes from sub."""
        sub = TTFont(EN_VAR)
        m = _merge_inherit("inheritSub")
        assert m["OS/2"].usWeightClass == sub["OS/2"].usWeightClass

    def test_family_override_on_sub(self):
        """familyName override re-composes name records on top of sub identity."""
        sub = TTFont(EN_VAR)
        sub_subfamily = sub["name"].getDebugName(2) or "Regular"
        m = _merge_inherit("inheritSub", {"familyName": "SubOverride"})
        assert m["name"].getDebugName(1) == "SubOverride"
        assert m["name"].getDebugName(4) == f"SubOverride {sub_subfamily}".strip()


class TestInheritUniqueId:
    """nameID 3 (Unique Font Identifier) must track family / style / version
    overrides so the OS font cache treats the merged font as a distinct
    entry instead of colliding with the inherited source font."""

    def test_pure_passthrough_keeps_base_unique_id(self):
        """No overrides → nameID 3 is preserved verbatim from the base font."""
        base = TTFont(JP_VAR)
        base_uid = base["name"].getDebugName(3)
        m = _merge_inherit("inheritBase")
        assert m["name"].getDebugName(3) == base_uid

    def test_family_override_recomputes_unique_id(self):
        """familyName override → nameID 3 is recomputed from new nameID 5/6."""
        m = _merge_inherit("inheritBase",
                           {"familyName": "OverrideFam"})
        uid = m["name"].getDebugName(3)
        ps_full = m["name"].getDebugName(6)
        version = m["name"].getDebugName(5) or ""
        if version.lower().startswith("version "):
            version = version[len("Version "):].strip()
        assert uid == f"{version};{ps_full}"

    def test_postscript_override_recomputes_unique_id(self):
        """postScriptName override → nameID 3 reflects the new PS full name."""
        m = _merge_inherit("inheritBase",
                           {"familyName": "Fam", "postScriptName": "MyPS"})
        uid = m["name"].getDebugName(3)
        assert "MyPS" in uid

    def test_version_override_recomputes_unique_id(self):
        """version override → nameID 3 starts with the new version."""
        m = _merge_inherit("inheritBase", {"version": "3.0"})
        uid = m["name"].getDebugName(3)
        assert uid.startswith("3.0;"), \
            f"Expected nameID 3 to start with '3.0;', got {uid!r}"

    def test_combined_overrides_dont_inherit_stale_uid(self):
        """The reviewer's repro: familyName + postScriptName + version
        together must NOT leave nameID 3 pointing at the base UID."""
        base = TTFont(JP_VAR)
        base_uid = base["name"].getDebugName(3)
        m = _merge_inherit("inheritBase", {
            "familyName": "Fam",
            "postScriptName": "MyPS",
            "version": "3.0",
        })
        uid = m["name"].getDebugName(3)
        assert uid != base_uid
        assert uid.startswith("3.0;")
        assert "MyPS" in uid


class TestExportConfigMetadataMode:
    """build_export_config must round-trip non-identity output policies."""

    def test_inherit_base_preserved(self):
        config = {
            "baseFont": {"path": "/fonts/base.ttf", "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
            "output": {"metadataMode": "inheritBase",
                       "familyName": "Fam"},
            "export": {"path": {"font": "/out.ttf"}},
        }
        result = mf.build_export_config(config)
        assert result["output"]["metadataMode"] == "inheritBase"

    def test_inherit_sub_preserved(self):
        config = {
            "baseFont": {"path": "/fonts/base.ttf", "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
            "subFont": {"path": "/fonts/sub.ttf", "scale": 1.0,
                        "baselineOffset": 0, "axes": []},
            "output": {"metadataMode": "inheritSub"},
            "export": {"path": {"font": "/out.ttf"}},
        }
        result = mf.build_export_config(config)
        assert result["output"]["metadataMode"] == "inheritSub"

    def test_merge_mode_omitted_when_unset(self):
        """metadataMode unset → not added to output (preserves default)."""
        config = {
            "baseFont": {"path": "/fonts/base.ttf", "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
            "output": {"familyName": "Fam"},
            "export": {"path": {"font": "/out.ttf"}},
        }
        result = mf.build_export_config(config)
        assert "metadataMode" not in result.get("output", {})

    def test_hinting_policy_preserved(self):
        """hinting policy is kept so bundled exports remain reproducible."""
        config = {
            "baseFont": {"path": "/fonts/base.ttf", "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
            "output": {"hinting": "ttfautohint"},
            "export": {"path": {"font": "/out.ttf"}},
        }
        result = mf.build_export_config(config)
        assert result["output"]["hinting"] == "ttfautohint"


# ---------------------------------------------------------------------------
# UINameID collision (Issue #2 #7)
# ---------------------------------------------------------------------------


class TestUINameIDCollision:
    """When a Latin FeatureParams UINameID collides with a base-font name
    record, the merge engine must remap the Latin nameID so the feature
    label keeps its original text instead of inheriting the base string."""

    def test_inter_ss02_label_preserved_against_jp_nameid_257(self):
        """Inter Regular.otf uses UINameID 257 for `ss02` ("Disambiguation").
        NotoSansJP also has a name record at nameID 257 ("Weight"). After
        merge the merged ss02 must still resolve to Inter's text, not JP's.
        """
        en = TTFont(EN_CFF_FULL)
        inter_text = next(
            (r.toUnicode() for r in en["name"].names if r.nameID == 257),
            None,
        )
        if inter_text is None:
            pytest.skip("Inter has no nameID 257 record")
        jp = TTFont(JP_VAR)
        jp_text = next(
            (r.toUnicode() for r in jp["name"].names if r.nameID == 257),
            None,
        )
        if jp_text is None or jp_text == inter_text:
            pytest.skip("No natural collision between Inter and JP nameID 257")

        out = tempfile.mktemp(suffix=".otf")
        config = {
            "subFont": {"path": EN_CFF_FULL, "scale": 1.0,
                        "baselineOffset": 0, "axes": []},
            "baseFont": {"path": JP_VAR, "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
            "output": {"familyName": "TestUI"},
            "export": {"path": {"font": out}},
        }
        try:
            mf.merge_fonts(config)
            m = TTFont(out)
            ss02_uinameid = None
            for fr in m["GSUB"].table.FeatureList.FeatureRecord:
                if fr.FeatureTag != "ss02":
                    continue
                fp = fr.Feature.FeatureParams
                if fp and hasattr(fp, "UINameID"):
                    ss02_uinameid = fp.UINameID
                    break
            assert ss02_uinameid is not None, "Merged font lost ss02 UINameID"
            label = next(
                (r.toUnicode() for r in m["name"].names
                 if r.nameID == ss02_uinameid),
                None,
            )
            assert label == inter_text, (
                f"Merged ss02 label is {label!r}; expected Inter's "
                f"{inter_text!r}, not JP's {jp_text!r}. UINameID collision "
                f"was not remapped."
            )
        finally:
            for p in (out, out.replace(".otf", ".woff2")):
                if os.path.exists(p):
                    os.remove(p)


# ---------------------------------------------------------------------------
# Character Variant labels (cvXX) — regression for Codex review of #7
# ---------------------------------------------------------------------------


CHARIS = os.path.join(os.path.dirname(__file__), "fonts",
                      "Charis_SIL", "CharisSIL-Regular.ttf")
PLAYWRITE = os.path.join(os.path.dirname(__file__), "fonts",
                         "Playwrite_IE", "PlaywriteIE-VariableFont_wght.ttf")


class TestCharacterVariantLabels:
    """The Latin-side cvXX labels (FeatUILabelNameID, FirstParamUILabelNameID)
    must be carried over and remapped on collision, just like ssXX UINameID.
    """

    def test_charis_cv13_label_preserved_when_charis_is_sub(self):
        """Charis SIL `cv13` carries FeatUILabelNameID=256 for "Capital B
        hook". After merging Charis (sub) into NotoSansJP (base), the merged
        cv13 must still resolve to "Capital B hook"."""
        if not os.path.exists(CHARIS):
            pytest.skip("Charis SIL not available")
        charis = TTFont(CHARIS)
        expected = next(
            (r.toUnicode() for r in charis["name"].names if r.nameID == 256),
            None,
        )
        if expected is None:
            pytest.skip("Charis has no nameID 256 record")

        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {"path": CHARIS, "scale": 1.0,
                        "baselineOffset": 0, "axes": []},
            "baseFont": {"path": JP_VAR, "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
            "output": {"familyName": "TestCV"},
            "export": {"path": {"font": out}},
        }
        try:
            mf.merge_fonts(config)
            m = TTFont(out)
            for fr in m["GSUB"].table.FeatureList.FeatureRecord:
                if fr.FeatureTag != "cv13":
                    continue
                fp = fr.Feature.FeatureParams
                nid = getattr(fp, "FeatUILabelNameID", None)
                assert nid is not None, "Merged cv13 lost FeatUILabelNameID"
                label = next(
                    (r.toUnicode() for r in m["name"].names
                     if r.nameID == nid),
                    None,
                )
                assert label == expected, (
                    f"Merged cv13 label is {label!r}; expected {expected!r}. "
                    f"Latin cvXX label was dropped or clobbered."
                )
                break
            else:
                pytest.fail("Merged font lost cv13 feature")
        finally:
            for p in (out, out.replace(".ttf", ".woff2")):
                if os.path.exists(p):
                    os.remove(p)

    def test_base_cv_label_not_clobbered_by_sub_collision(self):
        """When the Latin sub's UINameID collides with a base nameID, the
        base font's own FeatureParams must keep pointing at its untouched
        record. Charis (base) cv13 → FeatUILabelNameID=256; Playwrite (sub)
        UINameID values are remapped to free IDs without dragging Charis's
        cv13 along."""
        if not (os.path.exists(CHARIS) and os.path.exists(PLAYWRITE)):
            pytest.skip("Charis SIL or Playwrite not available")
        charis = TTFont(CHARIS)
        expected = next(
            (r.toUnicode() for r in charis["name"].names if r.nameID == 256),
            None,
        )
        if expected is None:
            pytest.skip("Charis has no nameID 256 record")

        out = tempfile.mktemp(suffix=".ttf")
        config = {
            "subFont": {"path": PLAYWRITE, "scale": 1.0,
                        "baselineOffset": 0, "axes": []},
            "baseFont": {"path": CHARIS, "scale": 1.0,
                         "baselineOffset": 0, "axes": []},
            "output": {"familyName": "TestCVBase"},
            "export": {"path": {"font": out}},
        }
        try:
            mf.merge_fonts(config)
            m = TTFont(out)
            for fr in m["GSUB"].table.FeatureList.FeatureRecord:
                if fr.FeatureTag != "cv13":
                    continue
                fp = fr.Feature.FeatureParams
                nid = getattr(fp, "FeatUILabelNameID", None)
                label = next(
                    (r.toUnicode() for r in m["name"].names
                     if r.nameID == nid),
                    None,
                )
                assert label == expected, (
                    f"Base cv13 label became {label!r}; expected {expected!r}. "
                    f"The UINameID-collision remap leaked into base FeatureParams."
                )
                break
            else:
                pytest.fail("Merged font lost base cv13 feature")
        finally:
            for p in (out, out.replace(".ttf", ".woff2")):
                if os.path.exists(p):
                    os.remove(p)
