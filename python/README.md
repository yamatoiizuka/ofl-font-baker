# Font Merge Engine

<p>English | <strong><a href="https://github.com/yamatoiizuka/ofl-font-baker/blob/main/python/README.ja.md">日本語</a></strong></p>

The core font merge engine behind [OFL Font Baker](https://github.com/yamatoiizuka/ofl-font-baker).
The code in this directory is MIT-licensed and can be freely used in other projects.

Merges a base font (typically CJK) with a sub font (typically Latin or kana) into a single font file, replacing glyphs and OpenType features via cmap-based mapping.

For details on features and background, see the [OFL Font Baker repository](https://github.com/yamatoiizuka/ofl-font-baker).

## OFL Fonts Only

This library only accepts fonts licensed under the [SIL Open Font License (OFL)](https://openfontlicense.org). If an input font's `name` table (nameID 13) does not contain an OFL license string, loading fails with an error.

Merged output is automatically tagged with OFL-compliant copyright and license metadata.

## Installation

```bash
pip install ofl-font-baker
```

Requires Python 3.9+. [fonttools](https://github.com/fonttools/fonttools) and [brotli](https://github.com/google/brotli) are installed automatically.

## Usage

Provide a JSON config on stdin. The engine supports two modes:

```bash
cat config.json | python3 merge_fonts.py
```

### Path Mode

Specify output file paths explicitly via `export.path`. Only the files whose paths are provided are written.

```json
{
  "baseFont": {
    "path": "/path/to/base.otf",
    "scale": 1.0,
    "baselineOffset": 0,
    "axes": []
  },
  "subFont": {
    "path": "/path/to/sub.ttf",
    "scale": 1.0,
    "baselineOffset": 0,
    "axes": []
  },
  "output": {
    "familyName": "My Font",
    "weight": 400,
    "italic": false,
    "width": 5
  },
  "export": {
    "path": {
      "font": "/out/MyFont-Regular.otf",
      "woff2": "/web/MyFont-Regular.woff2"
    }
  }
}
```

### Package Mode

Specify `export.package` to create a complete output directory with font files and metadata.

```json
{
  "baseFont": { "path": "/path/to/base.otf", "scale": 1.0, "baselineOffset": 0, "axes": [] },
  "subFont": { "path": "/path/to/sub.ttf", "scale": 1.0, "baselineOffset": 0, "axes": [] },
  "output": { "familyName": "My Font" },
  "export": {
    "package": {
      "dir": "/exports/MyFont-Regular"
    }
  }
}
```

Output (JSON manifest on stdout):

```json
{
  "outputDir": "/exports/MyFont-Regular",
  "fontPath": "/exports/MyFont-Regular/MyFont-Regular.otf",
  "woff2Path": "/exports/MyFont-Regular/MyFont-Regular.woff2",
  "oflPath": "/exports/MyFont-Regular/OFL.txt",
  "settingsPath": "/exports/MyFont-Regular/Settings.txt",
  "configPath": null,
  "files": [...]
}
```

Progress is emitted as JSON lines on stderr.

### `output`

| Key               | Default     | Description                                                                                                                                                                           |
| ----------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `familyName`      | `"Font"`    | Output font family name.                                                                                                                                                              |
| `postScriptName`  | `""`        | PostScript name (nameID 6). When empty, derived from `familyName` by stripping chars outside printable ASCII 33–126 and `[]{}<>()/%`, clamped to 63 bytes.                            |
| `version`         | `"1.000"`   | Version string (nameID 5). A `Version ` prefix is prepended automatically if missing.                                                                                                 |
| `weight`          | `400`       | Font weight (100–900).                                                                                                                                                                |
| `italic`          | `false`     | Whether the output is italic.                                                                                                                                                         |
| `width`           | `5`         | Font width class (1–9).                                                                                                                                                               |
| `upm`             | (from base) | Target units-per-em. When different from the base font, all metrics and outlines are scaled.                                                                                          |
| `manufacturer`    | `""`        | Manufacturer name (nameID 8).                                                                                                                                                         |
| `manufacturerURL` | `""`        | Manufacturer URL (nameID 11).                                                                                                                                                         |
| `copyright`       | `""`        | Additional copyright string appended to source copyrights.                                                                                                                            |
| `trademark`       | `""`        | Additional trademark string appended to source trademarks.                                                                                                                            |
| `metricsSource`   | `"base"`    | Which font's vertical metrics (OS/2, hhea) to use. `"base"` keeps the base font metrics and expands only when the sub font is larger. `"sub"` overwrites with the sub font's metrics. |

### `export.path`

All keys are optional. Only files whose paths are specified are written. `woff2` requires `font`.

| Key        | Description               |
| ---------- | ------------------------- |
| `font`     | Font file (OTF/TTF) path. |
| `woff2`    | WOFF2 file path.          |
| `ofl`      | OFL.txt path.             |
| `settings` | Settings.txt path.        |
| `config`   | ExportConfig.json path.   |

### `export.package`

Creates a complete output directory. Always generates font, WOFF2, OFL.txt, and Settings.txt.

| Key                | Default | Description                                                                                                                                          |
| ------------------ | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dir`              |         | Output directory path (required).                                                                                                                    |
| `overwrite`        | `false` | Allow overwriting an existing directory.                                                                                                             |
| `bundleInputFonts` | `false` | Copy input fonts into a `source/` subdirectory and write `ExportConfig.json` with relative paths. Makes the package self-contained and reproducible. |

## Tests

```bash
python3 -m pytest python/tests/test_merge.py -v
```

Test fonts are in `testdata/fonts/` (repository root).

## License

The source code in this directory is licensed under the MIT License. See [LICENSE](LICENSE) for details.

Other parts of the parent repository ([OFL Font Baker](https://github.com/yamatoiizuka/ofl-font-baker)) are licensed under AGPL-3.0-or-later and are not covered by this MIT notice.
