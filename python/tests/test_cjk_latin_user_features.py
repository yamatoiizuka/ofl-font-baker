"""Tests for Latin user features being reachable under CJK script LangSys.

Background:
    Apps such as Adobe Illustrator may shape mixed Latin/CJK runs through the
    `kana` or `hani` script's LangSys (rather than splitting into a separate
    Latin run that uses `latn`). When that happens, Latin user features such
    as `ss02` and `tnum` must remain reachable for the Latin glyphs in the run
    — otherwise toggling `ss02` / `tnum` in the app silently does nothing for
    text that contains any Japanese character.

    See ``docs/CJK_LATIN_USER_FEATURES_PLAN.md``.
"""

import pytest

from fontTools.ttLib import TTFont

from conftest import EN_VAR, JP_VAR

import merge_fonts as mf


def _coverage(*glyphs):
    from fontTools.ttLib.tables import otTables
    cov = otTables.Coverage()
    cov.glyphs = list(glyphs)
    return cov


def _make_single_subst(input_glyph, output_glyph):
    from fontTools.ttLib.tables import otTables
    st = otTables.SingleSubst()
    st.mapping = {input_glyph: output_glyph}
    lk = otTables.Lookup()
    lk.LookupType = 1
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _make_chain_context_format3(input_glyphs, subordinate_index=None,
                                backtrack=(), lookahead=(),
                                sequence_index=0):
    from fontTools.ttLib.tables import otTables

    st = otTables.ChainContextSubst()
    st.Format = 3
    st.BacktrackCoverage = [_coverage(g) for g in backtrack]
    st.BacktrackGlyphCount = len(st.BacktrackCoverage)
    st.InputCoverage = [_coverage(g) for g in input_glyphs]
    st.InputGlyphCount = len(st.InputCoverage)
    st.LookAheadCoverage = [_coverage(g) for g in lookahead]
    st.LookAheadGlyphCount = len(st.LookAheadCoverage)
    if subordinate_index is None:
        st.SubstLookupRecord = []
    else:
        rec = otTables.SubstLookupRecord()
        rec.SequenceIndex = sequence_index
        rec.LookupListIndex = subordinate_index
        st.SubstLookupRecord = [rec]
    st.SubstCount = len(st.SubstLookupRecord)

    lk = otTables.Lookup()
    lk.LookupType = 6
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _class_def(mapping):
    from fontTools.ttLib.tables import otTables
    cd = otTables.ClassDef()
    cd.classDefs = dict(mapping)
    return cd


def _make_sub_class_set(index, input_classes=()):
    from fontTools.ttLib.tables import otTables
    rule = otTables.SubClassRule()
    rule.GlyphCount = len(input_classes) + 1
    rule.Class = list(input_classes)
    rule.SubstLookupRecord = []
    rule.SubstCount = 0

    class_set = otTables.SubClassSet()
    class_set.SubClassRule = [rule]
    class_set.SubClassRuleCount = 1
    class_sets = [None] * (index + 1)
    class_sets[index] = class_set
    return class_sets


def _make_context_subst_format2(coverage_glyphs, class_defs,
                                class_set_index, input_classes=()):
    from fontTools.ttLib.tables import otTables
    st = otTables.ContextSubst()
    st.Format = 2
    st.Coverage = _coverage(*coverage_glyphs)
    st.ClassDef = _class_def(class_defs)
    st.SubClassSet = _make_sub_class_set(class_set_index, input_classes)
    st.SubClassSetCount = len(st.SubClassSet)

    lk = otTables.Lookup()
    lk.LookupType = 5
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _make_chain_sub_class_set(index, backtrack=(), input_classes=(),
                              lookahead=(), subordinate_index=None):
    from fontTools.ttLib.tables import otTables
    rule = otTables.ChainSubClassRule()
    rule.Backtrack = list(backtrack)
    rule.BacktrackGlyphCount = len(rule.Backtrack)
    rule.Input = list(input_classes)
    rule.InputGlyphCount = len(rule.Input) + 1
    rule.LookAhead = list(lookahead)
    rule.LookAheadGlyphCount = len(rule.LookAhead)
    if subordinate_index is None:
        rule.SubstLookupRecord = []
    else:
        rec = otTables.SubstLookupRecord()
        rec.SequenceIndex = 0
        rec.LookupListIndex = subordinate_index
        rule.SubstLookupRecord = [rec]
    rule.SubstCount = len(rule.SubstLookupRecord)

    class_set = otTables.ChainSubClassSet()
    class_set.ChainSubClassRule = [rule]
    class_set.ChainSubClassRuleCount = 1
    class_sets = [None] * (index + 1)
    class_sets[index] = class_set
    return class_sets


def _make_chain_context_format2(coverage_glyphs, input_class_defs,
                                class_set_index, backtrack_class_defs=None,
                                lookahead_class_defs=None, backtrack=(),
                                input_classes=(), lookahead=(),
                                subordinate_index=None):
    from fontTools.ttLib.tables import otTables
    st = otTables.ChainContextSubst()
    st.Format = 2
    st.Coverage = _coverage(*coverage_glyphs)
    st.BacktrackClassDef = _class_def(backtrack_class_defs or {})
    st.InputClassDef = _class_def(input_class_defs)
    st.LookAheadClassDef = _class_def(lookahead_class_defs or {})
    st.ChainSubClassSet = _make_chain_sub_class_set(
        class_set_index,
        backtrack=backtrack,
        input_classes=input_classes,
        lookahead=lookahead,
        subordinate_index=subordinate_index,
    )
    st.ChainSubClassSetCount = len(st.ChainSubClassSet)

    lk = otTables.Lookup()
    lk.LookupType = 6
    lk.LookupFlag = 0
    lk.SubTable = [st]
    lk.SubTableCount = 1
    return lk


def _make_feature_record(tag, lookup_indices):
    from fontTools.ttLib.tables import otTables
    feat = otTables.Feature()
    feat.FeatureParams = None
    feat.LookupListIndex = list(lookup_indices)
    feat.LookupCount = len(feat.LookupListIndex)
    rec = otTables.FeatureRecord()
    rec.FeatureTag = tag
    rec.Feature = feat
    return rec


def _make_langsys(feature_indices):
    from fontTools.ttLib.tables import otTables
    ls = otTables.LangSys()
    ls.LookupOrder = None
    ls.ReqFeatureIndex = 0xFFFF
    ls.FeatureIndex = list(feature_indices)
    ls.FeatureCount = len(ls.FeatureIndex)
    return ls


def _make_script_record(script_tag, default_feature_indices=(), named=None):
    from fontTools.ttLib.tables import otTables
    sr = otTables.ScriptRecord()
    sr.ScriptTag = script_tag
    sr.Script = otTables.Script()
    sr.Script.DefaultLangSys = _make_langsys(default_feature_indices)
    records = []
    for tag, feature_indices in (named or {}).items():
        lsr = otTables.LangSysRecord()
        lsr.LangSysTag = tag
        lsr.LangSys = _make_langsys(feature_indices)
        records.append(lsr)
    records.sort(key=lambda lsr: lsr.LangSysTag)
    sr.Script.LangSysRecord = records
    sr.Script.LangSysCount = len(records)
    return sr


def _make_gsub_table(lookups, feature_records, script_records):
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables import otTables

    table = newTable("GSUB")
    gsub = otTables.GSUB()
    gsub.Version = 0x00010000
    lookup_list = otTables.LookupList()
    lookup_list.Lookup = list(lookups)
    lookup_list.LookupCount = len(lookup_list.Lookup)
    gsub.LookupList = lookup_list
    feature_list = otTables.FeatureList()
    feature_list.FeatureRecord = list(feature_records)
    feature_list.FeatureCount = len(feature_list.FeatureRecord)
    gsub.FeatureList = feature_list
    script_list = otTables.ScriptList()
    script_list.ScriptRecord = list(script_records)
    script_list.ScriptCount = len(script_list.ScriptRecord)
    gsub.ScriptList = script_list
    table.table = gsub
    return table


def _merge_minimal_gsub(lat_lookups, lat_features, lat_scripts,
                        jp_lookups=None, jp_features=None, jp_scripts=None,
                        lat_glyph_names=None):
    jp_scripts = jp_scripts or [
        _make_script_record("kana"),
        _make_script_record("hani"),
    ]
    lat_table = _make_gsub_table(lat_lookups, lat_features, lat_scripts)
    jp_table = _make_gsub_table(
        jp_lookups or [], jp_features or [], jp_scripts)
    mf._merge_ot_table_v2(
        lat_table, jp_table, None, None, {}, "GSUB",
        lat_glyph_names or set(),
    )
    return jp_table.table


def _langsys(gsub, script_tag, lang_sys_tag=None):
    for sr in gsub.ScriptList.ScriptRecord:
        if sr.ScriptTag != script_tag:
            continue
        if lang_sys_tag is None:
            return sr.Script.DefaultLangSys
        for lsr in (sr.Script.LangSysRecord or []):
            if lsr.LangSysTag == lang_sys_tag:
                return lsr.LangSys
    return None


def _tags_for_langsys(gsub, langsys):
    return [gsub.FeatureList.FeatureRecord[i].FeatureTag
            for i in (langsys.FeatureIndex or [])]


def _feature_indices_for_tag(gsub, langsys, tag):
    return [
        i for i in (langsys.FeatureIndex or [])
        if gsub.FeatureList.FeatureRecord[i].FeatureTag == tag
    ]


# ---------------------------------------------------------------------------
# Shared HarfBuzz helper
# ---------------------------------------------------------------------------

def _shape(font_path, text, script, language, features=None):
    """Return the glyph-name sequence produced by HarfBuzz for *text*."""
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


@pytest.fixture(scope="module")
def merged_inter_path(tmp_path_factory):
    """Merge Inter (Latin) onto Noto Sans JP (TTF) once for the whole module."""
    out = tmp_path_factory.mktemp("cjk_latin_features") / "merged.ttf"
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
        "output": {"familyName": "TestCjkLatinFeatures"},
        "export": {"path": {"font": str(out)}},
    }
    mf.merge_fonts(config)
    return str(out)


# Note: a behavioural CID-base promotion test (Latin features actually
# firing on a CID-keyed base such as NotoSansCJKjp) is intentionally
# missing. The Inter CFF subset shipped under `python/tests/fonts` has
# its GSUB stripped, so it has no allowlisted features to promote;
# pairing the full Inter CFF or Inter Variable with the CID NotoSansCJKjp
# subset triggers a fontTools CID-compile error unrelated to this fix.
# The TTF base path (`merged_inter_path`) covers the engine
# behaviourally; the CID code path is exercised structurally by
# `test_glyph_data.py::TestCidBaseDigitNoLeak` and the related strip
# tests, neither of which depends on this promotion logic.


# ---------------------------------------------------------------------------
# Behavioral tests (HarfBuzz shaping)
# ---------------------------------------------------------------------------

class TestLatinUserFeaturesUnderCjkScripts:
    """Latin user features (ss02, tnum, ...) must still fire for Latin glyphs
    when the run is shaped under a CJK script's LangSys."""

    SAMPLE = "Gla369"

    def test_ss02_under_latn_baseline(self, merged_inter_path):
        """Sanity: ss02=1 changes the lowercase ``l`` under ``latn``."""
        plain = _shape(merged_inter_path, self.SAMPLE, "latn", "en")
        with_ss02 = _shape(merged_inter_path, self.SAMPLE,
                           "latn", "en", {"ss02": True})
        assert plain != with_ss02, (
            f"latn ss02=1 didn't change shaping (plain={plain})"
        )

    @pytest.mark.parametrize("script,language", [("kana", "ja"), ("hani", "ja")])
    def test_ss02_under_cjk_matches_latn(self, merged_inter_path,
                                         script, language):
        """``ss02=1`` shaped under ``kana`` / ``hani`` must produce the same
        Latin alternates that ``latn`` produces. Pre-fix the lowercase ``l``
        stays as ``l`` because the CJK LangSys never references Inter's
        ``ss02`` feature record."""
        latn = _shape(merged_inter_path, self.SAMPLE, "latn", "en",
                      {"ss02": True})
        cjk = _shape(merged_inter_path, self.SAMPLE, script, language,
                     {"ss02": True})
        assert cjk == latn, (
            f"{script}/{language} ss02=1 differs from latn/en: "
            f"{script}={cjk} vs latn={latn}"
        )

    DIGITS = "012345"

    @pytest.mark.parametrize("script,language", [("kana", "ja"), ("hani", "ja")])
    def test_tnum_under_cjk_matches_latn(self, merged_inter_path,
                                         script, language):
        """``tnum=1`` under ``kana`` / ``hani`` must reach Inter's tabular
        figure glyphs the same way it does under ``latn``."""
        latn = _shape(merged_inter_path, self.DIGITS, "latn", "en",
                      {"tnum": True})
        cjk = _shape(merged_inter_path, self.DIGITS, script, language,
                     {"tnum": True})
        assert cjk == latn, (
            f"{script}/{language} tnum=1 differs from latn/en: "
            f"{script}={cjk} vs latn={latn}"
        )

    @pytest.mark.parametrize("script,language", [("kana", "ja"), ("hani", "ja")])
    def test_tnum_under_cjk_changes_default(self, merged_inter_path,
                                            script, language):
        """Sanity: ``tnum=1`` under CJK scripts must not silently no-op."""
        default = _shape(merged_inter_path, self.DIGITS, script, language)
        with_tnum = _shape(merged_inter_path, self.DIGITS, script, language,
                           {"tnum": True})
        assert default != with_tnum, (
            f"{script}/{language} tnum=1 silently no-op'd "
            f"(default={default})"
        )

    @pytest.mark.parametrize("script,language", [("kana", "ja"), ("hani", "ja")])
    def test_default_calt_under_cjk_matches_latn_prefix(
            self, merged_inter_path, script, language):
        """Default-on Inter ``calt`` must remain reachable for Latin-owned
        glyphs inside a Japanese run shaped through a CJK script."""
        latin_text = "(15:00)"
        mixed_text = f"{latin_text} 日本語"
        latn = _shape(merged_inter_path, latin_text, "latn", "en")
        latn_without_calt = _shape(
            merged_inter_path, latin_text, "latn", "en", {"calt": False})
        assert latn != latn_without_calt, (
            "fixture sanity: Inter calt should affect '(15:00)' under latn"
        )

        cjk = _shape(merged_inter_path, mixed_text, script, language)
        assert cjk[:len(latn)] == latn, (
            f"{script}/{language} calt differs from latn/en for the Latin "
            f"prefix: {script}={cjk[:len(latn)]} vs latn={latn}"
        )


class TestCjkScriptShapingUnchangedForJapanese:
    """Plain Japanese text shaped under CJK scripts must not be affected by
    enabling allowlisted Latin user features. The Latin lookups only target
    Latin glyph names, so they should never match a Japanese run.
    """

    JP_TEXT = "あいうえお北海道"

    @pytest.mark.parametrize("features", [
        None,
        {"ss02": True},
        {"tnum": True},
        {"ss01": True, "ss02": True, "tnum": True, "zero": True},
    ])
    @pytest.mark.parametrize("script,language", [("kana", "ja"), ("hani", "ja")])
    def test_japanese_text_unchanged(self, merged_inter_path,
                                     script, language, features):
        baseline = _shape(merged_inter_path, self.JP_TEXT, script, language)
        toggled = _shape(merged_inter_path, self.JP_TEXT, script, language,
                         features)
        assert baseline == toggled, (
            f"plain Japanese under {script}/{language} changed when "
            f"toggling {features}: baseline={baseline} toggled={toggled}"
        )


class TestExistingCjkFeaturesStillReachable:
    """Existing CJK features (e.g. ``fwid`` / ``hwid``) the JP base font ships
    under ``kana`` / ``hani`` must remain reachable from those scripts after
    the allowlist fix.
    """

    @pytest.mark.parametrize("script,language", [("kana", "ja"), ("hani", "ja")])
    def test_fwid_feature_present_in_cjk_langsys(self, merged_inter_path,
                                                 script, language):
        merged = TTFont(merged_inter_path)
        gsub = merged["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != script or not sr.Script.DefaultLangSys:
                continue
            tags = {feat_records[i].FeatureTag
                    for i in (sr.Script.DefaultLangSys.FeatureIndex or [])}
            assert "fwid" in tags or "hwid" in tags, (
                f"{script} DefaultLangSys lost JP-side fwid/hwid: tags={tags}"
            )
            return
        pytest.fail(f"merged font has no {script} script in GSUB")


# ---------------------------------------------------------------------------
# Structural tests (FeatureList / LangSys shape)
# ---------------------------------------------------------------------------

class TestCjkLangSysIncludesAllowlistedLatinFeatures:
    """``kana`` / ``hani`` LangSys records must reference allowlisted Latin
    user features when the Latin font defines them."""

    @staticmethod
    def _cjk_default_langsys_tags(font, script_tag):
        gsub = font["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != script_tag or not sr.Script.DefaultLangSys:
                continue
            return {feat_records[i].FeatureTag
                    for i in (sr.Script.DefaultLangSys.FeatureIndex or [])}
        pytest.fail(f"merged font has no {script_tag} script in GSUB")

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_kana_hani_include_inter_user_features(self, merged_inter_path,
                                                   script):
        """Inter ships ``ss01..ss08``, ``tnum``, ``zero``, ``frac``, ``case``,
        ``calt``, ``locl``, etc.; the CJK LangSys must end up with the
        allowlisted *user* features (ss01..ss08, tnum, zero, frac)."""
        tags = self._cjk_default_langsys_tags(TTFont(merged_inter_path), script)
        for expected in ("ss01", "ss02", "tnum", "zero", "frac"):
            assert expected in tags, (
                f"{script} DefaultLangSys missing allowlisted Latin feature "
                f"'{expected}' (tags={sorted(tags)})"
            )


class TestCjkLangSysIncludesStrictSafeCalt:
    """Strictly sub-font-confined Latin ``calt`` may be promoted to CJK
    LangSys records even though it is not a user-feature allowlist tag."""

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_inter_calt_promoted_under_cjk_default(self, merged_inter_path,
                                                  script):
        merged = TTFont(merged_inter_path)
        gsub = merged["GSUB"].table
        ls = _langsys(gsub, script)
        assert ls is not None, f"merged font has no {script} DefaultLangSys"
        tags = set(_tags_for_langsys(gsub, ls))
        assert "calt" in tags, (
            f"{script} DefaultLangSys missing strict Latin calt promotion "
            f"(tags={sorted(tags)})"
        )

    def test_calt_stays_out_of_user_allowlist(self):
        assert "calt" not in mf.CJK_LATIN_USER_FEATURE_ALLOWLIST


class TestCjkLangSysExcludesAvoidedTags:
    """The fix must not blindly copy every Latin feature into CJK LangSys
    records. Defaults / context-sensitive features other than strictly safe
    ``calt`` must not become reachable from CJK scripts unless they were
    already on the JP side.
    """

    # Full avoid list from docs/CJK_LATIN_USER_FEATURES_PLAN.md. Tags the
    # JP base already carries are exempted by the per-tag check below
    # (preserving JP-owned `fwid` / `vert` is correct); the test only
    # flags tags newly inherited from the Latin side.
    AVOIDED_TAGS = (
        "case", "ccmp", "liga", "dlig",
        "aalt", "locl", "fwid", "hwid", "vert", "vrt2",
    )

    @staticmethod
    def _baseline_jp_tags(font_path, script_tag):
        """Tags the *base* font itself ships under ``script_tag`` — the merge
        should not strip these, but the avoided-tags assertion has to ignore
        them so we only catch *newly introduced* avoided tags from Latin."""
        font = TTFont(font_path)
        gsub = font["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != script_tag or not sr.Script.DefaultLangSys:
                continue
            return {feat_records[i].FeatureTag
                    for i in (sr.Script.DefaultLangSys.FeatureIndex or [])}
        return set()

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_no_new_avoided_tags_under_cjk(self, merged_inter_path, script):
        merged = TTFont(merged_inter_path)
        gsub = merged["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != script or not sr.Script.DefaultLangSys:
                continue
            merged_tags = {feat_records[i].FeatureTag
                           for i in (sr.Script.DefaultLangSys.FeatureIndex or [])}
            jp_tags = self._baseline_jp_tags(JP_VAR, script)
            for tag in self.AVOIDED_TAGS:
                if tag in jp_tags:
                    continue  # JP already had it; preserving it is correct.
                assert tag not in merged_tags, (
                    f"{script} DefaultLangSys gained avoided Latin tag "
                    f"'{tag}' (full tags={sorted(merged_tags)})"
                )
            return
        pytest.fail(f"merged font has no {script} script in GSUB")


class TestCjkPromotionRespectsLatinDefaultLangSys:
    """A Latin user feature must only become reachable from CJK scripts when
    the *Latin font* itself exposes it in its `latn` / `DFLT` DefaultLangSys.
    Orphan features and named-LangSys-only ones (e.g. `latn/TUR ` Turkish
    `tnum`) must not be promoted to a cross-script default."""

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_only_latn_default_features_promoted(self, merged_inter_path,
                                                 script):
        merged = TTFont(merged_inter_path)
        gsub = merged["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        cjk_tags = set()
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag == script and sr.Script.DefaultLangSys:
                cjk_tags = {feat_records[i].FeatureTag
                            for i in (sr.Script.DefaultLangSys.FeatureIndex or [])}
                break
        else:
            pytest.fail(f"merged font has no {script} script in GSUB")

        # Inter's pre-merge `latn` / `DFLT` DefaultLangSys feature tag set.
        inter = TTFont(EN_VAR)
        inter_gsub = inter["GSUB"].table
        inter_feat_records = inter_gsub.FeatureList.FeatureRecord
        latn_default_tags = set()
        if inter_gsub.ScriptList:
            for sr in inter_gsub.ScriptList.ScriptRecord:
                if sr.ScriptTag not in ("latn", "DFLT"):
                    continue
                ds = sr.Script.DefaultLangSys
                if ds:
                    latn_default_tags.update(
                        inter_feat_records[i].FeatureTag
                        for i in (ds.FeatureIndex or [])
                    )

        # JP base tags (we only care about *new* tags promoted from Latin).
        jp_base = TTFont(JP_VAR)
        jp_gsub = jp_base["GSUB"].table
        jp_feat_records = jp_gsub.FeatureList.FeatureRecord
        jp_tags = set()
        for sr in jp_gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag == script and sr.Script.DefaultLangSys:
                jp_tags = {jp_feat_records[i].FeatureTag
                           for i in (sr.Script.DefaultLangSys.FeatureIndex or [])}
                break

        from merge_fonts import CJK_LATIN_USER_FEATURE_ALLOWLIST
        promoted = (cjk_tags - jp_tags) & CJK_LATIN_USER_FEATURE_ALLOWLIST
        assert promoted, (
            f"sanity: at least one allowlisted Latin tag should be promoted "
            f"to {script} (got cjk_tags={sorted(cjk_tags)})"
        )
        leaked = promoted - latn_default_tags
        assert not leaked, (
            f"{script} DefaultLangSys promoted tags {sorted(leaked)} that "
            f"the Latin font doesn't expose under latn/DFLT default "
            f"(latn_default_tags={sorted(latn_default_tags)})"
        )


class TestCjkPromotedLookupsTouchOnlyLatinGlyphs:
    """Each promoted Latin user feature's lookups must only touch glyphs the
    Latin font owns. Otherwise a `tnum=1` toggle could rewrite Japanese
    glyphs the user never asked to change."""

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_promoted_feature_lookups_are_latin_only(self, merged_inter_path,
                                                     script):
        merged = TTFont(merged_inter_path)
        gsub = merged["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        lookup_list = gsub.LookupList.Lookup

        cjk_default = None
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag == script and sr.Script.DefaultLangSys:
                cjk_default = sr.Script.DefaultLangSys
                break
        assert cjk_default is not None, f"no {script} DefaultLangSys"

        # Identify Latin-promoted tags: allowlisted, in CJK LangSys, but NOT
        # in the JP base font's same LangSys.
        from merge_fonts import (
            CJK_LATIN_USER_FEATURE_ALLOWLIST, _collect_lookup_glyphs,
        )
        jp_base = TTFont(JP_VAR)
        jp_gsub = jp_base["GSUB"].table
        jp_feat_records = jp_gsub.FeatureList.FeatureRecord
        jp_tags = set()
        for sr in jp_gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag == script and sr.Script.DefaultLangSys:
                jp_tags = {jp_feat_records[i].FeatureTag
                           for i in (sr.Script.DefaultLangSys.FeatureIndex or [])}
                break

        # Conservative Latin-glyph-name superset: Inter's pre-merge glyphs
        # plus the merged font's `.lat` / `.subN` rename suffixes that the
        # merge engine introduces on collision.
        inter_glyphs = set(TTFont(EN_VAR).getGlyphOrder())
        merged_glyph_set = set(merged.getGlyphOrder())
        lat_owned = {
            g for g in merged_glyph_set
            if g in inter_glyphs
            or g.endswith(".lat")
            or g.rsplit(".", 1)[0] in inter_glyphs
        }

        offending = []
        promoted_count = 0
        for fi in (cjk_default.FeatureIndex or []):
            tag = feat_records[fi].FeatureTag
            if tag in jp_tags:
                continue
            if tag not in CJK_LATIN_USER_FEATURE_ALLOWLIST:
                continue
            promoted_count += 1
            for li in (feat_records[fi].Feature.LookupListIndex or []):
                glyphs = _collect_lookup_glyphs(lookup_list[li])
                bad = glyphs - lat_owned
                if bad:
                    offending.append((tag, li, sorted(bad)[:5]))

        assert promoted_count > 0, (
            f"sanity: expected at least one promoted Latin feature in {script}"
        )
        assert not offending, (
            f"{script} promoted Latin features touch non-Latin glyphs: "
            f"{offending[:5]}"
        )


class TestCjkNamedLangSysPromotion:
    """CJK named LangSys records (e.g. `kana/JAN`) should also expose the
    allowlisted Latin user features. Pre-fix the promotion only ran on
    the DefaultLangSys, so an Illustrator run that selected a CJK named
    LangSys (per Issue #12 fallback semantics) lost `ss02` / `tnum`."""

    @staticmethod
    def _named_langsys(font, script_tag, lang_sys_tag):
        gsub = font["GSUB"].table
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != script_tag:
                continue
            for lsr in (sr.Script.LangSysRecord or []):
                if lsr.LangSysTag == lang_sys_tag:
                    return lsr.LangSys
        return None

    @staticmethod
    def _tags(gsub, lang_sys):
        feat_records = gsub.FeatureList.FeatureRecord
        return {feat_records[i].FeatureTag
                for i in (lang_sys.FeatureIndex or [])}

    @pytest.mark.parametrize("script,lang_sys_tag", [
        ("kana", "JAN "),  # Noto Sans JP defines this for Japanese
        ("hani", "JAN "),
    ])
    def test_named_cjk_langsys_includes_allowlisted_latin_features(
            self, merged_inter_path, script, lang_sys_tag):
        merged = TTFont(merged_inter_path)
        ls = self._named_langsys(merged, script, lang_sys_tag)
        if ls is None:
            pytest.skip(f"merged font has no {script}/{lang_sys_tag.strip()} "
                        "named LangSys")
        tags = self._tags(merged["GSUB"].table, ls)
        for expected in ("ss01", "ss02", "tnum"):
            assert expected in tags, (
                f"{script}/{lang_sys_tag.strip()} missing allowlisted "
                f"Latin feature '{expected}' (tags={sorted(tags)})"
            )


class TestLatinOnlyNamedLangSysPropagatesToCjk:
    """A named LangSys that only the Latin font defines (and that exposes
    a unique allowlist tag missing from `latn/dflt`) must still result in
    a matching CJK named LangSys carrying the promoted feature.

    None of the bundled Latin fixtures have such a LangSys (Inter has
    only `latn/dflt`, TikTok Sans's named LangSys are subsets of its
    default), so the test mutates Inter in memory: it carves a fake
    `latn/JPN ` LangSys whose only feature is `tnum`, removes `tnum`
    from `latn/dflt`, writes the modified font to disk, runs the merge,
    and asserts that `kana/JPN ` and `hani/JPN ` exist in the merged
    font with `tnum` reachable.
    """

    @staticmethod
    def _patch_latin_with_named_only_tnum(src_path, dst_path):
        """Copy *src_path* and rewrite its GSUB so `tnum` lives only
        under a new `latn/JPN ` LangSys (removing it from every other
        DefaultLangSys, including `DFLT`, so the candidate-collection
        scope test is meaningful)."""
        font = TTFont(src_path)
        gsub = font["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        tnum_old_idx = None
        for i, fr in enumerate(feat_records):
            if fr.FeatureTag == "tnum":
                tnum_old_idx = i
                break
        if tnum_old_idx is None:
            pytest.skip(f"{src_path} has no tnum feature to relocate")

        # Strip tnum from every script's DefaultLangSys (latn, DFLT, ...).
        for sr in gsub.ScriptList.ScriptRecord:
            ds = sr.Script.DefaultLangSys
            if ds and tnum_old_idx in (ds.FeatureIndex or []):
                ds.FeatureIndex = [i for i in ds.FeatureIndex
                                   if i != tnum_old_idx]
                ds.FeatureCount = len(ds.FeatureIndex)

        latn_sr = None
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag == "latn":
                latn_sr = sr
                break
        assert latn_sr is not None, "fixture must define latn"

        # Build a fresh `latn/JPN ` named LangSys whose only FeatureIndex
        # is tnum.
        from fontTools.ttLib.tables import otTables
        new_ls = otTables.LangSys()
        new_ls.LookupOrder = None
        new_ls.ReqFeatureIndex = 0xFFFF
        new_ls.FeatureIndex = [tnum_old_idx]
        new_ls.FeatureCount = 1
        new_lsr = otTables.LangSysRecord()
        new_lsr.LangSysTag = "JPN "
        new_lsr.LangSys = new_ls

        existing = list(latn_sr.Script.LangSysRecord or [])
        existing.append(new_lsr)
        # LangSysRecords must remain sorted by tag for OpenType compliance.
        existing.sort(key=lambda lsr: lsr.LangSysTag)
        latn_sr.Script.LangSysRecord = existing
        latn_sr.Script.LangSysCount = len(existing)

        font.save(dst_path)

    @pytest.fixture(scope="class")
    def merged_latin_only_jpn_path(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp("latin_only_jpn")
        patched_inter = str(tmp / "InterPatched.ttf")
        self._patch_latin_with_named_only_tnum(EN_VAR, patched_inter)
        out = tmp / "merged.ttf"
        config = {
            "subFont": {
                "path": patched_inter,
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
            "output": {"familyName": "TestLatinOnlyJPN"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_cjk_jpn_named_langsys_created_with_tnum(
            self, merged_latin_only_jpn_path, script):
        merged = TTFont(merged_latin_only_jpn_path)
        gsub = merged["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != script:
                continue
            for lsr in (sr.Script.LangSysRecord or []):
                if lsr.LangSysTag != "JPN ":
                    continue
                tags = {feat_records[i].FeatureTag
                        for i in (lsr.LangSys.FeatureIndex or [])}
                assert "tnum" in tags, (
                    f"{script}/JPN missing promoted Latin tnum "
                    f"(tags={sorted(tags)})"
                )
                return
            pytest.fail(
                f"{script} has no JPN named LangSys (Latin-only named "
                f"LangSys did not propagate to CJK side)"
            )
        pytest.fail(f"merged font has no {script} script in GSUB")


class TestDuplicateAllowlistTagMergesLatinLookups:
    """When the JP base already exposes an allowlist tag (e.g. `tnum`)
    in a CJK LangSys, the Latin-side feature record must not be silently
    dropped. Instead the Latin lookups have to merge into the existing
    JP feature record so the user's `tnum=1` toggle reaches Latin
    glyphs too.

    Noto Sans JP doesn't ship `tnum` under `kana`/`hani`, so the test
    patches its GSUB to add a no-op `tnum` referencing a JP-only lookup
    before merging."""

    @staticmethod
    def _patch_jp_with_tnum_in_kana(src_path, dst_path):
        font = TTFont(src_path)
        gsub = font["GSUB"].table

        # Find an existing JP-only single-substitution lookup we can
        # alias as the JP-side tnum lookup (so its inputs are JP glyphs
        # and won't accidentally rewrite Latin digits).
        from fontTools.ttLib.tables import otTables
        existing_lookup_count = len(gsub.LookupList.Lookup)
        # Build a tiny JP-only lookup: maps a JP glyph to itself (no-op
        # in effect, but real glyph references so the merge engine
        # treats it as "japanese"-classified, not "latin").
        gs = font.getGlyphOrder()
        jp_glyph = next(g for g in gs if g.startswith("uni3") or g.startswith("cid"))
        st = otTables.SingleSubst()
        st.mapping = {jp_glyph: jp_glyph}
        new_lookup = otTables.Lookup()
        new_lookup.LookupType = 1
        new_lookup.LookupFlag = 0
        new_lookup.SubTable = [st]
        new_lookup.SubTableCount = 1
        gsub.LookupList.Lookup.append(new_lookup)
        gsub.LookupList.LookupCount = len(gsub.LookupList.Lookup)
        new_lookup_idx = existing_lookup_count

        # Build a JP-side tnum feature record pointing at it.
        feat = otTables.Feature()
        feat.FeatureParams = None
        feat.LookupListIndex = [new_lookup_idx]
        feat.LookupCount = 1
        rec = otTables.FeatureRecord()
        rec.FeatureTag = "tnum"
        rec.Feature = feat
        new_feat_idx = len(gsub.FeatureList.FeatureRecord)
        gsub.FeatureList.FeatureRecord.append(rec)
        gsub.FeatureList.FeatureCount = len(gsub.FeatureList.FeatureRecord)

        # Wire it into kana / hani DefaultLangSys *and* every named
        # LangSys those scripts ship — HarfBuzz routes Japanese text
        # through `kana/JAN` rather than `kana/dflt`, so without patching
        # the named LangSys too the test would silently exercise a
        # different code path.
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag not in ("kana", "hani"):
                continue
            for ls in [sr.Script.DefaultLangSys] + [
                    lsr.LangSys for lsr in (sr.Script.LangSysRecord or [])]:
                if ls is None:
                    continue
                ls.FeatureIndex = list(ls.FeatureIndex or []) + [new_feat_idx]
                ls.FeatureCount = len(ls.FeatureIndex)

        font.save(dst_path)

    @pytest.fixture(scope="class")
    def merged_jp_tnum_path(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp("jp_tnum_collision")
        patched_jp = str(tmp / "JpPatched.ttf")
        self._patch_jp_with_tnum_in_kana(JP_VAR, patched_jp)
        out = tmp / "merged.ttf"
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
                "path": patched_jp,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "TestJpTnumCollision"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    @pytest.mark.parametrize("script,language", [("kana", "ja"), ("hani", "ja")])
    def test_collision_tag_still_promotes_latin_lookups(
            self, merged_jp_tnum_path, script, language):
        """When JP already exposes `tnum` under the CJK LangSys, the
        Latin-side `tnum` lookups must still reach Latin digits. Without
        the merge, `kana tnum=1` would silently no-op on `012`."""
        DIGITS = "012345"
        latn = _shape(merged_jp_tnum_path, DIGITS, "latn", "en",
                      {"tnum": True})
        cjk = _shape(merged_jp_tnum_path, DIGITS, script, language,
                     {"tnum": True})
        assert cjk == latn, (
            f"{script}/{language} tnum=1 didn't reach Latin tabular figures "
            f"despite JP-side tnum collision: {script}={cjk} vs latn={latn}"
        )


class TestNamedOnlyLatinLookupDoesNotLeakToCjkDefault:
    """When the JP base exposes an allowlist tag in its CJK
    DefaultLangSys *and* the Latin font exposes the same tag only
    through a named LangSys (e.g. `latn/JPN`), the merged
    `kana/dflt` must keep its tnum strictly JP-only — only `kana/JPN`
    should fire the Latin named-only lookup. A naive in-place mutation
    of the shared JP FeatureRecord would leak the locale-specific
    Latin lookup into every CJK default run."""

    @staticmethod
    def _patched_paths(tmp_path):
        """Return (latin_path, jp_path) with:
            - Latin `latn/dflt` and `DFLT/dflt` have tnum stripped;
              tnum lives only under `latn/JPN`.
            - JP `kana/dflt` and `hani/dflt` (and their JAN named LangSys)
              gain a no-op JP-only `tnum` referencing a JP-glyph
              SingleSubst.
        """
        from fontTools.ttLib.tables import otTables

        # --- Latin patch: tnum becomes named-only (latn/JPN ) ---
        lat = TTFont(EN_VAR)
        gsub = lat["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        tnum_old_idx = next(i for i, fr in enumerate(feat_records)
                            if fr.FeatureTag == "tnum")
        for sr in gsub.ScriptList.ScriptRecord:
            ds = sr.Script.DefaultLangSys
            if ds and tnum_old_idx in (ds.FeatureIndex or []):
                ds.FeatureIndex = [i for i in ds.FeatureIndex
                                   if i != tnum_old_idx]
                ds.FeatureCount = len(ds.FeatureIndex)
        latn_sr = next(sr for sr in gsub.ScriptList.ScriptRecord
                       if sr.ScriptTag == "latn")
        new_ls = otTables.LangSys()
        new_ls.LookupOrder = None
        new_ls.ReqFeatureIndex = 0xFFFF
        new_ls.FeatureIndex = [tnum_old_idx]
        new_ls.FeatureCount = 1
        new_lsr = otTables.LangSysRecord()
        new_lsr.LangSysTag = "JPN "
        new_lsr.LangSys = new_ls
        existing = list(latn_sr.Script.LangSysRecord or []) + [new_lsr]
        existing.sort(key=lambda l: l.LangSysTag)
        latn_sr.Script.LangSysRecord = existing
        latn_sr.Script.LangSysCount = len(existing)
        latin_path = str(tmp_path / "InterPatched.ttf")
        lat.save(latin_path)

        # --- JP patch: kana/hani gain a no-op tnum (collision tag) ---
        jp = TTFont(JP_VAR)
        gsub_jp = jp["GSUB"].table
        gs = jp.getGlyphOrder()
        jp_glyph = next(g for g in gs if g.startswith("uni3"))
        st = otTables.SingleSubst()
        st.mapping = {jp_glyph: jp_glyph}
        new_lookup = otTables.Lookup()
        new_lookup.LookupType = 1
        new_lookup.LookupFlag = 0
        new_lookup.SubTable = [st]
        new_lookup.SubTableCount = 1
        gsub_jp.LookupList.Lookup.append(new_lookup)
        gsub_jp.LookupList.LookupCount = len(gsub_jp.LookupList.Lookup)
        new_lookup_idx = len(gsub_jp.LookupList.Lookup) - 1
        feat = otTables.Feature()
        feat.FeatureParams = None
        feat.LookupListIndex = [new_lookup_idx]
        feat.LookupCount = 1
        rec = otTables.FeatureRecord()
        rec.FeatureTag = "tnum"
        rec.Feature = feat
        new_feat_idx = len(gsub_jp.FeatureList.FeatureRecord)
        gsub_jp.FeatureList.FeatureRecord.append(rec)
        gsub_jp.FeatureList.FeatureCount = len(gsub_jp.FeatureList.FeatureRecord)
        for sr in gsub_jp.ScriptList.ScriptRecord:
            if sr.ScriptTag not in ("kana", "hani"):
                continue
            for ls in [sr.Script.DefaultLangSys] + [
                    lsr.LangSys for lsr in (sr.Script.LangSysRecord or [])]:
                if ls is None:
                    continue
                ls.FeatureIndex = list(ls.FeatureIndex or []) + [new_feat_idx]
                ls.FeatureCount = len(ls.FeatureIndex)
        jp_path = str(tmp_path / "JpPatched.ttf")
        jp.save(jp_path)

        return latin_path, jp_path

    @pytest.fixture(scope="class")
    def merged_path(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp("named_only_leak")
        latin_path, jp_path = self._patched_paths(tmp)
        out = tmp / "merged.ttf"
        config = {
            "subFont": {
                "path": latin_path,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [],
            },
            "baseFont": {
                "path": jp_path,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "TestNamedOnlyLeak"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    @staticmethod
    def _tnum_lookup_indices(font, script, lang_sys_tag):
        gsub = font["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != script:
                continue
            if lang_sys_tag is None:
                ls = sr.Script.DefaultLangSys
            else:
                ls = None
                for lsr in (sr.Script.LangSysRecord or []):
                    if lsr.LangSysTag == lang_sys_tag:
                        ls = lsr.LangSys
                        break
            if ls is None:
                return None
            for fi in (ls.FeatureIndex or []):
                if feat_records[fi].FeatureTag == "tnum":
                    return tuple(feat_records[fi].Feature.LookupListIndex or [])
        return None

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_default_tnum_does_not_inherit_named_only_latin_lookup(
            self, merged_path, script):
        merged = TTFont(merged_path)
        default_lookups = self._tnum_lookup_indices(merged, script, None)
        jpn_lookups = self._tnum_lookup_indices(merged, script, "JPN ")
        assert default_lookups is not None, (
            f"{script} DefaultLangSys has no tnum feature record"
        )
        assert jpn_lookups is not None, (
            f"{script}/JPN named LangSys has no tnum feature record"
        )
        leaked = set(jpn_lookups) - set(default_lookups)
        assert leaked, (
            f"{script}/JPN tnum should expose Latin's named-only lookup "
            f"that {script}/dflt does not (default={default_lookups}, "
            f"JPN={jpn_lookups})"
        )
        # The strict invariant: kana/dflt's tnum lookup set must NOT
        # include any of the Latin JPN-only lookup indices.
        latin_only = set(jpn_lookups) - set(default_lookups)
        assert not (set(default_lookups) & latin_only), (
            f"{script}/dflt tnum leaked Latin named-only lookups: "
            f"default={default_lookups}, latin-only={latin_only}"
        )


class TestStrictCaltSafetyHelper:
    """The strict default-on promotion helper must check the whole GSUB
    lookup closure, not just input coverage."""

    def test_accepts_context_and_output_inside_sub_font(self):
        sub = _make_single_subst("colon", "colon.time")
        chain = _make_chain_context_format3(
            ["one", "colon", "zero"], subordinate_index=0, sequence_index=1)
        feat_rec = _make_feature_record("calt", [1])
        sub_owned = {"one", "colon", "colon.time", "zero"}
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [sub, chain], sub_owned) is True

    def test_rejects_output_outside_sub_font(self):
        lookup = _make_single_subst("A", "uni65E5")
        feat_rec = _make_feature_record("calt", [0])
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [lookup], {"A"}) is False

    def test_rejects_lookahead_outside_sub_font(self):
        lookup = _make_chain_context_format3(["A"], lookahead=["uni65E5"])
        feat_rec = _make_feature_record("calt", [0])
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [lookup], {"A"}) is False

    def test_rejects_unknown_lookup_shape(self):
        from fontTools.ttLib.tables import otTables
        st = otTables.ContextSubst()
        st.Format = 99
        lookup = otTables.Lookup()
        lookup.LookupType = 5
        lookup.LookupFlag = 0
        lookup.SubTable = [st]
        lookup.SubTableCount = 1
        feat_rec = _make_feature_record("calt", [0])
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [lookup], set()) is False

    def test_rejects_empty_feature(self):
        from fontTools.ttLib.tables import otTables
        lookup = otTables.Lookup()
        lookup.LookupType = 1
        lookup.LookupFlag = 0
        lookup.SubTable = []
        lookup.SubTableCount = 0
        feat_rec = _make_feature_record("calt", [0])
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [lookup], set()) is False

    def test_rejects_context_format2_first_input_class_zero(self):
        lookup = _make_context_subst_format2(
            coverage_glyphs=["A"],
            class_defs={"A": 1},
            class_set_index=0,
        )
        feat_rec = _make_feature_record("calt", [0])
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [lookup], {"A", "A.alt"}) is False

    def test_rejects_context_format2_input_class_zero(self):
        lookup = _make_context_subst_format2(
            coverage_glyphs=["A"],
            class_defs={"A": 1, "colon": 2},
            class_set_index=1,
            input_classes=[0],
        )
        feat_rec = _make_feature_record("calt", [0])
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [lookup], {"A", "colon", "A.alt"}) is False

    def test_rejects_chain_context_format2_first_input_class_zero(self):
        lookup = _make_chain_context_format2(
            coverage_glyphs=["A"],
            input_class_defs={"A": 1},
            class_set_index=0,
        )
        feat_rec = _make_feature_record("calt", [0])
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [lookup], {"A", "A.alt"}) is False

    @pytest.mark.parametrize("seq_name,seq_kwargs", [
        ("backtrack", {"backtrack": [0], "backtrack_class_defs": {"colon": 2}}),
        ("input", {"input_classes": [0]}),
        ("lookahead", {"lookahead": [0], "lookahead_class_defs": {"colon": 2}}),
    ])
    def test_rejects_chain_context_format2_class_zero_sequence(
            self, seq_name, seq_kwargs):
        lookup = _make_chain_context_format2(
            coverage_glyphs=["A"],
            input_class_defs={"A": 1, "colon": 2},
            class_set_index=1,
            **seq_kwargs,
        )
        feat_rec = _make_feature_record("calt", [0])
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [lookup], {"A", "colon", "A.alt"}) is False

    def test_accepts_chain_context_format2_nonzero_sub_owned_classes(self):
        sub = _make_single_subst("A", "A.alt")
        chain = _make_chain_context_format2(
            coverage_glyphs=["A"],
            input_class_defs={"A": 1},
            class_set_index=1,
            lookahead_class_defs={"colon": 2},
            lookahead=[2],
            subordinate_index=0,
        )
        feat_rec = _make_feature_record("calt", [1])
        assert mf._sub_feature_strictly_safe_for_cjk_default_promotion(
            feat_rec, [sub, chain], {"A", "A.alt", "colon"}) is True


class TestStrictCaltPromotionStructure:
    """Synthetic GSUB tables exercise promotion scoping without the cost of
    compiling patched real fonts for every unsafe case."""

    @staticmethod
    def _latn_default_gsub_for_calt(lookup, lat_glyph_names):
        return _merge_minimal_gsub(
            [lookup],
            [_make_feature_record("calt", [0])],
            [_make_script_record("latn", [0])],
            lat_glyph_names=lat_glyph_names,
        )

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_safe_calt_is_promoted_to_cjk_default(self, script):
        lookup = _make_single_subst("A", "A.alt")
        gsub = self._latn_default_gsub_for_calt(lookup, {"A", "A.alt"})
        ls = _langsys(gsub, script)
        assert "calt" in _tags_for_langsys(gsub, ls)

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_unsafe_output_calt_is_not_promoted(self, script):
        lookup = _make_single_subst("A", "uni65E5")
        gsub = self._latn_default_gsub_for_calt(lookup, {"A"})
        ls = _langsys(gsub, script)
        assert "calt" not in _tags_for_langsys(gsub, ls)

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_unsafe_lookahead_calt_is_not_promoted(self, script):
        lookup = _make_chain_context_format3(["A"], lookahead=["uni65E5"])
        gsub = self._latn_default_gsub_for_calt(lookup, {"A"})
        ls = _langsys(gsub, script)
        assert "calt" not in _tags_for_langsys(gsub, ls)

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_duplicate_calt_tag_combines_without_mutating_jp_record(
            self, script):
        jp_lookup = _make_single_subst("uni65E5", "uni65E5.alt")
        lat_lookup = _make_single_subst("A", "A.alt")
        gsub = _merge_minimal_gsub(
            [lat_lookup],
            [_make_feature_record("calt", [0])],
            [_make_script_record("latn", [0])],
            jp_lookups=[jp_lookup],
            jp_features=[_make_feature_record("calt", [0])],
            jp_scripts=[
                _make_script_record("kana", [0]),
                _make_script_record("hani", [0]),
            ],
            lat_glyph_names={"A", "A.alt"},
        )
        ls = _langsys(gsub, script)
        tags = _tags_for_langsys(gsub, ls)
        assert tags.count("calt") == 1
        [combined_idx] = _feature_indices_for_tag(gsub, ls, "calt")
        combined_lookups = (
            gsub.FeatureList.FeatureRecord[combined_idx]
            .Feature.LookupListIndex
        )
        assert combined_lookups == [0, 1]
        original_jp_lookups = (
            gsub.FeatureList.FeatureRecord[0].Feature.LookupListIndex
        )
        assert original_jp_lookups == [0]

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_named_only_calt_does_not_leak_to_cjk_default(self, script):
        lookup = _make_single_subst("A", "A.alt")
        gsub = _merge_minimal_gsub(
            [lookup],
            [_make_feature_record("calt", [0])],
            [_make_script_record("latn", [], named={"JPN ": [0]})],
            lat_glyph_names={"A", "A.alt"},
        )
        default_ls = _langsys(gsub, script)
        named_ls = _langsys(gsub, script, "JPN ")
        assert "calt" not in _tags_for_langsys(gsub, default_ls)
        assert named_ls is not None
        assert "calt" in _tags_for_langsys(gsub, named_ls)


class TestSafetyHelperRecursesIntoSubordinateLookups:
    """`_latin_feature_safe_for_cjk_promotion` must recurse into Context /
    ChainContext SubstLookupRecord references — a Latin-only top-level
    coverage that drives a subordinate lookup touching a non-Latin glyph
    must still be rejected."""

    @staticmethod
    def _make_single_subst(input_glyph, output_glyph):
        from fontTools.ttLib.tables import otTables
        st = otTables.SingleSubst()
        st.mapping = {input_glyph: output_glyph}
        lk = otTables.Lookup()
        lk.LookupType = 1
        lk.LookupFlag = 0
        lk.SubTable = [st]
        lk.SubTableCount = 1
        return lk

    @staticmethod
    def _make_chain_context(input_glyph, subordinate_index):
        """Build a Format 3 ChainContextSubst whose top-level input
        coverage is *input_glyph* and that calls a subordinate lookup at
        *subordinate_index* on the matched position.
        """
        from fontTools.ttLib.tables import otTables

        st = otTables.ChainContextSubst()
        st.Format = 3
        st.BacktrackGlyphCount = 0
        st.BacktrackCoverage = []
        st.LookAheadGlyphCount = 0
        st.LookAheadCoverage = []

        cov = otTables.Coverage()
        cov.glyphs = [input_glyph]
        st.InputGlyphCount = 1
        st.InputCoverage = [cov]

        slr = otTables.SubstLookupRecord()
        slr.SequenceIndex = 0
        slr.LookupListIndex = subordinate_index
        st.SubstLookupRecord = [slr]
        st.SubstCount = 1

        lk = otTables.Lookup()
        lk.LookupType = 6
        lk.LookupFlag = 0
        lk.SubTable = [st]
        lk.SubTableCount = 1
        return lk

    @staticmethod
    def _make_feature_record(tag, lookup_indices):
        from fontTools.ttLib.tables import otTables
        feat = otTables.Feature()
        feat.FeatureParams = None
        feat.LookupListIndex = list(lookup_indices)
        feat.LookupCount = len(feat.LookupListIndex)
        rec = otTables.FeatureRecord()
        rec.FeatureTag = tag
        rec.Feature = feat
        return rec

    def test_safe_when_subordinate_only_touches_latin(self):
        """All-Latin chain (top-level + subordinate) → safe."""
        sub = self._make_single_subst("a", "a.alt")
        chain = self._make_chain_context("a", subordinate_index=0)
        merged_lookups = [sub, chain]
        feat_rec = self._make_feature_record("ss02", [1])
        lat_glyph_names = {"a", "a.alt"}
        assert mf._latin_feature_safe_for_cjk_promotion(
            feat_rec, merged_lookups, lat_glyph_names) is True

    def test_unsafe_when_subordinate_touches_non_latin_glyph(self):
        """Top-level coverage is Latin (`a`) but the subordinate lookup
        rewrites a JP glyph (`uni3042`). Must be rejected."""
        sub = self._make_single_subst("uni3042", "uni3042.alt")
        chain = self._make_chain_context("a", subordinate_index=0)
        merged_lookups = [sub, chain]
        feat_rec = self._make_feature_record("ss02", [1])
        lat_glyph_names = {"a"}
        assert mf._latin_feature_safe_for_cjk_promotion(
            feat_rec, merged_lookups, lat_glyph_names) is False

    def test_unsafe_when_top_level_is_non_latin(self):
        sub = self._make_single_subst("a", "a.alt")
        feat_rec = self._make_feature_record("ss02", [0])
        lat_glyph_names = set()
        assert mf._latin_feature_safe_for_cjk_promotion(
            feat_rec, [sub], lat_glyph_names) is False

    def test_unsafe_when_lookup_index_out_of_range(self):
        feat_rec = self._make_feature_record("ss02", [99])
        assert mf._latin_feature_safe_for_cjk_promotion(
            feat_rec, [], {"a"}) is False

    def test_safe_when_lookup_has_no_input_glyphs(self):
        """Empty lookup is treated as safe (matches `_classify_lookup`)."""
        from fontTools.ttLib.tables import otTables
        empty = otTables.Lookup()
        empty.LookupType = 1
        empty.LookupFlag = 0
        empty.SubTable = []
        empty.SubTableCount = 0
        feat_rec = self._make_feature_record("ss02", [0])
        assert mf._latin_feature_safe_for_cjk_promotion(
            feat_rec, [empty], set()) is True

    @staticmethod
    def _make_chain_subst_format1(input_seq):
        """Build a Format 1 ChainContextSubst with raw glyph-name input
        sequence (rather than Coverage). This is the rule-based form that
        the original `_collect_lookup_glyphs` did not walk."""
        from fontTools.ttLib.tables import otTables

        rule = otTables.ChainSubRule()
        rule.Backtrack = []
        rule.BacktrackGlyphCount = 0
        rule.Input = list(input_seq[1:])  # rule input excludes first glyph
        rule.InputGlyphCount = len(input_seq)
        rule.LookAhead = []
        rule.LookAheadGlyphCount = 0
        rule.SubstLookupRecord = []
        rule.SubstCount = 0

        ruleset = otTables.ChainSubRuleSet()
        ruleset.ChainSubRule = [rule]
        ruleset.ChainSubRuleCount = 1

        cov = otTables.Coverage()
        cov.glyphs = [input_seq[0]]

        st = otTables.ChainContextSubst()
        st.Format = 1
        st.Coverage = cov
        st.ChainSubRuleSet = [ruleset]
        st.ChainSubRuleSetCount = 1

        lk = otTables.Lookup()
        lk.LookupType = 6
        lk.LookupFlag = 0
        lk.SubTable = [st]
        lk.SubTableCount = 1
        return lk

    @staticmethod
    def _make_chain_subst_format2(coverage_glyphs, input_classdef):
        """Build a Format 2 ChainContextSubst with separate Coverage
        (position-0 input) and InputClassDef (per-position class table).
        The realistic shape: Coverage describes the first glyph's input
        set, InputClassDef classifies that *plus* later positions —
        sometimes including non-Latin glyphs that the existing Coverage
        walker would miss."""
        from fontTools.ttLib.tables import otTables

        cd = otTables.ClassDef()
        cd.classDefs = dict(input_classdef)

        st = otTables.ChainContextSubst()
        st.Format = 2
        st.InputClassDef = cd
        st.BacktrackClassDef = None
        st.LookAheadClassDef = None
        cov = otTables.Coverage()
        cov.glyphs = list(coverage_glyphs)
        st.Coverage = cov

        lk = otTables.Lookup()
        lk.LookupType = 6
        lk.LookupFlag = 0
        lk.SubTable = [st]
        lk.SubTableCount = 1
        return lk

    def test_unsafe_when_format1_rule_input_includes_non_latin(self):
        """Format 1 ChainSubRule input glyph references must be checked."""
        chain = self._make_chain_subst_format1(["a", "uni3042"])
        feat_rec = self._make_feature_record("ss02", [0])
        assert mf._latin_feature_safe_for_cjk_promotion(
            feat_rec, [chain], {"a"}) is False

    def test_safe_when_format1_rule_input_only_latin(self):
        chain = self._make_chain_subst_format1(["a", "b"])
        feat_rec = self._make_feature_record("ss02", [0])
        assert mf._latin_feature_safe_for_cjk_promotion(
            feat_rec, [chain], {"a", "b"}) is True

    def test_unsafe_when_format2_classdef_includes_non_latin(self):
        """Format 2 ClassDef glyph keys must be checked. The Coverage is
        all-Latin (position-0 only) so the existing Coverage walker would
        let this through; the safety failure must come from walking
        InputClassDef.classDefs."""
        chain = self._make_chain_subst_format2(
            coverage_glyphs=["a"],
            input_classdef={"a": 1, "uni3042": 2},
        )
        feat_rec = self._make_feature_record("ss02", [0])
        assert mf._latin_feature_safe_for_cjk_promotion(
            feat_rec, [chain], {"a"}) is False


class TestCjkLangSysNoDuplicateAllowlistTags:
    """A CJK LangSys must never list two records with the same allowlisted
    feature tag. If the JP font already references e.g. ``tnum``, the Latin
    record must be skipped to avoid HarfBuzz shadowing one of them."""

    @pytest.mark.parametrize("script", ["kana", "hani"])
    def test_no_duplicate_tags_in_cjk_default_langsys(self, merged_inter_path,
                                                      script):
        merged = TTFont(merged_inter_path)
        gsub = merged["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag != script or not sr.Script.DefaultLangSys:
                continue
            tags = [feat_records[i].FeatureTag
                    for i in (sr.Script.DefaultLangSys.FeatureIndex or [])]
            duplicates = {t for t in tags if tags.count(t) > 1}
            assert not duplicates, (
                f"{script} DefaultLangSys has duplicate feature tags: "
                f"{sorted(duplicates)} (full list={tags})"
            )
            return
        pytest.fail(f"merged font has no {script} script in GSUB")


# ---------------------------------------------------------------------------
# Structural tests across every CJK script in CJK_SCRIPTS
# ---------------------------------------------------------------------------

class TestPromotionAppliesToEveryCjkScript:
    """`merge_fonts.CJK_SCRIPTS` covers `kana`, `hani`, `hang`, `bopo`,
    and `yi  `. The promotion must apply to whichever of those the merged
    font ships, not just `kana` / `hani`. Skip scripts that the JP base
    font doesn't define."""

    def test_every_cjk_script_in_merged_font_promotes(self, merged_inter_path):
        from merge_fonts import CJK_SCRIPTS, CJK_LATIN_USER_FEATURE_ALLOWLIST
        merged = TTFont(merged_inter_path)
        gsub = merged["GSUB"].table
        feat_records = gsub.FeatureList.FeatureRecord

        # Inter's `latn` default tags ∩ allowlist
        inter = TTFont(EN_VAR)
        inter_gsub = inter["GSUB"].table
        inter_feat_records = inter_gsub.FeatureList.FeatureRecord
        latn_default = set()
        for sr in inter_gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag not in ("latn", "DFLT"):
                continue
            ds = sr.Script.DefaultLangSys
            if ds:
                latn_default.update(
                    inter_feat_records[i].FeatureTag
                    for i in (ds.FeatureIndex or [])
                )
        latn_user = latn_default & CJK_LATIN_USER_FEATURE_ALLOWLIST
        assert latn_user, "fixture must expose at least one allowlist tag"

        observed_scripts = set()
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag not in CJK_SCRIPTS or not sr.Script.DefaultLangSys:
                continue
            observed_scripts.add(sr.ScriptTag)
            tags = {feat_records[i].FeatureTag
                    for i in (sr.Script.DefaultLangSys.FeatureIndex or [])}
            missing = latn_user - tags
            assert not missing, (
                f"{sr.ScriptTag} DefaultLangSys missing promoted Latin "
                f"user features: {sorted(missing)}"
            )
        assert observed_scripts, "merged font has no CJK scripts at all"
