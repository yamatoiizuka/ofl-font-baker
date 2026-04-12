# Font Merge Engine

<p>English | <strong><a href="README.ja.md">日本語</a></strong></p>

Python-based font merge engine that powers OFL Font Baker.

Merges a Latin font with a Japanese (CJK) base font into a single font file, replacing glyphs and OpenType features via cmap-based mapping.

## Requirements

- Python 3.9+
- [fonttools](https://github.com/fonttools/fonttools) >= 4.47.0
- [brotli](https://github.com/google/brotli) >= 1.1.0

```bash
pip install -r requirements.txt
```

## Usage

Provide a JSON config on stdin. The engine runs in **export mode** when `outputDir` is present, producing a full export directory with font files and metadata.

```bash
cat config.json | python3 merge_fonts.py
```

### Export mode

Input:

```json
{
  "base": {
    "path": "/path/to/base.otf",
    "scale": 1.0,
    "baselineOffset": 0,
    "axes": []
  },
  "latin": {
    "path": "/path/to/latin.ttf",
    "scale": 1.0,
    "baselineOffset": 0,
    "axes": []
  },
  "outputDir": "/exports",
  "outputFolderName": "MyFont-Regular",
  "overwrite": false,
  "outputFamilyName": "My Font",
  "outputWeight": 400,
  "outputItalic": false,
  "outputWidth": 5,
  "outputOptions": {
    "includeWoff2": true,
    "writeConfigJson": false,
    "bundleInputFonts": false
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

### outputOptions

| Key | Default | Description |
|-----|---------|-------------|
| `includeWoff2` | `true` | Generate a WOFF2 file alongside the main font. |
| `writeConfigJson` | `false` | Write an `ExportConfig.json` that records the merge settings. |
| `bundleInputFonts` | `false` | Copy the input fonts into a `source/` subdirectory and rewrite paths in `ExportConfig.json` to relative paths (e.g. `./source/Base.otf`). Automatically enables `writeConfigJson`. This makes the export directory self-contained and reproducible. |

## Tests

```bash
python3 -m pytest python/tests/test_merge.py -v
```

Test fonts are in `tests/fonts/`.

## License

Unless otherwise noted, the source code in this directory is licensed under the MIT License. See [LICENSE](LICENSE) for details.

Test fonts and other third-party assets under `tests/fonts/` are licensed separately under their respective licenses.

Other parts of the parent repository are licensed under AGPL-3.0-or-later and are not covered by this MIT notice unless explicitly stated.
