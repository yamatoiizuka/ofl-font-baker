"""Helper-level tests for `_filter_subordinate_lookups` / `_reindex_table`.

Calling the helpers directly avoids downstream merge stages that mask the
bugs by rebuilding tables from scratch (e.g. _merge_ot_table_v2 builds a
fresh ScriptList, which hides ScriptList-remap bugs in `_reindex_table`).

Covers Issue #2:
  #1 chaining cross-lookup references not remapped after `_reindex_table`
  #2 ScriptList LangSys.FeatureIndex not remapped after `_reindex_table`
"""
from __future__ import annotations

import os

import pytest
from fontTools.ttLib import TTFont

from conftest import EN_VAR
import merge_fonts as mf


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
SHIPPORI = os.path.join(FONTS_DIR, "Shippori_Mincho", "ShipporiMincho-Regular.ttf")
NOTOCJK = os.path.join(FONTS_DIR, "NotoSansCJKjp", "NotoSansCJKjp-Regular.otf")


def _require(path):
    if not os.path.exists(path):
        pytest.skip(f"{os.path.basename(path)} not available")


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------


def _snapshot_lookup_identity(lookup_list) -> list[dict]:
    """Capture (LookupType, frozenset_of_glyphs) per lookup. Used to verify
    that an index in a SubstLookupRecord still resolves to the same logical
    lookup after reindex."""
    if not lookup_list:
        return []
    snaps = []
    for lookup in lookup_list.Lookup:
        glyphs = mf._collect_lookup_glyphs(lookup)
        snaps.append({
            "type": lookup.LookupType,
            "glyphs": frozenset(glyphs),
        })
    return snaps


def _walk_chaining_refs(table):
    """Yield (containing_lookup_index, referenced_lookup_index) for every
    SubstLookupRecord / PosLookupRecord index reference inside type 5/6/7/8
    lookups."""
    if not table.LookupList:
        return
    for li, lookup in enumerate(table.LookupList.Lookup):
        if lookup.LookupType not in (5, 6, 7, 8, 9):
            continue
        for st in lookup.SubTable:
            actual = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
            for attr in ("SubstLookupRecord", "PosLookupRecord"):
                for rec in (getattr(actual, attr, None) or []):
                    yield li, rec.LookupListIndex
            for rs_attr in (
                "SubRuleSet", "SubClassSet", "ChainSubRuleSet", "ChainSubClassSet",
                "PosRuleSet", "PosClassSet", "ChainPosRuleSet", "ChainPosClassSet",
            ):
                for rs in (getattr(actual, rs_attr, None) or []):
                    if rs is None:
                        continue
                    for r_attr in (
                        "SubRule", "SubClassRule", "ChainSubRule", "ChainSubClassRule",
                        "PosRule", "PosClassRule", "ChainPosRule", "ChainPosClassRule",
                    ):
                        for rule in (getattr(rs, r_attr, None) or []):
                            for rec_attr in ("SubstLookupRecord", "PosLookupRecord"):
                                for rec in (getattr(rule, rec_attr, None) or []):
                                    yield li, rec.LookupListIndex


def _walk_langsys_indices(table):
    """Yield (script_tag, langsys_label, feature_index)."""
    if not table.ScriptList:
        return
    for sr in table.ScriptList.ScriptRecord:
        if sr.Script.DefaultLangSys:
            for fi in sr.Script.DefaultLangSys.FeatureIndex or []:
                yield sr.ScriptTag, "DFLT", fi
        for lsr in (sr.Script.LangSysRecord or []):
            for fi in lsr.LangSys.FeatureIndex or []:
                yield sr.ScriptTag, lsr.LangSysTag, fi


# ---------------------------------------------------------------------------
# Bug #2 — ScriptList FeatureIndex must remain valid after filter
# ---------------------------------------------------------------------------


def test_filter_actually_removes_lookups_in_shippori():
    """Sanity: with Shippori + Inter the filter must actually remove lookups,
    otherwise downstream tests are vacuously passing."""
    _require(SHIPPORI)
    en = TTFont(EN_VAR)
    jp = TTFont(SHIPPORI)
    n_before = len(jp["GSUB"].table.LookupList.Lookup)
    mf._filter_subordinate_lookups(jp["GSUB"], set(en.getGlyphOrder()))
    n_after = len(jp["GSUB"].table.LookupList.Lookup)
    assert n_after < n_before, (
        f"Filter should remove lookups: before={n_before}, after={n_after}"
    )


def test_bug2_scriptlist_indices_in_range_after_filter():
    """`_reindex_table` must keep all ScriptList LangSys.FeatureIndex values
    within `len(FeatureList.FeatureRecord)`."""
    _require(SHIPPORI)
    en = TTFont(EN_VAR)
    jp = TTFont(SHIPPORI)
    mf._filter_subordinate_lookups(jp["GSUB"], set(en.getGlyphOrder()))

    table = jp["GSUB"].table
    n_features = len(table.FeatureList.FeatureRecord) if table.FeatureList else 0
    out_of_range = [
        (s, l, fi)
        for s, l, fi in _walk_langsys_indices(table)
        if not (0 <= fi < n_features)
    ]
    assert not out_of_range, (
        f"{len(out_of_range)} ScriptList FeatureIndex value(s) are out of "
        f"range after _reindex_table; expected indices < {n_features}. "
        f"_reindex_table failed to remap ScriptList. Examples: "
        f"{out_of_range[:5]}"
    )


def test_bug2_scriptlist_indices_resolve_to_kept_features():
    """Stronger: every surviving FeatureIndex must point to a feature whose
    tag matches what that LangSys originally referenced. Catches stale-but-
    in-range indices that have drifted to an unrelated feature.

    Run as a regular test rather than xfail: while the in-range bug (#2) is
    open, this assertion is vacuously true (out-of-range indices are skipped
    below, leaving few in-range entries to drift). After the in-range fix
    lands, this becomes a real drift-regression check; if a future change
    reintroduces drift, the test fails loudly instead of silently XFAIL-ing.
    """
    _require(SHIPPORI)
    en = TTFont(EN_VAR)
    jp = TTFont(SHIPPORI)

    # Snapshot original (script, lang, tag) triples
    before_tags = [
        fr.FeatureTag for fr in jp["GSUB"].table.FeatureList.FeatureRecord
    ]
    before_triples = {
        (s, l, before_tags[fi])
        for s, l, fi in _walk_langsys_indices(jp["GSUB"].table)
    }

    mf._filter_subordinate_lookups(jp["GSUB"], set(en.getGlyphOrder()))

    after_tags = [
        fr.FeatureTag for fr in jp["GSUB"].table.FeatureList.FeatureRecord
    ]
    leaks = []
    for s, l, fi in _walk_langsys_indices(jp["GSUB"].table):
        if not (0 <= fi < len(after_tags)):
            continue  # already covered by previous test
        triple = (s, l, after_tags[fi])
        if triple not in before_triples:
            leaks.append(triple)

    assert not leaks, (
        f"{len(leaks)} ScriptList LangSys.FeatureIndex value(s) now point to "
        f"a feature whose tag was not originally referenced by that LangSys. "
        f"_reindex_table did not remap ScriptList correctly. Examples: "
        f"{leaks[:5]}"
    )


# ---------------------------------------------------------------------------
# Bug #1 — chaining cross-lookup references must remain valid
# ---------------------------------------------------------------------------
#
# To exercise Bug #1, we need a chaining lookup that *survives* filter while
# at least one earlier lookup gets removed. Real fixtures rarely satisfy
# this (Shippori's only chaining lookup is itself classified as Latin and
# removed; NotoSansCJKjp's lookups don't classify as Latin so nothing is
# removed). We force the scenario by monkey-patching `_classify_lookup`:
# a lookup at a chosen index is classified as 'latin' so it gets removed,
# and we verify cross-refs in *surviving* chaining lookups still resolve to
# the correct target lookup post-reindex.
#
# This is the cleanest way to test the helper: it isolates the
# `_reindex_table` remap responsibility from the classifier's behaviour.


def _find_chaining_lookup_with_refs(table):
    """Return the first lookup index whose chaining/context subtables have
    at least one cross-ref."""
    if not table.LookupList:
        return None
    for li, lookup in enumerate(table.LookupList.Lookup):
        if lookup.LookupType not in (5, 6, 7, 8, 9):
            continue
        for st in lookup.SubTable:
            actual = st.ExtSubTable if hasattr(st, "ExtSubTable") else st
            for attr in ("SubstLookupRecord", "PosLookupRecord"):
                if getattr(actual, attr, None):
                    return li
    return None


def test_bug1_cross_refs_stay_in_range_after_reindex(monkeypatch):
    """Force a non-chaining lookup to be removed; verify chaining lookup's
    cross-refs are still in range afterwards."""
    _require(SHIPPORI)
    jp = TTFont(SHIPPORI)
    chaining_idx = _find_chaining_lookup_with_refs(jp["GSUB"].table)
    if chaining_idx is None:
        pytest.skip("Base font has no chaining lookup with cross-refs")

    # Pick a non-chaining lookup at a *lower* index than the chaining one to
    # remove. That guarantees reindex shifts higher indices down by 1+,
    # exposing the bug if cross-refs aren't remapped.
    n = len(jp["GSUB"].table.LookupList.Lookup)
    victim_indices = {
        i for i in range(n)
        if i < chaining_idx
        and jp["GSUB"].table.LookupList.Lookup[i].LookupType not in (5, 6, 7, 8, 9)
    }
    if not victim_indices:
        pytest.skip("No earlier non-chaining lookup to remove")

    real_classify = mf._classify_lookup
    lookup_list = jp["GSUB"].table.LookupList.Lookup

    def fake_classify(lookup, lat_glyph_names):
        # Identify by object identity — lookup_list[i] is unique
        for i, l in enumerate(lookup_list):
            if l is lookup and i in victim_indices:
                return "latin"
        return real_classify(lookup, lat_glyph_names)

    monkeypatch.setattr(mf, "_classify_lookup", fake_classify)
    mf._filter_subordinate_lookups(jp["GSUB"], set())

    table = jp["GSUB"].table
    n_after = len(table.LookupList.Lookup)
    out_of_range = [
        (ci, ri) for ci, ri in _walk_chaining_refs(table)
        if not (0 <= ri < n_after)
    ]
    assert not out_of_range, (
        f"{len(out_of_range)} chaining cross-ref(s) out of range after "
        f"_reindex_table; LookupList has {n_after} entries. "
        f"_reindex_table failed to remap SubstLookupRecord/PosLookupRecord "
        f"indices. Examples: {out_of_range[:5]}"
    )


def test_bug1_cross_refs_preserve_lookup_identity(monkeypatch):
    """Strongest check: a cross-ref must point to a lookup whose (type,
    Coverage glyphs) signature matches the original target. Catches stale-
    but-in-range indices that have drifted to an unrelated lookup.

    Run as a regular test rather than xfail: while the in-range bug (#1) is
    open, the out-of-range cross-refs are skipped, leaving few in-range
    entries to drift, so the assertion is currently vacuously true. After
    the in-range fix lands, this becomes a real drift-regression check.
    """
    _require(SHIPPORI)
    jp = TTFont(SHIPPORI)
    chaining_idx = _find_chaining_lookup_with_refs(jp["GSUB"].table)
    if chaining_idx is None:
        pytest.skip("Base font has no chaining lookup with cross-refs")

    n = len(jp["GSUB"].table.LookupList.Lookup)
    victim_indices = {
        i for i in range(n)
        if i < chaining_idx
        and jp["GSUB"].table.LookupList.Lookup[i].LookupType not in (5, 6, 7, 8, 9)
    }
    if not victim_indices:
        pytest.skip("No earlier non-chaining lookup to remove")

    # Snapshot identities BEFORE
    before_snaps = _snapshot_lookup_identity(jp["GSUB"].table.LookupList)
    before_pairs = []
    for ci, ri in _walk_chaining_refs(jp["GSUB"].table):
        before_pairs.append((before_snaps[ci], before_snaps[ri]))

    real_classify = mf._classify_lookup
    lookup_list = jp["GSUB"].table.LookupList.Lookup

    def fake_classify(lookup, lat_glyph_names):
        for i, l in enumerate(lookup_list):
            if l is lookup and i in victim_indices:
                return "latin"
        return real_classify(lookup, lat_glyph_names)

    monkeypatch.setattr(mf, "_classify_lookup", fake_classify)
    mf._filter_subordinate_lookups(jp["GSUB"], set())

    after_snaps = _snapshot_lookup_identity(jp["GSUB"].table.LookupList)
    n_after = len(after_snaps)

    # For each surviving chaining lookup, find it by signature in the new
    # table and compare its current cross-ref targets against the original.
    surviving_pairs = []
    for ci, ri in _walk_chaining_refs(jp["GSUB"].table):
        if not (0 <= ri < n_after):
            continue
        surviving_pairs.append((after_snaps[ci], after_snaps[ri]))

    # Convert dicts to hashable representations
    def _norm(snap):
        return (snap["type"], snap["glyphs"])

    before_set = {(_norm(b[0]), _norm(b[1])) for b in before_pairs}
    drifted = []
    for after_pair in surviving_pairs:
        key = (_norm(after_pair[0]), _norm(after_pair[1]))
        if key not in before_set:
            drifted.append(after_pair)

    assert not drifted, (
        f"{len(drifted)} chaining cross-ref(s) point to a lookup with "
        f"mismatched identity after _reindex_table; the index was not "
        f"remapped through _transform_lookup_references."
    )
