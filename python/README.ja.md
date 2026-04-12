# Font Merge Engine

<p><strong><a href="https://github.com/yamatoiizuka/font-baker/blob/main/python/README.md">English</a></strong> | 日本語</p>

[OFL Font Baker](https://github.com/yamatoiizuka/font-baker) のコア機能にあたる、Python ベースのフォントマージエンジンです。
このディレクトリ内のコードは MIT ライセンスとなっており、他のプロジェクトでも自由に活用いただけます。

ベースフォント（CJK 書体を想定）とサブフォント（欧文・かな書体を想定）を cmap ベースのマッピングで統合し、グリフと OpenType フィーチャーを置換して単一のフォントファイルを生成します。

機能の詳細や背景については [OFL Font Baker のリポジトリ](https://github.com/yamatoiizuka/font-baker) を参照してください。

## インストール

```bash
pip install font-baker
```

Python 3.9 以上が必要です。[fonttools](https://github.com/fonttools/fonttools) と [brotli](https://github.com/google/brotli) が自動的にインストールされます。

## Usage

JSON 設定を stdin に渡します。`outputDir` が指定されている場合は、フォントファイルとメタデータを含む出力ディレクトリを生成します。

```bash
cat config.json | python3 merge_fonts.py
```

### Export Mode

入力:

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

出力 (stdout に JSON マニフェスト):

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

進捗は stderr に JSON Lines で出力されます。

### outputOptions

| Key                | Default | 説明                                                                                                                                                                                                                                         |
| ------------------ | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `includeWoff2`     | `true`  | メインフォントに加えて WOFF2 ファイルを生成する。                                                                                                                                                                                            |
| `writeConfigJson`  | `false` | マージ設定を記録した `ExportConfig.json` を出力する。                                                                                                                                                                                        |
| `bundleInputFonts` | `false` | 入力フォントを `source/` サブディレクトリにコピーし、`ExportConfig.json` 内のパスを相対パス（例: `./source/Base.otf`）に書き換える。`writeConfigJson` は自動的に有効になる。出力ディレクトリだけで再現可能な自己完結型のエクスポートになる。 |

## Tests

```bash
python3 -m pytest python/tests/test_merge.py -v
```

テスト用フォントは `tests/fonts/` にあります。

## License

特に断りのない限り、このディレクトリ内のソースコードは MIT License の下で提供されています。詳細は [LICENSE](LICENSE) を参照してください。

`tests/fonts/` 配下のテスト用フォントおよびサードパーティの資産は、それぞれのライセンスに従います。

親リポジトリ（[OFL Font Baker](https://github.com/yamatoiizuka/font-baker)）のその他の部分は AGPL-3.0-or-later でライセンスされており、明示されない限りこの MIT 表記の対象外です。
