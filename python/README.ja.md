# Font Merge Engine

<p><strong><a href="https://github.com/yamatoiizuka/ofl-font-baker/blob/main/python/README.md">English</a></strong> | 日本語</p>

[OFL Font Baker](https://github.com/yamatoiizuka/ofl-font-baker) のコア機能にあたる、Python ベースのフォントマージエンジンです。
このディレクトリ内のコードは MIT ライセンスとなっており、他のプロジェクトでも自由に活用いただけます。

ベースフォント（CJK 書体を想定）とサブフォント（欧文・かな書体を想定）を cmap ベースのマッピングで統合し、グリフと OpenType フィーチャーを置換して単一のフォントファイルを生成します。

機能の詳細や背景については [OFL Font Baker のリポジトリ](https://github.com/yamatoiizuka/ofl-font-baker) を参照してください。

## OFL Fonts Only

このライブラリは [SIL Open Font License (OFL)](https://openfontlicense.org) でライセンスされたフォントのみを受け付けます。入力フォントの `name` テーブル (nameID 13) にライセンス文字列が含まれていない場合はエラーになります。

マージ結果は OFL に準拠するよう、著作権表示とライセンス情報が自動的に設定されます。

## Installation

```bash
pip install ofl-font-baker
```

Python 3.9 以上が必要です。[fonttools](https://github.com/fonttools/fonttools) と [brotli](https://github.com/google/brotli) が自動的にインストールされます。

## Usage

JSON 設定を stdin に渡します。エンジンは 2 つのモードをサポートしています。

```bash
cat config.json | python3 merge_fonts.py
```

### Path Mode

`export.path` で出力ファイルパスを明示的に指定します。パスが指定されたファイルのみ書き出されます。

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
    "axes": [],
    "excludeCodepoints": ["U+2460-U+24FF", "U+203B"]
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

`export.package` を指定すると、フォントファイルとメタデータを含む出力ディレクトリを生成します。

```json
{
  "baseFont": { "path": "/path/to/base.otf", "scale": 1.0, "baselineOffset": 0, "axes": [] },
  "subFont": { "path": "/path/to/sub.ttf", "scale": 1.0, "baselineOffset": 0, "axes": [], "excludeCodepoints": [] },
  "output": { "familyName": "My Font" },
  "export": {
    "package": {
      "dir": "/exports/MyFont-Regular"
    }
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

### `baseFont` / `subFont`

| Key                 | デフォルト | 説明 |
| ------------------- | ---------- | ---- |
| `path`              |            | フォントファイルのパス（必須）。 |
| `scale`             | `1.0`      | アウトラインのスケール倍率。 |
| `baselineOffset`    | `0`        | フォントユニット単位のベースラインオフセット。 |
| `axes`              | `[]`       | Variable Font の軸値: `[{"tag": "wght", "currentValue": 400}, ...]`。Static フォントでは空。 |
| `excludeCodepoints` | `[]`       | **subFont 専用。** `baseFont` 由来の字形を残したい codepoint のリスト。各エントリは `"U+XXXX"`、`"U+XXXX-U+YYYY"`（閉区間）、または整数。Latin + CJK マージで `①` `◯` `※` `Ⅰ` `℃` のような記号・囲み文字を CJK 慣習の字形のまま残したいときに使う。`baseFont` 側に書かれた場合は無視される。 |

sub フォントが、base フォントが**別の codepoint で**使っているグリフ名を保持している場合（例: Inter は `U+0298 ʘ` を `uni25CE` として持っているが、Noto Sans JP は `uni25CE` を `U+25CE ◎` に使っている）、マージエンジンは sub 側のグリフを `{元のグリフ名}.sub` にリネームし、孤立する base 側 codepoint の字形を保護する。リネームのたび stderr に警告が出力される。同じグリフ名でも codepoint 集合がずれていれば両者は別グリフ、という前提で無条件に行う。

### `output`

| Key               | デフォルト   | 説明                                                                                                                                                                            |
| ----------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `familyName`      | `"Font"`     | 出力フォントのファミリー名。                                                                                                                                                    |
| `postScriptName`  | `""`         | PostScript 名（nameID 6）。空のとき `familyName` から派生（printable ASCII 33–126 外と `[]{}<>()/%` を除去、63 byte clamp）。                                                   |
| `version`         | `"1.000"`    | Version String（nameID 5）。`Version ` プレフィクスがなければ自動付与される。                                                                                                   |
| `weight`          | `400`        | フォントウェイト（100–900）。                                                                                                                                                   |
| `italic`          | `false`      | 出力がイタリックかどうか。                                                                                                                                                      |
| `width`           | `5`          | フォント幅クラス（1–9）。                                                                                                                                                       |
| `upm`             | (ベースから) | ターゲット units-per-em。ベースフォントと異なる場合、すべてのメトリクスとアウトラインがスケーリングされる。                                                                     |
| `manufacturer`    | `""`         | Manufacturer 名（nameID 8）。                                                                                                                                                   |
| `manufacturerURL` | `""`         | Manufacturer URL（nameID 11）。                                                                                                                                                 |
| `copyright`       | `""`         | ソースのコピーライトに追加されるコピーライト文字列。                                                                                                                            |
| `trademark`       | `""`         | ソースの商標に追加される商標文字列。                                                                                                                                            |
| `metricsSource`   | `"base"`     | 垂直メトリクス（OS/2, hhea）の参照元。`"base"` はベースフォントのメトリクスを維持し、サブフォントの方が大きい場合のみ拡張する。`"sub"` はサブフォントのメトリクスで上書きする。 |
| `metadataMode`    | `"merge"`    | 識別レコードのポリシー。`"merge"`（`null` または未指定も同義）は name / OS/2 / head の識別レコードを派生著作物として書き直す（現行のデフォルト）。`"inheritBase"` は base フォントの識別をそのまま流用、`"inheritSub"` は sub フォントの識別を流用する（`subFont` がなければエラー）。`output.*` で明示的に指定したフィールドだけが継承元を上書きし、OFL nameID 13/14・designer・vendor ID・`head.created/modified` などは触らない。中間生成物や、新しい派生として再宣言したくないマージ（例：`Noto Hentaigana` のグリフを `Noto Sans JP` に取り込みたい場合）に有用。 |
| `hinting`         | `"strip"`    | TrueType 出力のヒンティング方針。`"strip"`（`"unhinted"` / `"none"` も同義）は TT bytecode、`fpgm`、`prep`、`cvt ` を削除し、unhinted outline として妥当な `maxp` に正規化する。`"ttfautohint"`（`"autohint"` も同義）は最終 TTF を一度 strip 状態で書き出した後、外部 `ttfautohint` バイナリを実行する。CFF 出力は別系統の CFF hint 保持処理を使う。 |

### `export.path`

全キーがオプション。パスが指定されたファイルのみ書き出される。`woff2` は `font` が必要。

| Key        | 説明                                |
| ---------- | ----------------------------------- |
| `font`     | フォントファイル（OTF/TTF）のパス。 |
| `woff2`    | WOFF2 ファイルのパス。              |
| `ofl`      | OFL.txt のパス。                    |
| `settings` | Settings.txt のパス。               |
| `config`   | ExportConfig.json のパス。          |

### `export.package`

出力ディレクトリを作成し、全アーティファクト（font, WOFF2, OFL.txt, Settings.txt）を生成する。

| Key                | デフォルト | 説明                                                                                                                                  |
| ------------------ | ---------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `dir`              |            | 出力ディレクトリのパス（必須）。                                                                                                      |
| `overwrite`        | `false`    | 既存ディレクトリの上書きを許可する。                                                                                                  |
| `bundleInputFonts` | `false`    | 入力フォントを `source/` サブディレクトリにコピーし、`ExportConfig.json` を相対パスで出力する。パッケージを自己完結・再現可能にする。 |

## Tests

```bash
python3 -m pytest python/tests/ -v
```

テスト用フォントは `python/tests/fonts/` にあります。

## License

このディレクトリ内のソースコードは MIT License の下で提供されています。詳細は [LICENSE](LICENSE) を参照してください。

`tests/fonts/` 配下のテスト用フォントは、それぞれのフォント自身のライセンス（OFL など）に従い、MIT 表記の対象外です。

親リポジトリ（[OFL Font Baker](https://github.com/yamatoiizuka/ofl-font-baker)）のその他の部分は AGPL-3.0-or-later でライセンスされており、この MIT 表記の対象外です。
