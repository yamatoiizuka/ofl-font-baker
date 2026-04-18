# OFL Font Baker ― Architecture

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Renderer Process (React)                                    │
│                                                              │
│  FontCard → mergeStore (Zustand) → SettingsPanel             │
│       │          │    ↕ undo/redo      VariableAxes          │
│       ▼          ▼                       │                   │
│  useFontLoader   GlyphPreview       ExportPanel              │
│  (opentype.js)   (HarfBuzz WASM)        │                   │
│                  + tofu (.notdef)   Metadata Modal           │
│                    rendering             │                   │
│                          IPC: "merge:start"                  │
└──────────────────────────┼───────────────────────────────────┘
                           │
            ┌──────────────▼───────────────────────────────────┐
            │  Main Process (Node.js)                          │
            │                                                  │
            │  ipc-handlers.ts                                 │
            │    ├─ font:check-exists (startup path validation)│
            │    ├─ dialog:missing-font (missing font dialog)  │
            │    ├─ overwrite confirm (overwrite dialog)       │
            │    │                                             │
            │    ▼                                             │
            │  merge-engine.ts                                 │
            │    │  binary or python3 spawn                    │
            │    ▼                                             │
            │  merge_fonts (binary or .py)                     │
            │    │                                             │
            │    ▼                                             │
            │  Output folder:                                  │
            │    ├─ {Family}-{Style}.otf                       │
            │    ├─ {Family}-{Style}.woff2                     │
            │    ├─ OFL.txt                                    │
            │    └─ settings.txt                               │
            └──────────────────────────────────────────────────┘
```

## Data Flow

### 1. Font Loading

```
User drops or clicks to select a font
  → webUtils.getPathForFile() to get the native file path
  → IPC "font:read-file" to read the ArrayBuffer
  → Parse with opentype.js
  → Resolve family name: preferredFamily (nameID 16) takes priority
  → Build style name: preferredSubfamily (nameID 17) + usWeightClass + usWidthClass
  → Cache metadata (copyright, designer, license) for instant modal display
  → Store as FontSource in Zustand + record undo history
```

### 2. Startup Font Validation

```
After restoring persisted state:
  → Verify each font path via IPC "font:check-exists"
  → If missing: show native dialog "Select Font" / "Clear"
  → Auto-select the available font as selectedRole
```

### 3. Preview (HarfBuzz WASM)

```
Whenever a FontSource is updated:
  → Create HB blob/face/font via harfbuzzjs
  → Split text into Latin/CJK runs (splitRuns — based on the Latin font's cmap)
  → Shape each run with the corresponding font
  → Missing runs → shape with the loaded font → render .notdef (tofu)
  → Cache shaping results → render via Canvas 2D Path2D
  → Line wrapping + kinsoku (Japanese line-breaking rules)
  → Highlight glyphs on card hover
```

### 4. Merge (Export)

```
useMerge.startMerge()
  → Directory selection dialog
  → Overwrite confirmation dialog (if folder exists)
  → Send MergeConfig via IPC "merge:start"
  → merge_fonts.py processes:
      1. Variable Font instantiation (bake axis values)
      2. Clone the Japanese font
      3. CID-keyed CFF: skip TT conversion for >60000 glyphs, keep as CFF
      4. cmap-based glyph replacement (Latin → merged glyph name mapping)
      5. CFF-to-CFF: redraw via TransformPen (scale + Private dict rebinding)
      6. GSUB/GPOS merge (skip Latin features for CID fonts)
      7. Set OFL metadata (copyright, license, description)
      8. Remove mac_roman name records with non-encodable strings
      9. post format 3.0 (for >32767 glyphs)
      10. Write OTF + WOFF2
      11. Generate OFL.txt + Settings.txt
  → Main process: receives JSON manifest (fontPath, woff2Path, oflPath, settingsPath)
```

## Font Merge Engine (merge_fonts.py)

### cmap-based Glyph Replacement

1. Build `lat_to_merged_name` mapping from Latin cmap and merged cmap
2. Overwrite existing slots: Latin `A` (U+0041) → merged `cid00033` (U+0041)
3. Glyph count does not increase → avoids hitting the 65535 limit
4. Only truly new glyphs are counted against the budget

### Glyph Copy Strategy

| Source → Target | Method |
|---|---|
| CFF → TrueType | `TransformPen` → `Cu2QuPen` → `TTGlyphPen` |
| TrueType → TrueType | `copy_glyph_tt` (composite dependency resolution) |
| CFF → CFF | T2 CharString program walk: affine-transform operands in place, preserving `hstem`/`vstem`/`hintmask` ops; copy + transform Private dict (`BlueValues`, `StdHW`/`StdVW`, `StemSnap*`) |
| TrueType → CFF | `TransformPen` → `ReverseContourPen` → `T2CharStringPen` |

The output format always mirrors the base font (TT base → TTF, CFF base → OTF). Round-tripping TT↔CFF is avoided because CFF→TT via cu2qu drops hints and TT→CFF via `T2CharStringPen` bloats the point count. WOFF2 output inherits whichever format the base uses.

TT→CFF glyph copy (used for Latin sources that don't match the base) always interposes `ReverseContourPen` before `T2CharStringPen`: TrueType uses outer-CW/inner-CCW winding while CFF uses outer-CCW/inner-CW. Without the reversal, non-zero fill swaps fills and holes, and the glyph renders with hollow intersections at low zoom (especially visible in Illustrator's zoom-out view).

CFF hint preservation: hint operators and `Private` dict blue zones / stem widths are scaled by the same affine (scale, baseline) used on the outlines, so hints continue to align with the transformed glyph after merge.

### Unified UPM / Scale / Baseline Transform

`outputUpm` (user-editable, default 1000 in the UI) drives a single affine
pass over the JP side of the merge. The ratio `jp_upm_ratio = outputUpm /
jp_source_upm` is folded into `jp_scale_eff` / `jp_baseline_eff` so the
existing JP transform block handles outlines, hmtx, CFF Private dict
blues/stems, and (for TT) composite components in one shot — there is no
second rounding pass. Latin is scaled directly to `outputUpm` via
`final_lat_scale = lat_scale * (outputUpm / lat_upm)`.

After the glyph transforms, JP-origin metrics (OS/2 sTypo*/usWin*/sxHeight/
sCapHeight, hhea ascent/descent/lineGap, post underline, head bbox) and JP
GPOS lookups are scaled by `jp_upm_ratio`, then `head.unitsPerEm` is set to
`outputUpm`. `reconcile_tables` then compares against the already-scaled JP
values, so the Latin envelope is taken in output UPM units.

### Metrics

- `head.unitsPerEm` = `outputUpm` (user-set, default 1000)
- OS/2 and hhea ascender/descender are the envelope of both fonts in output UPM
- Latin scale/baseline do not affect global metrics

### OFL Metadata

- nameID 0 (Copyright): concatenate both sources' copyright + user addition
- nameID 3 (Unique Font Identifier): auto-built as `{version};{vendorID};{PostScript full name}`; vendorID is omitted when blank. Ensures OS font caches treat distinct versions/styles as separate entries so derivatives don't collide with their base font.
- nameID 5 (Version String): from `outputVersion` (default `1.000`); Python prepends `Version ` if not already present. Resets to the default whenever a font is loaded, so derivative fonts don't inherit the base font's version.
- nameID 6 (PostScript Name): from `outputPostScriptName` if set; otherwise derived from `outputFamilyName` by stripping characters outside printable ASCII 33-126 or in `[]{}<>()/%`, clamped to 63 bytes
- nameID 8 (Manufacturer): user-specified value; cleared if empty
- nameID 9 (Designer): user-specified value; cleared if empty
- nameID 10 (Description): "Based on {fonts}. Merged/Baked with OFL Font Baker."
- nameID 11 (Manufacturer URL): user-specified value; cleared if empty
- nameID 12 (Designer URL): user-specified value; cleared if empty
- nameID 13/14 (License): OFL 1.1 text + URL
- OS/2 `achVendID`: user-specified 4-char tag (right-padded with spaces); defaults to `"    "` (unknown vendor) when empty

## State Management (Zustand)

### Undo/Redo History

All operations are managed in a single timeline:

- **⌘Z**: undo, **⌘⇧Z**: redo
- Maximum 100 snapshots
- Tracked: font add/remove, sample text, metadata, slider values
- Excluded: hoveredRole, mergeProgress, isMerging
- Sliders: recorded on mouseup/touchend (not during drag)
- Text inputs (Family / Designer / Copyright / UPM / sample text): recorded on blur, not per keystroke
- Changing the Latin or base input font resets `outputWeight`, `outputWidth`, `outputUpm`, and `outputItalic` to their defaults (400 / 5 / 1000 / false)

### Persist

State persisted to localStorage:
- latinFont, baseFont
- sampleText
- outputFamilyName, outputPostScriptName, outputVersion, outputWeight, outputItalic, outputWidth
- outputDesigner, outputDesignerURL, outputManufacturer, outputManufacturerURL, outputVendorID, outputCopyright, outputUpm

## IPC Channels

Electron inter-process communication between renderer and main. The renderer cannot access the file system or native UI directly; IPC channels serve as the API.

| Channel | Direction | Purpose |
|---|---|---|
| `dialog:pick-font` | renderer → main | File selection dialog |
| `dialog:pick-output` | renderer → main | Directory selection dialog |
| `dialog:missing-font` | renderer → main | Missing font dialog |
| `font:read-file` | renderer → main | Read font file |
| `font:check-exists` | renderer → main | Check file existence |
| `merge:start` | renderer → main | Start merge |
| `merge:progress` | main → renderer | Progress notification (JSON line) |

## Tests

```bash
npm test                                                       # Standard tests (~3 min)
python3 -m pytest python/tests/test_merge.py -k LargeCID -v   # 65535-glyph test (~20 min)
```

| Category | Count | Verifies |
|---|---|---|
| Variable instantiation | 4 | wght bake, JP weight, fvar removal, default axes |
| Baseline offset | 3 | Simple shift, composite double-shift prevention, JP unaffected |
| Scale | 2 | Glyph size, advance width |
| UPM normalization | 3 | 2048→1000 conversion, OS/2 metrics |
| GPOS scaling | 3 | Kern scale, baseline unaffected, T+o pair kerning |
| Feature preservation | 8 | calt/case/frac/ss01, subordinate Latin removal, chaining remap |
| Metadata correctness | 12 | familyName, copyright concat, designer, OFL license, description |
| Metadata (base only) | 5 | familyName, OFL, copyright, designer, "Baked with" |
| Output weight | 4 | usWeightClass, nameID 2/4/17 |
| Glyph names | 2 | post format 2.0, alternate glyph names |
| Composite integrity | 2 | Reference completeness, hmtx completeness |
| CID Japanese font | 4 | CID-keyed CFF merge, Latin/JP outlines, hmtx |
| Metrics preservation | 10 | UPM, OS/2, hhea, scale/baseline unaffected |
| Hinting preservation | 9 | prep/gasp/maxp, instructions cleared on scale |
| Base-only merge | 2 | Merge without Latin, JP glyphs preserved |
| WOFF2 output | 2 | WOFF2 generation, base-only WOFF2 |
| Large CID font | 4 | 65535 glyphs, glyph count limit, cmap replacement, post format 3.0 |

## Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Start dev server |
| `npm run start` | Build + launch Electron |
| `npm run build` | Build JS/CSS |
| `npm test` | Run pytest tests |
| `npm run python:build` | Generate PyInstaller binary |
| `npm run pack` | Package app (unpacked) |
| `npm run dist` | Build arm64 dmg/zip (Apple Silicon) |

## Distribution Build (macOS)

OFL Font Baker ships **Apple Silicon (arm64) macOS only**. Intel Mac is not
supported: GitHub Actions retired the free `macos-13` Intel runners, and a
universal2 build doubled the Electron Framework inside one .app (~530MB vs
~105MB for arm64-only).

### Local builds

`npm run dist` builds the arm64 dmg/zip on the developer machine. PyInstaller
produces a native arm64 `merge_fonts` using whatever `python3` is on PATH, so
no special Python install is required.

### CI builds (GitHub Actions)

`.github/workflows/release.yml` runs on `macos-14` (arm64), installs Python via
`actions/setup-python`, runs `npm run dist`, and uploads the dmg/zip as an
artifact. Triggered by pushing a `v*` tag (or manually via `workflow_dispatch`);
a downstream `release` job collects the artifacts and creates a draft GitHub
Release.

### Bundle size optimizations

- `electronLanguages: ["en", "ja"]` — strips ~50 unused locale `.lproj` directories
- `compression: "maximum"` — slower build, smaller dmg/zip
- `asar: true` — packs renderer/main JS into a single archive

## Dependencies

### Node.js
- `electron` — Desktop app framework
- `react`, `react-dom` — UI
- `zustand` — State management (persist middleware)
- `opentype.js` — Font parsing (metadata extraction)
- `harfbuzzjs` — HarfBuzz WASM (text shaping)
- `tailwindcss`, `@tailwindcss/vite` — Styling
- `@radix-ui/react-dialog` — Modal dialogs
- `electron-builder` — Distribution packaging

### Python
- `fonttools` (>= 4.47.0) — Font parsing, editing, instancer
- `brotli` — WOFF2 compression
- `pyinstaller` — Binary generation (for distribution)
- `pytest` — Testing
