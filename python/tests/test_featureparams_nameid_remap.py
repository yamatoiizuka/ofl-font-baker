"""Tests for FeatureParams `UINameID` / `FeatUILabelNameID` remap collisions.

Regression coverage for issue #26: when an Inter (sub-font) feature label
nameID collides with a base-font (Noto) name record, the remap allocator
in `reconcile_tables` must pick a target that is also free across the
*Latin* feature-label namespace. Without that reservation, the remapped
ID can land on another Latin feature's unchanged ID and two Latin
features end up sharing the same UINameID — Illustrator then shows
duplicate or misleading labels in the OpenType panel.

Repro shape from the issue:

    Inter source: ss02 UINameID 257 -> "Disambiguation"
                  ss03 UINameID 258 -> "Round quotes & commas"
    Noto base:    nameID 257       -> "Weight"
    Merged (buggy): ss02 UINameID 258 -> "Disambiguation"
                    ss03 UINameID 258 -> "Round quotes & commas"

The actual Inter subset shipped with the fixtures uses UINameIDs in
276..282 for ssXX. The synthetic test below patches Noto Sans JP to
hold a colliding nameID at one of Inter's ssXX UINameIDs so the bug
is reachable from the bundled fixtures.
"""

import os
import tempfile

import pytest

from fontTools.ttLib import TTFont

from conftest import EN_VAR, JP_VAR

import merge_fonts as mf


def _patched_jp_with_collision(src_path, dst_path, collide_name_id, value):
    """Copy *src_path* and add a name record at *collide_name_id*."""
    font = TTFont(src_path)
    font["name"].setName(value, collide_name_id, 3, 1, 0x409)
    font.save(dst_path)


def _ssxx_uinameids(merged):
    """Return {feature_tag: UINameID} for ssXX features in merged GSUB."""
    out = {}
    gsub = merged["GSUB"].table
    for fr in gsub.FeatureList.FeatureRecord:
        if not fr.FeatureTag.startswith("ss"):
            continue
        fp = fr.Feature.FeatureParams
        if fp is None:
            continue
        nid = getattr(fp, "UINameID", None)
        if nid is not None:
            out[fr.FeatureTag] = nid
    return out


def _all_lat_feat_label_nameids(latin_font):
    """All FeatureParams label nameIDs in the Latin source GSUB/GPOS."""
    ids = set()
    for tag in ("GSUB", "GPOS"):
        ot = latin_font.get(tag)
        if not ot or not getattr(ot, "table", None):
            continue
        if not ot.table.FeatureList:
            continue
        for fr in ot.table.FeatureList.FeatureRecord:
            fp = fr.Feature.FeatureParams
            if fp is None:
                continue
            for attr in ("UINameID", "FeatUILabelNameID",
                         "FeatUITooltipTextNameID", "SampleTextNameID",
                         "SubfamilyNameID"):
                nid = getattr(fp, attr, None)
                if nid:
                    ids.add(nid)
            num = (getattr(fp, "NumNamedParameters", None)
                   or getattr(fp, "NamedParameters", None))
            first = getattr(fp, "FirstParamUILabelNameID", None)
            if num and first:
                ids.update(range(first, first + num))
    return ids


def _base_feat_param_targets(base_font):
    """Return the set of nameIDs already referenced by the *base*
    font's FeatureParams (so the merged-font uniqueness checks can
    subtract base-side reuse / sharing that the merge engine never
    touches). Generic across base fonts."""
    ids = set()
    for tag in ("GSUB", "GPOS"):
        ot = base_font.get(tag)
        if not ot or not getattr(ot, "table", None):
            continue
        if not ot.table.FeatureList:
            continue
        for fr in ot.table.FeatureList.FeatureRecord:
            fp = fr.Feature.FeatureParams
            if fp is None:
                continue
            for attr in ("UINameID", "FeatUILabelNameID",
                         "FeatUITooltipTextNameID", "SampleTextNameID",
                         "SubfamilyNameID"):
                nid = getattr(fp, attr, None)
                if nid:
                    ids.add(nid)
            num = (getattr(fp, "NumNamedParameters", None)
                   or getattr(fp, "NamedParameters", None))
            first = getattr(fp, "FirstParamUILabelNameID", None)
            if num and first:
                ids.update(range(first, first + num))
    return ids


@pytest.fixture(scope="module")
def collision_paths(tmp_path_factory):
    """Patch Noto Sans JP so its name table holds a record at *Inter's*
    ss02 UINameID. Latin label allocation in `reconcile_tables` then
    needs to remap Inter's ss02 — and the buggy allocator picks a target
    that lands on Inter's ss03 UINameID."""
    inter = TTFont(EN_VAR)
    ssxx = {fr.FeatureTag: fr.Feature.FeatureParams
            for fr in inter["GSUB"].table.FeatureList.FeatureRecord
            if fr.FeatureTag.startswith("ss") and fr.Feature.FeatureParams}
    assert "ss02" in ssxx and "ss03" in ssxx, (
        "fixture must define ssXX UINameIDs"
    )
    inter_ss02_nid = ssxx["ss02"].UINameID
    # Confirm Inter's ssXX UINameIDs are contiguous so the buggy
    # next_free allocator can land on ss03 / ss04 / etc.
    assert {ssxx[t].UINameID for t in ("ss02", "ss03")} \
        == {inter_ss02_nid, inter_ss02_nid + 1}, (
        "fixture invariant: Inter ssXX UINameIDs are contiguous"
    )

    tmp = tmp_path_factory.mktemp("nameid_collision")
    jp_patched = str(tmp / "JpPatched.ttf")
    _patched_jp_with_collision(JP_VAR, jp_patched, inter_ss02_nid,
                               "Noto-side colliding label")
    return EN_VAR, jp_patched, inter_ss02_nid


@pytest.fixture(scope="module")
def merged_collision_path(collision_paths, tmp_path_factory):
    latin_path, jp_path, _ = collision_paths
    out = tmp_path_factory.mktemp("nameid_collision_merged") / "merged.ttf"
    config = {
        "subFont": {
            "path": latin_path,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [
                {"tag": "opsz", "currentValue": 14},
                {"tag": "wght", "currentValue": 400},
            ],
        },
        "baseFont": {
            "path": jp_path,
            "scale": 1.0,
            "baselineOffset": 0,
            "axes": [{"tag": "wght", "currentValue": 400}],
        },
        "output": {"familyName": "TestNameIdCollision"},
        "export": {"path": {"font": str(out)}},
    }
    mf.merge_fonts(config)
    return str(out)


class TestLatinFeatureLabelsKeepDistinctNameIDs:
    """When an Inter ssXX UINameID collides with a base-font name
    record, the merge engine must remap it to a target that doesn't
    already belong to another Latin feature label — otherwise two
    different stylistic sets end up sharing the same UINameID and
    the OpenType UI panel shows duplicate labels."""

    def test_no_two_ssxx_features_share_a_uinameid(
            self, merged_collision_path):
        merged = TTFont(merged_collision_path)
        ssxx = _ssxx_uinameids(merged)
        ids = list(ssxx.values())
        duplicates = {nid for nid in ids if ids.count(nid) > 1}
        assert not duplicates, (
            f"duplicate UINameIDs across ssXX features: {duplicates} "
            f"(full map: {ssxx})"
        )

    def test_no_two_feature_labels_share_a_target_id(
            self, merged_collision_path, collision_paths):
        """Strict invariant for *Latin-derived* FeatureParams: no two
        target nameIDs collide after the merge. The `_lat_origin`
        marker is Python-only and doesn't survive `font.save()`, so
        we identify base-side FeatureParams by collecting them from
        the pre-merge JP fixture and subtracting their nameIDs from
        the assertion. This stays correct even for future base fonts
        that legitimately reuse / share their own FeatureParams
        nameIDs."""
        _, jp_path, _ = collision_paths
        base_targets = _base_feat_param_targets(TTFont(jp_path))

        merged = TTFont(merged_collision_path)
        gsub = merged["GSUB"].table
        targets = []
        for fr in gsub.FeatureList.FeatureRecord:
            fp = fr.Feature.FeatureParams
            if fp is None:
                continue
            for attr in ("UINameID", "FeatUILabelNameID",
                         "FeatUITooltipTextNameID", "SampleTextNameID",
                         "SubfamilyNameID"):
                nid = getattr(fp, attr, None)
                if nid and nid not in base_targets:
                    targets.append((fr.FeatureTag, attr, nid))
            num = (getattr(fp, "NumNamedParameters", None)
                   or getattr(fp, "NamedParameters", None))
            first = getattr(fp, "FirstParamUILabelNameID", None)
            if num and first:
                for offset in range(num):
                    nid = first + offset
                    if nid not in base_targets:
                        targets.append(
                            (fr.FeatureTag, f"ParamLabel[{offset}]", nid))
        seen = {}
        for tag, attr, nid in targets:
            seen.setdefault(nid, []).append((tag, attr))
        collisions = {nid: refs for nid, refs in seen.items() if len(refs) > 1}
        assert not collisions, (
            f"multiple Latin-derived FeatureParams share the same "
            f"nameID: {collisions}"
        )

    def test_ssxx_labels_resolve_to_their_original_inter_strings(
            self, merged_collision_path):
        """Each merged ssXX label must resolve to the same string Inter
        shipped under the same feature tag — no swapped labels."""
        inter = TTFont(EN_VAR)
        inter_ssxx = {}
        for fr in inter["GSUB"].table.FeatureList.FeatureRecord:
            if not fr.FeatureTag.startswith("ss"):
                continue
            fp = fr.Feature.FeatureParams
            if fp is None:
                continue
            label = inter["name"].getDebugName(fp.UINameID)
            if label:
                inter_ssxx[fr.FeatureTag] = label

        merged = TTFont(merged_collision_path)
        for fr in merged["GSUB"].table.FeatureList.FeatureRecord:
            if not fr.FeatureTag.startswith("ss"):
                continue
            fp = fr.Feature.FeatureParams
            if fp is None:
                continue
            inter_label = inter_ssxx.get(fr.FeatureTag)
            if inter_label is None:
                continue
            merged_label = merged["name"].getDebugName(fp.UINameID)
            assert merged_label == inter_label, (
                f"{fr.FeatureTag} label changed after merge: "
                f"Inter={inter_label!r} merged={merged_label!r}"
            )

    def test_base_colliding_nameid_text_is_untouched(
            self, merged_collision_path, collision_paths):
        """The Noto-side name record at the colliding nameID must keep
        its original text — the Latin remap must not overwrite it."""
        _, jp_path, collide_nid = collision_paths
        jp_label = TTFont(jp_path)["name"].getDebugName(collide_nid)
        merged = TTFont(merged_collision_path)
        merged_label = merged["name"].getDebugName(collide_nid)
        assert merged_label == jp_label, (
            f"base nameID {collide_nid} text changed: "
            f"base={jp_label!r} merged={merged_label!r}"
        )


class TestSyntheticMultiCollisionAllocator:
    """Synthetic stress test: every Inter ssXX UINameID is also occupied
    in the base font, so the allocator has to remap *all* Latin labels
    at once. The resulting nameIDs must still be pairwise unique and
    distinct from every nameID that survived from the base."""

    @pytest.fixture(scope="class")
    def merged_path(self, tmp_path_factory):
        inter = TTFont(EN_VAR)
        lat_ids = sorted(_all_lat_feat_label_nameids(inter))
        assert lat_ids, "fixture must have Latin feature label nameIDs"
        tmp = tmp_path_factory.mktemp("multi_collision")
        jp_patched = str(tmp / "JpPatched.ttf")
        font = TTFont(JP_VAR)
        for nid in lat_ids:
            font["name"].setName(f"Noto fake label {nid}",
                                 nid, 3, 1, 0x409)
        font.save(jp_patched)
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
                "path": jp_patched,
                "scale": 1.0,
                "baselineOffset": 0,
                "axes": [{"tag": "wght", "currentValue": 400}],
            },
            "output": {"familyName": "TestNameIdMultiCollision"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out)

    def test_all_remapped_targets_are_pairwise_unique(self, merged_path):
        """No two *Latin-derived* FeatureParams in the merged GSUB
        may share a nameID. Base-side targets are subtracted via the
        pre-merge fixture so future base fonts that legitimately
        reuse / share their own FeatureParams nameIDs don't trip
        this assertion."""
        base_targets = _base_feat_param_targets(TTFont(JP_VAR))
        merged = TTFont(merged_path)
        gsub = merged["GSUB"].table
        targets = []
        for fr in gsub.FeatureList.FeatureRecord:
            fp = fr.Feature.FeatureParams
            if fp is None:
                continue
            for attr in ("UINameID", "FeatUILabelNameID",
                         "FeatUITooltipTextNameID", "SampleTextNameID",
                         "SubfamilyNameID"):
                nid = getattr(fp, attr, None)
                if nid and nid not in base_targets:
                    targets.append((fr.FeatureTag, attr, nid))
            num = (getattr(fp, "NumNamedParameters", None)
                   or getattr(fp, "NamedParameters", None))
            first = getattr(fp, "FirstParamUILabelNameID", None)
            if num and first:
                for offset in range(num):
                    nid = first + offset
                    if nid not in base_targets:
                        targets.append(
                            (fr.FeatureTag, f"ParamLabel[{offset}]", nid))
        ids = [t[2] for t in targets]
        assert len(ids) == len(set(ids)), (
            f"Latin-derived FeatureParams nameIDs are not pairwise "
            f"unique: targets={targets}"
        )

    def test_all_latin_labels_resolve_correctly(self, merged_path):
        """Every Latin ssXX label still resolves to its original Inter
        string after the multi-collision remap."""
        inter = TTFont(EN_VAR)
        inter_ssxx = {}
        for fr in inter["GSUB"].table.FeatureList.FeatureRecord:
            if not fr.FeatureTag.startswith("ss"):
                continue
            fp = fr.Feature.FeatureParams
            if fp is None:
                continue
            label = inter["name"].getDebugName(fp.UINameID)
            if label:
                inter_ssxx[fr.FeatureTag] = label

        merged = TTFont(merged_path)
        mismatches = []
        for fr in merged["GSUB"].table.FeatureList.FeatureRecord:
            if not fr.FeatureTag.startswith("ss"):
                continue
            fp = fr.Feature.FeatureParams
            if fp is None:
                continue
            inter_label = inter_ssxx.get(fr.FeatureTag)
            if inter_label is None:
                continue
            merged_label = merged["name"].getDebugName(fp.UINameID)
            if merged_label != inter_label:
                mismatches.append(
                    (fr.FeatureTag, inter_label, merged_label))
        assert not mismatches, (
            f"Latin labels diverged after multi-collision remap: "
            f"{mismatches}"
        )


class TestSizeFeatureSubfamilyNameIDRemap:
    """`size` features expose their subfamily label through
    `FeatureParamsSize.SubfamilyNameID`. The allocator must
    treat that field exactly like UINameID — collect it, reserve
    it across the Latin namespace, and rewrite it after collisions.
    Inter doesn't ship a `size` feature, so the test patches one in
    by replacing the existing FeatureParams of an unused tag."""

    @pytest.fixture(scope="class")
    def merged_path(self, tmp_path_factory):
        from fontTools.ttLib.tables import otTables

        inter = TTFont(EN_VAR)
        existing = sorted(_all_lat_feat_label_nameids(inter))
        size_subfamily_id = max(existing or [255]) + 10
        # Add the Inter-side label.
        inter["name"].setName("Inter optical size",
                              size_subfamily_id, 3, 1, 0x409)

        # Inject a `size` FeatureRecord pointing at that nameID.
        gsub = inter["GSUB"].table
        size_fp = otTables.FeatureParamsSize()
        size_fp.DesignSize = 100
        size_fp.SubfamilyID = 1
        size_fp.SubfamilyNameID = size_subfamily_id
        size_fp.RangeStart = 0
        size_fp.RangeEnd = 0
        size_feat = otTables.Feature()
        size_feat.FeatureParams = size_fp
        size_feat.LookupListIndex = []
        size_feat.LookupCount = 0
        size_rec = otTables.FeatureRecord()
        size_rec.FeatureTag = "size"
        size_rec.Feature = size_feat
        gsub.FeatureList.FeatureRecord.append(size_rec)
        gsub.FeatureList.FeatureCount = len(gsub.FeatureList.FeatureRecord)
        # Wire the new size feature into latn DefaultLangSys so it
        # actually ships in the merged font.
        new_feat_idx = len(gsub.FeatureList.FeatureRecord) - 1
        for sr in gsub.ScriptList.ScriptRecord:
            if sr.ScriptTag == "latn":
                ds = sr.Script.DefaultLangSys
                if ds:
                    ds.FeatureIndex = list(ds.FeatureIndex or []) + [new_feat_idx]
                    ds.FeatureCount = len(ds.FeatureIndex)
                break

        tmp = tmp_path_factory.mktemp("size_subfamily")
        latin_path = str(tmp / "InterPatched.ttf")
        inter.save(latin_path)

        # Patch Noto so its name table holds the same nameID — the
        # allocator must remap.
        jp = TTFont(JP_VAR)
        jp["name"].setName("Noto colliding size label",
                           size_subfamily_id, 3, 1, 0x409)
        jp_path = str(tmp / "JpPatched.ttf")
        jp.save(jp_path)

        out = tmp / "merged.ttf"
        config = {
            "subFont": {"path": latin_path, "scale": 1.0,
                        "baselineOffset": 0,
                        "axes": [
                            {"tag": "opsz", "currentValue": 14},
                            {"tag": "wght", "currentValue": 400},
                        ]},
            "baseFont": {"path": jp_path, "scale": 1.0,
                         "baselineOffset": 0,
                         "axes": [{"tag": "wght", "currentValue": 400}]},
            "output": {"familyName": "TestSizeSubfamily"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out), size_subfamily_id

    def test_size_subfamily_label_remapped_and_resolves(self, merged_path):
        path, original_id = merged_path
        merged = TTFont(path)
        size_fp = None
        for fr in merged["GSUB"].table.FeatureList.FeatureRecord:
            if fr.FeatureTag == "size":
                size_fp = fr.Feature.FeatureParams
                break
        assert size_fp is not None, "merged font lost size FeatureParams"
        new_id = getattr(size_fp, "SubfamilyNameID", None)
        assert new_id is not None and new_id != 0, (
            f"size FeatureParams.SubfamilyNameID missing: {new_id}"
        )
        # On collision the allocator should pick a fresh ID.
        assert new_id != original_id, (
            f"size SubfamilyNameID was not remapped despite colliding "
            f"with the base name table (still {original_id})"
        )
        label = merged["name"].getDebugName(new_id)
        assert label == "Inter optical size", (
            f"size SubfamilyNameID resolves to {label!r}, expected "
            f"Inter's 'Inter optical size'"
        )
        # And the base record at the original ID stays put.
        base_label = merged["name"].getDebugName(original_id)
        assert base_label == "Noto colliding size label", (
            f"base nameID {original_id} text changed: "
            f"got {base_label!r}"
        )


class TestOverlappingCvRangesRelocateTogether:
    """Two cvXX features with overlapping but non-identical
    `FirstParamUILabelNameID..+NumNamedParameters` ranges must move as
    a single unioned block when any of their IDs collides — otherwise
    a longer cv whose start was already remapped (because a shorter cv
    occupied the same first ID) has its tail IDs left at the original
    positions, and `first + offset` reads point at empty / wrong
    records (codex finding)."""

    @pytest.fixture(scope="class")
    def merged_path(self, tmp_path_factory):
        from fontTools.ttLib.tables import otTables

        inter = TTFont(EN_VAR)
        existing = sorted(_all_lat_feat_label_nameids(inter))
        first_param_id = max(existing or [255]) + 10  # leave a gap

        # Two cv features starting at the same nameID but with
        # different lengths.
        short_labels = ["cv01 short alt 1", "cv01 short alt 2",
                        "cv01 short alt 3"]
        long_labels = ["cv02 long alt 1", "cv02 long alt 2",
                       "cv02 long alt 3", "cv02 long alt 4",
                       "cv02 long alt 5"]
        # Union of both ranges is first..first+5 (5 IDs). Use the long
        # set to seed the name table; the short set's first 3 IDs reuse
        # the same records.
        for offset, text in enumerate(long_labels):
            inter["name"].setName(text, first_param_id + offset,
                                  3, 1, 0x409)
        # Override the first 3 IDs with the short-set labels — but keep
        # the long set's tail alive at offsets 3 and 4.
        for offset, text in enumerate(short_labels):
            inter["name"].setName(text, first_param_id + offset,
                                  3, 1, 0x409)

        gsub = inter["GSUB"].table
        cv_first = next(
            (fr for fr in gsub.FeatureList.FeatureRecord
             if fr.FeatureTag == "cv01"),
            None,
        )
        cv_second = next(
            (fr for fr in gsub.FeatureList.FeatureRecord
             if fr.FeatureTag == "cv02"),
            None,
        )
        assert cv_first and cv_second, "fixture must have cv01 + cv02"
        for cv, num in ((cv_first, 3), (cv_second, 5)):
            fp = cv.Feature.FeatureParams
            assert fp is not None
            if hasattr(fp, "NumNamedParameters"):
                fp.NumNamedParameters = num
            else:
                fp.NamedParameters = num
            fp.FirstParamUILabelNameID = first_param_id

        tmp = tmp_path_factory.mktemp("cv_overlap_atomic")
        latin_path = str(tmp / "InterPatched.ttf")
        inter.save(latin_path)

        # Patch Noto so that one ID inside the overlap collides.
        jp = TTFont(JP_VAR)
        jp["name"].setName("Noto colliding label",
                           first_param_id, 3, 1, 0x409)
        jp_path = str(tmp / "JpPatched.ttf")
        jp.save(jp_path)

        out = tmp / "merged.ttf"
        config = {
            "subFont": {"path": latin_path, "scale": 1.0,
                        "baselineOffset": 0,
                        "axes": [
                            {"tag": "opsz", "currentValue": 14},
                            {"tag": "wght", "currentValue": 400},
                        ]},
            "baseFont": {"path": jp_path, "scale": 1.0,
                         "baselineOffset": 0,
                         "axes": [{"tag": "wght", "currentValue": 400}]},
            "output": {"familyName": "TestCvOverlap"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out), short_labels, long_labels

    def test_long_cv_tail_labels_resolve(self, merged_path):
        path, _, long_labels = merged_path
        merged = TTFont(path)
        cv02_fp = None
        for fr in merged["GSUB"].table.FeatureList.FeatureRecord:
            if fr.FeatureTag == "cv02":
                cv02_fp = fr.Feature.FeatureParams
                break
        assert cv02_fp is not None
        first = cv02_fp.FirstParamUILabelNameID
        num = (getattr(cv02_fp, "NumNamedParameters", None)
               or getattr(cv02_fp, "NamedParameters", None))
        assert num == 5, f"cv02 NumNamedParameters changed: {num}"
        for offset in (3, 4):  # tail offsets that codex flagged
            actual = merged["name"].getDebugName(first + offset)
            expected = long_labels[offset]
            assert actual == expected, (
                f"cv02 ParamLabel[{offset}] = {actual!r}, expected "
                f"{expected!r}. Overlapping cv ranges were not unioned, "
                f"so cv02's tail IDs were left behind at the original "
                f"position when cv01 took the shorter mapped block."
            )


class TestCvParameterLabelRangeAtomic:
    """`cvXX` features expose a contiguous block of per-variant labels
    at `FirstParamUILabelNameID .. FirstParamUILabelNameID + NumNamedParameters - 1`.
    The font reader resolves each label as `FirstParamUILabelNameID + offset`,
    so the entire range must move together — relocating just the IDs
    that happen to collide leaves the param-label block fragmented
    (some labels at the original position, others moved elsewhere).

    Inter doesn't ship a cv feature with `NumNamedParameters` set, so
    the test patches Inter in memory: it carves a fake `cv01` whose
    `NumNamedParameters` covers a contiguous block, and patches Noto
    so that *one* of those range IDs collides. After merge the entire
    cv01 range must be relocated as a unit, so every offset still
    resolves to its original Inter label."""

    PARAM_COUNT = 3
    PARAM_LABELS = [
        "cv01 alt 1",
        "cv01 alt 2",
        "cv01 alt 3",
    ]

    @pytest.fixture(scope="class")
    def merged_path(self, tmp_path_factory):
        from fontTools.ttLib.tables import otTables

        # Pick a fresh nameID range outside Inter's existing
        # FeatureParams namespace so we don't accidentally clash with
        # other Latin labels.
        inter = TTFont(EN_VAR)
        existing = sorted(_all_lat_feat_label_nameids(inter))
        first_param_id = max(existing or [255]) + 10  # leave a gap

        # Add the param-label name records to Inter and rewire its
        # `cv01` FeatureRecord (or create one) to point at them.
        for offset, text in enumerate(self.PARAM_LABELS):
            inter["name"].setName(text, first_param_id + offset,
                                  3, 1, 0x409)
        gsub = inter["GSUB"].table
        cv01_fr = next(
            (fr for fr in gsub.FeatureList.FeatureRecord
             if fr.FeatureTag == "cv01"),
            None,
        )
        assert cv01_fr is not None and cv01_fr.Feature.FeatureParams, (
            "Inter fixture must define cv01 with FeatureParams"
        )
        fp = cv01_fr.Feature.FeatureParams
        # fontTools' FeatureParamsCharacterVariants writes
        # NumNamedParameters; older versions used NamedParameters.
        if hasattr(fp, "NumNamedParameters"):
            fp.NumNamedParameters = self.PARAM_COUNT
        else:
            fp.NamedParameters = self.PARAM_COUNT
        fp.FirstParamUILabelNameID = first_param_id

        tmp = tmp_path_factory.mktemp("cv_param_atomic")
        latin_path = str(tmp / "InterPatched.ttf")
        inter.save(latin_path)

        # Make Noto collide on the *middle* ID of the range. Without
        # atomic allocation, the allocator will move only that single
        # ID and the param block will fragment.
        jp = TTFont(JP_VAR)
        collide_nid = first_param_id + 1
        jp["name"].setName("Noto fake collision",
                           collide_nid, 3, 1, 0x409)
        jp_path = str(tmp / "JpPatched.ttf")
        jp.save(jp_path)

        out = tmp / "merged.ttf"
        config = {
            "subFont": {"path": latin_path, "scale": 1.0,
                        "baselineOffset": 0,
                        "axes": [
                            {"tag": "opsz", "currentValue": 14},
                            {"tag": "wght", "currentValue": 400},
                        ]},
            "baseFont": {"path": jp_path, "scale": 1.0,
                         "baselineOffset": 0,
                         "axes": [{"tag": "wght", "currentValue": 400}]},
            "output": {"familyName": "TestCvAtomic"},
            "export": {"path": {"font": str(out)}},
        }
        mf.merge_fonts(config)
        return str(out), first_param_id

    def test_param_label_range_stays_contiguous_and_resolves(
            self, merged_path):
        path, original_first = merged_path
        merged = TTFont(path)
        cv01_fp = None
        for fr in merged["GSUB"].table.FeatureList.FeatureRecord:
            if fr.FeatureTag == "cv01":
                cv01_fp = fr.Feature.FeatureParams
                break
        assert cv01_fp is not None, "merged font lost cv01 FeatureParams"

        first = cv01_fp.FirstParamUILabelNameID
        num = (getattr(cv01_fp, "NumNamedParameters", None)
               or getattr(cv01_fp, "NamedParameters", None))
        assert num == self.PARAM_COUNT, (
            f"cv01 NumNamedParameters changed: {num} vs {self.PARAM_COUNT}"
        )

        # Each label position must resolve to the original Inter text.
        for offset, expected in enumerate(self.PARAM_LABELS):
            actual = merged["name"].getDebugName(first + offset)
            assert actual == expected, (
                f"cv01 ParamLabel[{offset}] = {actual!r}, expected "
                f"{expected!r}. Range was fragmented across the "
                f"collision (FirstParamUILabelNameID was {original_first}, "
                f"merged FirstParamUILabelNameID is now {first})."
            )

    def test_no_label_in_range_collides_with_other_feature_params(
            self, merged_path):
        """The atomic relocation must also avoid landing on another
        FeatureParams' nameID."""
        path, _ = merged_path
        merged = TTFont(path)
        cv01_range = None
        other_ids = set()
        for fr in merged["GSUB"].table.FeatureList.FeatureRecord:
            fp = fr.Feature.FeatureParams
            if fp is None:
                continue
            num = (getattr(fp, "NumNamedParameters", None)
                   or getattr(fp, "NamedParameters", None))
            first = getattr(fp, "FirstParamUILabelNameID", None)
            if fr.FeatureTag == "cv01" and num and first:
                cv01_range = set(range(first, first + num))
                continue
            for attr in ("UINameID", "FeatUILabelNameID",
                         "FeatUITooltipTextNameID", "SampleTextNameID",
                         "SubfamilyNameID"):
                nid = getattr(fp, attr, None)
                if nid:
                    other_ids.add(nid)
            if num and first:
                other_ids |= set(range(first, first + num))
        assert cv01_range is not None, "cv01 not found in merged font"
        overlap = cv01_range & other_ids
        assert not overlap, (
            f"cv01 ParamLabel range overlaps with other FeatureParams "
            f"nameIDs: {overlap}"
        )
