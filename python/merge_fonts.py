#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Composite font merge engine.

Merges a sub font (e.g. Latin, kana) with a base font (e.g. CJK) into
a single font file. Sub-font glyphs and their OpenType features replace
the base font's corresponding glyphs and features.

Usage (package mode — full export with artifacts):
    cat config.json | python3 merge_fonts.py

    config.json must include "export.dir".
    Outputs a JSON manifest on stdout with paths to all generated files.

Usage (single-file mode):
    echo '{"baseFont": {...}, "export": {"fontPath": "/out/font.ttf"}}' | python3 merge_fonts.py

    Outputs the font file path on stdout.

Progress: JSON lines on stderr.
"""

import copy
import datetime
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from typing import NamedTuple

from fontTools.misc.timeTools import timestampNow
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables.otBase import USE_HARFBUZZ_REPACKER
from fontTools.pens.pointPen import SegmentToPointPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen



def progress(stage: str, percent: int, message: str):
    """Emit progress to stderr as JSON line."""
    print(json.dumps({
        "stage": stage,
        "percent": percent,
        "message": message,
    }), file=sys.stderr, flush=True)


def _disable_harfbuzz_repacker(font: TTFont):
    """Keep final GSUB/GPOS serialization in fontTools' pure Python path.

    hb.repack can preserve valid tables, but for large merged GPOS tables it
    may emit CJK kern PairPos lookups behind ExtensionPos. Adobe apps appear
    not to apply those CJK metrics kern pairs, so prefer direct PairPos output.
    """
    font.cfg[USE_HARFBUZZ_REPACKER] = False


def _has_extension_non_latin_kern(font: TTFont, lat_glyph_names: set) -> bool:
    """Return True when a saved font wraps non-Latin kern PairPos in ExtensionPos."""
    gpos = font.get("GPOS")
    if not gpos or not getattr(gpos, "table", None):
        return False
    table = gpos.table
    if not table.LookupList or not table.FeatureList:
        return False

    for feature_record in table.FeatureList.FeatureRecord:
        if feature_record.FeatureTag != "kern":
            continue
        for lookup_index in feature_record.Feature.LookupListIndex:
            lookup = table.LookupList.Lookup[lookup_index]
            if lookup.LookupType != 9:
                continue
            for subtable in lookup.SubTable:
                if getattr(subtable, "ExtensionLookupType", None) != 2:
                    continue
                pairpos = getattr(subtable, "ExtSubTable", None)
                coverage = getattr(pairpos, "Coverage", None)
                glyphs = getattr(coverage, "glyphs", None) if coverage else None
                if glyphs and any(g not in lat_glyph_names for g in glyphs):
                    return True
    return False


def _save_with_adobe_kern_compat(font: TTFont, output_path: str,
                                 lat_glyph_names: set):
    """Save normally, then fall back only if hb.repack hides CJK kern."""
    font.save(output_path)

    saved = TTFont(output_path)
    try:
        needs_fallback = _has_extension_non_latin_kern(saved, lat_glyph_names)
    finally:
        saved.close()

    if needs_fallback:
        _disable_harfbuzz_repacker(font)
        font.save(output_path)


# ---------------------------------------------------------------------------
# Weight / width name tables (mirrors shared/constants.ts)
# ---------------------------------------------------------------------------

WEIGHT_MAP = {
    100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular",
    500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold",
    900: "Black",
}

WIDTH_MAP = {
    1: "UltraCondensed", 2: "ExtraCondensed", 3: "Condensed",
    4: "SemiCondensed", 5: "", 6: "SemiExpanded", 7: "Expanded",
    8: "ExtraExpanded", 9: "UltraExpanded",
}


def compute_style_name(weight: int, italic: bool, width: int) -> str:
    """Compute OpenType style name, e.g. 'SemiBold Italic'."""
    width_name = WIDTH_MAP.get(width, "")
    weight_name = WEIGHT_MAP.get(weight, "Regular")
    parts = []
    if width_name:
        parts.append(width_name)
    parts.append(weight_name)
    if italic:
        parts.append("Italic")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# PostScript name (nameID 6) sanitization and validation
# ---------------------------------------------------------------------------

# Per OpenType spec, a PostScript name must consist of printable ASCII
# (U+0021-U+007E) minus the ten characters below, and be at most 63 bytes.
_PS_NAME_FORBIDDEN = set("[](){}<>/%")
_PS_NAME_MAX_BYTES = 63


def sanitize_postscript_name(name: str) -> str:
    """Strip characters not allowed in a PostScript name.

    Allowed: printable ASCII 33-126 minus [](){}<>/% (and space, which
    falls outside the printable-ASCII range). Result is truncated to 63
    bytes to match the spec limit for nameID 6.
    """
    result = []
    for c in name:
        cp = ord(c)
        if 33 <= cp <= 126 and c not in _PS_NAME_FORBIDDEN:
            result.append(c)
    return "".join(result)[:_PS_NAME_MAX_BYTES]


def validate_postscript_name(name: str) -> None:
    """Raise ValueError if name is not a spec-compliant PostScript name.

    A valid name is non-empty, uses only printable ASCII 33-126 minus
    [](){}<>/% (space is excluded as it is outside that range), and is
    at most 63 bytes long.
    """
    if not name:
        raise ValueError("PostScript name is empty")
    if len(name.encode("utf-8")) > _PS_NAME_MAX_BYTES:
        raise ValueError(
            f"PostScript name exceeds {_PS_NAME_MAX_BYTES} bytes: {name!r}"
        )
    for c in name:
        cp = ord(c)
        if not (33 <= cp <= 126) or c in _PS_NAME_FORBIDDEN:
            raise ValueError(
                f"PostScript name contains invalid character {c!r} "
                f"(U+{cp:04X}): {name!r}"
            )


# ---------------------------------------------------------------------------
# Export artifact generators
# ---------------------------------------------------------------------------

_OFL_BODY = """\
This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
https://openfontlicense.org

-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
"""


def build_ofl_text(config: dict) -> str:
    """Build OFL.txt content from merge config."""
    output = config.get("output") or {}
    copyrights = []
    for key in ("baseFont", "subFont"):
        src = config.get(key)
        if not src:
            continue
        c = (src.get("copyright") or "").strip()
        if c and c not in copyrights:
            copyrights.append(c)
    user_copyright = (output.get("copyright") or "").strip()
    if user_copyright and user_copyright not in copyrights:
        copyrights.append(user_copyright)

    if copyrights:
        copyright_line = "\n".join(copyrights)
    else:
        year = datetime.datetime.now().year
        family = output.get("familyName", "Font")
        copyright_line = f"Copyright (c) {year} {family} Authors"

    return f"{copyright_line}\n\n{_OFL_BODY}"


def build_settings_text(config: dict) -> str:
    """Build Settings.txt content from merge config."""
    output = config.get("output") or {}
    weight = output.get("weight", 400)
    italic = output.get("italic", False)
    width = output.get("width", 5)
    style = compute_style_name(weight, italic, width)
    family = output.get("familyName", "")

    base = config["baseFont"]
    lines = [
        f"{family} {style}",
        "",
        "-",
        "",
        f"[Base Font] {base.get('familyName', '')} {base.get('styleName', '')}",
        f"\u00b7 Scale: {base.get('scale', 1.0)}",
        f"\u00b7 Baseline Offset: {base.get('baselineOffset', 0)}",
    ]
    for a in base.get("axes", []):
        if a.get("name"):
            lines.append(f"\u00b7 {a['name']} ({a.get('tag', '')}): {a.get('currentValue', '')}")
    lines.append(f"\u00b7 Path: {base.get('path', '')}")

    lat = config.get("subFont")
    if lat:
        lines.append("")
        lines.append(f"[Sub Font] {lat.get('familyName', '')} {lat.get('styleName', '')}")
        lines.append(f"\u00b7 Scale: {lat.get('scale', 1.0)}")
        lines.append(f"\u00b7 Baseline Offset: {lat.get('baselineOffset', 0)}")
        for a in lat.get("axes", []):
            if a.get("name"):
                lines.append(f"\u00b7 {a['name']} ({a.get('tag', '')}): {a.get('currentValue', '')}")
        lines.append(f"\u00b7 Path: {lat.get('path', '')}")

    lines.extend(["", "-", ""])
    lines.append("Built with OFL Font Baker by Yamato Iizuka")
    lines.append("https://github.com/yamatoiizuka/ofl-font-baker")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Output directory and extension helpers
# ---------------------------------------------------------------------------

def detect_sfnt_ext(font_path: str) -> str:
    """Detect output extension by inspecting sfnt magic number."""
    lower = font_path.lower()
    if lower.endswith(".woff2") or lower.endswith(".woff"):
        return "otf" if lower.endswith(".otf") else "ttf"
    try:
        with open(font_path, "rb") as f:
            magic = f.read(4)
        return "otf" if magic == b"OTTO" else "ttf"
    except OSError:
        return "otf" if lower.endswith(".otf") else "ttf"


def prepare_output_dir(dir_path: str, overwrite: bool) -> str:
    """Create the output directory. Returns the directory path."""
    if os.path.exists(dir_path):
        if not overwrite:
            folder_name = os.path.basename(dir_path)
            raise FileExistsError(
                f'Output folder already exists: "{folder_name}". '
                f"Pass overwrite=true to replace."
            )
        shutil.rmtree(dir_path)
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


_PACKAGE_DEFAULTS = {
    "overwrite": False,
    "bundleInputFonts": False,
}


def resolve_package_options(config: dict) -> dict:
    """Resolve package-mode options with defaults from export.package."""
    export = config.get("export") or {}
    raw = export.get("package") or {}
    return dict(_PACKAGE_DEFAULTS, **{k: v for k, v in raw.items()
                                       if k in _PACKAGE_DEFAULTS})


def bundle_input_fonts(config: dict, folder_path: str) -> dict:
    """Copy input fonts to source/ and return a path mapping.

    Returns a dict mapping original absolute paths to relative paths
    within the output directory.
    """
    source_dir = os.path.join(folder_path, "source")
    os.makedirs(source_dir, exist_ok=True)
    path_map = {}
    for key in ("baseFont", "subFont"):
        src = config.get(key)
        if not src or not src.get("path"):
            continue
        src_path = src["path"]
        file_name = os.path.basename(src_path)
        dst_path = os.path.join(source_dir, file_name)
        shutil.copy2(src_path, dst_path)
        path_map[src_path] = f"./source/{file_name}"
    return path_map


def build_export_config(config: dict, path_map: dict = None) -> dict:
    """Build ExportConfig.json content from merge config.

    If path_map is provided (bundleInputFonts=true), font paths are
    replaced with relative paths.
    """
    def _font_entry(key):
        src = config.get(key)
        if not src:
            return None
        entry = {
            "path": (path_map or {}).get(src.get("path", ""), src.get("path", "")),
            "scale": src.get("scale", 1.0),
            "baselineOffset": src.get("baselineOffset", 0),
        }
        axes = src.get("axes")
        if axes:
            entry["axes"] = axes
        # Persist sub-font-only options so re-running the saved config
        # reproduces the same merge. Without this, a downstream user that
        # protected CJK-conventional symbols via excludeCodepoints would
        # silently lose that protection on re-export.
        if key == "subFont":
            exclude = src.get("excludeCodepoints")
            if exclude:
                entry["excludeCodepoints"] = list(exclude)
        return entry

    result = {}
    base_entry = _font_entry("baseFont")
    if base_entry:
        result["baseFont"] = base_entry
    sub_entry = _font_entry("subFont")
    if sub_entry:
        result["subFont"] = sub_entry

    output = config.get("output") or {}
    for field in ("familyName", "postScriptName", "version", "weight", "italic",
                  "width", "manufacturer", "manufacturerURL",
                  "copyright", "trademark", "upm", "metadataMode",
                  "hinting"):
        val = output.get(field)
        if val is not None:
            result.setdefault("output", {})[field] = val

    export = config.get("export") or {}
    export_out = {}
    pkg = export.get("package")
    if pkg:
        pkg_out = {"dir": pkg.get("dir", "")}
        pkg_out.update(resolve_package_options(config))
        export_out["package"] = pkg_out
    path = export.get("path")
    if path:
        export_out["path"] = dict(path)
    if export_out:
        result["export"] = export_out
    return result


# ---------------------------------------------------------------------------
# Glyph name mapping helpers
# ---------------------------------------------------------------------------

def build_cmap(font: TTFont) -> dict:
    """Build codepoint -> glyph name mapping from a font's best cmap."""
    cmap_table = font.getBestCmap()
    return dict(cmap_table) if cmap_table else {}


_CODEPOINT_PATTERN = re.compile(r"^U\+([0-9A-Fa-f]{1,6})$")


def _parse_codepoint_token(token) -> int:
    """Parse a single codepoint token into an int.

    Accepts ``"U+XXXX"`` (1-6 hex digits) or a non-negative integer.
    """
    if isinstance(token, bool):
        # bool is an int subclass — reject explicitly so True/False don't
        # silently become codepoints 1 / 0.
        raise ValueError(f"Invalid codepoint: {token!r}")
    if isinstance(token, int):
        cp = token
    elif isinstance(token, str):
        m = _CODEPOINT_PATTERN.match(token.strip())
        if not m:
            raise ValueError(
                f"Invalid codepoint {token!r}: expected 'U+XXXX' or integer"
            )
        cp = int(m.group(1), 16)
    else:
        raise ValueError(f"Invalid codepoint: {token!r}")
    if cp < 0 or cp > 0x10FFFF:
        raise ValueError(f"Codepoint out of range: U+{cp:04X}")
    return cp


def parse_codepoint_list(values) -> set:
    """Parse a config codepoint list into a set of int codepoints.

    Accepted entry forms (any mix in the list):
        "U+2460"            single codepoint
        "U+2460-U+24FF"     inclusive range
        0x2460              raw integer
    """
    if values is None:
        return set()
    if not isinstance(values, (list, tuple)):
        raise ValueError(
            f"excludeCodepoints must be a list, got {type(values).__name__}"
        )
    if not values:
        return set()
    result = set()
    for entry in values:
        if isinstance(entry, str) and "-" in entry and entry.strip().startswith("U+"):
            parts = entry.split("-", 1)
            start = _parse_codepoint_token(parts[0])
            end = _parse_codepoint_token(parts[1])
            if end < start:
                raise ValueError(
                    f"Invalid codepoint range {entry!r}: end < start"
                )
            result.update(range(start, end + 1))
        else:
            result.add(_parse_codepoint_token(entry))
    return result


# ---------------------------------------------------------------------------
# CFF to TrueType conversion for individual glyphs
# ---------------------------------------------------------------------------

def convert_cff_glyphs_to_tt(src_font: TTFont, dst_font: TTFont,
                              glyph_names: list, scale: float, dy: float,
                              on_progress=None, copied: set = None,
                              name_map: dict = None):
    """
    Batch-convert CFF glyphs from src_font into dst_font's glyf table.
    copied: optional set of destination names already owned by the sub font.
    name_map: optional dict mapping src glyph names to dst glyph names.
    """
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.transformPen import TransformPen

    src_gs = src_font.getGlyphSet()
    transform = (scale, 0, 0, scale, 0, dy)

    total = len(glyph_names)
    for i, glyph_name in enumerate(glyph_names):
        if glyph_name not in src_gs:
            continue

        dst_name = name_map.get(glyph_name, glyph_name) if name_map else glyph_name

        tt_pen = TTGlyphPen(None)
        cu2qu_pen = Cu2QuPen(tt_pen, max_err=1.0, reverse_direction=True)
        transform_pen = TransformPen(cu2qu_pen, transform)

        try:
            src_gs[glyph_name].draw(transform_pen)
            glyph = tt_pen.glyph()
        except Exception:
            from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph
            glyph = TTGlyph()

        dst_font["glyf"][dst_name] = glyph
        if copied is not None:
            copied.add(dst_name)

        if glyph_name in src_font["hmtx"].metrics:
            orig_aw, orig_lsb = src_font["hmtx"].metrics[glyph_name]
            dst_font["hmtx"].metrics[dst_name] = (
                int(round(orig_aw * scale)),
                int(round(orig_lsb * scale)),
            )

        if on_progress and (i + 1) % 200 == 0:
            on_progress(i + 1, total)


# ---------------------------------------------------------------------------
# TrueType to CFF conversion
# ---------------------------------------------------------------------------

def convert_tt_glyphs_to_cff(src_font: TTFont, dst_font: TTFont,
                              glyph_names: list, scale: float, dy: float,
                              copied: set, existing_names: set,
                              name_map: dict = None):
    """
    Convert TrueType glyphs from src_font into dst_font's CFF table.
    name_map: optional dict mapping src glyph names to dst glyph names.
    """
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.pens.reverseContourPen import ReverseContourPen

    src_gs = src_font.getGlyphSet()
    dst_cff_td = dst_font["CFF "].cff.topDictIndex[0]
    if hasattr(dst_cff_td, 'Private') and dst_cff_td.Private:
        private = dst_cff_td.Private
    elif hasattr(dst_cff_td, 'FDArray') and dst_cff_td.FDArray:
        private = dst_cff_td.FDArray[0].Private
    else:
        private = None
    global_subrs = dst_font["CFF "].cff.GlobalSubrs
    transform = (scale, 0, 0, scale, 0, dy)

    for glyph_name in glyph_names:
        dst_name = name_map.get(glyph_name, glyph_name) if name_map else glyph_name
        if dst_name in copied:
            continue
        copied.add(dst_name)

        if glyph_name not in src_gs:
            continue

        orig_aw = src_font["hmtx"].metrics.get(glyph_name, (0, 0))[0]
        width = int(round(orig_aw * scale))

        t2_pen = T2CharStringPen(width, None)
        # Reverse contour direction: TT uses outer-CW, CFF uses outer-CCW.
        # Without this, converted glyphs render with inverted fills.
        transform_pen = TransformPen(ReverseContourPen(t2_pen), transform)

        try:
            src_gs[glyph_name].draw(transform_pen)
            charstring = t2_pen.getCharString()
        except Exception:
            from fontTools.misc.psCharStrings import T2CharString
            charstring = T2CharString()

        charstring.private = private
        charstring.globalSubrs = global_subrs

        cs = dst_cff_td.CharStrings
        if dst_name in cs.charStrings:
            cs[dst_name] = charstring
        elif cs.charStringsAreIndexed:
            next_idx = len(cs.charStringsIndex)
            cs.charStringsIndex.append(charstring)
            cs.charStrings[dst_name] = next_idx
        else:
            cs.charStrings[dst_name] = charstring

        if glyph_name in src_font["hmtx"].metrics:
            orig_aw, orig_lsb = src_font["hmtx"].metrics[glyph_name]
            dst_font["hmtx"].metrics[dst_name] = (
                int(round(orig_aw * scale)),
                int(round(orig_lsb * scale)),
            )

        existing_names.add(dst_name)


# ---------------------------------------------------------------------------
# CFF (Type 2 CharString) hint-preserving affine transform
# ---------------------------------------------------------------------------

# Operators that introduce a stack-clearing point AND can carry a leading
# advance-width operand at the start of a CharString.
_T2_STACK_CLEARING = frozenset({
    "hstem", "hstemhm", "vstem", "vstemhm",
    "cntrmask", "hintmask",
    "hmoveto", "vmoveto", "rmoveto",
    "endchar",
})


def _t2_strip_width(operands: list, op: str) -> tuple:
    """Detect and strip a leading width operand from the first stack-clearing op.

    Returns (width_or_None, remaining_operands).
    The advance width is encoded as the first operand of the first stack-clearing
    operator when the actual operand count is one greater than the operator's
    expected modulo.
    """
    n = len(operands)
    has_width = False
    if op in ("hstem", "hstemhm", "vstem", "vstemhm"):
        # Stem ops take pairs (y dy / x dx). Odd count → leading width present.
        has_width = (n % 2) == 1
    elif op in ("cntrmask", "hintmask"):
        # Operands form an implicit vstem (pairs). Odd count → width present.
        has_width = (n % 2) == 1
    elif op == "hmoveto" or op == "vmoveto":
        # Expects 1 operand. 2 → width + dx/dy.
        has_width = n == 2
    elif op == "rmoveto":
        # Expects 2 operands. 3 → width + dx + dy.
        has_width = n == 3
    elif op == "endchar":
        # Optional 4 SEAC operands; 1 or 5 → width present.
        has_width = n in (1, 5)
    if has_width:
        return operands[0], operands[1:]
    return None, operands


def transform_t2_program(program: list, scale: float, dy_offset: float,
                         src_nominal_width: float = 0,
                         dst_nominal_width: float = 0):
    """Apply (scale, dy_offset) affine to a Type 2 CharString program in-place.

    Walks the program token list and rewrites operands so that:
        x' = x * scale
        y' = y * scale + dy_offset

    Hint operators (hstem*, vstem*, hintmask, cntrmask) and their masks are
    preserved as-is (operands transformed). Drawing operators use relative
    deltas, so a uniform scale just multiplies every operand. The baseline
    offset is absorbed into the absolute Y reference of the first hstem(hm)
    and the first move-to encountered.

    src_nominal_width / dst_nominal_width are the nominalWidthX values from
    the source / destination Private dicts so that an embedded leading width
    operand can be re-encoded against the destination's nominalWidthX.
    """
    result = []
    operands = []
    first_op_seen = False
    first_hstem_pending = True  # absolute-from-origin Y in first hstem
    first_move_pending = True   # baseline offset injected into first move-to

    def _scale_all(values):
        return [v * scale for v in values]

    for token in program:
        if isinstance(token, (int, float)):
            operands.append(token)
            continue

        if isinstance(token, bytes):
            # Mask byte payload for hintmask/cntrmask — copy unchanged.
            result.append(token)
            continue

        if not isinstance(token, str):
            continue

        op = token

        # Strip leading width on the very first stack-clearing operator
        if not first_op_seen and op in _T2_STACK_CLEARING:
            first_op_seen = True
            width_operand, operands = _t2_strip_width(operands, op)
            if width_operand is not None:
                # Decode absolute width from src, scale, re-encode for dst
                abs_width = width_operand + src_nominal_width
                new_abs_width = abs_width * scale
                new_width_operand = new_abs_width - dst_nominal_width
                result.append(int(round(new_width_operand)))

        if op in ("hstem", "hstemhm"):
            xformed = []
            for i, v in enumerate(operands):
                if i == 0 and first_hstem_pending:
                    xformed.append(int(round(v * scale + dy_offset)))
                    first_hstem_pending = False
                else:
                    xformed.append(int(round(v * scale)))
            result.extend(xformed)
            result.append(op)
            # Subsequent hstem operators (rare) use deltas relative to last edge
            first_hstem_pending = False

        elif op in ("vstem", "vstemhm"):
            # X coordinates: no Y translation, just scale.
            result.extend(int(round(v * scale)) for v in operands)
            result.append(op)

        elif op in ("hintmask", "cntrmask"):
            # If operands precede the mask, they're an implicit vstem set.
            if operands:
                # If this is BEFORE first hstem (no hstems at all in this glyph),
                # the implicit set is still a vstem — only X coords, no dy.
                result.extend(int(round(v * scale)) for v in operands)
            result.append(op)
            # Mask bytes (next token) will be appended as-is by the bytes branch.

        elif op == "rmoveto":
            dx, dy = operands[0], operands[1]
            new_dx = dx * scale
            new_dy = dy * scale
            if first_move_pending:
                new_dy += dy_offset
                first_move_pending = False
            result.append(int(round(new_dx)))
            result.append(int(round(new_dy)))
            result.append(op)

        elif op == "hmoveto":
            dx = operands[0]
            new_dx = dx * scale
            if first_move_pending and dy_offset != 0:
                # Convert to rmoveto so we can carry the baseline shift.
                result.append(int(round(new_dx)))
                result.append(int(round(dy_offset)))
                result.append("rmoveto")
                first_move_pending = False
            else:
                result.append(int(round(new_dx)))
                result.append(op)
                first_move_pending = False

        elif op == "vmoveto":
            dy = operands[0]
            new_dy = dy * scale
            if first_move_pending:
                new_dy += dy_offset
                first_move_pending = False
            result.append(int(round(new_dy)))
            result.append(op)

        else:
            # All other Type 2 operators (lineto/curveto/flex/endchar/...) take
            # purely relative-delta operands which uniform-scale safely.
            result.extend(int(round(v * scale)) for v in operands)
            result.append(op)

        operands = []

    return result


_T2_DRAW_OPS = frozenset({
    "rmoveto", "hmoveto", "vmoveto",
    "rlineto", "hlineto", "vlineto",
    "rrcurveto", "rcurveline", "rlinecurve",
    "hhcurveto", "vvcurveto", "hvcurveto", "vhcurveto",
    "flex", "hflex", "hflex1", "flex1",
    "endchar",
})


def _transform_prologue_and_width(program: list, scale: float, dy_offset: float,
                                   src_nominal: float, dst_nominal: float):
    """Walk the hint prologue of a T2 program and return ``(prologue, width)``.

    Stops at the first drawing operator. Stem edges are tracked in absolute
    coordinates so that two stems originally at the same Y/X land on the
    same rounded Y/X. Width is detected on the first stack-clearing operator
    and re-encoded against ``dst_nominal``.
    """
    out = []
    operands = []
    width_operand = None
    width_extracted = False

    hstem_abs = 0.0
    hstem_emit = 0
    vstem_abs = 0.0
    vstem_emit = 0

    def maybe_extract_width(op):
        nonlocal width_operand, width_extracted, operands
        if width_extracted or op not in _T2_STACK_CLEARING:
            return
        w, operands = _t2_strip_width(operands, op)
        if w is not None:
            abs_w = w + src_nominal
            new_abs_w = abs_w * scale
            width_operand = int(round(new_abs_w - dst_nominal))
        width_extracted = True

    def emit_hstem_edges():
        nonlocal hstem_abs, hstem_emit
        for v in operands:
            hstem_abs += v
            new_e = int(round(hstem_abs * scale + dy_offset))
            out.append(new_e - hstem_emit)
            hstem_emit = new_e

    def emit_vstem_edges():
        nonlocal vstem_abs, vstem_emit
        for v in operands:
            vstem_abs += v
            new_e = int(round(vstem_abs * scale))
            out.append(new_e - vstem_emit)
            vstem_emit = new_e

    for tok in program:
        if isinstance(tok, (int, float)):
            operands.append(tok)
            continue
        if isinstance(tok, bytes):
            out.append(tok)
            continue
        if not isinstance(tok, str):
            continue
        op = tok

        if op in _T2_DRAW_OPS:
            maybe_extract_width(op)
            return out, width_operand

        maybe_extract_width(op)

        if op in ("hstem", "hstemhm"):
            emit_hstem_edges()
            out.append(op)
        elif op in ("vstem", "vstemhm"):
            emit_vstem_edges()
            out.append(op)
        elif op in ("hintmask", "cntrmask"):
            if operands:
                # Implicit vstem set immediately before the mask.
                emit_vstem_edges()
            out.append(op)
        else:
            out.extend(int(round(v * scale)) for v in operands)
            out.append(op)

        operands = []

    return out, width_operand


def transform_t2_charstring(src_cs, scale: float, dy_offset: float,
                             dst_private, dst_global_subrs):
    """Return a new T2CharString equivalent to src_cs under (scale, dy_offset).

    Preserves CFF hint operators (hstem*, vstem*, hintmask, cntrmask).

    Outline points are rounded in *absolute* coordinates rather than per-delta,
    so two source points that share an absolute (x, y) are guaranteed to land
    on the same rounded (x, y) in the output. This avoids tiny gaps/notches
    that would otherwise appear at coincident vertices when the scale is not
    a divisor of 1 (e.g. UPM 2048 → 1000, ratio ≈ 0.488).

    Implementation: hint declarations from the source prologue are transformed
    in place, then the outline is redrawn through ``T2CharStringPen`` with each
    absolute coordinate snapped to int up-front. Glyphs that switch hint sets
    mid-outline (mid-glyph hintmask/cntrmask/stem) fall back to the per-delta
    walker, which preserves hints but cannot guarantee coincidence.
    """
    from fontTools.misc.psCharStrings import T2CharString
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    src_cs.decompile()
    src_program = list(src_cs.program)

    if any(isinstance(t, str) and t.endswith("subr") for t in src_program):
        raise ValueError("source CharString contains subroutine calls; "
                         "desubroutinize the source CFF before calling")

    src_private = src_cs.private
    src_nominal = getattr(src_private, "nominalWidthX", 0) if src_private else 0
    dst_nominal = getattr(dst_private, "nominalWidthX", 0) if dst_private else 0

    # Detect mid-glyph hint changes — pen-based redraw can't preserve them.
    seen_draw = False
    has_mid_hint = False
    for tok in src_program:
        if not isinstance(tok, str):
            continue
        if tok in _T2_DRAW_OPS and tok != "endchar":
            seen_draw = True
        elif seen_draw and tok in (
            "hintmask", "cntrmask", "hstem", "hstemhm", "vstem", "vstemhm",
        ):
            has_mid_hint = True
            break

    if has_mid_hint:
        new_program = transform_t2_program(
            src_program, scale, dy_offset,
            src_nominal_width=src_nominal,
            dst_nominal_width=dst_nominal,
        )
        return T2CharString(program=new_program, private=dst_private,
                            globalSubrs=dst_global_subrs)

    prologue, width_op = _transform_prologue_and_width(
        src_program, scale, dy_offset, src_nominal, dst_nominal,
    )

    pen = T2CharStringPen(None, None)

    def _xform(pt):
        return (
            int(round(pt[0] * scale)),
            int(round(pt[1] * scale + dy_offset)),
        )

    class _RoundingPen:
        def moveTo(self, pt):
            pen.moveTo(_xform(pt))

        def lineTo(self, pt):
            pen.lineTo(_xform(pt))

        def curveTo(self, *pts):
            pen.curveTo(*[_xform(p) for p in pts])

        def qCurveTo(self, *pts):
            pen.qCurveTo(*[_xform(p) for p in pts])

        def closePath(self):
            pen.closePath()

        def endPath(self):
            if hasattr(pen, "endPath"):
                pen.endPath()

        def addComponent(self, *args, **kwargs):
            pass  # CFF charstrings don't compose other glyphs at draw time

    src_cs.draw(_RoundingPen())

    pen_cs = pen.getCharString(private=dst_private, globalSubrs=dst_global_subrs)
    pen_cs.decompile()
    body = list(pen_cs.program)

    combined = []
    if width_op is not None:
        combined.append(width_op)
    combined.extend(prologue)
    combined.extend(body)

    return T2CharString(program=combined, private=dst_private,
                        globalSubrs=dst_global_subrs)


def transform_blue_values(values, scale: float, dy_offset: float):
    """Transform a Private-dict Blue zone list (Y coordinates) by affine."""
    if not values:
        return values
    return [int(round(v * scale + dy_offset)) for v in values]


def scale_stem_widths(values, scale: float):
    """Transform Private-dict StdHW/StdVW/StemSnapH/StemSnapV by uniform scale."""
    if values is None:
        return values
    if isinstance(values, (int, float)):
        return int(round(values * scale))
    return [int(round(v * scale)) for v in values]


def build_private_dict_from_latin(lat_font: TTFont, scale: float, dy_offset: float):
    """Construct a fresh CFF PrivateDict mirroring lat_font's, transformed.

    All Y-bearing zones (BlueValues, OtherBlues, Family*) are scaled and
    shifted; stem-width hints are scaled. nominalWidthX/defaultWidthX are
    reset to 0 so that downstream charstring writers can emit absolute widths.
    Returns a dict of attribute name → value suitable for setupCFF.
    """
    from fontTools.cffLib import PrivateDict as _PrivateDict  # noqa: F401

    src_priv = None
    if "CFF " in lat_font:
        td = lat_font["CFF "].cff.topDictIndex[0]
        if hasattr(td, "Private") and td.Private:
            src_priv = td.Private
        elif hasattr(td, "FDArray") and td.FDArray:
            src_priv = td.FDArray[0].Private

    out = {
        "defaultWidthX": 0,
        "nominalWidthX": 0,
    }

    if src_priv is None:
        return out

    blue_attrs = ("BlueValues", "OtherBlues", "FamilyBlues", "FamilyOtherBlues")
    for attr in blue_attrs:
        v = getattr(src_priv, attr, None)
        if v:
            out[attr] = transform_blue_values(v, scale, dy_offset)

    stem_attrs = ("StdHW", "StdVW", "StemSnapH", "StemSnapV")
    for attr in stem_attrs:
        v = getattr(src_priv, attr, None)
        if v is not None:
            out[attr] = scale_stem_widths(v, scale)

    passthrough = ("BlueScale", "BlueShift", "BlueFuzz",
                   "ForceBold", "LanguageGroup", "ExpansionFactor")
    for attr in passthrough:
        v = getattr(src_priv, attr, None)
        if v is not None:
            out[attr] = v

    return out


def recalc_cff_font_bbox(font: TTFont) -> None:
    """Recompute ``TopDict.FontBBox`` from all CharStrings in a CFF font.

    The CFF format has no per-glyph bounding box, only a single FontBBox
    on the TopDict. fontTools does not refresh it automatically after
    glyphs change, so this is the CFF-side analogue of ``recalcBounds``
    on TT glyphs. Should be called after any pass that mutates outlines
    (Latin glyph copy with scale, baseline transform, base TT→CFF).
    """
    if "CFF " not in font and "CFF2" not in font:
        return
    cff = font["CFF "].cff if "CFF " in font else font["CFF2"].cff
    td = cff.topDictIndex[0]
    cs_table = td.CharStrings

    from fontTools.pens.boundsPen import BoundsPen
    gs = font.getGlyphSet()

    x_min = y_min = None
    x_max = y_max = None
    for gname in cs_table.keys():
        try:
            pen = BoundsPen(gs)
            gs[gname].draw(pen)
        except Exception:
            continue
        if pen.bounds is None:
            continue
        bx_min, by_min, bx_max, by_max = pen.bounds
        if x_min is None or bx_min < x_min: x_min = bx_min
        if y_min is None or by_min < y_min: y_min = by_min
        if x_max is None or bx_max > x_max: x_max = bx_max
        if y_max is None or by_max > y_max: y_max = by_max

    if x_min is None:
        td.FontBBox = [0, 0, 0, 0]
    else:
        td.FontBBox = [
            int(round(x_min)), int(round(y_min)),
            int(round(x_max)), int(round(y_max)),
        ]


# ---------------------------------------------------------------------------
# TrueType glyph copy with transform
# ---------------------------------------------------------------------------

def copy_glyph_tt(src: TTFont, dst: TTFont, src_name: str,
                  scale: float, dy: float, copied: set,
                  dst_name: str = None, name_map: dict = None):
    """Copy a TrueType glyph from src to dst, applying scale and offset.

    src_name: glyph name in source font
    dst_name: glyph name in destination (defaults to src_name)
    name_map: dict mapping src glyph names to dst glyph names (for dependencies)
    """
    if dst_name is None:
        dst_name = src_name
    if dst_name in copied:
        return
    copied.add(dst_name)

    src_glyf = src["glyf"]
    dst_glyf = dst["glyf"]

    if src_name not in src_glyf:
        return

    src_glyph = copy.deepcopy(src_glyf[src_name])

    # Handle composite dependencies first
    if src_glyph.isComposite():
        for component in src_glyph.components:
            dep_src = component.glyphName
            dep_dst = name_map.get(dep_src, dep_src) if name_map else dep_src
            copy_glyph_tt(src, dst, dep_src, scale, dy, copied,
                          dst_name=dep_dst, name_map=name_map)
            component.glyphName = dep_dst
            if scale != 1.0:
                if hasattr(component, 'x') and hasattr(component, 'y'):
                    component.x = int(round(component.x * scale))
                    component.y = int(round(component.y * scale))
    elif src_glyph.numberOfContours > 0:
        # Simple glyph — transform coordinates
        if scale != 1.0 or dy != 0:
            coords = []
            for x, y in src_glyph.coordinates:
                coords.append((int(round(x * scale)), int(round(y * scale + dy))))
            from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
            src_glyph.coordinates = GlyphCoordinates(coords)
            if hasattr(src_glyph, 'program') and src_glyph.program:
                from array import array
                src_glyph.program.bytecode = array('B')

    dst_glyf[dst_name] = src_glyph

    try:
        src_glyph.recalcBounds(dst_glyf)
    except Exception:
        pass

    if src_name in src["hmtx"].metrics:
        orig_aw, orig_lsb = src["hmtx"].metrics[src_name]
        dst["hmtx"].metrics[dst_name] = (
            int(round(orig_aw * scale)),
            int(round(orig_lsb * scale))
        )


# ---------------------------------------------------------------------------
# Transform TrueType glyphs in-place (for Japanese glyphs)
# ---------------------------------------------------------------------------

def transform_tt_glyph_inplace(font: TTFont, glyph_name: str,
                                scale: float, dy: float):
    """Apply scale and baseline offset to a TrueType glyph in-place."""
    if scale == 1.0 and dy == 0:
        return

    glyf = font["glyf"]
    if glyph_name not in glyf:
        return

    glyph = glyf[glyph_name]

    if glyph.isComposite():
        for component in glyph.components:
            if hasattr(component, 'x') and hasattr(component, 'y'):
                component.x = int(round(component.x * scale))
                # `dy` is intentionally not added here: the base glyph that
                # this component points to is processed separately in the
                # same loop and gets its contours shifted by `dy`. Adding
                # `dy` to the component offset on top of that double-shifts
                # the composite render. Mirrors copy_glyph_tt's composite
                # branch, which has the same design.
                component.y = int(round(component.y * scale))
    elif glyph.numberOfContours > 0 and glyph.coordinates:
        coords = []
        for x, y in glyph.coordinates:
            coords.append((int(round(x * scale)), int(round(y * scale + dy))))
        from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
        glyph.coordinates = GlyphCoordinates(coords)
        try:
            glyph.recalcBounds(glyf)
        except Exception:
            pass  # Bounds recalc can fail for empty or degenerate glyphs

    # Scale metrics
    hmtx = font["hmtx"]
    if glyph_name in hmtx.metrics:
        aw, lsb = hmtx.metrics[glyph_name]
        hmtx.metrics[glyph_name] = (int(round(aw * scale)), int(round(lsb * scale)))


def _copy_vertical_metrics(font: TTFont, src_name: str, dst_name: str) -> None:
    """Copy vertical metrics from one glyph slot to another in the same font."""
    if "vmtx" in font and src_name in font["vmtx"].metrics:
        font["vmtx"].metrics[dst_name] = font["vmtx"].metrics[src_name]
    if "VORG" in font:
        vorg = font["VORG"]
        records = getattr(vorg, "VOriginRecords", None)
        if records is not None and src_name in records:
            records[dst_name] = records[src_name]


def _copy_single_substitutions_for_features(
    font: TTFont, src_name: str, dst_name: str, feature_tags: set
) -> None:
    """Copy feature-scoped SingleSubst mappings from one glyph to another."""
    gsub = font.get("GSUB")
    if not gsub or not getattr(gsub, "table", None):
        return
    table = gsub.table
    if not table.FeatureList or not table.LookupList:
        return

    for feature_record in table.FeatureList.FeatureRecord:
        if feature_record.FeatureTag not in feature_tags:
            continue
        for lookup_index in feature_record.Feature.LookupListIndex:
            lookup = table.LookupList.Lookup[lookup_index]
            if lookup.LookupType != 1:
                continue
            for subtable in lookup.SubTable:
                st = (subtable.ExtSubTable if hasattr(subtable, "ExtSubTable")
                      else subtable)
                mapping = getattr(st, "mapping", None)
                if not mapping or src_name not in mapping or dst_name in mapping:
                    continue
                mapping[dst_name] = mapping[src_name]
                coverage = getattr(st, "Coverage", None)
                if (coverage and hasattr(coverage, "glyphs")
                        and dst_name not in coverage.glyphs):
                    coverage.glyphs.append(dst_name)


# ---------------------------------------------------------------------------
# TrueType hinting normalization
# ---------------------------------------------------------------------------

# maxp v1 hint-related fields. Cleared together with the bytecode tables so
# the merged font's "this is unhinted" status is consistent across maxp,
# glyf, and the font-wide hint programs.
_MAXP_HINT_FIELDS_ZERO = (
    "maxTwilightPoints",
    "maxStorage",
    "maxFunctionDefs",
    "maxInstructionDefs",
    "maxStackElements",
    "maxSizeOfInstructions",
)


def normalize_truetype_hinting(font: TTFont) -> None:
    """Drop all TrueType bytecode hinting from a merged TTF.

    Glyph bytecode from one source cannot reliably run against the font-wide
    ``fpgm`` / ``prep`` / ``cvt `` from a different source: function indices,
    storage slots, and CVT entries are all source-specific. The merge engine
    happily mixes Latin glyphs with the base font's hint program, so we
    publish unhinted output and let the platform's autohinter handle small
    sizes. ``gasp`` is left in place — it controls smoothing strategy, not
    bytecode execution.

    Mirrors the policy described in Issue #17: per-glyph programs are
    cleared, ``fpgm`` / ``prep`` / ``cvt `` are removed, and the maxp v1
    hint counters are reset to zero so renderers don't reserve workspace
    for instructions that aren't there.
    """
    if "glyf" not in font:
        return  # CFF output uses a separate hint-preserving path.

    from array import array

    glyf = font["glyf"]
    for gname in glyf.glyphOrder:
        try:
            g = glyf[gname]
        except KeyError:
            continue
        program = getattr(g, "program", None)
        if program is not None and getattr(program, "bytecode", None):
            program.bytecode = array("B")

    for tag in ("fpgm", "prep", "cvt "):
        if tag in font:
            del font[tag]

    maxp = font.get("maxp")
    if maxp is not None:
        if hasattr(maxp, "maxZones"):
            # OpenType maxp v1 requires maxZones to be 1 when instructions
            # do not use the twilight zone. Zero is not a conformant value,
            # even for unhinted TrueType outlines.
            maxp.maxZones = 1
        for attr in _MAXP_HINT_FIELDS_ZERO:
            if hasattr(maxp, attr):
                setattr(maxp, attr, 0)


def _resolve_hinting_policy(config: dict) -> str:
    """Resolve output hinting policy for TrueType output.

    The default is ``strip`` because preserving mixed-source TT bytecode is
    unsafe. ``ttfautohint`` is an opt-in post-process for environments that
    provide the external tool.
    """
    output = config.get("output") or {}
    raw = (output.get("hinting") or "strip").strip().lower()
    aliases = {
        "none": "strip",
        "unhinted": "strip",
        "strip": "strip",
        "ttfautohint": "ttfautohint",
        "autohint": "ttfautohint",
    }
    if raw not in aliases:
        raise ValueError(
            "output.hinting must be one of: strip, unhinted, none, "
            "ttfautohint, autohint"
        )
    return aliases[raw]


def _apply_ttfautohint(output_path: str, tool_path: str = None) -> None:
    """Run ttfautohint over the final saved TTF file in-place."""
    exe = tool_path or shutil.which("ttfautohint")
    if not exe:
        raise RuntimeError(
            "output.hinting=ttfautohint requested, but ttfautohint was not "
            "found on PATH"
        )

    tmp_path = f"{output_path}.ttfautohint.tmp"
    try:
        subprocess.run(
            [exe, output_path, tmp_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        os.replace(tmp_path, output_path)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"ttfautohint failed for {os.path.basename(output_path)}"
            + (f": {stderr}" if stderr else "")
        ) from e
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ---------------------------------------------------------------------------
# GSUB/GPOS feature table merging
# ---------------------------------------------------------------------------

def _collect_lookup_glyphs(lookup) -> set:
    """Collect all glyph names referenced by a lookup's input coverage."""
    glyph_names = set()
    try:
        for subtable in lookup.SubTable:
            st = subtable
            if hasattr(st, 'ExtSubTable'):
                st = st.ExtSubTable
            if hasattr(st, 'Coverage') and st.Coverage:
                # ContextSubst / ContextPos Format 3 store Coverage as a
                # list of Coverage objects (one per input position), not a
                # single object. Treat both shapes uniformly so Format 3
                # lookups don't silently come back as "no glyphs" (Issue #2 #4).
                cov = st.Coverage
                cov_list = cov if isinstance(cov, list) else [cov]
                for c in cov_list:
                    if c and hasattr(c, 'glyphs'):
                        glyph_names.update(c.glyphs)
            if hasattr(st, 'BacktrackCoverage'):
                for cov in (st.BacktrackCoverage or []):
                    glyph_names.update(cov.glyphs)
            if hasattr(st, 'LookAheadCoverage'):
                for cov in (st.LookAheadCoverage or []):
                    glyph_names.update(cov.glyphs)
            if hasattr(st, 'InputCoverage'):
                for cov in (st.InputCoverage or []):
                    glyph_names.update(cov.glyphs)
            if hasattr(st, 'ligatures') and st.ligatures:
                glyph_names.update(st.ligatures.keys())
                # Type 4 ligatures stash the trailing INPUT glyphs in
                # `Component`. Walk them too so `_classify_lookup` sees the
                # full input set. We deliberately do NOT add `LigGlyph`
                # (the output): including the output would let a JP-designed
                # `f i → JP-fi` ligature look like a `mixed` lookup just
                # because the output glyph is JP-side, even though every
                # input is Latin. That is the textbook "subordinate Latin
                # liga" the merge engine wants to drop.
                for lig_list in st.ligatures.values():
                    if not lig_list:
                        continue
                    for lig in lig_list:
                        comp = getattr(lig, 'Component', None)
                        if comp:
                            glyph_names.update(comp)
            if hasattr(st, 'mapping') and st.mapping:
                glyph_names.update(st.mapping.keys())
            if hasattr(st, 'alternates') and st.alternates:
                glyph_names.update(st.alternates.keys())
            # Format 1 Context / ChainContext rule-based subtables stash
            # the input/backtrack/lookahead sequences as raw glyph-name
            # lists inside SubRule / ChainSubRule / PosRule / ChainPosRule
            # records. Without this walk the safety check missed any
            # non-Latin glyph reachable only through Format 1 rules.
            for ruleset_attr in ('SubRuleSet', 'ChainSubRuleSet',
                                 'PosRuleSet', 'ChainPosRuleSet'):
                rulesets = getattr(st, ruleset_attr, None)
                if not rulesets:
                    continue
                for ruleset in rulesets:
                    if not ruleset:
                        continue
                    for rule_attr in ('SubRule', 'ChainSubRule',
                                      'PosRule', 'ChainPosRule'):
                        rules = getattr(ruleset, rule_attr, None)
                        if not rules:
                            continue
                        for rule in rules:
                            for cov_attr in ('Backtrack', 'Input',
                                             'LookAhead'):
                                seq = getattr(rule, cov_attr, None)
                                if seq:
                                    glyph_names.update(seq)
            # Format 2 Context / ChainContext class-based subtables
            # describe input glyphs through ClassDef.classDefs (a
            # {glyph_name: class_id} dict). Coverage covers only the
            # first input position; later positions live in the ClassDef
            # tables and would otherwise be invisible.
            for cd_attr in ('ClassDef', 'BacktrackClassDef',
                            'InputClassDef', 'LookAheadClassDef'):
                cd = getattr(st, cd_attr, None)
                if cd is not None and getattr(cd, 'classDefs', None):
                    glyph_names.update(cd.classDefs.keys())
    except Exception:
        pass  # Malformed subtable; return partial results for classification
    return glyph_names


class LookupGlyphDomain(NamedTuple):
    glyphs: set[str]
    unknown: bool = False


def _add_glyph(glyph_names: set, glyph) -> bool:
    if glyph is None:
        return False
    if isinstance(glyph, str):
        glyph_names.add(glyph)
        return False
    return True


def _add_glyph_sequence(glyph_names: set, glyphs) -> bool:
    if glyphs is None:
        return False
    unknown = False
    for glyph in glyphs:
        unknown = _add_glyph(glyph_names, glyph) or unknown
    return unknown


def _add_coverage_domain_glyphs(glyph_names: set, coverage) -> bool:
    if coverage is None:
        return False
    if isinstance(coverage, list):
        unknown = False
        for cov in coverage:
            unknown = _add_coverage_domain_glyphs(glyph_names, cov) or unknown
        return unknown
    glyphs = getattr(coverage, 'glyphs', None)
    if glyphs is None:
        return True
    glyph_names.update(glyphs)
    return False


def _coverage_domain_has_glyphs(coverage) -> bool:
    if coverage is None:
        return False
    if isinstance(coverage, list):
        return any(_coverage_domain_has_glyphs(cov) for cov in coverage)
    return bool(getattr(coverage, 'glyphs', None))


def _classdef_glyphs_by_class(class_def) -> dict[int, set[str]]:
    out = {}
    class_defs = getattr(class_def, 'classDefs', None) or {}
    for glyph, class_id in class_defs.items():
        out.setdefault(class_id, set()).add(glyph)
    return out


def _add_class_sequence_domain(glyph_names: set, class_ids,
                               glyphs_by_class: dict[int, set[str]]) -> bool:
    """Return True when a class sequence cannot be proven sub-font-confined."""
    if class_ids is None:
        return False

    unknown = False
    for class_id in class_ids:
        if class_id == 0:
            unknown = True
            continue

        members = glyphs_by_class.get(class_id)
        if not members:
            unknown = True
            continue

        glyph_names.update(members)

    return unknown


def _add_class_set_domain(glyph_names: set, class_set_index: int, rules,
                          glyphs_by_class: dict[int, set[str]]) -> bool:
    if not rules:
        return False
    if class_set_index == 0:
        return True
    members = glyphs_by_class.get(class_set_index)
    if not members:
        return True
    glyph_names.update(members)
    return False


def _context_rule_input_classes(rule):
    input_classes = getattr(rule, 'Input', None)
    if input_classes is not None:
        return input_classes
    return getattr(rule, 'Class', None)


def _add_substitution_output_glyphs(glyph_names: set, value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        glyph_names.add(value)
        return False
    try:
        return _add_glyph_sequence(glyph_names, value)
    except TypeError:
        return True


def _collect_gsub_subtable_full_domain(lookup_type: int, subtable) \
        -> LookupGlyphDomain:
    """Collect every glyph a supported GSUB subtable can match or emit."""
    glyph_names = set()
    unknown = False
    st = subtable

    if hasattr(st, 'ExtSubTable'):
        lookup_type = getattr(st, 'ExtensionLookupType', lookup_type)
        st = st.ExtSubTable
        if st is None:
            return LookupGlyphDomain(glyph_names, True)

    for cov_attr in ('Coverage', 'BacktrackCoverage', 'InputCoverage',
                     'LookAheadCoverage'):
        unknown = _add_coverage_domain_glyphs(
            glyph_names, getattr(st, cov_attr, None)) or unknown
    has_input_coverage = _coverage_domain_has_glyphs(
        getattr(st, 'Coverage', None))

    if lookup_type == 1:
        mapping = getattr(st, 'mapping', None)
        if mapping:
            glyph_names.update(mapping.keys())
            for out_glyph in mapping.values():
                unknown = _add_substitution_output_glyphs(
                    glyph_names, out_glyph) or unknown
        substitute = getattr(st, 'Substitute', None)
        if substitute is not None and not mapping and not has_input_coverage:
            unknown = True
        unknown = _add_substitution_output_glyphs(
            glyph_names, substitute) or unknown

    elif lookup_type == 2:
        mapping = getattr(st, 'mapping', None)
        if mapping:
            glyph_names.update(mapping.keys())
            for sequence in mapping.values():
                unknown = _add_substitution_output_glyphs(
                    glyph_names, sequence) or unknown
        sequences = getattr(st, 'Sequence', None) or []
        if sequences and not has_input_coverage:
            unknown = True
        for sequence in sequences:
            unknown = _add_substitution_output_glyphs(
                glyph_names, getattr(sequence, 'Substitute', None)) or unknown

    elif lookup_type == 3:
        alternates = getattr(st, 'alternates', None)
        if alternates:
            glyph_names.update(alternates.keys())
            for alt_set in alternates.values():
                unknown = _add_substitution_output_glyphs(
                    glyph_names, alt_set) or unknown
        alt_sets = getattr(st, 'AlternateSet', None) or []
        if alt_sets and not has_input_coverage:
            unknown = True
        for alt_set in alt_sets:
            unknown = _add_substitution_output_glyphs(
                glyph_names, getattr(alt_set, 'Alternate', None)) or unknown

    elif lookup_type == 4:
        ligatures = getattr(st, 'ligatures', None)
        if ligatures:
            glyph_names.update(ligatures.keys())
            for lig_list in ligatures.values():
                for lig in (lig_list or []):
                    unknown = _add_glyph_sequence(
                        glyph_names, getattr(lig, 'Component', None)) or unknown
                    unknown = _add_glyph(
                        glyph_names, getattr(lig, 'LigGlyph', None)) or unknown
        lig_sets = getattr(st, 'LigatureSet', None) or []
        if lig_sets and not has_input_coverage:
            unknown = True
        for lig_set in lig_sets:
            for lig in (getattr(lig_set, 'Ligature', None) or []):
                unknown = _add_glyph_sequence(
                    glyph_names, getattr(lig, 'Component', None)) or unknown
                unknown = _add_glyph(
                    glyph_names, getattr(lig, 'LigGlyph', None)) or unknown

    elif lookup_type == 5:
        fmt = getattr(st, 'Format', None)
        if fmt == 1:
            for ruleset in (getattr(st, 'SubRuleSet', None) or []):
                for rule in (getattr(ruleset, 'SubRule', None) or []):
                    unknown = _add_glyph_sequence(
                        glyph_names, getattr(rule, 'Input', None)) or unknown
        elif fmt == 2:
            glyphs_by_class = _classdef_glyphs_by_class(
                getattr(st, 'ClassDef', None))
            for class_set_index, class_set in enumerate(
                    getattr(st, 'SubClassSet', None) or []):
                rules = getattr(class_set, 'SubClassRule', None) or []
                unknown = _add_class_set_domain(
                    glyph_names, class_set_index, rules,
                    glyphs_by_class) or unknown
                for rule in rules:
                    unknown = _add_class_sequence_domain(
                        glyph_names,
                        _context_rule_input_classes(rule),
                        glyphs_by_class,
                    ) or unknown
        elif fmt != 3:
            unknown = True

    elif lookup_type == 6:
        fmt = getattr(st, 'Format', None)
        if fmt == 1:
            for ruleset in (getattr(st, 'ChainSubRuleSet', None) or []):
                for rule in (getattr(ruleset, 'ChainSubRule', None) or []):
                    for seq_attr in ('Backtrack', 'Input', 'LookAhead'):
                        unknown = _add_glyph_sequence(
                            glyph_names, getattr(rule, seq_attr, None)
                        ) or unknown
        elif fmt == 2:
            backtrack_by_class = _classdef_glyphs_by_class(
                getattr(st, 'BacktrackClassDef', None))
            input_by_class = _classdef_glyphs_by_class(
                getattr(st, 'InputClassDef', None))
            lookahead_by_class = _classdef_glyphs_by_class(
                getattr(st, 'LookAheadClassDef', None))
            for class_set_index, class_set in enumerate(
                    getattr(st, 'ChainSubClassSet', None) or []):
                rules = getattr(class_set, 'ChainSubClassRule', None) or []
                unknown = _add_class_set_domain(
                    glyph_names, class_set_index, rules,
                    input_by_class) or unknown
                for rule in rules:
                    unknown = _add_class_sequence_domain(
                        glyph_names, getattr(rule, 'Backtrack', None),
                        backtrack_by_class) or unknown
                    unknown = _add_class_sequence_domain(
                        glyph_names, getattr(rule, 'Input', None),
                        input_by_class) or unknown
                    unknown = _add_class_sequence_domain(
                        glyph_names, getattr(rule, 'LookAhead', None),
                        lookahead_by_class) or unknown
        elif fmt != 3:
            unknown = True

    elif lookup_type == 7:
        unknown = True

    elif lookup_type == 8:
        substitute = getattr(st, 'Substitute', None)
        if substitute is not None and not has_input_coverage:
            unknown = True
        unknown = _add_substitution_output_glyphs(
            glyph_names, substitute) or unknown

    else:
        unknown = True

    return LookupGlyphDomain(glyph_names, unknown)


def _collect_gsub_lookup_full_domain(lookup) -> LookupGlyphDomain:
    """Collect input, context, and output glyphs for a GSUB lookup.

    Unknown or malformed subtable shapes are marked unsafe instead of being
    treated as empty no-ops; this collector is used for default-on promotion
    safety, not broad lookup classification.
    """
    glyph_names = set()
    unknown = False
    try:
        lookup_type = getattr(lookup, 'LookupType', None)
        if lookup_type is None:
            return LookupGlyphDomain(glyph_names, True)
        for subtable in (getattr(lookup, 'SubTable', None) or []):
            domain = _collect_gsub_subtable_full_domain(lookup_type, subtable)
            glyph_names.update(domain.glyphs)
            unknown = domain.unknown or unknown
    except Exception:
        unknown = True
    return LookupGlyphDomain(glyph_names, unknown)


def _classify_lookup(lookup, lat_glyph_names: set) -> str:
    """
    Classify a Japanese font's lookup as 'latin', 'japanese', or 'mixed'.

    Instead of relying on hardcoded Unicode ranges, this checks whether
    the glyphs referenced by the lookup exist in the Latin font:

    - 'latin': ALL input glyphs exist in the Latin font
      → This is a subordinate Latin lookup and should be REMOVED
    - 'japanese': NO input glyphs exist in the Latin font
      → This is a CJK-only lookup and should be KEPT
    - 'mixed': Some glyphs exist in both fonts
      → Keep the lookup (it likely handles both scripts)
    """
    glyph_names = _collect_lookup_glyphs(lookup)

    if not glyph_names:
        return 'mixed'

    in_en = 0
    not_in_en = 0
    for name in glyph_names:
        if name in lat_glyph_names:
            in_en += 1
        else:
            not_in_en += 1

    if in_en > 0 and not_in_en == 0:
        return 'latin'
    if not_in_en > 0 and in_en == 0:
        return 'japanese'
    return 'mixed'


def _transform_lookup_references(lookup, transform):
    """Apply *transform* (a callable: old_index → new_index | None) to every
    internal lookup reference inside chaining / context lookups.

    When *transform* returns ``None`` the record itself is dropped from its
    parent list. This is how callers signal "the target lookup no longer
    exists, so this reference must die" rather than letting a stale index
    silently land on a different lookup.

    Works for both GSUB (types 5/6) and GPOS (types 7/8), including
    extension wrappers and nested rule sets (Format 1/2/3).
    """
    def _rewrite(records):
        if not records:
            return records
        kept = []
        for rec in records:
            new_idx = transform(rec.LookupListIndex)
            if new_idx is None:
                continue
            rec.LookupListIndex = new_idx
            kept.append(rec)
        return kept

    for subtable in lookup.SubTable:
        st = subtable
        if hasattr(st, 'ExtSubTable'):
            st = st.ExtSubTable
        # GSUB: ChainContextSubst (type 6), ContextSubst (type 5)
        if hasattr(st, 'SubstLookupRecord') and st.SubstLookupRecord:
            st.SubstLookupRecord = _rewrite(st.SubstLookupRecord)
        # GPOS: ChainContextPos (type 8), ContextPos (type 7)
        if hasattr(st, 'PosLookupRecord') and st.PosLookupRecord:
            st.PosLookupRecord = _rewrite(st.PosLookupRecord)
        # Nested rule sets (Format 1/2)
        for attr in ('SubRuleSet', 'SubClassSet', 'ChainSubRuleSet', 'ChainSubClassSet',
                      'PosRuleSet', 'PosClassSet', 'ChainPosRuleSet', 'ChainPosClassSet'):
            ruleset_list = getattr(st, attr, None)
            if not ruleset_list:
                continue
            for ruleset in ruleset_list:
                if not ruleset:
                    continue
                for attr2 in ('SubRule', 'SubClassRule', 'ChainSubRule', 'ChainSubClassRule',
                              'PosRule', 'PosClassRule', 'ChainPosRule', 'ChainPosClassRule'):
                    rules = getattr(ruleset, attr2, None)
                    if not rules:
                        continue
                    for rule in rules:
                        if hasattr(rule, 'SubstLookupRecord') and rule.SubstLookupRecord:
                            rule.SubstLookupRecord = _rewrite(rule.SubstLookupRecord)
                        if hasattr(rule, 'PosLookupRecord') and rule.PosLookupRecord:
                            rule.PosLookupRecord = _rewrite(rule.PosLookupRecord)


def _offset_lookup_references(lookup, offset: int):
    """Offset all internal lookup references in chaining/context lookups."""
    _transform_lookup_references(lookup, lambda idx: idx + offset)


def _remap_lookup_references(lookup, remap: dict):
    """Remap internal lookup references using an old→new index mapping.

    References to lookups that are not in *remap* (because the target
    lookup has been removed) are dropped from their parent record list,
    rather than being left to silently land on a different lookup.
    """
    _transform_lookup_references(lookup, lambda idx: remap.get(idx))


def _rename_glyphs_in_ot_table(ot_table, name_map: dict):
    """Rename glyph references in a GSUB/GPOS table using name_map."""
    def rename(name):
        return name_map.get(name, name)

    if not ot_table or not ot_table.LookupList:
        return
    for lookup in ot_table.LookupList.Lookup:
        for st in lookup.SubTable:
            real_st = st.ExtSubTable if hasattr(st, 'ExtSubTable') else st
            # Rename Coverage glyphs
            if hasattr(real_st, 'Coverage') and real_st.Coverage:
                # ContextSubst/ContextPos Format 3 stores Coverage as a list.
                cov = real_st.Coverage
                cov_list = cov if isinstance(cov, list) else [cov]
                for c in cov_list:
                    if c and hasattr(c, 'glyphs'):
                        c.glyphs = [rename(g) for g in c.glyphs]
            # Rename BacktrackCoverage, InputCoverage, LookAheadCoverage (chaining)
            for attr in ('BacktrackCoverage', 'InputCoverage', 'LookAheadCoverage'):
                covs = getattr(real_st, attr, None)
                if covs:
                    for cov in covs:
                        if cov and hasattr(cov, 'glyphs'):
                            cov.glyphs = [rename(g) for g in cov.glyphs]
            # Rename ClassDef glyphs. Chaining contextual Format 2 lookups
            # (GSUB type 6 / GPOS type 8) split their classification across
            # three ClassDefs — Backtrack/Input/LookAhead — and missing any
            # of them leaves stale glyph names that crash CFF compile when a
            # cmap-based rename has remapped the original name.
            for attr in ('ClassDef1', 'ClassDef2', 'ClassDef',
                         'BacktrackClassDef', 'InputClassDef', 'LookAheadClassDef',
                         'MarkCoverage', 'Mark1Coverage', 'Mark2Coverage',
                         'BaseCoverage', 'LigatureCoverage'):
                cd = getattr(real_st, attr, None)
                if cd and hasattr(cd, 'classDefs'):
                    cd.classDefs = {rename(g): v for g, v in cd.classDefs.items()}
                elif cd and hasattr(cd, 'glyphs'):
                    cd.glyphs = [rename(g) for g in cd.glyphs]
            # Rename PairSet glyph names
            if hasattr(real_st, 'PairSet') and real_st.PairSet:
                for ps in real_st.PairSet:
                    if ps and ps.PairValueRecord:
                        for pvr in ps.PairValueRecord:
                            pvr.SecondGlyph = rename(pvr.SecondGlyph)
            # Rename ligature tables
            if hasattr(real_st, 'ligatures'):
                real_st.ligatures = {rename(g): v for g, v in real_st.ligatures.items()}
                for gname, ligs in real_st.ligatures.items():
                    for lig in ligs:
                        if hasattr(lig, 'Component'):
                            lig.Component = [rename(c) for c in lig.Component]
                        if hasattr(lig, 'LigGlyph'):
                            lig.LigGlyph = rename(lig.LigGlyph)
            # Rename Alternate/Multiple substitution
            if hasattr(real_st, 'alternates') and real_st.alternates:
                new_alts = {}
                for g, alts in real_st.alternates.items():
                    if isinstance(alts, list):
                        new_alts[rename(g)] = [rename(a) for a in alts]
                    else:
                        new_alts[rename(g)] = alts
                real_st.alternates = new_alts
            if hasattr(real_st, 'mapping') and real_st.mapping:
                new_mapping = {}
                for g, alts in real_st.mapping.items():
                    if isinstance(alts, list):
                        new_mapping[rename(g)] = [rename(a) for a in alts]
                    elif isinstance(alts, str):
                        # SingleSubst: mapping value is a single replacement glyph name
                        new_mapping[rename(g)] = rename(alts)
                    else:
                        new_mapping[rename(g)] = alts
                real_st.mapping = new_mapping
            # Rename glyph names inside Context / ChainContext Format 1 rule
            # sets (Issue #2 #5). Format 1 rules carry raw glyph names in
            # their Input / Backtrack / LookAhead arrays; if these are not
            # renamed alongside Coverage / ClassDef the rules silently
            # reference the pre-merge name and the lookup misfires.
            for rs_attr in ('SubRuleSet', 'ChainSubRuleSet',
                            'PosRuleSet', 'ChainPosRuleSet'):
                ruleset_list = getattr(real_st, rs_attr, None)
                if not ruleset_list:
                    continue
                for ruleset in ruleset_list:
                    if not ruleset:
                        continue
                    for r_attr in ('SubRule', 'ChainSubRule',
                                   'PosRule', 'ChainPosRule'):
                        rules = getattr(ruleset, r_attr, None)
                        if not rules:
                            continue
                        for rule in rules:
                            for seq_attr in ('Input', 'Backtrack', 'LookAhead'):
                                seq = getattr(rule, seq_attr, None)
                                if seq:
                                    setattr(rule, seq_attr,
                                            [rename(g) for g in seq])


def _resort_lookup_coverages(font: TTFont):
    """Re-sort every GSUB/GPOS Coverage and PairValueRecord by merged
    glyph ID. fontTools doesn't auto-sort either on save; HarfBuzz binary-
    searches both, and silently skips entries when the order is wrong.

    Two failure modes had to be addressed at once:

    1. **Coverage**: Latin font Coverages are sorted by the *Latin* font's
       glyph IDs. After cmap merge the IDs are renumbered (JP glyphs come
       first, Latin glyphs are appended), so the Coverages are unsorted
       relative to the output. HarfBuzz then can't find the gating glyph
       for kern / calt / chain context lookups. Sort Coverage and reorder
       any parallel arrays (PairSet, Context rule sets) in lockstep.

    2. **PairValueRecord**: each PairSet's PairValueRecord array must be
       sorted in increasing SecondGlyph gid order — same binary-search
       requirement, applied per first-glyph entry. With merged-renumbered
       IDs, the originally sorted records become arbitrary and HB locks
       onto the wrong pair (or misses the pair entirely).

    Format-2 PairPos has no parallel-array problem — Coverage gates and
    ClassDefs are name-keyed, so sorting Coverage alone is sufficient.
    Mark/Base coverages are skipped because their attached MarkArray /
    BaseArray use index alignments that aren't load-bearing for the kern
    bug and would risk corrupting if reordered carelessly.
    """
    glyph_id = {g: i for i, g in enumerate(font.getGlyphOrder())}

    def gid(name):
        return glyph_id.get(name, 0)

    PARALLEL_ATTRS = (
        'PairSet',         # PairPos Format 1
        'Value',           # SinglePos Format 2 (list of ValueRecords)
        'SubRuleSet',      # ContextSubst Format 1
        'ChainSubRuleSet', # ChainContextSubst Format 1
        'PosRuleSet',      # ContextPos Format 1
        'ChainPosRuleSet', # ChainContextPos Format 1
    )

    for tag in ('GSUB', 'GPOS'):
        ot = font.get(tag)
        if not ot or not getattr(ot, 'table', None):
            continue
        ll = ot.table.LookupList
        if not ll:
            continue
        for lookup in ll.Lookup:
            for subtable in lookup.SubTable:
                st = subtable
                if hasattr(st, 'ExtSubTable'):
                    st = st.ExtSubTable
                cov = getattr(st, 'Coverage', None)
                if cov:
                    if isinstance(cov, list):
                        # ContextPos/ContextSubst Format 3: each input position
                        # has its own gating Coverage; no parallel array.
                        for c in cov:
                            if c and getattr(c, 'glyphs', None):
                                c.glyphs = sorted(c.glyphs, key=gid)
                    else:
                        glyphs = getattr(cov, 'glyphs', None)
                        if glyphs:
                            order = sorted(range(len(glyphs)),
                                           key=lambda i: gid(glyphs[i]))
                            if order != list(range(len(glyphs))):
                                cov.glyphs = [glyphs[i] for i in order]
                                for attr in PARALLEL_ATTRS:
                                    arr = getattr(st, attr, None)
                                    if isinstance(arr, list) and len(arr) == len(glyphs):
                                        setattr(st, attr, [arr[i] for i in order])
                # PairPos Format 1: sort PairValueRecord by SecondGlyph gid.
                # Done after any Coverage permutation above so each PairSet
                # is already at its final position.
                pair_sets = getattr(st, 'PairSet', None)
                if pair_sets:
                    for ps in pair_sets:
                        pvrs = getattr(ps, 'PairValueRecord', None)
                        if pvrs:
                            pvrs.sort(key=lambda pvr: gid(pvr.SecondGlyph))
                # Chain context backtrack/input/lookahead Coverages are
                # independent gating sets — sort each.
                for attr in ('BacktrackCoverage', 'InputCoverage',
                             'LookAheadCoverage'):
                    covs = getattr(st, attr, None)
                    if covs:
                        for c in covs:
                            if c and getattr(c, 'glyphs', None):
                                c.glyphs = sorted(c.glyphs, key=gid)


def _strip_latin_only_ligatures(lookup, lat_glyph_names: set):
    """Drop ligature entries whose every input glyph is in the Latin font.

    Pan-CJK fonts pack Latin-input ligatures into the same `dlig` / `liga`
    lookup as JP-only ligatures and emit CJK compatibility square symbols
    (e.g. ``n+s → ㎱`` U+33B1, ``A+m → ㏟`` U+33DF). The lookup is then
    `mixed` to ``_classify_lookup`` (some inputs Latin, some not) and
    survives merging. With dlig enabled in Illustrator / InDesign the
    base-side rules fire on plain Latin text — typing "Sans" produces
    "Sa㎱" because ``n+s`` matches a square-symbol ligature.

    This is the GSUB analogue of ``_strip_latin_first_from_pairpos``:
    walk Type 4 LigatureSubst subtables and drop entries where the first
    input *and* every Component glyph is in the Latin font. Cross-script
    entries (CJK first or any CJK Component) are preserved so the JP
    side keeps its legitimate ligatures.
    """
    if not lat_glyph_names:
        return
    for subtable in lookup.SubTable:
        st = subtable
        if hasattr(st, 'ExtSubTable'):
            st = st.ExtSubTable
        ligatures = getattr(st, 'ligatures', None)
        if not ligatures:
            continue
        new_ligatures = {}
        for first, ligs in ligatures.items():
            if not ligs:
                continue
            kept = []
            for lig in ligs:
                comp = getattr(lig, 'Component', None) or []
                inputs = (first,) + tuple(comp)
                if all(g in lat_glyph_names for g in inputs):
                    continue  # purely-Latin input — Latin font owns this
                kept.append(lig)
            if kept:
                new_ligatures[first] = kept
        st.ligatures = new_ligatures


def _strip_latin_owned_substitutions(lookup, lat_glyph_names: set,
                                     preserved_lat_names: set = None):
    """Drop Type 1 / Type 3 GSUB entries whose source glyph is Latin-owned.

    Pan-CJK fonts (Noto Sans JP, Noto Sans CJK JP, …) ship Latin-script
    `locl`, `aalt`, `fwid`, `hwid`, `tnum` lookups that map Latin digit /
    letter glyphs to base-font alternates. After cross-codepoint glyph
    rename (#20) the base-side reference set drifts so the lookup is
    classified `mixed` rather than `latin`, and the rule survives the
    merge. Once it survives, plain ``0123456789`` shaped under
    ``latn/en`` shapes to base-font full-width / locl alternates instead
    of the Latin font's digits — even when no `fwid` / `tnum` was asked
    for, because the base-side `locl` rewrites the input first.

    This is the GSUB Type 1 / Type 3 analogue of
    ``_strip_latin_only_ligatures`` and ``_strip_latin_first_from_pairpos``.
    Walk surviving base-side SingleSubst (Type 1) and AlternateSubst
    (Type 3) subtables and drop entries whose source glyph is owned by
    the Latin font. Cross-script entries (source glyph CJK-owned) are
    preserved so JP-only behavior such as ``vert`` / ``vrt2`` keeps
    firing on Japanese glyphs.

    ``preserved_lat_names`` lists Latin glyph names the merge engine
    renamed during cross-codepoint preservation (e.g. Inter's ``ellipsis``
    → ``ellipsis.sub`` so Noto's ``ellipsis`` at U+22EF survives). Those
    renamed glyphs sit at non-Latin codepoints in the merged font and
    inherit base-side ``vert`` / ``vrt2`` mappings via
    ``_copy_single_substitutions_for_features``; stripping them would
    silently kill the inherited behavior.

    fontTools rebuilds Coverage from the surviving ``mapping`` /
    ``alternates`` keys at compile time, so updating those dicts is
    sufficient.
    """
    if not lat_glyph_names:
        return
    preserve = preserved_lat_names or set()
    for subtable in lookup.SubTable:
        st = subtable
        if hasattr(st, 'ExtSubTable'):
            st = st.ExtSubTable
        for attr in ('mapping', 'alternates'):
            data = getattr(st, attr, None)
            if not data:
                continue
            stripped = {g: v for g, v in data.items()
                        if g not in lat_glyph_names or g in preserve}
            if len(stripped) != len(data):
                setattr(st, attr, stripped)


def _strip_latin_first_from_pairpos(lookup, lat_glyph_names: set):
    """Drop Latin first-position glyphs from PairPos subtables.

    JP fonts (e.g. Noto Sans JP) ship their own Latin glyphs and bake Latin
    pair kerning for them. After the Latin font is merged in to overwrite
    those slots, JP's leftover Latin kerning still references the same
    glyph names — so the Latin font's kern lookup *and* the JP font's kern
    lookup both fire for pairs like ``T+o``/``T+y``, stacking adjustments
    and producing visibly broken spacing in words like "Tokyo" / "Type".

    Stripping Latin glyphs from the *first* position Coverage neutralises
    JP's redundant Latin kerning while leaving cross-script kerning that
    starts on a JP glyph (CJK + Latin / CJK + CJK) intact.
    """
    if not lat_glyph_names:
        return
    for subtable in lookup.SubTable:
        st = subtable
        if hasattr(st, 'ExtSubTable'):
            st = st.ExtSubTable
        cov = getattr(st, 'Coverage', None)
        # ContextPos format 3 stores Coverage as a list — that's not PairPos.
        if not cov or isinstance(cov, list) or not getattr(cov, 'glyphs', None):
            continue
        glyphs = cov.glyphs
        keep = [i for i, g in enumerate(glyphs) if g not in lat_glyph_names]
        if len(keep) == len(glyphs):
            continue
        # PairPos Format 1: PairSet array is aligned with Coverage.glyphs.
        if hasattr(st, 'PairSet') and st.PairSet is not None:
            st.PairSet = [st.PairSet[i] for i in keep]
            if hasattr(st, 'PairSetCount'):
                st.PairSetCount = len(st.PairSet)
            cov.glyphs = [glyphs[i] for i in keep]
        # PairPos Format 2: class-based; Coverage gates whether the lookup
        # fires at all, so dropping Latin glyphs here suppresses every
        # Latin-first pair. Mirror the change on ClassDef1 for hygiene.
        elif hasattr(st, 'Class1Record'):
            cov.glyphs = [glyphs[i] for i in keep]
            cd1 = getattr(st, 'ClassDef1', None)
            if cd1 and getattr(cd1, 'classDefs', None):
                cd1.classDefs = {
                    g: c for g, c in cd1.classDefs.items()
                    if g not in lat_glyph_names
                }


def merge_feature_tables(lat_font: TTFont, jp_font: TTFont, merged: TTFont,
                         lat_scale: float = 1.0, lat_baseline: float = 0,
                         lat_name_map: dict = None,
                         append_lat_lookups: bool = True,
                         preserved_lat_names: set = None,
                         lat_glyph_names_override: set = None):
    """
    Merge GSUB/GPOS tables with correct feature separation.

    lat_scale: total scale factor applied to Latin glyphs (user_scale * upm_ratio)
    lat_baseline: vertical offset applied to Latin glyphs (in merged UPM units)
    lat_name_map: optional {lat_glyph_name -> merged_glyph_name}. When Latin
        glyphs are renamed on copy (e.g. Playwrite's ``A.cur_locl`` → ``A``
        because the merged slot for U+0041 is ``A``), the Latin GSUB/GPOS
        lookup glyph references must be rewritten to match so that features
        like ``calt`` keep working.
    append_lat_lookups: when ``False``, the Latin font's GSUB/GPOS lookups
        are NOT appended to the merged tables, but the Latin-owned glyph
        name set is still computed and used to strip base-side mixed
        lookups (so e.g. base ``locl`` rules on Latin digits get removed).
        Used by the 65535-glyph budget fallback path: Latin lookups can't
        be appended because some Latin glyphs were dropped, but base-side
        leakage onto the digits that *did* fit must still be cleaned up.
    preserved_lat_names: Latin merged names that the cross-codepoint
        rename pass produced (e.g. ``ellipsis.sub``). Excluded from the
        base-side strip so the inherited ``vert`` / ``vrt2`` mappings
        added by ``_copy_single_substitutions_for_features`` survive.
    lat_glyph_names_override: explicit Latin-owned merged-name set. Used
        on the budget fallback path where some Latin glyphs were dropped
        (so ``lat_font.getGlyphOrder()`` overstates the actually-copied
        set). Stripping a dropped name would over-eagerly remove
        legitimate base-side rules whose source glyph is still owned by
        the base font.
    """
    # Remap Latin glyph names so JP lookup classification and Latin lookup
    # references both line up with the *merged* glyph space.
    if lat_glyph_names_override is not None:
        lat_glyph_names = lat_glyph_names_override
    elif lat_font and lat_name_map:
        lat_glyph_names = {lat_name_map.get(g, g) for g in lat_font.getGlyphOrder()}
    else:
        lat_glyph_names = set(lat_font.getGlyphOrder()) if lat_font else set()
    preserved_lat_names = preserved_lat_names or set()

    for table_tag in ('GSUB', 'GPOS'):
        lat_table = lat_font.get(table_tag) if (
            lat_font and append_lat_lookups) else None
        jp_table = merged.get(table_tag)

        # If we need to rename Latin glyphs, deep-copy the Latin table first
        # so the original lat_font (used later by reconcile_tables) is untouched.
        if lat_table and lat_name_map:
            lat_table = copy.deepcopy(lat_table)
            if lat_table.table:
                _rename_glyphs_in_ot_table(lat_table.table, lat_name_map)

        if not lat_table and not jp_table:
            continue

        if not jp_table and lat_table:
            merged[table_tag] = lat_table if lat_name_map else copy.deepcopy(lat_table)
            continue

        if not lat_table:
            # Even when we aren't appending Latin lookups (budget path) or
            # there's no Latin GSUB/GPOS at all, base-side mixed lookups
            # may reference Latin-owned glyph names that the merge engine
            # placed at base codepoints (cmap CID remap, same-name
            # overwrite). Drop the lookups that are wholly Latin-input
            # first, then strip Latin-source entries out of the surviving
            # mixed lookups. Reversing the order would leave the wholly-
            # Latin lookups around as empty husks — `_classify_lookup`
            # treats an empty lookup as ``mixed``, not ``latin``, so it
            # would no longer be eligible for removal.
            _filter_subordinate_lookups(jp_table, lat_glyph_names)
            if lat_glyph_names and jp_table and jp_table.table \
                    and jp_table.table.LookupList:
                for lookup in jp_table.table.LookupList.Lookup:
                    if table_tag == 'GSUB':
                        _strip_latin_only_ligatures(lookup, lat_glyph_names)
                        _strip_latin_owned_substitutions(
                            lookup, lat_glyph_names, preserved_lat_names)
                    elif table_tag == 'GPOS':
                        _strip_latin_first_from_pairpos(lookup, lat_glyph_names)
            continue

        _merge_ot_table_v2(lat_table, jp_table, lat_font, jp_font, merged,
                           table_tag, lat_glyph_names,
                           lat_scale=lat_scale, lat_baseline=lat_baseline,
                           preserved_lat_names=preserved_lat_names)


def _filter_subordinate_lookups(table, lat_glyph_names: set):
    """Remove subordinate Latin lookups from a table (in-place)."""
    if not hasattr(table, 'table') or not table.table:
        return
    ot = table.table
    if not ot.LookupList:
        return

    lookups = ot.LookupList.Lookup
    keep_indices = []
    for i, lookup in enumerate(lookups):
        if _classify_lookup(lookup, lat_glyph_names) != 'latin':
            keep_indices.append(i)

    if len(keep_indices) == len(lookups):
        return

    _reindex_table(ot, keep_indices)


def _reindex_table(ot, kept_lookup_indices: list):
    """Reindex a GSUB/GPOS table after removing lookups.

    Updates four things in order:
      1. Cross-lookup references inside surviving chaining/context lookups —
         remapped or dropped via _remap_lookup_references.
      2. FeatureList — drop features whose every lookup was removed; build
         an old-feature-index → new-feature-index mapping for step 3.
      3. ScriptList — every LangSys.FeatureIndex (and ReqFeatureIndex)
         rewritten through the feature mapping; references to removed
         features are dropped.
      4. LookupList — trimmed to the kept indices.
    """
    lookup_remap = {old: new for new, old in enumerate(kept_lookup_indices)}

    # 1. Remap (and drop) cross-lookup references in surviving lookups.
    #    Done before LookupList is trimmed so the indices still address
    #    the original positions while we walk.
    for old_idx in kept_lookup_indices:
        _remap_lookup_references(ot.LookupList.Lookup[old_idx], lookup_remap)

    # 2. Rebuild FeatureList and track old→new feature index mapping.
    feat_remap: dict[int, int] = {}
    if ot.FeatureList:
        new_features = []
        for old_idx, feat_rec in enumerate(ot.FeatureList.FeatureRecord):
            feat = feat_rec.Feature
            new_indices = [lookup_remap[i] for i in feat.LookupListIndex
                           if i in lookup_remap]
            if not new_indices:
                continue  # feature has no surviving lookups → drop
            feat.LookupListIndex = new_indices
            feat.LookupCount = len(new_indices)
            feat_remap[old_idx] = len(new_features)
            new_features.append(feat_rec)
        ot.FeatureList.FeatureRecord = new_features
        ot.FeatureList.FeatureCount = len(new_features)

    # 3. Rewrite ScriptList LangSys feature references.
    if ot.ScriptList:
        for sr in ot.ScriptList.ScriptRecord:
            lang_systems = []
            if sr.Script.DefaultLangSys is not None:
                lang_systems.append(sr.Script.DefaultLangSys)
            for lsr in (sr.Script.LangSysRecord or []):
                if lsr.LangSys is not None:
                    lang_systems.append(lsr.LangSys)
            for ls in lang_systems:
                ls.FeatureIndex = [
                    feat_remap[fi]
                    for fi in (ls.FeatureIndex or [])
                    if fi in feat_remap
                ]
                # ReqFeatureIndex: 0xFFFF means "none"; otherwise remap or
                # drop (collapse to 0xFFFF) when the required feature is gone.
                req = getattr(ls, 'ReqFeatureIndex', 0xFFFF)
                if req != 0xFFFF:
                    ls.ReqFeatureIndex = feat_remap.get(req, 0xFFFF)

    # 4. Trim the LookupList itself.
    ot.LookupList.Lookup = [ot.LookupList.Lookup[i] for i in kept_lookup_indices]
    ot.LookupList.LookupCount = len(ot.LookupList.Lookup)


# Latin-oriented scripts use EN features
LATIN_SCRIPTS = {'latn', 'DFLT', 'cyrl', 'grek'}
EXPLICIT_LATIN_SCRIPTS = LATIN_SCRIPTS - {'DFLT'}
# CJK scripts use JP features
CJK_SCRIPTS = {'kana', 'hani', 'hang', 'bopo', 'yi  '}

# GSUB feature tags whose JP-side record shadows the Latin-side record
# under explicit Latin scripts in HarfBuzz, mirroring the GPOS dedupe
# (`kern` / `mark` / `mkmk`).
#
# - `ccmp`: verified by `M̀` / `Ê̄` shaping — JP `ccmp` fires
#   first under `latn` and keeps Latin's `gravecomb → gravecomb.case`
#   / `uni0304 → uni0304.case` rules from running.
# - `dlig`: verified with Inter (Variable) + Noto Sans JP — Inter's
#   chain-context dlig (`f → f.i` before `i`, `r → f.1` after `r`,
#   `t → t.1` between two `t`s, etc.) never fires in the merged font
#   because the JP `dlig` feature record sits ahead of Inter's under
#   `latn`. The per-entry strip (`_strip_latin_only_ligatures`) empties
#   JP's Latin-input entries but the *feature record* itself still
#   shadows. Dedupe at the LangSys level so Inter's dlig fires.
#
# Other GSUB shared tags intentionally keep both records: JP-side
# `aalt` for CJK glyphs needs to remain reachable under `latn` (Issue
# #2 #6), and other tags either follow the same per-entry strip or
# haven't been observed shadowing.
GSUB_LATN_DEDUPE_TAGS = frozenset({'ccmp', 'dlig'})


# Restricted to explicit user-selected Latin/sub features. Default-on,
# context-sensitive, or semantically special GSUB tags (`calt`, `liga`,
# `ccmp`, `case`, `dlig`) remain out of this allowlist and use the strict
# full-domain GSUB promotion policy below. Language/alternate/CJK-layout
# tags (`locl`, `aalt`, `fwid`, `hwid`, `vert`, `vrt2`) remain out of scope
# for cross-script Latin/sub promotion.
# See `docs/CJK_LATIN_USER_FEATURES_PLAN.md`.
CJK_LATIN_USER_FEATURE_ALLOWLIST = frozenset(
    {f'ss{n:02d}' for n in range(1, 21)}    # ss01..ss20
    | {f'cv{n:02d}' for n in range(1, 100)}  # cv01..cv99
    | {'salt', 'zero', 'tnum', 'pnum', 'frac', 'numr', 'dnom',
       'sups', 'subs', 'sinf', 'ordn'}
)


# Latin/sub GSUB tags that may be exposed under CJK LangSys only after the
# strict sub-font-confined full-domain check passes. This policy includes
# default-on, context-sensitive, or semantically special tags whose inputs,
# context, outputs, and subordinate lookup closure must all stay sub-owned.
CJK_LATIN_STRICT_GSUB_PROMOTION_POLICIES = {
    'calt': {
        'kind': 'default_contextual',
        'scope': 'default_and_named',
    },
    'liga': {
        'kind': 'default_ligature',
        'scope': 'default_and_named',
    },
    'ccmp': {
        'kind': 'required_composition',
        'scope': 'default_and_named',
    },
    'case': {
        'kind': 'app_or_user_enabled',
        'scope': 'default_and_named',
    },
    'dlig': {
        'kind': 'user_enabled_ligature',
        'scope': 'default_and_named',
    },
}
CJK_LATIN_STRICT_GSUB_PROMOTION_TAGS = frozenset(
    CJK_LATIN_STRICT_GSUB_PROMOTION_POLICIES)


def _collect_subordinate_lookup_indices(lookup) -> set:
    """Collect every lookup index reachable from *lookup* via Context /
    ChainContext SubstLookupRecord / PosLookupRecord, including nested
    rule sets (Format 1/2). Does not include *lookup* itself."""
    indices = set()
    for subtable in lookup.SubTable:
        st = subtable
        if hasattr(st, 'ExtSubTable'):
            st = st.ExtSubTable
        if hasattr(st, 'SubstLookupRecord') and st.SubstLookupRecord:
            for rec in st.SubstLookupRecord:
                indices.add(rec.LookupListIndex)
        if hasattr(st, 'PosLookupRecord') and st.PosLookupRecord:
            for rec in st.PosLookupRecord:
                indices.add(rec.LookupListIndex)
        for attr in ('SubRuleSet', 'SubClassSet',
                     'ChainSubRuleSet', 'ChainSubClassSet',
                     'PosRuleSet', 'PosClassSet',
                     'ChainPosRuleSet', 'ChainPosClassSet'):
            ruleset_list = getattr(st, attr, None)
            if not ruleset_list:
                continue
            for ruleset in ruleset_list:
                if not ruleset:
                    continue
                for attr2 in ('SubRule', 'SubClassRule',
                              'ChainSubRule', 'ChainSubClassRule',
                              'PosRule', 'PosClassRule',
                              'ChainPosRule', 'ChainPosClassRule'):
                    rules = getattr(ruleset, attr2, None)
                    if not rules:
                        continue
                    for rule in rules:
                        if hasattr(rule, 'SubstLookupRecord') \
                                and rule.SubstLookupRecord:
                            for rec in rule.SubstLookupRecord:
                                indices.add(rec.LookupListIndex)
                        if hasattr(rule, 'PosLookupRecord') \
                                and rule.PosLookupRecord:
                            for rec in rule.PosLookupRecord:
                                indices.add(rec.LookupListIndex)
    return indices


def _latin_feature_safe_for_cjk_promotion(feat_record, merged_lookups,
                                          lat_glyph_names):
    """Return True if every glyph referenced by *feat_record*'s lookups —
    transitively, including subordinate lookups reached through Context /
    ChainContext records — is in *lat_glyph_names*. The feature is then
    safe to expose under a CJK script's LangSys: it can only rewrite
    Latin-owned glyphs.

    A lookup with no detectable input glyphs is treated as safe (the same
    convention `_classify_lookup` uses for its `mixed` fallback): an empty
    lookup is a no-op.
    """
    feat = feat_record.Feature
    pending = list(feat.LookupListIndex or [])
    visited = set()
    while pending:
        li = pending.pop()
        if li in visited:
            continue
        visited.add(li)
        if li < 0 or li >= len(merged_lookups):
            return False
        lookup = merged_lookups[li]
        glyphs = _collect_lookup_glyphs(lookup)
        if glyphs:
            for g in glyphs:
                if g not in lat_glyph_names:
                    return False
        # Walk Context / ChainContext subordinate lookups too: a top-level
        # coverage that's all-Latin can still drive a subordinate lookup
        # that touches non-Latin glyphs.
        for sub_li in _collect_subordinate_lookup_indices(lookup):
            if sub_li not in visited:
                pending.append(sub_li)
    return True


def _sub_feature_strictly_safe_for_cjk_gsub_promotion(
        feat_record, merged_lookups, sub_owned_glyphs):
    """Return True only when a GSUB feature is sub-font-confined.

    Unlike the explicit user-feature safety helper, this checks every glyph
    reachable from the lookup closure: inputs, backtrack/lookahead context,
    class definitions, and substitution outputs. Unknown lookup shapes are
    unsafe because this path exposes default-on contextual features.
    """
    feat = feat_record.Feature
    pending = list(feat.LookupListIndex or [])
    visited = set()
    saw_glyph = False

    while pending:
        li = pending.pop()
        if li in visited:
            continue
        visited.add(li)

        if li < 0 or li >= len(merged_lookups):
            return False

        lookup = merged_lookups[li]
        domain = _collect_gsub_lookup_full_domain(lookup)
        if domain.unknown:
            return False
        if domain.glyphs:
            saw_glyph = True
            if not domain.glyphs <= sub_owned_glyphs:
                return False

        for sub_li in _collect_subordinate_lookup_indices(lookup):
            if sub_li not in visited:
                pending.append(sub_li)

    return saw_glyph


def _sub_feature_strictly_safe_for_cjk_default_promotion(
        feat_record, merged_lookups, sub_owned_glyphs):
    """Backward-compatible wrapper for the Phase 1 `calt` helper name."""
    return _sub_feature_strictly_safe_for_cjk_gsub_promotion(
        feat_record, merged_lookups, sub_owned_glyphs)


def _build_lang_sys(jp_lang_sys, lat_lang_sys, script_tag, table_tag,
                    jp_feat_index_map, lat_feat_index_map,
                    jp_feature_records, lat_feature_records,
                    cjk_extra_lat_features=None,
                    merged_feature_records=None,
                    combined_record_cache=None):
    """Build a merged LangSys with correct feature references.

    Parameters:
        jp_lang_sys: Japanese LangSys object (or None)
        lat_lang_sys: Latin LangSys object (or None)
        script_tag: OpenType script tag (e.g. 'latn', 'kana')
        table_tag: 'GSUB' or 'GPOS'
        jp_feat_index_map: old JP feature index -> new merged feature index
        lat_feat_index_map: old EN feature index -> new merged feature index
        jp_feature_records: JP FeatureList.FeatureRecord (for tag lookup)
        lat_feature_records: EN FeatureList.FeatureRecord (for tag lookup)
        cjk_extra_lat_features: list of (tag, new_merged_idx) for Latin/sub
            features promoted into CJK LangSys records. This includes
            allowlisted explicit user features (ss02, tnum, ...) and strict
            sub-font-confined GSUB features such as calt, liga, ccmp, case,
            and dlig. Only consulted when script_tag is in CJK_SCRIPTS.
        merged_feature_records: the merged FeatureList.FeatureRecord list
            (jp_features + lat_features, in the same order as the merged
            FeatureList). Required to support the duplicate-tag merge in
            CJK_SCRIPTS: when a promoted tag already lives on the JP
            side of the current LangSys, a fresh combined FeatureRecord
            (JP lookups + Latin lookups) is appended to this list and the
            LangSys references the new index. The original JP record is
            left untouched, so a Latin named-only lookup never leaks into
            the JP DefaultLangSys (or any other LangSys that shares the
            same JP record by index).
        combined_record_cache: dict keyed by (jp_merged_idx, lat_merged_idx)
            mapping to the cached combined FeatureRecord index. Lets every
            LangSys that needs the same combination reuse the same
            appended record.
    """
    from fontTools.ttLib.tables import otTables

    new_lang_sys = otTables.LangSys()
    new_lang_sys.ReqFeatureIndex = 0xFFFF
    new_lang_sys.LookupOrder = None

    feat_indices = []

    # Tags that the Latin side actually contributes through *this* LangSys.
    # The shadowing dedupe must compare per-LangSys, not table-globally:
    # otherwise an explicit Latin script that the Latin font doesn't even
    # define (e.g. `grek` when TikTok Sans has no Greek LangSys) would
    # still drop JP-side features just because the tag exists somewhere
    # else on the Latin side.
    lat_tags_in_langsys = set()
    if lat_lang_sys and lat_lang_sys.FeatureIndex:
        for old_idx in lat_lang_sys.FeatureIndex:
            if 0 <= old_idx < len(lat_feature_records):
                lat_tags_in_langsys.add(lat_feature_records[old_idx].FeatureTag)

    if script_tag in CJK_SCRIPTS:
        # CJK script: use JP features, plus narrow Latin-side promotions so
        # apps that shape mixed Latin/CJK runs through a CJK LangSys can still
        # reach them. Explicit user features use the allowlist; default-on /
        # context-sensitive Latin tags stay excluded unless they pass the
        # separate strict sub-font-confined GSUB policy.
        jp_tags_in_langsys = set()
        jp_tag_to_merged_idx = {}
        if jp_lang_sys and jp_lang_sys.FeatureIndex:
            for old_idx in jp_lang_sys.FeatureIndex:
                if old_idx in jp_feat_index_map:
                    merged_idx = jp_feat_index_map[old_idx]
                    feat_indices.append(merged_idx)
                    if old_idx < len(jp_feature_records):
                        tag = jp_feature_records[old_idx].FeatureTag
                        jp_tags_in_langsys.add(tag)
                        jp_tag_to_merged_idx.setdefault(tag, merged_idx)
        # Latin-side promoted features live under Latin's `latn`/`DFLT`
        # LangSys, not the (typically nonexistent) Latin `kana`/`hani`
        # LangSys, so iterate the pre-computed list collected in
        # `_merge_ot_table_v2` rather than `lat_lang_sys` (which is None for
        # CJK script tags).
        if table_tag == 'GSUB' and cjk_extra_lat_features:
            for tag, new_idx in cjk_extra_lat_features:
                if tag not in jp_tags_in_langsys:
                    feat_indices.append(new_idx)
                    continue
                # Duplicate tag: HarfBuzz would only fire one of two
                # same-tag records (the shadowing pattern that bites `tnum`
                # under CJK and GSUB_LATN_DEDUPE_TAGS under `latn`). Instead
                # of dropping the Latin promotion *or* mutating the shared JP
                # record (which would leak the Latin lookups into
                # every LangSys that references the same JP record by
                # index — for example a Latin named-only `tnum`
                # leaking into `kana/dflt`), build a fresh combined
                # FeatureRecord (JP lookups + Latin lookups), cache it
                # by `(jp_idx, lat_idx)` so other LangSys reuse it, and
                # have this LangSys reference the combined index in
                # place of the bare JP one.
                if (merged_feature_records is None
                        or combined_record_cache is None):
                    continue
                jp_merged_idx = jp_tag_to_merged_idx.get(tag)
                if jp_merged_idx is None:
                    continue
                if jp_merged_idx >= len(merged_feature_records):
                    continue
                if new_idx >= len(merged_feature_records):
                    continue
                cache_key = (jp_merged_idx, new_idx)
                combined_idx = combined_record_cache.get(cache_key)
                if combined_idx is None:
                    jp_rec = merged_feature_records[jp_merged_idx]
                    lat_rec = merged_feature_records[new_idx]
                    combined_rec = copy.deepcopy(jp_rec)
                    seen = set(combined_rec.Feature.LookupListIndex or [])
                    for li in (lat_rec.Feature.LookupListIndex or []):
                        if li not in seen:
                            combined_rec.Feature.LookupListIndex.append(li)
                            seen.add(li)
                    combined_rec.Feature.LookupCount = len(
                        combined_rec.Feature.LookupListIndex)
                    combined_idx = len(merged_feature_records)
                    merged_feature_records.append(combined_rec)
                    combined_record_cache[cache_key] = combined_idx
                # Replace the bare JP index in feat_indices with the
                # combined index. (feat_indices was filled in the JP
                # loop above; replace the first occurrence.)
                for i, fi in enumerate(feat_indices):
                    if fi == jp_merged_idx:
                        feat_indices[i] = combined_idx
                        break
    elif script_tag in LATIN_SCRIPTS:
        # Latin script: use EN features, plus JP CJK-only features
        # (some features like vert, vrt2 should still be available)
        if lat_lang_sys and lat_lang_sys.FeatureIndex:
            for old_idx in lat_lang_sys.FeatureIndex:
                if old_idx in lat_feat_index_map:
                    feat_indices.append(lat_feat_index_map[old_idx])
        # Also add JP features. When a tag is shared with the Latin font
        # (e.g. both define `dlig` or `aalt`), we generally keep both
        # feature records under the Latin script's LangSys so JP-side
        # lookups on JP glyphs remain reachable (Issue #2 #6). The
        # exception is shadowing tags: HarfBuzz effectively lets the first
        # duplicate tag win under explicit Latin scripts, so for those the
        # JP-side record has to be dropped or the Latin one becomes
        # unreachable. Verified shadowing tags so far: every GPOS tag and
        # GSUB `ccmp`.
        if jp_lang_sys and jp_lang_sys.FeatureIndex:
            for old_idx in jp_lang_sys.FeatureIndex:
                if old_idx in jp_feat_index_map:
                    tag = None
                    if old_idx < len(jp_feature_records):
                        tag = jp_feature_records[old_idx].FeatureTag
                    # Drop the JP duplicate under explicit Latin scripts
                    # for tags HB picks the first record of:
                    #   - any GPOS tag (kern / mark / mkmk / etc.)
                    #   - GSUB ccmp (verified by hb-shape against
                    #     M̀ / Ê̄: the Latin-side
                    #     gravecomb → gravecomb.case rule never fires
                    #     when the JP-side ccmp is still present)
                    if script_tag in EXPLICIT_LATIN_SCRIPTS \
                            and tag in lat_tags_in_langsys:
                        if table_tag == 'GPOS' or (
                                table_tag == 'GSUB'
                                and tag in GSUB_LATN_DEDUPE_TAGS):
                            continue
                    feat_indices.append(jp_feat_index_map[old_idx])
    else:
        # Unknown script: include both
        if jp_lang_sys and jp_lang_sys.FeatureIndex:
            for old_idx in jp_lang_sys.FeatureIndex:
                if old_idx in jp_feat_index_map:
                    feat_indices.append(jp_feat_index_map[old_idx])
        if lat_lang_sys and lat_lang_sys.FeatureIndex:
            for old_idx in lat_lang_sys.FeatureIndex:
                if old_idx in lat_feat_index_map:
                    feat_indices.append(lat_feat_index_map[old_idx])

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for idx in feat_indices:
        if idx not in seen:
            seen.add(idx)
            deduped.append(idx)

    new_lang_sys.FeatureIndex = sorted(deduped)
    new_lang_sys.FeatureCount = len(new_lang_sys.FeatureIndex)
    return new_lang_sys


def _merge_ot_table_v2(lat_table, jp_table, lat_font, jp_font, merged,
                       table_tag, lat_glyph_names: set,
                       lat_scale: float = 1.0, lat_baseline: float = 0,
                       preserved_lat_names: set = None):
    """
    Merge Latin and Japanese GSUB/GPOS tables.

    lat_scale: total scale factor for Latin glyphs (user_scale * upm_ratio)
    lat_baseline: vertical offset for Latin glyphs (in merged UPM units)
    """
    from fontTools.ttLib.tables import otTables

    lat_ot = lat_table.table
    jp_ot = jp_table.table

    if not lat_ot or not jp_ot:
        return

    # --- Step 1: Filter JP lookups ---
    jp_lookups = jp_ot.LookupList.Lookup if jp_ot.LookupList else []
    lat_lookups = lat_ot.LookupList.Lookup if lat_ot.LookupList else []

    # Classify JP lookups: remove those whose glyphs all exist in Latin font
    jp_keep_indices = []
    for i, lookup in enumerate(jp_lookups):
        cls = _classify_lookup(lookup, lat_glyph_names)
        if cls != 'latin':
            jp_keep_indices.append(i)

    jp_remap = {old: new for new, old in enumerate(jp_keep_indices)}
    filtered_jp_lookups = [jp_lookups[i] for i in jp_keep_indices]

    # Fix internal lookup references in JP lookups after filtering.
    # When lookups are removed, remaining lookups' indices shift,
    # so chaining/context lookups must be remapped.
    for lookup in filtered_jp_lookups:
        _remap_lookup_references(lookup, jp_remap)

    # Drop Latin-only layout entries from base-side `mixed` lookups so the
    # base font's leftover Latin layout (kern stacking, dlig hijacking
    # plain Latin text into CJK square symbols, etc.) doesn't fire alongside
    # the Latin font's own layout.
    if lat_glyph_names:
        if table_tag == 'GPOS':
            for lookup in filtered_jp_lookups:
                _strip_latin_first_from_pairpos(lookup, lat_glyph_names)
        elif table_tag == 'GSUB':
            for lookup in filtered_jp_lookups:
                _strip_latin_only_ligatures(lookup, lat_glyph_names)
                _strip_latin_owned_substitutions(
                    lookup, lat_glyph_names, preserved_lat_names)

    # --- Step 2: Build merged lookup list ---
    lat_offset = len(filtered_jp_lookups)
    lat_lookups_copy = copy.deepcopy(lat_lookups)

    # Fix chaining context lookup references in Latin lookups.
    # Lookups like calt/frac/case use ChainContextSubst (type 6) or
    # ContextSubst (type 5) which reference other lookups by index.
    # These indices must be offset since Latin lookups are appended
    # after Japanese lookups in the merged list.
    for lookup in lat_lookups_copy:
        _offset_lookup_references(lookup, lat_offset)

    merged_lookups = filtered_jp_lookups + lat_lookups_copy

    # --- Step 3: Build merged FeatureList ---
    # Collect JP features (with remapped lookup indices, dropping empty ones)
    jp_features = []  # list of (tag, Feature object, source='jp')
    jp_feat_index_map = {}  # old JP feature index → new merged feature index
    merged_gpos_kern_index = None

    def _merge_lookup_indices_into_feature(feature_index, lookup_indices):
        if feature_index < len(jp_features):
            feature = jp_features[feature_index][1].Feature
        else:
            feature = lat_features[feature_index - len(jp_features)][1].Feature
        seen = set(feature.LookupListIndex or [])
        for lookup_index in lookup_indices:
            if lookup_index not in seen:
                feature.LookupListIndex.append(lookup_index)
                seen.add(lookup_index)
        feature.LookupCount = len(feature.LookupListIndex)

    if jp_ot.FeatureList:
        for old_idx, feat_rec in enumerate(jp_ot.FeatureList.FeatureRecord):
            new_indices = [jp_remap[i] for i in feat_rec.Feature.LookupListIndex
                           if i in jp_remap]
            if new_indices:
                if table_tag == 'GPOS' and feat_rec.FeatureTag == 'kern' \
                        and merged_gpos_kern_index is not None:
                    _merge_lookup_indices_into_feature(
                        merged_gpos_kern_index, new_indices)
                    jp_feat_index_map[old_idx] = merged_gpos_kern_index
                    continue
                new_feat = copy.deepcopy(feat_rec)
                new_feat.Feature.LookupListIndex = new_indices
                new_feat.Feature.LookupCount = len(new_indices)
                new_merged_idx = len(jp_features)
                jp_feat_index_map[old_idx] = new_merged_idx
                jp_features.append((feat_rec.FeatureTag, new_feat, 'jp'))
                if table_tag == 'GPOS' and feat_rec.FeatureTag == 'kern':
                    merged_gpos_kern_index = new_merged_idx

    # Collect EN features (with offset lookup indices)
    lat_features = []  # list of (tag, Feature object, source='en')
    lat_feat_index_map = {}  # old EN feature index → new merged feature index
    if lat_ot.FeatureList:
        for old_idx, feat_rec in enumerate(lat_ot.FeatureList.FeatureRecord):
            new_feat = copy.deepcopy(feat_rec)
            new_feat.Feature.LookupListIndex = [
                i + lat_offset for i in new_feat.Feature.LookupListIndex
            ]
            new_feat.Feature.LookupCount = len(new_feat.Feature.LookupListIndex)
            if table_tag == 'GPOS' and feat_rec.FeatureTag == 'kern' \
                    and merged_gpos_kern_index is not None:
                _merge_lookup_indices_into_feature(
                    merged_gpos_kern_index, new_feat.Feature.LookupListIndex)
                lat_feat_index_map[old_idx] = merged_gpos_kern_index
                continue
            # Mark this record so the later UINameID-collision remap in
            # reconcile_tables only touches Latin-derived FeatureParams,
            # not the base font's ones that happen to share a nameID value.
            new_feat._lat_origin = True
            new_merged_idx = len(jp_features) + len(lat_features)
            lat_feat_index_map[old_idx] = new_merged_idx
            lat_features.append((feat_rec.FeatureTag, new_feat, 'en'))
            if table_tag == 'GPOS' and feat_rec.FeatureTag == 'kern':
                merged_gpos_kern_index = new_merged_idx

    # Merged feature list: JP features first, then EN features
    all_features = jp_features + lat_features

    merged_feature_list = otTables.FeatureList()
    merged_feature_list.FeatureRecord = [f[1] for f in all_features]
    merged_feature_list.FeatureCount = len(all_features)

    # Cache for per-LangSys CJK duplicate-tag combined records, keyed by
    # (jp_merged_idx, lat_merged_idx). Same combination across LangSys
    # reuses the same appended FeatureRecord rather than producing a new
    # one each time.
    combined_record_cache = {}

    # --- Step 4: Build merged ScriptList ---
    # Collect all script tags from both fonts
    all_script_tags = set()
    jp_script_records = {}
    if jp_ot.ScriptList:
        for sr in jp_ot.ScriptList.ScriptRecord:
            all_script_tags.add(sr.ScriptTag)
            jp_script_records[sr.ScriptTag] = sr
    lat_script_records = {}
    if lat_ot.ScriptList:
        for sr in lat_ot.ScriptList.ScriptRecord:
            all_script_tags.add(sr.ScriptTag)
            lat_script_records[sr.ScriptTag] = sr

    # Capture feature records for _build_lang_sys tag lookups (per-LangSys
    # dedupe needs the Latin records too).
    jp_feature_records = jp_ot.FeatureList.FeatureRecord if jp_ot.FeatureList else []
    lat_feature_records = lat_ot.FeatureList.FeatureRecord if lat_ot.FeatureList else []

    # Pre-compute Latin/sub GSUB promotions so CJK-script LangSys records can
    # re-expose explicit user features and strict default features. Two
    # restrictions:
    #
    #   1. Only features reachable from the Latin font's `latn` / `DFLT`
    #      LangSys (default or named) are eligible. Iterating all of
    #      `lat_feat_index_map` would also pick up orphan features that
    #      no LangSys references at all.
    #   2. Each candidate's lookups must only touch glyphs the Latin font
    #      owns — including subordinate lookups reached via Context /
    #      ChainContext records. Pan-CJK base fonts ship Latin-script
    #      lookups too, but those live in `jp_features`, not
    #      `lat_features`; the check still pins the invariant in case the
    #      Latin source ever ships an allowlist tag whose lookup reaches
    #      outside its own glyph set.
    #
    # Named LangSys handling: a feature only reachable through Latin's
    # `latn/JAN` (and missing from the default) should still be reachable
    # through CJK `kana/JAN` — Issue #12-style locale fallback.
    # `cjk_extras_default` is the union of Latin `latn` / `DFLT` defaults
    # (used by every CJK DefaultLangSys), and `cjk_extras_named[lang_tag]`
    # adds the union of `latn/<lang_tag>` and `DFLT/<lang_tag>` named
    # LangSys candidates on top of the defaults (used by every CJK named
    # LangSys with that tag).
    def _collect_lat_user_candidates(feat_indices, seen_tags):
        out = []
        for old_idx in feat_indices or []:
            if old_idx not in lat_feat_index_map:
                continue
            if old_idx >= len(lat_feature_records):
                continue
            tag = lat_feature_records[old_idx].FeatureTag
            if tag not in CJK_LATIN_USER_FEATURE_ALLOWLIST:
                continue
            # Per OpenType spec a LangSys has at most one FeatureRecord
            # per tag, so winner-takes-all on the first occurrence is
            # safe. If a malformed Latin source ever ships multiple
            # `tnum` records under the same LangSys, the first wins and
            # later duplicates are skipped here (matches HarfBuzz's
            # behaviour for the same shape).
            if tag in seen_tags:
                continue
            new_merged_idx = lat_feat_index_map[old_idx]
            merged_feat = all_features[new_merged_idx][1]
            if not _latin_feature_safe_for_cjk_promotion(
                    merged_feat, merged_lookups, lat_glyph_names):
                continue
            seen_tags.add(tag)
            out.append((tag, new_merged_idx))
        return out

    def _collect_lat_strict_gsub_candidates(feat_indices, seen_tags):
        out = []
        for old_idx in feat_indices or []:
            if old_idx not in lat_feat_index_map:
                continue
            if old_idx >= len(lat_feature_records):
                continue
            tag = lat_feature_records[old_idx].FeatureTag
            if tag not in CJK_LATIN_STRICT_GSUB_PROMOTION_TAGS:
                continue
            if tag in seen_tags:
                continue
            new_merged_idx = lat_feat_index_map[old_idx]
            merged_feat = all_features[new_merged_idx][1]
            if not _sub_feature_strictly_safe_for_cjk_gsub_promotion(
                    merged_feat, merged_lookups, lat_glyph_names):
                continue
            seen_tags.add(tag)
            out.append((tag, new_merged_idx))
        return out

    def _collect_lat_cjk_extra_candidates(feat_indices, seen_tags):
        out = []
        out.extend(_collect_lat_user_candidates(feat_indices, seen_tags))
        out.extend(_collect_lat_strict_gsub_candidates(feat_indices, seen_tags))
        return out

    cjk_extras_default = []  # [(tag, new_merged_idx)]
    cjk_extras_named = {}    # lang_tag -> [(tag, new_merged_idx)]
    if table_tag == 'GSUB' and lat_ot.ScriptList:
        default_seen = set()
        for sr in lat_ot.ScriptList.ScriptRecord:
            if sr.ScriptTag not in ('latn', 'DFLT'):
                continue
            ds = sr.Script.DefaultLangSys
            if ds:
                cjk_extras_default.extend(
                    _collect_lat_cjk_extra_candidates(
                        ds.FeatureIndex, default_seen))
        for sr in lat_ot.ScriptList.ScriptRecord:
            if sr.ScriptTag not in ('latn', 'DFLT'):
                continue
            for lsr in (sr.Script.LangSysRecord or []):
                tag_key = lsr.LangSysTag
                merged_extras = cjk_extras_named.get(tag_key)
                if merged_extras is None:
                    merged_extras = list(cjk_extras_default)
                    cjk_extras_named[tag_key] = merged_extras
                seen = {t for t, _ in merged_extras}
                merged_extras.extend(
                    _collect_lat_cjk_extra_candidates(
                        lsr.LangSys.FeatureIndex, seen))

    # Build merged script records
    merged_script_records = []
    for script_tag in sorted(all_script_tags):
        jp_sr = jp_script_records.get(script_tag)
        lat_sr = lat_script_records.get(script_tag)

        new_sr = otTables.ScriptRecord()
        new_sr.ScriptTag = script_tag
        new_sr.Script = otTables.Script()

        # Default LangSys
        jp_default = jp_sr.Script.DefaultLangSys if jp_sr else None
        lat_default = lat_sr.Script.DefaultLangSys if lat_sr else None
        new_sr.Script.DefaultLangSys = _build_lang_sys(
            jp_default, lat_default, script_tag, table_tag,
            jp_feat_index_map, lat_feat_index_map,
            jp_feature_records, lat_feature_records,
            cjk_extra_lat_features=cjk_extras_default,
            merged_feature_records=merged_feature_list.FeatureRecord,
            combined_record_cache=combined_record_cache)

        # Named LangSys records
        lang_sys_tags = set()
        jp_lang_map = {}
        lat_lang_map = {}
        if jp_sr and jp_sr.Script.LangSysRecord:
            for lsr in jp_sr.Script.LangSysRecord:
                lang_sys_tags.add(lsr.LangSysTag)
                jp_lang_map[lsr.LangSysTag] = lsr.LangSys
        if lat_sr and lat_sr.Script.LangSysRecord:
            for lsr in lat_sr.Script.LangSysRecord:
                lang_sys_tags.add(lsr.LangSysTag)
                lat_lang_map[lsr.LangSysTag] = lsr.LangSys
        # For CJK scripts, also create a named LangSys for any tag that
        # Latin's matching named LangSys (e.g. `latn/JAN`) contributes
        # allowlist features for, even if neither side defines that tag
        # under this CJK script. Without this, an Inter `latn/JAN`-only
        # `tnum` is unreachable from any Japanese run shaped under
        # `kana/JAN`.
        if script_tag in CJK_SCRIPTS and table_tag == 'GSUB':
            for tag_key, extras in cjk_extras_named.items():
                if extras and extras != cjk_extras_default:
                    lang_sys_tags.add(tag_key)

        new_lang_records = []
        for lang_tag in sorted(lang_sys_tags):
            new_lsr = otTables.LangSysRecord()
            new_lsr.LangSysTag = lang_tag
            # If only one input defines a named LangSys, the other input's
            # DefaultLangSys is still active for that language before merge.
            # Preserve that effective feature set so the new named record does
            # not shadow the missing side's default features.
            jp_lang_sys = jp_lang_map.get(lang_tag, jp_default)
            lat_lang_sys = lat_lang_map.get(lang_tag, lat_default)
            extras = cjk_extras_named.get(lang_tag, cjk_extras_default)
            new_lsr.LangSys = _build_lang_sys(
                jp_lang_sys,
                lat_lang_sys,
                script_tag, table_tag,
                jp_feat_index_map, lat_feat_index_map,
                jp_feature_records, lat_feature_records,
                cjk_extra_lat_features=extras,
                merged_feature_records=merged_feature_list.FeatureRecord,
                combined_record_cache=combined_record_cache)
            new_lang_records.append(new_lsr)

        new_sr.Script.LangSysRecord = new_lang_records if new_lang_records else []
        new_sr.Script.LangSysCount = len(new_lang_records)
        merged_script_records.append(new_sr)

    merged_script_list = otTables.ScriptList()
    merged_script_list.ScriptRecord = merged_script_records
    merged_script_list.ScriptCount = len(merged_script_records)

    # CJK duplicate-tag merge may have appended combined FeatureRecords
    # to merged_feature_list.FeatureRecord; refresh the count so it
    # matches the final list.
    merged_feature_list.FeatureCount = len(merged_feature_list.FeatureRecord)

    # --- Step 5: Apply to merged font ---
    jp_ot.LookupList.Lookup = merged_lookups
    jp_ot.LookupList.LookupCount = len(merged_lookups)
    jp_ot.FeatureList = merged_feature_list
    jp_ot.ScriptList = merged_script_list

    # --- Step 6: Scale GPOS values from Latin font ---
    # GPOS values must be transformed to match the glyph transformations:
    # - XAdvance/XPlacement: scale by lat_scale (includes UPM ratio + user scale)
    # - YAdvance/YPlacement: scale by lat_scale
    # - Anchor coordinates: scale by lat_scale, Y also shifted by lat_baseline
    if table_tag == 'GPOS' and (lat_scale != 1.0 or lat_baseline != 0):
        for i in range(lat_offset, len(merged_lookups)):
            _scale_gpos_lookup(merged_lookups[i], lat_scale, lat_baseline)


def _scale_value_record(vr, scale: float):
    """Scale relative positioning fields in a GPOS ValueRecord.

    ValueRecords contain relative adjustments (kerning, placement shifts).
    These scale proportionally with glyph size but are NOT affected by
    baseline offset (since both glyphs shift by the same amount).
    """
    if vr is None:
        return
    for attr in ('XPlacement', 'YPlacement', 'XAdvance', 'YAdvance'):
        val = getattr(vr, attr, None)
        if val is not None and val != 0:
            setattr(vr, attr, int(round(val * scale)))


def _scale_gpos_lookup(lookup, scale: float, dy: float = 0):
    """Scale all positional values in a GPOS lookup.

    scale: combined factor (user_scale * upm_ratio) for all coordinates
    dy: baseline offset for anchor Y coordinates (absolute positions)
    """
    for subtable in lookup.SubTable:
        st = subtable
        if hasattr(st, 'ExtSubTable'):
            st = st.ExtSubTable
        _scale_gpos_subtable(st, scale, dy)


def _scale_gpos_subtable(st, scale: float, dy: float):
    """Scale values in a single GPOS subtable.

    - ValueRecords (kerning, placement): scale only (relative adjustments)
    - Anchors (mark/base attachment points): scale + baseline offset
      (absolute coordinates within the glyph's coordinate space)
    """
    # SinglePos (type 1)
    if hasattr(st, 'Value') and st.Value:
        if isinstance(st.Value, (list, tuple)):
            for value_record in st.Value:
                _scale_value_record(value_record, scale)
        else:
            _scale_value_record(st.Value, scale)
    if hasattr(st, 'Value1') and st.Value1:
        _scale_value_record(st.Value1, scale)
    if hasattr(st, 'Value2') and st.Value2:
        _scale_value_record(st.Value2, scale)

    # PairPos format 1 (type 2): individual pairs
    if hasattr(st, 'PairSet') and st.PairSet:
        for pair_set in st.PairSet:
            if pair_set and pair_set.PairValueRecord:
                for pvr in pair_set.PairValueRecord:
                    if hasattr(pvr, 'Value1') and pvr.Value1:
                        _scale_value_record(pvr.Value1, scale)
                    if hasattr(pvr, 'Value2') and pvr.Value2:
                        _scale_value_record(pvr.Value2, scale)

    # PairPos format 2 (type 2): class-based
    if hasattr(st, 'Class1Record') and st.Class1Record:
        for c1rec in st.Class1Record:
            if c1rec.Class2Record:
                for c2rec in c1rec.Class2Record:
                    if hasattr(c2rec, 'Value1') and c2rec.Value1:
                        _scale_value_record(c2rec.Value1, scale)
                    if hasattr(c2rec, 'Value2') and c2rec.Value2:
                        _scale_value_record(c2rec.Value2, scale)

    # CursivePos (type 3) — anchors are absolute positions
    if hasattr(st, 'EntryExitRecord') and st.EntryExitRecord:
        for rec in st.EntryExitRecord:
            if rec.EntryAnchor:
                _scale_anchor(rec.EntryAnchor, scale, dy)
            if rec.ExitAnchor:
                _scale_anchor(rec.ExitAnchor, scale, dy)

    # MarkBasePos (type 4), MarkLigPos (type 5), MarkMarkPos (type 6)
    if hasattr(st, 'MarkArray') and st.MarkArray:
        for mr in st.MarkArray.MarkRecord:
            if mr.MarkAnchor:
                _scale_anchor(mr.MarkAnchor, scale, dy)
    if hasattr(st, 'BaseArray') and st.BaseArray:
        for br in st.BaseArray.BaseRecord:
            for anchor in br.BaseAnchor:
                if anchor:
                    _scale_anchor(anchor, scale, dy)
    if hasattr(st, 'LigatureArray') and st.LigatureArray:
        for la in st.LigatureArray.LigatureAttach:
            for cr in la.ComponentRecord:
                for anchor in cr.LigatureAnchor:
                    if anchor:
                        _scale_anchor(anchor, scale, dy)
    if hasattr(st, 'Mark2Array') and st.Mark2Array:
        for m2r in st.Mark2Array.Mark2Record:
            for anchor in m2r.Mark2Anchor:
                if anchor:
                    _scale_anchor(anchor, scale, dy)


def _scale_anchor(anchor, scale: float, dy: float):
    """Scale and shift an anchor point.

    Anchors are absolute positions in glyph coordinate space.
    X is scaled, Y is scaled AND shifted by baseline offset.
    """
    if hasattr(anchor, 'XCoordinate') and anchor.XCoordinate:
        anchor.XCoordinate = int(round(anchor.XCoordinate * scale))
    if hasattr(anchor, 'YCoordinate'):
        anchor.YCoordinate = int(round(anchor.YCoordinate * scale + dy))


# ---------------------------------------------------------------------------
# OFL metadata helpers
# ---------------------------------------------------------------------------

_OFL_LICENSE_TEXT = (
    "This Font Software is licensed under the SIL Open Font License, "
    "Version 1.1. This license is available with a FAQ at: "
    "https://openfontlicense.org"
)
_OFL_LICENSE_URL = "https://openfontlicense.org"

# nameIDs reserved for predefined identity records. Records >= 256 are
# user-defined slots used by Stylistic Set / Character Variant labels and
# must never be touched by the identity-pass-through logic — they belong
# to the feature label remapping path (see lat_name handling below).
_IDENTITY_NAMEID_LIMIT = 256

# Triple of OS/2 / head fields that together define the static style
# identity (weight class, italic bit, width class). Touched as a unit so
# nameID 2 / 4 / 6 / 17 stay internally consistent.
_VALID_METADATA_MODES = ("merge", "inheritBase", "inheritSub")
_OPTIONAL_NAME_IDS = frozenset({
    7,   # Trademark
    8,   # Manufacturer
    9,   # Designer
    10,  # Description
    11,  # Vendor URL
    12,  # Designer URL
    13,  # License Description
    14,  # License Info URL
    19,  # Sample text
})
_REQUIRED_NAME_IDS = frozenset({
    1,  # Font Family
    2,  # Font Subfamily
    3,  # Unique font identifier
    4,  # Full font name
    5,  # Version string
    6,  # PostScript name
})


def _resolve_metadata_mode(output: dict, has_sub_font: bool) -> str:
    """Validate and normalise ``output.metadataMode``.

    Returns one of ``"merge"`` / ``"inheritBase"`` / ``"inheritSub"``.
    Missing, ``None``, or ``"merge"`` collapse to ``"merge"``. Other
    values raise. ``"inheritSub"`` requires a sub font.
    """
    raw = output.get("metadataMode")
    if raw is None or raw == "merge":
        return "merge"
    if raw not in _VALID_METADATA_MODES:
        raise ValueError(
            f"output.metadataMode must be one of {_VALID_METADATA_MODES} "
            f"or null, got {raw!r}"
        )
    if raw == "inheritSub" and not has_sub_font:
        raise ValueError(
            "output.metadataMode='inheritSub' requires a subFont"
        )
    return raw


def _get_name(font: "TTFont", nameID: int) -> str:
    """Return the best available string for *nameID*, or ''."""
    nt = font.get("name")
    if not nt:
        return ""
    return nt.getDebugName(nameID) or ""


def _is_empty_name_value(value) -> bool:
    return value is None or str(value).strip() == ""


def _remove_name_id(name_table, nameID: int) -> None:
    name_table.removeNames(nameID=nameID)


def _set_name(name_table, nameID: int, value: str):
    """Set *nameID* on Windows-Unicode platform. Mac-Roman is skipped for non-ASCII values."""
    if _is_empty_name_value(value):
        if nameID in _REQUIRED_NAME_IDS:
            raise ValueError(f"Required nameID {nameID} is empty")
        if nameID in _OPTIONAL_NAME_IDS:
            _remove_name_id(name_table, nameID)
        return

    value = str(value)
    name_table.setName(value, nameID, 3, 1, 0x0409)   # Windows, Unicode BMP, English
    try:
        value.encode("mac_roman")
        name_table.setName(value, nameID, 1, 0, 0)    # Macintosh, Roman, English
    except UnicodeEncodeError:
        pass  # Skip Mac-Roman if value contains non-encodable characters


def _override_name(name_table, nameID: int, value: str):
    """Replace all records for *nameID* with *value*, or remove if empty.

    Inherit mode uses this so user overrides cleanly displace whatever
    platform/encoding/language combinations the source font already had,
    instead of leaving stale Mac-Japanese / Unicode-only records behind.
    """
    if _is_empty_name_value(value):
        if nameID in _REQUIRED_NAME_IDS:
            raise ValueError(f"Required nameID {nameID} is empty")
        _remove_name_id(name_table, nameID)
        return

    _remove_name_id(name_table, nameID)
    _set_name(name_table, nameID, value)


def _prune_empty_optional_name_records(font: TTFont) -> int:
    """Remove optional name records whose decoded text is empty."""
    name_table = font.get("name")
    if not name_table:
        return 0

    kept = []
    removed = 0
    for record in name_table.names:
        if record.nameID in _OPTIONAL_NAME_IDS:
            try:
                if _is_empty_name_value(record.toUnicode()):
                    removed += 1
                    continue
            except Exception:
                pass
        kept.append(record)
    name_table.names = kept
    return removed


def _validate_required_name_records_non_empty(font: TTFont) -> None:
    """Ensure core identity records exist and contain non-whitespace text."""
    name_table = font.get("name")
    if not name_table:
        raise ValueError("Missing name table")

    by_id = {}
    for record in name_table.names:
        if record.nameID in _REQUIRED_NAME_IDS:
            by_id.setdefault(record.nameID, []).append(record)

    for nameID in sorted(_REQUIRED_NAME_IDS):
        records = by_id.get(nameID, [])
        if not records:
            raise ValueError(f"Missing required nameID {nameID}")
        has_non_empty_record = False
        for record in records:
            try:
                if not _is_empty_name_value(record.toUnicode()):
                    has_non_empty_record = True
                    break
            except Exception:
                continue
        if not has_non_empty_record:
            raise ValueError(f"Required nameID {nameID} is empty")


def _set_ofl_metadata(lat_font, jp_font, merged, config: dict):
    """Merge copyright notices from both sources and set OFL license fields.

    OFL 1.1 requires derivative works to:
      - Preserve all original copyright notices  (nameID 0)
      - Distribute under the same OFL license    (nameID 13, 14)
      - Not use Reserved Font Names in the output name
    """
    name_table = merged["name"]
    output = config.get("output") or {}
    user_copyright = output.get("copyright", "").strip()
    user_trademark = output.get("trademark", "").strip()
    user_manufacturer = output.get("manufacturer", "").strip()
    user_manufacturer_url = output.get("manufacturerURL", "").strip()

    # --- Copyright (nameID 0): combine both sources + user's addition ---
    copyrights: list[str] = []
    for font in (jp_font, lat_font):
        if font is None:
            continue
        c = _get_name(font, 0)
        if c and c not in copyrights:
            copyrights.append(c)
    if user_copyright and user_copyright not in copyrights:
        copyrights.append(user_copyright)
    combined_copyright = "\n".join(copyrights) if copyrights else ""
    if combined_copyright:
        _set_name(name_table, 0, combined_copyright)

    # --- Trademark (nameID 7): combine both sources + user's addition ---
    # Preserved as acknowledgment per OFL 1.1 §4 (trademark text is
    # factual attribution, not promotional use of the author's name).
    trademarks: list[str] = []
    for font in (jp_font, lat_font):
        if font is None:
            continue
        t = _get_name(font, 7)
        if t and t not in trademarks:
            trademarks.append(t)
    if user_trademark and user_trademark not in trademarks:
        trademarks.append(user_trademark)
    combined_trademark = "\n".join(trademarks) if trademarks else ""
    if combined_trademark:
        _set_name(name_table, 7, combined_trademark)

    # --- Description (nameID 10): attribution with designer credit ---
    desc_parts: list[str] = []
    for font in (jp_font, lat_font):
        if font is None:
            continue
        family = _get_name(font, 1)
        designer = _get_name(font, 9)
        if family:
            part = family
            if designer:
                part += f" by {designer}"
            desc_parts.append(part)
    if desc_parts:
        desc = f"Based on {' and '.join(desc_parts)}. Built with OFL Font Baker."
        _set_name(name_table, 10, desc)

    # --- Designer (nameID 9) / Designer URL (nameID 12) ---
    # Always cleared. The merge operator is represented via Manufacturer
    # (nameID 8 / 11), not Designer, because "designer" rightfully
    # belongs to the type designers of the source fonts — which are
    # acknowledged in the Description (nameID 10) via the "by <source
    # designer>" clause.
    _set_name(name_table, 9, "")
    _set_name(name_table, 12, "")

    # --- Manufacturer (nameID 8) and Manufacturer URL (nameID 11) ---
    # Same policy: user-supplied values overwrite, empty clears the
    # original vendor's attribution on the derivative.
    _set_name(name_table, 8, user_manufacturer if user_manufacturer else "")
    _set_name(name_table, 11, user_manufacturer_url if user_manufacturer_url else "")

    # --- License (nameID 13) ---
    _set_name(name_table, 13, _OFL_LICENSE_TEXT)

    # --- License URL (nameID 14) ---
    _set_name(name_table, 14, _OFL_LICENSE_URL)

    # --- Version string (nameID 5) ---
    # Default to 1.000 so derivative fonts don't inherit the base font's
    # version. Users may supply any string; the "Version " prefix is
    # enforced because the OpenType spec requires nameID 5 to begin with
    # it (case-insensitive). A `;ofl-font-baker X.Y.Z` suffix is appended
    # (when the generator version is provided) so the tool that produced
    # the font is identifiable from its metadata.
    version_value = (output.get("version") or "").strip() or "1.000"
    if not version_value.lower().startswith("version "):
        version_value = f"Version {version_value}"
    app_version = (config.get("appVersion") or "").strip()
    if app_version:
        version_value = f"{version_value};ofl-font-baker {app_version}"
    _set_name(name_table, 5, version_value)


# ---------------------------------------------------------------------------
# Identity passes (merge-mode default vs. inherit-mode pass-through)
# ---------------------------------------------------------------------------

# OS/2 fsSelection bits.
_FS_SELECTION_ITALIC = 0x0001
_FS_SELECTION_BOLD = 0x0020
_FS_SELECTION_REGULAR = 0x0040
# head.macStyle bit 0 = bold, bit 1 = italic.
_MAC_STYLE_BOLD = 0x0001
_MAC_STYLE_ITALIC = 0x0002


def _apply_style_bits(os2, head, weight: int, italic: bool, width: int = 5) -> None:
    """Sync OS/2.fsSelection and head.macStyle to the static style identity.

    REGULAR / BOLD / ITALIC in fsSelection and the bold / italic bits in
    head.macStyle must agree with ``usWeightClass`` / ``usWidthClass``
    and the italic flag, or Windows and Adobe pick the wrong style when
    matching the family. Re-syncing here also fixes inherited
    inconsistencies (e.g. a base font that carried ``fsSelection=REGULAR``
    while the derivative is Bold).

    The static naming policy exposes only RIBBI subfamilies in legacy
    nameID 2. Weight 700 is the sole Bold face; every other non-italic
    weight is the Regular face of its own legacy family (for example
    "Family ExtraBold" + "Regular"). This matches fontbakery's
    fsSelection convention and keeps GDI/PDF fallback paths aligned with
    nameID 1/2.
    """
    is_bold = weight == 700
    is_regular = (not italic and weight != 700)
    if os2 is not None:
        if italic:
            os2.fsSelection |= _FS_SELECTION_ITALIC
        else:
            os2.fsSelection &= ~_FS_SELECTION_ITALIC
        if is_bold:
            os2.fsSelection |= _FS_SELECTION_BOLD
        else:
            os2.fsSelection &= ~_FS_SELECTION_BOLD
        if is_regular:
            os2.fsSelection |= _FS_SELECTION_REGULAR
        else:
            os2.fsSelection &= ~_FS_SELECTION_REGULAR
    if head is not None:
        if italic:
            head.macStyle |= _MAC_STYLE_ITALIC
        else:
            head.macStyle &= ~_MAC_STYLE_ITALIC
        if is_bold:
            head.macStyle |= _MAC_STYLE_BOLD
        else:
            head.macStyle &= ~_MAC_STYLE_BOLD


def _apply_derivative_metadata(lat_font, jp_font, merged, config: dict):
    """Rewrite identity records as a derivative work (merge mode).

    This is the historical Font-Baker identity pipeline: nameID 1/2/3/4/6/16/17
    are recomposed from ``output.familyName`` + ``output.weight/italic/width``,
    OS/2 / head are forced to derivative defaults, OFL nameID 13/14 are pinned
    to the canonical OFL text, and ``head.created/modified`` are refreshed to
    "now" so the derivative reports its own provenance.
    """
    output = config.get("output") or {}
    output_name = output.get("familyName", "Merged Font")
    output_weight = output.get("weight", 400)
    output_italic = output.get("italic", False)
    output_width = output.get("width", 5)

    style_name = compute_style_name(output_weight, output_italic, output_width)
    width_name = WIDTH_MAP.get(output_width, "")
    ribbi_bold = output_weight == 700
    non_ribbi_weight_name = (
        WEIGHT_MAP.get(output_weight, "")
        if output_weight not in (400, 700) else ""
    )
    legacy_family = " ".join(
        part for part in (output_name, width_name, non_ribbi_weight_name) if part
    ).strip()
    legacy_subfamily = (
        "Bold Italic" if ribbi_bold and output_italic else
        "Bold" if ribbi_bold else
        "Italic" if output_italic else
        "Regular"
    )

    # Resolve and validate the PostScript base name (without style suffix).
    # Explicit postScriptName takes priority; otherwise derive from familyName
    # by stripping disallowed characters.
    output_ps_base = (output.get("postScriptName") or "").strip()
    if not output_ps_base:
        output_ps_base = sanitize_postscript_name(output_name)
    validate_postscript_name(output_ps_base)

    # --- name table ---
    # Legacy Windows GDI and some PDF exporters only understand RIBBI in
    # nameID 1/2. If all static weights share nameID 1 and put
    # ExtraLight/Black/etc. in nameID 2, those fallback paths collapse the
    # family and substitute the first face (often Thin). Follow Google
    # Fonts static naming: move width and non-RIBBI weight into the legacy
    # family, keep nameID 2 to Regular/Bold/Italic/Bold Italic, and expose
    # the full typographic family/style through nameID 16/17.
    name_table = merged["name"]
    had_typographic_family = any(r.nameID == 16 for r in name_table.names)
    had_typographic_subfamily = any(r.nameID == 17 for r in name_table.names)
    for record in name_table.names:
        try:
            record.toUnicode()
        except Exception:
            continue  # Skip name records with undecodable encodings
        if record.nameID == 1:
            record.string = legacy_family
        elif record.nameID == 2:
            record.string = legacy_subfamily
        elif record.nameID == 4:
            record.string = f"{output_name} {style_name}".strip()
        elif record.nameID == 6:
            ps_style = style_name.replace(" ", "")
            record.string = f"{output_ps_base}-{ps_style}"
        elif record.nameID == 16:
            record.string = output_name
        elif record.nameID == 17:
            record.string = style_name

    if (legacy_family, legacy_subfamily) != (output_name, style_name):
        if not had_typographic_family:
            _set_name(name_table, 16, output_name)
        if not had_typographic_subfamily:
            _set_name(name_table, 17, style_name)

    # Set OS/2 usWeightClass and usWidthClass
    os2 = merged.get("OS/2")
    if os2:
        os2.usWeightClass = output_weight
        os2.usWidthClass = output_width
        # achVendID is fixed to four spaces — the "unknown vendor"
        # placeholder. The merge operator doesn't typically have a
        # Microsoft-registered vendor tag, and inheriting the base
        # font's tag would misattribute the derivative.
        os2.achVendID = "    "

    # Refresh timestamps so the derivative reports its own creation/
    # modification time rather than inheriting the base font's.
    head = merged.get("head")
    if head:
        now = timestampNow()
        head.created = now
        head.modified = now
        # fontTools rewrites head.modified to "now" during save() when
        # recalcTimestamp is true (the default), which would make created
        # and modified disagree by a few seconds. Pin both to the same
        # instant so inspectors report a consistent timestamp pair.
        merged.recalcTimestamp = False

        # fontRevision (Fixed 16.16) should track the nameID 5 number.
        # Parse the leading numeric from output.version so values like
        # "1.000-beta" or "Version 2.5" collapse to the numeric prefix
        # (1.0 / 2.5). Anything that doesn't start with a number falls
        # back to the 1.000 default.
        head.fontRevision = _parse_font_revision(output.get("version"))

    # Sync REGULAR / BOLD / ITALIC bits in OS/2.fsSelection and the
    # bold / italic bits in head.macStyle to the output style. Inherited
    # bits would otherwise contradict the new identity — base fonts that
    # carried fsSelection=REGULAR keep advertising "Regular" even when
    # the derivative is Bold or any other non-Regular weight.
    _apply_style_bits(os2, head, output_weight, output_italic, output_width)

    # --- Unique Font Identifier (nameID 3) ---
    # Auto-built as "{version};{PostScript full name}" so the OS font
    # cache can tell distinct versions/styles apart. Without a fresh
    # ID, derivatives collide with the base font in the cache and
    # render using stale glyphs. Vendor ID is omitted because the
    # derivative has no vendor tag.
    version_for_id = (output.get("version") or "").strip() or "1.000"
    if version_for_id.lower().startswith("version "):
        version_for_id = version_for_id[len("Version "):].strip()
    ps_full_name = f"{output_ps_base}-{style_name.replace(' ', '')}"
    _set_name(name_table, 3, f"{version_for_id};{ps_full_name}")

    # --- OFL metadata: copyright, license, description ---
    _set_ofl_metadata(lat_font, jp_font, merged, config)

    # --- Drop Variations PostScript Name Prefix (nameID 25) ---
    # nameID 25 is the prefix used to build PostScript names for a
    # variable font's named instances. Because the output is always a
    # static instance (we bake axis values), this record has no purpose
    # and inheriting it from the variable base font would leak the
    # source family name into inspectors.
    name_table.removeNames(nameID=25)

    # --- CFF TopDict metadata (OTF only) ---
    # CFF fonts carry a second copy of FullName / FamilyName / Copyright
    # inside the CFF table's TopDict. PDF embedders and Adobe tools read
    # those directly, so derivatives would keep the base font's name
    # unless we mirror the name-table values here.
    if "CFF " in merged:
        cff = merged["CFF "].cff
        td = cff.topDictIndex[0]
        td.FullName = f"{output_name} {style_name}".strip()
        td.FamilyName = output_name
        cff_copyright = _get_name(merged, 0)
        if cff_copyright:
            # CFF 1 uses "Notice" as the canonical copyright field;
            # "Copyright" is defined but rarely populated. Set whichever
            # the TopDict exposes so inspectors see a consistent value.
            td.Notice = cff_copyright
            if hasattr(td, "Copyright"):
                td.Copyright = cff_copyright
        # CFF Name INDEX — the PostScript name at the very top of the
        # CFF binary. PDF embedders and some Adobe tools read it in
        # preference to the name table / TopDict FullName, so leaving
        # it at the base font's value would re-leak the source name.
        ps_full = _get_name(merged, 6)
        if ps_full and cff.fontNames:
            cff.fontNames[0] = ps_full


def _parse_font_revision(version_raw) -> float:
    """Extract a Fixed 16.16-friendly float from an output.version string."""
    raw = (version_raw or "").strip() or "1.000"
    if raw.lower().startswith("version "):
        raw = raw[len("Version "):].strip()
    m = re.match(r"^\d+(?:\.\d+)?", raw)
    return float(m.group(0)) if m else 1.0


def _swap_identity_records_to_sub(merged: TTFont, sub_font: TTFont):
    """Replace merged's identity name records (nameID < 256) with sub's.

    Merged's name table arrives as a clone of base, so this is the only
    way to make ``inheritSub`` actually identify as the sub font. Records
    >= 256 (feature labels) are kept untouched on both sides — they are
    handled by the lat_name copy pass downstream.
    """
    name_table = merged["name"]
    sub_name = sub_font.get("name")
    if sub_name is None:
        return
    name_table.names = [
        r for r in name_table.names if r.nameID >= _IDENTITY_NAMEID_LIMIT
    ]
    for record in sub_name.names:
        if record.nameID < _IDENTITY_NAMEID_LIMIT:
            name_table.names.append(copy.deepcopy(record))

    # Mirror sub's identity slice of OS/2 / head into merged. Only the
    # fields that name a *style identity* are copied — vertical metrics
    # are reconciled separately in reconcile_tables based on glyph extent.
    sub_os2 = sub_font.get("OS/2")
    merged_os2 = merged.get("OS/2")
    if sub_os2 and merged_os2:
        merged_os2.usWeightClass = sub_os2.usWeightClass
        merged_os2.usWidthClass = sub_os2.usWidthClass
        # Preserve only the italic+regular bits from sub — other fsSelection
        # bits encode unrelated state that merged may have set already.
        sub_italic_bits = sub_os2.fsSelection & (
            _FS_SELECTION_ITALIC | _FS_SELECTION_REGULAR
        )
        merged_os2.fsSelection = (
            merged_os2.fsSelection
            & ~(_FS_SELECTION_ITALIC | _FS_SELECTION_REGULAR)
            | sub_italic_bits
        )
        merged_os2.achVendID = sub_os2.achVendID

    sub_head = sub_font.get("head")
    merged_head = merged.get("head")
    if sub_head and merged_head:
        # macStyle italic bit only; bold bit (0x0001) follows weight class
        # and we don't want to leak unrelated bits like underline (0x0008).
        merged_head.macStyle = (
            merged_head.macStyle & ~_MAC_STYLE_ITALIC
            | (sub_head.macStyle & _MAC_STYLE_ITALIC)
        )
        merged_head.fontRevision = sub_head.fontRevision
        merged_head.created = sub_head.created
        merged_head.modified = sub_head.modified


def _apply_inherited_metadata(lat_font, jp_font, merged, config: dict, mode: str):
    """Pass identity through from the chosen source, then apply explicit overrides.

    ``mode`` is ``"inheritBase"`` or ``"inheritSub"``. The merged font's name
    table arrives as a clone of base, so ``inheritBase`` is the no-op case
    (any ``output.*`` overrides are layered on base's records); ``inheritSub``
    first swaps identity records over from sub, then applies overrides.

    In contrast to merge mode, OFL nameID 13 / 14 are *not* forced, designer
    9 / 12 are *not* cleared, ``achVendID`` is *not* zeroed, ``head.created/
    modified`` are *not* refreshed, nameID 25 is *not* stripped, and
    ``;ofl-font-baker`` is *not* appended to the version string. The output
    keeps whatever provenance the source font carried.
    """
    output = config.get("output") or {}
    name_table = merged["name"]

    if mode == "inheritSub":
        if lat_font is None:
            # Defensive: should already be caught by _resolve_metadata_mode.
            raise ValueError(
                "output.metadataMode='inheritSub' requires a subFont"
            )
        _swap_identity_records_to_sub(merged, lat_font)

    # fontTools' TTFont save() defaults to recalcTimestamp=True, which would
    # bump head.modified to "now" — defeating the inherit-mode promise that
    # the source font's timestamps survive into the output.
    merged.recalcTimestamp = False

    progress(
        "info", 0,
        f"[metadata] mode={mode}; identity inherited from "
        f"{'sub' if mode == 'inheritSub' else 'base'}"
    )

    # Snapshot post-swap state — these are the values to fall back to
    # when a particular output.* override is absent.
    os2 = merged.get("OS/2")
    head = merged.get("head")
    cur_family = _get_name(merged, 1)
    cur_ps_full = _get_name(merged, 6)
    # nameID 6 is conventionally "<PSBase>-<PSStyle>"; use the prefix as
    # the PS base when the user only renames family without supplying a
    # postScriptName. If there is no hyphen we treat the whole thing as
    # the base.
    cur_ps_base = cur_ps_full.split("-", 1)[0] if "-" in cur_ps_full else cur_ps_full
    cur_subfamily = _get_name(merged, 2) or "Regular"
    cur_weight = os2.usWeightClass if os2 else 400
    cur_italic = bool(os2.fsSelection & _FS_SELECTION_ITALIC) if os2 else False
    cur_width = os2.usWidthClass if os2 else 5

    family_specified = "familyName" in output
    psname_specified = "postScriptName" in output
    weight_specified = "weight" in output
    italic_specified = "italic" in output
    width_specified = "width" in output
    style_changed = weight_specified or italic_specified or width_specified
    name_changed = family_specified or psname_specified or style_changed

    new_family = output.get("familyName") if family_specified else cur_family
    new_ps_base = (output.get("postScriptName") or "").strip() if psname_specified else ""
    if not new_ps_base:
        new_ps_base = (
            sanitize_postscript_name(new_family) if family_specified else cur_ps_base
        )
    if name_changed:
        validate_postscript_name(new_ps_base)

    new_weight = output.get("weight", cur_weight)
    new_italic = output.get("italic", cur_italic)
    new_width = output.get("width", cur_width)
    new_style = (
        compute_style_name(new_weight, new_italic, new_width)
        if style_changed else cur_subfamily
    )

    overrides: list[str] = []

    # nameID 1 / 16 (family) -----------------------------------------------
    if family_specified:
        _override_name(name_table, 1, new_family)
        # nameID 16 is only required when nameID 1 cannot represent the
        # full family naming (non-RIBBI subfamilies). Update it only when
        # the source already carried one — adding a fresh nameID 16 in
        # pure pass-through would change identity beyond the user's intent.
        if any(r.nameID == 16 for r in name_table.names):
            _override_name(name_table, 16, new_family)
        overrides.append(f"familyName={new_family!r}")

    # nameID 2 / 17 (subfamily) --------------------------------------------
    if style_changed:
        _override_name(name_table, 2, new_style)
        if any(r.nameID == 17 for r in name_table.names):
            _override_name(name_table, 17, new_style)

    # nameID 4 / 6 (full name + PostScript name) ---------------------------
    # These are composite records: any change to family OR style requires
    # re-composition so the parts stay in sync.
    if name_changed:
        family_for_full = new_family if family_specified else cur_family
        style_for_full = new_style if style_changed else cur_subfamily
        full_name = f"{family_for_full} {style_for_full}".strip()
        _override_name(name_table, 4, full_name)
        ps_base_for_id = new_ps_base if (family_specified or psname_specified) else cur_ps_base
        ps_style = (style_for_full or "Regular").replace(" ", "") or "Regular"
        _override_name(name_table, 6, f"{ps_base_for_id}-{ps_style}")
        if psname_specified:
            overrides.append(f"postScriptName={new_ps_base!r}")

    # OS/2 numeric style fields -------------------------------------------
    if os2:
        if weight_specified:
            os2.usWeightClass = new_weight
            overrides.append(f"weight={new_weight}")
        if width_specified:
            os2.usWidthClass = new_width
            overrides.append(f"width={new_width}")
        if italic_specified:
            overrides.append(f"italic={new_italic}")

    # Style bits ----------------------------------------------------------
    # Recompute fsSelection REGULAR/BOLD/ITALIC and head.macStyle bold/
    # italic when any style component is overridden so the inherited bits
    # don't contradict the new style. Pure pass-through (no style
    # override) keeps the source bits untouched.
    if style_changed:
        _apply_style_bits(os2, head, new_weight, new_italic, new_width)

    # nameID 5 (version) + head.fontRevision ------------------------------
    version_specified = "version" in output
    if version_specified:
        version_value = (output.get("version") or "").strip() or "1.000"
        if not version_value.lower().startswith("version "):
            version_value = f"Version {version_value}"
        # Note: ;ofl-font-baker suffix is intentionally NOT appended in
        # inherit mode. This matches the "pass-through" intent — the
        # output should not announce Font Baker as a producer of fonts
        # whose metadata claims to be the unmodified base/sub font.
        _override_name(name_table, 5, version_value)
        if head:
            head.fontRevision = _parse_font_revision(output.get("version"))
        overrides.append(f"version={version_value!r}")

    # nameID 3 (Unique Font Identifier) -----------------------------------
    # Cache identity must track family / style / version. Pure pass-through
    # leaves nameID 3 alone — but as soon as any of those identity inputs
    # is overridden, the inherited UID would conflict with the new name
    # records and the OS font cache would render derivatives with the
    # source font's stale glyphs.
    if name_changed or version_specified:
        version_for_id = _get_name(merged, 5) or "1.000"
        if version_for_id.lower().startswith("version "):
            version_for_id = version_for_id[len("Version "):].strip()
        ps_full_name = _get_name(merged, 6)
        if ps_full_name:
            _override_name(name_table, 3, f"{version_for_id};{ps_full_name}")

    # Simple-overwrite text fields ----------------------------------------
    for key, name_id in (
        ("copyright", 0),
        ("trademark", 7),
        ("manufacturer", 8),
        ("manufacturerURL", 11),
    ):
        if key in output:
            value = (output.get(key) or "").strip()
            _override_name(name_table, name_id, value)
            overrides.append(f"{key}={value!r}")

    # CFF TopDict identity sync -------------------------------------------
    # When base is CFF and inheriting from sub, merged's CFF TopDict still
    # carries base's name — PDF embedders read it directly, so inheritSub
    # would otherwise leak base's identity through the CFF side.
    # When merge-style overrides happened (family / style / copyright),
    # the same fields need to be mirrored into the TopDict for consistency.
    cff_sync_needed = (
        mode == "inheritSub" or name_changed or "copyright" in output
    )
    if cff_sync_needed and "CFF " in merged:
        cff = merged["CFF "].cff
        td = cff.topDictIndex[0]
        full_name = _get_name(merged, 4)
        family_name = _get_name(merged, 1)
        cff_copyright = _get_name(merged, 0)
        if full_name:
            td.FullName = full_name
        if family_name:
            td.FamilyName = family_name
        if cff_copyright:
            td.Notice = cff_copyright
            if hasattr(td, "Copyright"):
                td.Copyright = cff_copyright
        ps_full = _get_name(merged, 6)
        if ps_full and cff.fontNames:
            cff.fontNames[0] = ps_full

    for ov in overrides:
        progress("info", 0, f"[metadata] override {ov}")


# ---------------------------------------------------------------------------
# Table reconciliation
# ---------------------------------------------------------------------------

def reconcile_tables(lat_font: TTFont, jp_font: TTFont, merged: TTFont, config: dict):
    """Reconcile name, OS/2, hhea, head tables after merge.

    Identity records (nameID 0-25, OS/2 weight/width/fsSelection, head
    macStyle/fontRevision/timestamps, CFF TopDict identity) are handled
    differently per ``output.metadataMode``:

      * ``merge``        — derivative defaults, with user-supplied
                           ``output.*`` values overlaid (current behavior).
      * ``inheritBase``  — keep base font's identity untouched, only
                           rewrite the records the user explicitly set.
      * ``inheritSub``   — copy sub font's identity into the merged font,
                           then apply user overrides on top.

    Vertical metrics, feature-label name records (nameID >= 256), DSIG
    removal, and post-table fix-up are unconditional — they affect
    correctness of the merged font, not its identity.
    """
    output = config.get("output") or {}
    metadata_mode = _resolve_metadata_mode(output, lat_font is not None)
    name_table = merged["name"]

    if metadata_mode == "merge":
        _apply_derivative_metadata(lat_font, jp_font, merged, config)
    else:
        _apply_inherited_metadata(lat_font, jp_font, merged, config, metadata_mode)

    # --- Copy feature name records from Latin font ---
    lat_name = lat_font.get("name") if lat_font else None
    if lat_name:
        # Stylistic Sets (`ssXX`) hang their UI label off `UINameID`;
        # Character Variants (`cvXX`) use `FeatUILabelNameID` /
        # `FeatUITooltipTextNameID` / `SampleTextNameID` and a contiguous
        # block of per-variant labels at
        # `FirstParamUILabelNameID .. FirstParamUILabelNameID + NumNamedParameters - 1`.
        # Older fontTools versions also expose `NamedParameters`. The
        # collector has to walk all of these so cvXX labels survive merge
        # (Issue #2 #7).
        # `SubfamilyNameID` is used by the `size` FeatureParams
        # (`FeatureParamsSize`) to label the size-instance subfamily.
        # Without it the same collision/leak class hits that shape.
        SCALAR_ATTRS = ('UINameID', 'FeatUILabelNameID',
                        'FeatUITooltipTextNameID', 'SampleTextNameID',
                        'SubfamilyNameID')

        def _collect_feat_param_nameids(fp):
            ids = set()
            if not fp:
                return ids
            for attr in SCALAR_ATTRS:
                nid = getattr(fp, attr, None)
                if nid:
                    ids.add(nid)
            num = (getattr(fp, 'NumNamedParameters', None)
                   or getattr(fp, 'NamedParameters', None))
            first = getattr(fp, 'FirstParamUILabelNameID', None)
            if num and first:
                for nid in range(first, first + num):
                    ids.add(nid)
            return ids

        # Collect name IDs used by Latin font's feature params
        lat_feat_name_ids = set()
        for tag in ('GSUB', 'GPOS'):
            lat_ot = lat_font.get(tag)
            if not lat_ot or not hasattr(lat_ot, 'table') or not lat_ot.table:
                continue
            ot = lat_ot.table
            if not ot.FeatureList:
                continue
            for feat_rec in ot.FeatureList.FeatureRecord:
                lat_feat_name_ids |= _collect_feat_param_nameids(
                    feat_rec.Feature.FeatureParams)

        # Copy those name records into the merged font, remapping any nameID
        # that the merged name table is already using to a fresh ID. Without
        # this, a Latin label that happens to clash with a base-font name
        # record would silently inherit the base's text (Issue #2 #7).
        #
        # The reserved set must include both the base/merged name IDs *and*
        # every Latin feature-label ID that will be copied unchanged
        # (Issue #26): otherwise the allocator can pick a target that is
        # already in use by another Latin feature label, collapsing two
        # different stylistic sets onto the same UINameID and producing
        # duplicate / misleading entries in the OpenType UI panel.
        existing_nameids = {r.nameID for r in name_table.names}
        reserved_nameids = set(existing_nameids) | set(lat_feat_name_ids)
        next_free = max(reserved_nameids | {255}) + 1

        def _alloc_contiguous(size):
            """Reserve and return the start of a contiguous block of
            *size* fresh nameIDs."""
            nonlocal next_free
            while True:
                if all(next_free + i not in reserved_nameids
                       for i in range(size)):
                    start = next_free
                    for i in range(size):
                        reserved_nameids.add(start + i)
                    next_free = start + size
                    return start
                next_free += 1

        nameid_remap: dict[int, int] = {}

        # Pre-pass: cvXX parameter-label ranges
        # (`FirstParamUILabelNameID..+NumNamedParameters`) are read by
        # the font as `first + offset`. If only some IDs in the range
        # collide, moving them individually fragments the block — the
        # offsets that didn't collide stay at the original positions
        # while the moved ones land elsewhere, so the FeatureParams
        # ends up pointing at the wrong labels (or at base records).
        #
        # Two cv FeatureRecords may also reference overlapping but
        # non-identical ranges (e.g. cv01 covers 300..302 while cv02
        # covers 300..304). Treating each range independently would
        # let one cv take a short mapped block and leave the other's
        # tail IDs un-relocated. To stay correct in all shapes,
        # collect every cv range first, **union overlapping ranges
        # into maximal blocks**, and atomically allocate one fresh
        # contiguous block per colliding union.
        cv_ranges = []
        for tag in ('GSUB', 'GPOS'):
            lat_ot = lat_font.get(tag)
            if not lat_ot or not hasattr(lat_ot, 'table') or not lat_ot.table:
                continue
            ot = lat_ot.table
            if not ot.FeatureList:
                continue
            for feat_rec in ot.FeatureList.FeatureRecord:
                fp = feat_rec.Feature.FeatureParams
                if not fp:
                    continue
                num = (getattr(fp, 'NumNamedParameters', None)
                       or getattr(fp, 'NamedParameters', None))
                first = getattr(fp, 'FirstParamUILabelNameID', None)
                if not first or not num:
                    continue
                cv_ranges.append((first, first + num))

        # Merge overlapping intervals.
        cv_blocks: list[tuple[int, int]] = []
        for s, e in sorted(cv_ranges):
            if cv_blocks and s <= cv_blocks[-1][1]:
                cv_blocks[-1] = (cv_blocks[-1][0], max(cv_blocks[-1][1], e))
            else:
                cv_blocks.append((s, e))

        for block_start, block_end in cv_blocks:
            block_ids = list(range(block_start, block_end))
            if not any(rid in existing_nameids for rid in block_ids):
                continue  # No collision; block stays put.
            new_start = _alloc_contiguous(block_end - block_start)
            for offset, rid in enumerate(block_ids):
                nameid_remap[rid] = new_start + offset

        # Per-scalar allocation for everything else.
        for old_id in sorted(lat_feat_name_ids):
            if old_id in nameid_remap:
                continue  # Handled by the range pass above.
            if old_id in existing_nameids:
                # Skip past anything already reserved or previously
                # handed out so two collisions never share a target.
                while next_free in reserved_nameids:
                    next_free += 1
                nameid_remap[old_id] = next_free
                reserved_nameids.add(next_free)
                next_free += 1

        for record in lat_name.names:
            if record.nameID not in lat_feat_name_ids:
                continue
            new_record = copy.deepcopy(record)
            new_record.nameID = nameid_remap.get(record.nameID, record.nameID)
            name_table.names.append(new_record)

        # Rewrite FeatureParams to point at the newly assigned nameIDs.
        # Restrict the rewrite to FeatureRecords copied from the Latin font
        # (marked with `_lat_origin` in `_merge_ot_table_v2`); base-font
        # records that happen to share a numeric nameID with a Latin
        # collision must keep pointing at their own (untouched) name
        # records.
        if nameid_remap:
            for tag in ('GSUB', 'GPOS'):
                merged_ot = merged.get(tag)
                if not merged_ot or not getattr(merged_ot, 'table', None):
                    continue
                if not merged_ot.table.FeatureList:
                    continue
                for feat_rec in merged_ot.table.FeatureList.FeatureRecord:
                    if not getattr(feat_rec, '_lat_origin', False):
                        continue
                    fp = feat_rec.Feature.FeatureParams
                    if not fp:
                        continue
                    for attr in SCALAR_ATTRS + ('FirstParamUILabelNameID',):
                        nid = getattr(fp, attr, None)
                        if nid in nameid_remap:
                            setattr(fp, attr, nameid_remap[nid])

    _prune_empty_optional_name_records(merged)
    _validate_required_name_records_non_empty(merged)

    # --- OS/2 ---
    if not lat_font:
        return
    # Latin font metrics must be scaled to target UPM before comparison
    lat_upm = lat_font["head"].unitsPerEm
    merged_upm = merged["head"].unitsPerEm
    upm_ratio = merged_upm / lat_upm if lat_upm != merged_upm else 1.0

    # metricsSource: "base" (default) keeps base-font metrics and only
    # expands them when the sub font is larger; "sub" overwrites
    # vertical metrics with the sub font's values unconditionally.
    metrics_source = output.get("metricsSource", "base")

    lat_os2 = lat_font.get("OS/2")
    jp_os2 = merged.get("OS/2")
    if lat_os2 and jp_os2:
        en_typo_asc = int(round(lat_os2.sTypoAscender * upm_ratio))
        en_typo_desc = int(round(lat_os2.sTypoDescender * upm_ratio))
        en_win_asc = int(round(lat_os2.usWinAscent * upm_ratio))
        en_win_desc = int(round(lat_os2.usWinDescent * upm_ratio))

        if metrics_source == "sub":
            jp_os2.sTypoAscender = en_typo_asc
            jp_os2.sTypoDescender = en_typo_desc
            jp_os2.usWinAscent = en_win_asc
            jp_os2.usWinDescent = en_win_desc
        else:
            jp_os2.sTypoAscender = max(en_typo_asc, jp_os2.sTypoAscender)
            jp_os2.sTypoDescender = min(en_typo_desc, jp_os2.sTypoDescender)
            jp_os2.usWinAscent = max(en_win_asc, jp_os2.usWinAscent)
            jp_os2.usWinDescent = max(en_win_desc, jp_os2.usWinDescent)
        for attr in ('ulUnicodeRange1', 'ulUnicodeRange2',
                     'ulUnicodeRange3', 'ulUnicodeRange4'):
            setattr(jp_os2, attr,
                    getattr(lat_os2, attr, 0) | getattr(jp_os2, attr, 0))
        for attr in ('ulCodePageRange1', 'ulCodePageRange2'):
            if hasattr(lat_os2, attr) and hasattr(jp_os2, attr):
                setattr(jp_os2, attr,
                        getattr(lat_os2, attr, 0) | getattr(jp_os2, attr, 0))

    # --- hhea ---
    lat_hhea = lat_font.get("hhea")
    jp_hhea = merged.get("hhea")
    if lat_hhea and jp_hhea:
        lat_hhea_asc = int(round(lat_hhea.ascent * upm_ratio))
        lat_hhea_desc = int(round(lat_hhea.descent * upm_ratio))
        if metrics_source == "sub":
            jp_hhea.ascent = lat_hhea_asc
            jp_hhea.descent = lat_hhea_desc
        else:
            jp_hhea.ascent = max(lat_hhea_asc, jp_hhea.ascent)
            jp_hhea.descent = min(lat_hhea_desc, jp_hhea.descent)

    # --- Remove DSIG (will be invalid) ---
    if "DSIG" in merged:
        del merged["DSIG"]

    # --- Remove STAT ---
    # STAT (Style Attributes) places the font within a family's style
    # hierarchy. fontTools.varLib.instancer prunes it to the instantiated
    # location, leaving stale axis records — or a partial table for
    # off-axis instances (e.g. wght=465) — and any output.weight /
    # italic / width override would make the inherited STAT contradict
    # the static identity. ofl-font-baker only emits static instances,
    # so the safer default (matching many static TTF families like
    # Inter) is to drop STAT and let name / OS/2 be the source of truth.
    # See issue #16.
    if "STAT" in merged:
        del merged["STAT"]

    # --- post table: use format 2.0 to preserve glyph names ---
    # Format 3.0 discards all glyph names, causing GSUB/GPOS lookups
    # to lose their glyph name references on save→load round-trip.
    post = merged.get("post")
    if post and post.formatType == 3.0:
        post.formatType = 2.0
        post.extraNames = []
        post.mapping = {}


# ---------------------------------------------------------------------------
# Variable font instantiation
# ---------------------------------------------------------------------------

def _instantiate_if_variable(font: TTFont, cfg: dict, label: str) -> TTFont:
    """If font has an fvar table, instantiate at the given axis values.

    Variable fonts MUST be instantiated before merging, even at default
    axis values, because the glyf table contains un-applied deltas that
    only render correctly when gvar is present.
    """
    if "fvar" not in font:
        return font

    from fontTools.varLib.instancer import instantiateVariableFont

    # Build axis location from config; fall back to fvar defaults
    location = {}
    cfg_axes = {a["tag"]: a["currentValue"] for a in cfg.get("axes", [])
                if a.get("tag") and a.get("currentValue") is not None}

    for axis in font["fvar"].axes:
        location[axis.axisTag] = cfg_axes.get(axis.axisTag, axis.defaultValue)

    font = instantiateVariableFont(font, location)
    return font



# ---------------------------------------------------------------------------
# Main merge pipeline
# ---------------------------------------------------------------------------

def _check_ofl(font: TTFont, label: str):
    """Verify the font is licensed under the SIL Open Font License."""
    name_table = font.get("name")
    if not name_table:
        raise ValueError(f"{label}: No name table found — cannot verify license.")
    lic = name_table.getDebugName(13) or ""
    lic_lower = lic.lower()
    if ("open font license" not in lic_lower
            and "openfont license" not in lic_lower
            and "ofl" not in lic_lower):
        raise ValueError(
            f"{label}: This font is not licensed under the SIL Open Font License. "
            f"Only OFL-licensed fonts are supported."
        )


def _scale_jp_metrics(merged: TTFont, ratio: float):
    """Scale merged (JP-origin) metrics by the UPM ratio.

    Called when the target output UPM differs from the base font's source UPM,
    so the JP-derived glyph/hint/GPOS scaling has a matching set of vertical
    metrics. Must run BEFORE reconcile_tables so Latin comparisons see the
    already-scaled JP values.
    """
    if ratio == 1.0:
        return

    def _r(v):
        return int(round(v * ratio))

    os2 = merged.get("OS/2")
    if os2 is not None:
        for attr in ("sTypoAscender", "sTypoDescender", "sTypoLineGap",
                     "usWinAscent", "usWinDescent",
                     "sxHeight", "sCapHeight",
                     "ySubscriptXSize", "ySubscriptYSize",
                     "ySubscriptXOffset", "ySubscriptYOffset",
                     "ySuperscriptXSize", "ySuperscriptYSize",
                     "ySuperscriptXOffset", "ySuperscriptYOffset",
                     "yStrikeoutSize", "yStrikeoutPosition"):
            v = getattr(os2, attr, None)
            if v is not None:
                setattr(os2, attr, _r(v))

    hhea = merged.get("hhea")
    if hhea is not None:
        for attr in ("ascent", "descent", "lineGap",
                     "advanceWidthMax",
                     "minLeftSideBearing", "minRightSideBearing",
                     "xMaxExtent",
                     "caretOffset"):
            v = getattr(hhea, attr, None)
            if v is not None:
                setattr(hhea, attr, _r(v))

    vhea = merged.get("vhea")
    if vhea is not None:
        for attr in ("ascent", "descent", "lineGap",
                     "advanceHeightMax",
                     "minTopSideBearing", "minBottomSideBearing",
                     "yMaxExtent", "caretOffset"):
            v = getattr(vhea, attr, None)
            if v is not None:
                setattr(vhea, attr, _r(v))

    vmtx = merged.get("vmtx")
    if vmtx is not None:
        for gname, (advance, tsb) in list(vmtx.metrics.items()):
            vmtx.metrics[gname] = (_r(advance), _r(tsb))

    vorg = merged.get("VORG")
    if vorg is not None:
        default_y = getattr(vorg, "defaultVertOriginY", None)
        if default_y is not None:
            vorg.defaultVertOriginY = _r(default_y)
        records = getattr(vorg, "VOriginRecords", None)
        if records is not None:
            for gname, y_origin in list(records.items()):
                records[gname] = _r(y_origin)

    post = merged.get("post")
    if post is not None:
        for attr in ("underlinePosition", "underlineThickness"):
            v = getattr(post, attr, None)
            if v is not None:
                setattr(post, attr, _r(v))

    base = merged.get("BASE")
    if base is not None:
        _scale_base_table(base.table, ratio)

    head = merged.get("head")
    if head is not None:
        for attr in ("xMin", "yMin", "xMax", "yMax"):
            v = getattr(head, attr, None)
            if v is not None:
                setattr(head, attr, _r(v))


def _scale_base_table(table, ratio: float):
    """Scale OpenType BASE coordinates for output-UPM changes."""
    if ratio == 1.0:
        return

    def _r(v):
        return int(round(v * ratio))

    seen = set()

    def _walk(obj):
        if obj is None:
            return
        if isinstance(obj, (str, bytes, int, float, bool)):
            return
        if isinstance(obj, (list, tuple)):
            for item in obj:
                _walk(item)
            return

        obj_id = id(obj)
        if obj_id in seen:
            return
        seen.add(obj_id)

        if hasattr(obj, "Coordinate"):
            coord = getattr(obj, "Coordinate")
            if isinstance(coord, int):
                setattr(obj, "Coordinate", _r(coord))

        for value in getattr(obj, "__dict__", {}).values():
            _walk(value)

    _walk(table)



def merge_fonts(config: dict) -> str:
    """Run the merge pipeline and write the output font.

    Reads output paths from export.path (path mode).
    """
    export = config.get("export") or {}
    paths = export.get("path") or {}
    output = config.get("output") or {}
    lat_cfg = config.get("subFont")
    jp_cfg = config["baseFont"]
    hinting_policy = _resolve_hinting_policy(config)

    if "woff2" in paths and "font" not in paths:
        raise ValueError("export.path.woff2 requires export.path.font")
    output_path = paths["font"]

    # Validate metadataMode up-front so a typo or a missing subFont fails
    # before we spend time loading and merging glyphs.
    _resolve_metadata_mode(output, lat_cfg is not None)

    S = 5

    # Step 1: Load fonts
    progress("loading", 1, f"1/{S} \u00b7 Loading fonts...")
    if lat_cfg:
        lat_font = TTFont(lat_cfg["path"])
        _check_ofl(lat_font, "Sub font")
        lat_font = _instantiate_if_variable(lat_font, lat_cfg, "Sub")
    else:
        lat_font = None

    jp_font = TTFont(jp_cfg["path"])
    _check_ofl(jp_font, "Base font")
    jp_font = _instantiate_if_variable(jp_font, jp_cfg, "Japanese")

    # Step 2: Clone base
    progress("loading", 1, f"1/{S} \u00b7 Loading fonts...")
    merged = TTFont(jp_cfg["path"])
    merged = _instantiate_if_variable(merged, jp_cfg, "Japanese (base)")

    # Unified UPM transform: fold the target-UPM ratio into the JP/Latin
    # scale values so the existing transform pipeline handles everything
    # (outlines, hmtx, CFF hints, Private dict blues/stems, GPOS, metrics).
    jp_source_upm = merged["head"].unitsPerEm
    output_upm = int(output.get("upm") or jp_source_upm)
    jp_upm_ratio = output_upm / jp_source_upm

    # Output format always mirrors the base font (CFF base → CFF out,
    # TT base → TT out). This avoids TT↔CFF round-trips that would either
    # drop CFF hints or bloat point counts through cu2qu conversion.
    #
    # For CID-keyed CFF we still need one carve-out: modestly-sized CID
    # fonts may be converted to TrueType only when the glyf pipeline is
    # strictly required (e.g. >65535 glyph limit doesn't apply). Since we
    # now keep CFF end-to-end, we simply stay in CID CFF for all sizes.
    _jp_transform_done = False

    # Step 3: Build cmap lookups
    lat_cmap = build_cmap(lat_font) if lat_font else {}
    jp_cmap = build_cmap(jp_font)

    # Apply subFont.excludeCodepoints: strip codepoints the caller wants to
    # keep sourced from baseFont. Filtering at the cmap level is enough — the
    # downstream pipeline keys all replacement decisions off lat_cmap, so the
    # base outline at those codepoints stays untouched.
    if lat_font and lat_cfg:
        excluded_cps = parse_codepoint_list(lat_cfg.get("excludeCodepoints"))
        if excluded_cps:
            lat_cmap = {cp: g for cp, g in lat_cmap.items()
                        if cp not in excluded_cps}

    progress("analyzing", 3, f"2/{S} \u00b7 Merging glyphs...")

    copied = set()
    existing_names = set(merged.getGlyphOrder())
    merged_is_tt = "glyf" in merged
    final_lat_scale = 1.0
    lat_baseline = 0

    jp_scale = jp_cfg.get("scale", 1.0)
    jp_baseline = jp_cfg.get("baselineOffset", 0)
    # Fold output-UPM ratio into the JP transform so a single pass over
    # the JP outlines / hints / hmtx produces output-UPM-ready values.
    jp_scale_eff = jp_scale * jp_upm_ratio
    jp_baseline_eff = jp_baseline * jp_upm_ratio

    # Scale JP-origin GPOS lookups by the same transform used for JP outlines
    # before any Latin lookups are merged in. Latin lookups merged later are
    # scaled separately via final_lat_scale inside merge_feature_tables.
    if jp_scale_eff != 1.0 or jp_baseline_eff != 0:
        _gpos = merged.get("GPOS")
        if _gpos is not None and _gpos.table and _gpos.table.LookupList:
            for _lk in _gpos.table.LookupList.Lookup:
                _scale_gpos_lookup(_lk, jp_scale_eff, jp_baseline_eff)

    if not lat_font:
        progress("merging-glyphs", 4, f"2/{S} \u00b7 Merging glyphs...")
    else:
        # Step 4: Build cmap-based name mapping (Latin name → merged name)
        latin_glyphs_to_copy = dict(lat_cmap)
        merged_cmap = build_cmap(merged)

        # Map Latin glyph names to merged glyph names via shared codepoints
        # e.g. Latin "A" (U+0041) → merged "cid00033" (U+0041)
        lat_glyph_order_set = set(lat_font.getGlyphOrder())
        lat_to_merged_name = {}  # Latin glyph name → target name in merged font
        for cp, lat_gname in lat_cmap.items():
            merged_gname = merged_cmap.get(cp)
            if merged_gname and merged_gname != lat_gname:
                # If the merged target name already exists as a DISTINCT glyph
                # in the Latin font (e.g. Playwrite IE has both `e` and `e.mod`,
                # with cmap U+0065 → `e.mod`), renaming `e.mod` → `e` would
                # collide with Latin's own `e`, fusing two distinct glyphs and
                # breaking GSUB lookups that reference them separately. In that
                # case, leave `lat_gname` unchanged and repoint the merged cmap
                # to it instead.
                if merged_gname in lat_glyph_order_set:
                    continue
                lat_to_merged_name[lat_gname] = merged_gname

        all_lat_glyphs = set(lat_font.getGlyphOrder())
        all_lat_glyphs.discard('.notdef')
        existing_names = set(merged.getGlyphOrder())

        # Detect cross-codepoint glyph-name collisions. A sub-font glyph name
        # may match a base-font glyph reachable from a *different* base
        # codepoint — e.g. Inter encodes U+0298 (ʘ) as `uni25CE` while Noto
        # uses `uni25CE` for U+25CE (◎). Copying Inter's `uni25CE` would
        # silently overwrite Noto's bullseye outline, so U+25CE renders as
        # the Latin click. Same-name-different-codepoint always means the
        # two glyphs are unrelated, so always rename the sub glyph
        # (`uni25CE` → `uni25CE.sub`) and let the base glyph keep its slot.
        sub_reverse_cmap: dict[str, set[int]] = {}
        for cp, gname in lat_cmap.items():
            sub_reverse_cmap.setdefault(gname, set()).add(cp)
        base_reverse_cmap: dict[str, set[int]] = {}
        for cp, gname in merged_cmap.items():
            base_reverse_cmap.setdefault(gname, set()).add(cp)

        # Reserve set must include sub-font's own glyph names too — otherwise
        # picking ``{g}.sub`` here could silently collide with a glyph that
        # already exists in the sub font under that exact name (the later
        # Latin-glyph copy would land at the same destination and clobber
        # the renamed one).
        reserved_for_rename = (set(existing_names)
                               | set(lat_to_merged_name.values())
                               | all_lat_glyphs)
        # Track only the *cross-codepoint* .sub renames here. The base-side
        # GSUB strip later excludes these names from removal because
        # `_copy_single_substitutions_for_features` will add their inherited
        # `vert` / `vrt2` mappings after the strip runs (e.g. Inter's
        # ``ellipsis`` → ``ellipsis.sub`` keeps base's ``ellipsis`` vert
        # rule reachable for U+22EF). CID-style cmap remaps (e.g. Inter's
        # ``zero`` → ``cid00017``) must NOT be in this set — those are the
        # bug cases where base ``locl: cid00017 → cid63153`` should be
        # stripped.
        cross_codepoint_lat_renames: set = set()
        for sub_gname, sub_cps in sub_reverse_cmap.items():
            if sub_gname in lat_to_merged_name:
                continue
            base_cps = base_reverse_cmap.get(sub_gname)
            if not base_cps:
                continue
            if base_cps - sub_cps:
                new_name = f"{sub_gname}.sub"
                i = 1
                while new_name in reserved_for_rename:
                    i += 1
                    new_name = f"{sub_gname}.sub{i}"
                lat_to_merged_name[sub_gname] = new_name
                reserved_for_rename.add(new_name)
                cross_codepoint_lat_renames.add(new_name)
                stranded = sorted(base_cps - sub_cps)
                stranded_repr = ", ".join(f"U+{c:04X}" for c in stranded[:6])
                if len(stranded) > 6:
                    stranded_repr += f", ... (+{len(stranded) - 6} more)"
                print(
                    f"warning: glyph name collision — sub-font glyph "
                    f"{sub_gname!r} renamed to {new_name!r} to preserve "
                    f"base-font glyph at {stranded_repr}",
                    file=sys.stderr,
                )

        # Handle name collisions between Latin glyphs (copied as-is) and
        # existing merged-font glyphs. When a Latin glyph name already exists
        # in the merged font AND is not being remapped via cmap, suffix it so
        # we don't overwrite the Japanese glyph. Without this, Playwrite's
        # plain `e` would clobber Kaisei's `e`, and GSUB lookups referencing
        # Latin `e` would snap onto the Japanese glyph.
        # Latin glyph names that ARE cmap targets may legitimately overwrite
        # an existing merged glyph of the same name (e.g. Inter `H` replacing
        # Noto `H` at U+0048). We only suffix non-cmap-target Latin glyphs
        # that collide — those are the ones referenced purely by GSUB.
        lat_cmap_targets = set(lat_cmap.values())
        reserved = set(existing_names) | set(lat_to_merged_name.values())
        for g in sorted(all_lat_glyphs):
            if g in lat_to_merged_name:
                continue
            if g in lat_cmap_targets:
                continue
            if g in existing_names:
                new_name = f"{g}.lat"
                i = 1
                while new_name in reserved:
                    i += 1
                    new_name = f"{g}.lat{i}"
                lat_to_merged_name[g] = new_name
                reserved.add(new_name)

        # For truly new glyphs (no cmap overlap), check 65535 budget
        budget = 65535 - len(existing_names)
        if budget < 0:
            budget = 0
        lat_glyphs_dropped = False
        for g in list(all_lat_glyphs):
            dst = lat_to_merged_name.get(g, g)
            if dst not in existing_names:
                if budget > 0:
                    budget -= 1
                else:
                    lat_glyphs_dropped = True
                    all_lat_glyphs.discard(g)
                    for cp in list(latin_glyphs_to_copy):
                        if latin_glyphs_to_copy[cp] == g:
                            del latin_glyphs_to_copy[cp]

        # Step 4b: Preserve base-font glyphs shared across codepoints.
        # When a merged glyph is the target of a Latin replacement (via
        # lat_to_merged_name), other non-Latin codepoints that reference
        # the same glyph would silently lose their original outline.
        # Example: Noto Sans JP maps both U+2027 and U+30FB to glyph
        # "uni2027".  Inter replaces U+2027, overwriting that glyph with
        # a half-width Latin outline — U+30FB (katakana middle dot) then
        # displays the wrong glyph.  Fix: duplicate the original glyph
        # under a new name and repoint collateral cmap entries before
        # the Latin copy overwrites anything.
        merged_reverse_cmap: dict[str, set[int]] = {}
        for cp, gname in merged_cmap.items():
            merged_reverse_cmap.setdefault(gname, set()).add(cp)

        lat_cmap_set = set(lat_cmap.keys())
        overwritten_glyphs = set(lat_to_merged_name.values())
        # Inherit whatever budget the Latin-glyph allocation pass above left
        # behind. Recomputing from ``existing_names`` would double-count the
        # slots that the budget loop already consumed for ``.sub`` / ``.lat``
        # / cmap-remap-NEW glyph names — none of those have been written
        # into ``existing_names`` yet, so a fresh ``65535 - len(...)`` would
        # over-report headroom and let near-limit CID fonts overflow.
        dup_budget = budget

        for merged_gname in sorted(overwritten_glyphs):
            referencing_cps = merged_reverse_cmap.get(merged_gname, set())
            collateral_cps = referencing_cps - lat_cmap_set
            if not collateral_cps:
                continue

            if dup_budget <= 0:
                # No room to duplicate — cancel the Latin replacement for
                # this glyph so the shared base glyph is preserved intact.
                for lat_g, merged_g in list(lat_to_merged_name.items()):
                    if merged_g == merged_gname:
                        del lat_to_merged_name[lat_g]
                        # Also remove from copy list so the glyph is skipped
                        for cp_k in list(latin_glyphs_to_copy):
                            if latin_glyphs_to_copy[cp_k] == lat_g:
                                del latin_glyphs_to_copy[cp_k]
                        all_lat_glyphs.discard(lat_g)
                        break
                continue

            dup_name = f"{merged_gname}.orig"
            i = 1
            while dup_name in existing_names:
                dup_name = f"{merged_gname}.orig{i}"
                i += 1
            existing_names.add(dup_name)
            dup_budget -= 1

            # Duplicate outline data
            if merged_is_tt:
                src_glyf = merged["glyf"]
                if merged_gname in src_glyf:
                    src_glyf[dup_name] = copy.deepcopy(
                        src_glyf[merged_gname]
                    )
            else:
                cff_td = merged["CFF "].cff.topDictIndex[0]
                cs_table = cff_td.CharStrings
                if merged_gname in cs_table.charStrings:
                    if cs_table.charStringsAreIndexed:
                        gid = cs_table.charStrings[merged_gname]
                        orig_cs = copy.deepcopy(
                            cs_table.charStringsIndex[gid]
                        )
                        next_idx = len(cs_table.charStringsIndex)
                        cs_table.charStringsIndex.append(orig_cs)
                        cs_table.charStrings[dup_name] = next_idx
                    else:
                        cs_table.charStrings[dup_name] = copy.deepcopy(
                            cs_table.charStrings[merged_gname]
                        )
                # CID FDSelect: assign same FD as the source glyph
                _cid_td = cff_td
                if hasattr(_cid_td, 'FDSelect') and _cid_td.FDSelect:
                    order = merged.getGlyphOrder()
                    if merged_gname in order:
                        src_gid = order.index(merged_gname)
                        fd_idx = _cid_td.FDSelect[src_gid]
                        # FDSelect will be extended after glyph order is
                        # synced; stash the fd index so we can patch it.
                        if not hasattr(_cid_td, '_pending_fd'):
                            _cid_td._pending_fd = {}
                        _cid_td._pending_fd[dup_name] = fd_idx

            # Duplicate metrics
            if merged_gname in merged["hmtx"].metrics:
                merged["hmtx"].metrics[dup_name] = (
                    merged["hmtx"].metrics[merged_gname]
                )
            _copy_vertical_metrics(merged, merged_gname, dup_name)
            _copy_single_substitutions_for_features(
                merged, merged_gname, dup_name, {"vert", "vrt2"}
            )

            # Repoint collateral cmap entries to the duplicate
            for table in merged["cmap"].tables:
                if not hasattr(table, 'cmap') or not table.cmap:
                    continue
                for cp in collateral_cps:
                    if cp in table.cmap and table.cmap[cp] == merged_gname:
                        table.cmap[cp] = dup_name

            # Keep merged_cmap consistent for later steps
            for cp in collateral_cps:
                if merged_cmap.get(cp) == merged_gname:
                    merged_cmap[cp] = dup_name

        # Step 5: Determine outline formats
        lat_is_cff = "CFF " in lat_font or "CFF2" in lat_font

        lat_scale = lat_cfg.get("scale", 1.0)
        lat_baseline = lat_cfg.get("baselineOffset", 0)

        lat_upm = lat_font["head"].unitsPerEm
        # Latin outlines are scaled directly to the target output UPM so the
        # merge writes outlines that already match the final head.unitsPerEm.
        upm_scale = output_upm / lat_upm
        final_lat_scale = lat_scale * upm_scale

        vertical_metric_source_for_dst = {}
        if "vmtx" in merged or "VORG" in merged:
            for cp, lat_glyph_name in latin_glyphs_to_copy.items():
                base_glyph_name = merged_cmap.get(cp)
                if not base_glyph_name:
                    continue
                dst_name = lat_to_merged_name.get(lat_glyph_name, lat_glyph_name)
                if dst_name not in existing_names:
                    vertical_metric_source_for_dst.setdefault(
                        dst_name, base_glyph_name
                    )

        # Step 6: Copy Latin glyphs into merged font (using name mapping)
        progress("merging-glyphs", 4, f"2/{S} \u00b7 Merging glyphs...")

        unique_lat_glyphs = sorted(all_lat_glyphs)

        if lat_is_cff and merged_is_tt:
            from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph
            for glyph_name in unique_lat_glyphs:
                dst = lat_to_merged_name.get(glyph_name, glyph_name)
                if dst not in existing_names:
                    merged["glyf"][dst] = TTGlyph()
                    merged["hmtx"].metrics[dst] = (0, 0)
                    existing_names.add(dst)
                copied.add(dst)
            convert_cff_glyphs_to_tt(lat_font, merged, unique_lat_glyphs,
                                      final_lat_scale, lat_baseline,
                                      copied=copied,
                                      name_map=lat_to_merged_name)

        elif not lat_is_cff and merged_is_tt:
            from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph
            for glyph_name in unique_lat_glyphs:
                dst = lat_to_merged_name.get(glyph_name, glyph_name)
                if dst not in existing_names:
                    merged["glyf"][dst] = TTGlyph()
                    merged["hmtx"].metrics[dst] = (0, 0)
                    existing_names.add(dst)
            for glyph_name in unique_lat_glyphs:
                dst = lat_to_merged_name.get(glyph_name, glyph_name)
                copy_glyph_tt(lat_font, merged, glyph_name,
                              final_lat_scale, lat_baseline, copied,
                              dst_name=dst, name_map=lat_to_merged_name)

        elif lat_is_cff and not merged_is_tt:
            # CFF-to-CFF: copy each source CharString with hint operators
            # preserved (hstem*, vstem*, hintmask, cntrmask). The full T2
            # program is walked and operands are scaled/translated in place
            # by ``transform_t2_charstring``. This preserves Latin CFF
            # hinting through the merge — the previous implementation
            # redrew via T2CharStringPen, which only emits drawing operators
            # and silently dropped every hint.
            src_cff = (lat_font["CFF "].cff if "CFF " in lat_font
                       else lat_font["CFF2"].cff)
            src_cff.desubroutinize()
            src_td = src_cff.topDictIndex[0]
            src_charstrings = src_td.CharStrings

            dst_cff_td = merged["CFF "].cff.topDictIndex[0]
            dst_global_subrs = merged["CFF "].cff.GlobalSubrs
            _is_cid = hasattr(dst_cff_td, 'FDArray') and dst_cff_td.FDArray
            if not _is_cid and hasattr(dst_cff_td, 'Private') and dst_cff_td.Private:
                dst_private_default = dst_cff_td.Private
            elif _is_cid:
                dst_private_default = dst_cff_td.FDArray[0].Private
            else:
                dst_private_default = None

            def _private_for_dst(dst_gname):
                """Return the Private dict that the destination CharStrings
                table actually associates with ``dst_gname``. For CID fonts
                this is FDArray[FDSelect[gid]]; for name-keyed CFF it is the
                single TopDict.Private."""
                if not _is_cid:
                    return dst_private_default
                cs_table = dst_cff_td.CharStrings
                try:
                    if cs_table.charStringsAreIndexed:
                        gid = cs_table.charStrings.get(dst_gname)
                        if gid is None:
                            return dst_private_default
                    else:
                        gid = list(cs_table.charStrings.keys()).index(dst_gname)
                    fd_idx = dst_cff_td.FDSelect[gid]
                    return dst_cff_td.FDArray[fd_idx].Private
                except Exception:
                    return dst_private_default

            for glyph_name in unique_lat_glyphs:
                dst = lat_to_merged_name.get(glyph_name, glyph_name)
                if dst in copied:
                    continue
                copied.add(dst)
                if glyph_name not in src_charstrings:
                    continue

                dst_private = _private_for_dst(dst)
                try:
                    src_cs = src_charstrings[glyph_name]
                    new_cs = transform_t2_charstring(
                        src_cs, final_lat_scale, lat_baseline,
                        dst_private, dst_global_subrs,
                    )
                except Exception:
                    from fontTools.misc.psCharStrings import T2CharString
                    new_cs = T2CharString(private=dst_private,
                                          globalSubrs=dst_global_subrs)

                cs_table = dst_cff_td.CharStrings
                if dst in cs_table.charStrings:
                    cs_table[dst] = new_cs
                elif cs_table.charStringsAreIndexed:
                    next_idx = len(cs_table.charStringsIndex)
                    cs_table.charStringsIndex.append(new_cs)
                    cs_table.charStrings[dst] = next_idx
                else:
                    cs_table.charStrings[dst] = new_cs

                if glyph_name in lat_font["hmtx"].metrics:
                    aw, lsb = lat_font["hmtx"].metrics[glyph_name]
                    merged["hmtx"].metrics[dst] = (
                        int(round(aw * final_lat_scale)),
                        int(round(lsb * final_lat_scale))
                    )
                existing_names.add(dst)

        elif not lat_is_cff and not merged_is_tt:
            convert_tt_glyphs_to_cff(lat_font, merged, unique_lat_glyphs,
                                      final_lat_scale, lat_baseline, copied,
                                      existing_names, name_map=lat_to_merged_name)

        for dst_name, base_glyph_name in vertical_metric_source_for_dst.items():
            if dst_name in existing_names:
                _copy_vertical_metrics(merged, base_glyph_name, dst_name)
                _copy_single_substitutions_for_features(
                    merged, base_glyph_name, dst_name, {"vert", "vrt2"}
                )

        # Sync font-level glyph order
        if merged_is_tt:
            merged.setGlyphOrder(merged["glyf"].glyphOrder)
        else:
            original_order = merged.getGlyphOrder()
            new_glyphs = [g for g in existing_names if g not in set(original_order)]
            final_order = original_order + sorted(new_glyphs)
            merged.setGlyphOrder(final_order)
            cff_td = merged["CFF "].cff.topDictIndex[0]
            cff_td.charset = final_order[:]
            # Patch FDSelect for duplicated collateral glyphs
            if hasattr(cff_td, '_pending_fd'):
                for gname, fd_idx in cff_td._pending_fd.items():
                    if gname in final_order:
                        gid = final_order.index(gname)
                        while len(cff_td.FDSelect) <= gid:
                            cff_td.FDSelect.append(0)
                        cff_td.FDSelect[gid] = fd_idx
                del cff_td._pending_fd
        progress("merging-glyphs", 5, f"3/{S} \u00b7 Merging features...")

        # Step 8: Update cmap tables (use mapped names)
        lat_cmap_set = set(lat_cmap.keys())
        for table in merged["cmap"].tables:
            if not hasattr(table, 'cmap') or not table.cmap:
                continue
            max_cp = 0xFFFF if table.format in (0, 2, 4, 6) else 0x10FFFF
            for cp, lat_glyph_name in latin_glyphs_to_copy.items():
                if cp <= max_cp:
                    # Use the merged name (e.g. cid00033) if mapping exists
                    dst_name = lat_to_merged_name.get(lat_glyph_name, lat_glyph_name)
                    table.cmap[cp] = dst_name

        # Step 9: Merge feature tables
        progress("merging-features", 6, f"3/{S} \u00b7 Merging features...")
        # When Latin glyph names were remapped on copy (CID fonts, or scripts
        # like Playwrite IE that use contextual-default names such as
        # ``A.cur_locl``), the Latin GSUB/GPOS tables reference the *old*
        # names. Pass the map so those references get rewritten to the
        # merged names rather than dropping Latin features entirely.
        #
        # Exception: if glyphs were dropped due to the 65535 budget (typical
        # CID case like Noto CJK), the Latin lookups would reference
        # non-existent glyphs. In that case, fall back to base-font-only
        # features to keep the output valid.
        # Build the Latin-owned merged-name set from the *post-prune*
        # ``all_lat_glyphs``, not ``lat_font.getGlyphOrder()``. The budget
        # loop and the Step 4b collateral-cancel can both prune entries,
        # and using the unpruned set would mark dropped / cancelled
        # glyphs as Latin-owned — over-eagerly stripping legitimate base
        # behavior on them.
        lat_owned = {lat_to_merged_name.get(g, g) for g in all_lat_glyphs}
        if lat_glyphs_dropped:
            # Latin lookups reference non-existent (dropped) glyphs and
            # cannot be appended, but base-side ``locl`` / ``aalt`` /
            # ``fwid`` rules on Latin-owned names must still be stripped
            # — otherwise NotoSansCJKjp's ``cid00017 → cid63153`` (the
            # bug case from #23) survives and plain digits shape to base
            # CJK alternates.
            #
            # Limitation: this branch also bypasses Latin user-feature
            # promotion (`ss02` / `tnum` / ... reachable from CJK
            # scripts). Filtering the Latin GSUB to lookups whose
            # post-rename inputs all survived would re-enable promotion
            # here, but it requires lookup pruning + chain-context
            # reference remap + feature/LangSys cleanup with non-trivial
            # regression risk. Out of scope for the initial CJK-promotion
            # fix; tracked as a follow-up.
            merge_feature_tables(None, jp_font, merged,
                                 lat_scale=final_lat_scale, lat_baseline=lat_baseline,
                                 append_lat_lookups=False,
                                 preserved_lat_names=cross_codepoint_lat_renames,
                                 lat_glyph_names_override=lat_owned)
        else:
            merge_feature_tables(lat_font, jp_font, merged,
                                 lat_scale=final_lat_scale, lat_baseline=lat_baseline,
                                 lat_name_map=lat_to_merged_name or None,
                                 preserved_lat_names=cross_codepoint_lat_renames,
                                 lat_glyph_names_override=lat_owned)

    # Step 7: Apply transforms to Japanese glyphs (always, even without Latin font)
    if (jp_scale_eff != 1.0 or jp_baseline_eff != 0) and not _jp_transform_done:
        progress("merging-glyphs", 6, f"3/{S} \u00b7 Merging features...")
        jp_glyph_names = [
            gname for gname in merged.getGlyphOrder()
            if gname not in copied
        ]

        if merged_is_tt:
            for gname in jp_glyph_names:
                transform_tt_glyph_inplace(merged, gname, jp_scale_eff, jp_baseline_eff)
        else:
            # CFF path — apply scale/baseline to each JP CharString in place,
            # respecting per-glyph FDSelect for CID fonts.
            _cff = merged["CFF "].cff
            _cff.desubroutinize()
            _td = _cff.topDictIndex[0]
            _cs = _td.CharStrings
            _global_subrs = _cff.GlobalSubrs
            _is_cid = hasattr(_td, "FDArray") and _td.FDArray

            def _jp_private_for(gname):
                if not _is_cid:
                    return _td.Private if hasattr(_td, "Private") else None
                try:
                    if _cs.charStringsAreIndexed:
                        gid = _cs.charStrings.get(gname)
                        if gid is None:
                            return _td.FDArray[0].Private
                    else:
                        gid = list(_cs.charStrings.keys()).index(gname)
                    fd_idx = _td.FDSelect[gid]
                    return _td.FDArray[fd_idx].Private
                except Exception:
                    return _td.FDArray[0].Private

            for gname in jp_glyph_names:
                if gname not in _cs:
                    continue
                src_cs = _cs[gname]
                priv = _jp_private_for(gname)
                try:
                    new_cs = transform_t2_charstring(
                        src_cs, jp_scale_eff, jp_baseline_eff,
                        priv, _global_subrs,
                    )
                except Exception:
                    continue
                if _cs.charStringsAreIndexed:
                    idx = _cs.charStrings[gname]
                    _cs.charStringsIndex[idx] = new_cs
                else:
                    _cs.charStrings[gname] = new_cs
                # Scale advance width (hmtx). Baseline doesn't affect aw.
                if gname in merged["hmtx"].metrics:
                    aw, lsb = merged["hmtx"].metrics[gname]
                    merged["hmtx"].metrics[gname] = (
                        int(round(aw * jp_scale_eff)),
                        int(round(lsb * jp_scale_eff)),
                    )
            # Transform the JP Private dict's blue zones / stems so that
            # hints continue to land on the moved glyph outlines.
            if not _is_cid and hasattr(_td, "Private") and _td.Private:
                _privs = [_td.Private]
            elif _is_cid:
                _privs = [fd.Private for fd in _td.FDArray]
            else:
                _privs = []
            for _p in _privs:
                for _attr in ("BlueValues", "OtherBlues", "FamilyBlues",
                              "FamilyOtherBlues"):
                    _vals = getattr(_p, _attr, None)
                    if _vals:
                        setattr(_p, _attr, transform_blue_values(
                            _vals, jp_scale_eff, jp_baseline_eff))
                for _attr in ("StdHW", "StdVW"):
                    _v = getattr(_p, _attr, None)
                    if _v is not None:
                        setattr(_p, _attr, scale_stem_widths(_v, jp_scale_eff))
                for _attr in ("StemSnapH", "StemSnapV"):
                    _v = getattr(_p, _attr, None)
                    if _v:
                        setattr(_p, _attr, scale_stem_widths(_v, jp_scale_eff))

    # Scale JP-origin vertical metrics and update head.unitsPerEm so that
    # reconcile_tables (which compares Latin metrics against merged via
    # upm_ratio = merged_upm / lat_upm) sees the final target UPM.
    if jp_upm_ratio != 1.0:
        _scale_jp_metrics(merged, jp_upm_ratio)
        merged["head"].unitsPerEm = output_upm

    # Step 10: Reconcile global tables
    progress("merging-features", 7, f"3/{S} \u00b7 Merging features...")
    reconcile_tables(lat_font, jp_font, merged, config)

    # Step 11: Ensure glyph order, glyf, and hmtx are fully consistent
    progress("writing", 8, f"3/{S} \u00b7 Merging features...")
    if merged_is_tt:
        glyf = merged["glyf"]
        hmtx = merged["hmtx"]

        # The authoritative glyph list is glyf.glyphOrder (managed by glyf.__setitem__)
        canonical_order = list(glyf.glyphOrder)

        # Ensure every glyph in glyf.glyphs is in glyf.glyphOrder
        for gname in list(glyf.glyphs.keys()):
            if gname not in canonical_order:
                canonical_order.append(gname)
        # Note: 65535 limit should not be hit here because cmap-based
        # replacement reuses existing glyph slots instead of adding new ones.

        # Ensure hmtx and vmtx have metrics for every glyph
        vmtx = merged.get("vmtx")
        for gname in canonical_order:
            if gname not in hmtx.metrics:
                hmtx.metrics[gname] = (0, 0)
            if vmtx and gname not in vmtx.metrics:
                vmtx.metrics[gname] = (output_upm, 0)  # default vertical advance
            if gname not in glyf.glyphs:
                from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph
                glyf.glyphs[gname] = TTGlyph()

        # Force-sync all glyph orders
        glyf.glyphOrder = canonical_order
        merged.setGlyphOrder(canonical_order)
    # NOTE: the CFF case doesn't need extra normalization here. The base is
    # always a CFF font (we never convert TT→CFF), so all hmtx entries
    # already exist — the merge only overwrote outlines in place.

    # Step 12: Sanitise name table — drop Mac-Roman records that can't encode
    name_table = merged["name"]
    to_remove = []
    for record in name_table.names:
        if record.platformID == 1 and record.platEncID == 0:
            try:
                text = record.toUnicode()
                text.encode("mac_roman")
            except (UnicodeEncodeError, UnicodeDecodeError):
                to_remove.append(record)
    for record in to_remove:
        name_table.names.remove(record)

    # For large fonts, use post format 3.0 (no glyph names) to avoid
    # ushort overflow in format 2.0's name index
    if len(merged.getGlyphOrder()) > 32767:
        merged["post"].formatType = 3.0

    # Step 13: Write output
    ext = os.path.splitext(output_path)[1]
    progress("writing", 9, f"4/{S} \u00b7 Exporting {ext}...")
    # When the output is CFF, fontTools' CFF compile may reset the font
    # glyph order to match the CFF table's internal indexing. Re-derive
    # glyph order from the CFF table now and backfill any hmtx rows that
    # are missing for that order so hmtx.compile() can't trip on a stray
    # name.
    if "CFF " in merged and "glyf" not in merged:
        _cff = merged["CFF "]
        # Only re-sync glyph order when we converted the base from TT to CFF
        # in this run; for native CFF (CID) flows the glyph order was already
        # established and overwriting it would lose the prepared order.
        # Also: calling ``_cff.getGlyphOrder`` directly trips fontTools'
        # ``_gaveGlyphOrder`` guard on a native CFF table, so we go through
        # the font-level getter instead.
        if _jp_transform_done:
            _td = _cff.cff.topDictIndex[0]
            _charset_order = list(_td.charset) if hasattr(_td, "charset") else None
            if _charset_order:
                merged.setGlyphOrder(_charset_order)
        _go_from_cff = list(merged.getGlyphOrder())
        # Backfill hmtx/vmtx for any glyph in the CFF charset that doesn't
        # have a metrics row yet — fontTools' hmtx.compile would otherwise
        # KeyError on the missing entry.
        _hm = merged["hmtx"].metrics
        for _g in _go_from_cff:
            if _g not in _hm:
                _hm[_g] = (0, 0)
        _vmtx = merged.get("vmtx")
        if _vmtx is not None:
            _upm = merged["head"].unitsPerEm
            for _g in _go_from_cff:
                if _g not in _vmtx.metrics:
                    _vmtx.metrics[_g] = (_upm, 0)
    # Recompute CFF FontBBox after all outline mutations. CFF has no
    # per-glyph bbox, only TopDict.FontBBox; fontTools will not refresh
    # it on its own. Skip for very large CID fonts where the walk would
    # be slow and the original FontBBox is still valid.
    if "CFF " in merged and "glyf" not in merged:
        _cff = merged["CFF "]
        _td = _cff.cff.topDictIndex[0]
        _n = len(_td.CharStrings) if hasattr(_td, "CharStrings") else 0
        if _n < 60000:
            recalc_cff_font_bbox(merged)
    # Recompute maxp sub-fields for TrueType output. fontTools' save()
    # refreshes numGlyphs but does not walk glyf to refresh the per-glyph
    # maxima, so adding new Latin glyphs would otherwise leave maxp
    # pointing at the base font's old values (Issue #2 #8). We avoid
    # maxp.recalc() because fontTools' implementation reads g.xMin which
    # empty glyphs may not carry; walking glyf ourselves keeps the merge
    # robust on every fixture.
    if "maxp" in merged and "glyf" in merged:
        _maxp = merged["maxp"]
        _glyf = merged["glyf"]
        max_pts = max_contours = 0
        max_comp_pts = max_comp_contours = 0
        max_comp_elems = max_comp_depth = 0

        # Memoised flatten of each glyph to (points, contours, depth).
        _flat_cache: dict = {}

        def _flat_stats(name):
            if name in _flat_cache:
                return _flat_cache[name]
            try:
                g = _glyf[name]
            except KeyError:
                _flat_cache[name] = (0, 0, 0)
                return _flat_cache[name]
            if g.numberOfContours == 0:
                _flat_cache[name] = (0, 0, 0)
            elif g.isComposite():
                pts = contours = 0
                depth = 0
                for c in g.components:
                    sub_pts, sub_contours, sub_depth = _flat_stats(c.glyphName)
                    pts += sub_pts
                    contours += sub_contours
                    depth = max(depth, sub_depth + 1)
                _flat_cache[name] = (pts, contours, depth)
            else:
                pts = (len(g.coordinates)
                       if hasattr(g, "coordinates") and g.coordinates else 0)
                contours = g.numberOfContours if g.numberOfContours > 0 else 0
                _flat_cache[name] = (pts, contours, 0)
            return _flat_cache[name]

        for _g in merged.getGlyphOrder():
            try:
                g = _glyf[_g]
            except KeyError:
                continue
            if g.numberOfContours == 0:
                continue
            if g.isComposite():
                if g.components:
                    max_comp_elems = max(max_comp_elems, len(g.components))
                pts, contours, depth = _flat_stats(_g)
                max_comp_pts = max(max_comp_pts, pts)
                max_comp_contours = max(max_comp_contours, contours)
                max_comp_depth = max(max_comp_depth, depth)
            else:
                if hasattr(g, "coordinates") and g.coordinates is not None:
                    max_pts = max(max_pts, len(g.coordinates))
                if g.numberOfContours > 0:
                    max_contours = max(max_contours, g.numberOfContours)

        for attr, value in (
            ("maxPoints", max_pts),
            ("maxContours", max_contours),
            ("maxCompositePoints", max_comp_pts),
            ("maxCompositeContours", max_comp_contours),
            ("maxComponentElements", max_comp_elems),
            ("maxComponentDepth", max_comp_depth),
        ):
            if hasattr(_maxp, attr):
                setattr(_maxp, attr, max(getattr(_maxp, attr, 0), value))

    # Normalize TT hinting for merged TTF output (Issue #17). Glyph-level
    # bytecode from the sub font cannot reliably execute against the base
    # font's fpgm/prep/cvt, and partial preservation made the output look
    # bytecode-hinted to renderers without actually moving any points.
    if "glyf" in merged:
        normalize_truetype_hinting(merged)
    # Ensure parent directory exists for all path-mode outputs
    for p in (output_path, paths.get("woff2"), paths.get("ofl"),
              paths.get("settings"), paths.get("config")):
        if p:
            os.makedirs(os.path.dirname(p), exist_ok=True)

    # Re-sort GSUB/GPOS Coverages by the final merged glyph order so
    # HarfBuzz's binary search can resolve Latin lookups after the cmap
    # merge renumbered glyph IDs.
    _resort_lookup_coverages(merged)

    output_lat_glyph_names = set()
    if lat_font:
        output_lat_glyph_names = {
            lat_to_merged_name.get(g, g) for g in lat_font.getGlyphOrder()
        }
    _save_with_adobe_kern_compat(merged, output_path, output_lat_glyph_names)

    font_for_woff2 = merged
    if "glyf" in merged and hinting_policy == "ttfautohint":
        progress("writing", 9, f"4/{S} \u00b7 Applying TrueType autohint...")
        _apply_ttfautohint(output_path)
        if paths.get("woff2"):
            font_for_woff2 = TTFont(output_path)

    # Step 14: Write WOFF2
    woff2_out = paths.get("woff2")
    if woff2_out:
        progress("writing", 10, f"5/{S} \u00b7 Exporting .woff2...")
        font_for_woff2.flavor = "woff2"
        font_for_woff2.save(woff2_out)
        if font_for_woff2 is not merged:
            font_for_woff2.close()

    # Path-mode artifact writing
    ofl_out = paths.get("ofl")
    if ofl_out:
        with open(ofl_out, "w", encoding="utf-8") as f:
            f.write(build_ofl_text(config))

    settings_out = paths.get("settings")
    if settings_out:
        with open(settings_out, "w", encoding="utf-8") as f:
            f.write(build_settings_text(config))

    config_out = paths.get("config")
    if config_out:
        export_cfg = build_export_config(config)
        with open(config_out, "w", encoding="utf-8") as f:
            json.dump(export_cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")

    progress("done", 100, "Merge complete")
    return output_path


def package_fonts(config: dict) -> dict:
    """Run a package export: create output dir, merge font, write all artifacts.

    Returns a manifest dict with paths of all generated files.
    """
    export = config.get("export") or {}
    pkg = export["package"]
    opts = resolve_package_options(config)

    dir_path = pkg["dir"]
    overwrite = opts["overwrite"]

    folder_path = prepare_output_dir(dir_path, overwrite)
    folder_name = os.path.basename(dir_path)

    base_ext = detect_sfnt_ext(config["baseFont"]["path"])
    font_file_name = f"{folder_name}.{base_ext}"
    font_path = os.path.join(folder_path, font_file_name)
    woff2_path = os.path.join(folder_path, f"{folder_name}.woff2")
    ofl_path = os.path.join(folder_path, "OFL.txt")
    settings_path = os.path.join(folder_path, "Settings.txt")

    # Build path-mode config to delegate to merge_fonts
    path_block = {
        "font": font_path,
        "woff2": woff2_path,
        "ofl": ofl_path,
        "settings": settings_path,
    }
    merge_config = dict(config, export={"path": path_block})
    merge_fonts(merge_config)

    files = [font_path, woff2_path, ofl_path, settings_path]

    config_path = None
    if opts["bundleInputFonts"]:
        path_map = bundle_input_fonts(config, folder_path)
        for src_path in path_map.values():
            files.append(os.path.join(folder_path, src_path.lstrip("./")))

        export_cfg = build_export_config(config, path_map)
        config_path = os.path.join(folder_path, "ExportConfig.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(export_cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        files.append(config_path)

    return {
        "outputDir": folder_path,
        "fontPath": font_path,
        "woff2Path": woff2_path,
        "oflPath": ofl_path,
        "settingsPath": settings_path,
        "configPath": config_path,
        "files": files,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        config_str = sys.stdin.read()
        config = json.loads(config_str)

        export = config.get("export") or {}
        if "package" in export:
            manifest = package_fonts(config)
            print(json.dumps(manifest), flush=True)
        else:
            result = merge_fonts(config)
            print(result, flush=True)
    except Exception as e:
        progress("error", 0, str(e))
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
