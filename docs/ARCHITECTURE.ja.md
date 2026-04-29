# OFL Font Baker ― アーキテクチャ

## アーキテクチャ

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
            │    ├─ font:check-exists (起動時パス検証)           │
            │    ├─ dialog:missing-font (欠落ダイアログ)        │
            │    ├─ overwrite confirm (上書き確認)              │
            │    │                                             │
            │    ▼                                             │
            │  merge-engine.ts                                 │
            │    │  バイナリ or python3 spawn                    │
            │    ▼                                             │
            │  merge_fonts (binary or .py)                     │
            │    │                                             │
            │    ▼                                             │
            │  出力フォルダ:                                     │
            │    ├─ {Family}-{Style}.otf                       │
            │    ├─ {Family}-{Style}.woff2                     │
            │    ├─ OFL.txt                                    │
            │    └─ settings.txt                               │
            └──────────────────────────────────────────────────┘
```

## データフロー

### 1. フォント読み込み

```
ユーザーが D&D またはクリック
  → webUtils.getPathForFile() でネイティブパス取得
  → IPC "font:read-file" で ArrayBuffer 取得
  → opentype.js でパース
  → preferredFamily (nameID 16) 優先でファミリー名取得
  → preferredSubfamily (nameID 17) + usWeightClass + usWidthClass でスタイル名構築
  → copyright, designer, license をキャッシュ (モーダル即時表示用)
  → FontSource として Zustand ストアに保存 + ヒストリー記録
```

### 2. 起動時のフォント検証

```
persist から復元後:
  → 各フォントのパスを IPC "font:check-exists" で確認
  → 見つからない場合: ネイティブダイアログ "Select Font" / "Clear"
  → フォントがある方を自動で selectedRole に設定
```

### 3. プレビュー (HarfBuzz WASM)

```
FontSource が更新されるたびに:
  → harfbuzzjs で HB blob/face/font を生成
  → テキストを Latin/CJK ランに分割 (splitRuns — Latin フォントの cmap ベース)
  → 各ランを対応するフォントで shaping
  → フォントがないラン → 読み込み済みフォントで shaping → .notdef (tofu) を描画
  → shaping 結果をキャッシュ → Canvas 2D で Path2D 描画
  → 行折返し + 禁則処理 (kinsoku)
  → カードホバー時にグリフをハイライト
```

### 4. マージ (Export)

```
useMerge.startMerge()
  → ディレクトリ選択ダイアログ
  → 上書き確認ダイアログ (既存フォルダの場合)
  → IPC "merge:start" で MergeConfig を送信
  → merge_fonts.py が処理:
      1. Variable Font instantiate (axis 値 bake)
      2. 日本語フォントをクローン
      3. CID-keyed CFF: >60000 glyphs は TT 変換スキップ、CFF のまま
      4. cmap ベースのグリフ置換 (Latin→merged glyph name マッピング)
      5. CFF-to-CFF: TransformPen で再描画 (スケール + Private dict 再バインド)
      6. GSUB/GPOS マージ (CID フォントは Latin features スキップ)
      7. OFL メタデータ設定 (copyright, license, description)
      8. mac_roman 非エンコード可能 name レコード除去
      9. post format 3.0 (>32767 glyphs)
      10. OTF 書き出し + WOFF2 書き出し
      11. OFL.txt + Settings.txt を生成
  → Main process: JSON manifest を受け取る (fontPath, woff2Path, oflPath, settingsPath)
```

## フォントマージエンジン (merge_fonts.py)

### cmap ベースのグリフ置換

1. Latin cmap と merged cmap から `lat_to_merged_name` マッピングを構築
2. Latin `A` (U+0041) → merged `cid00033` (U+0041) のように既存スロットを上書き
3. グリフ数が増えない → 65535 上限に抵触しない
4. 本当に新規のグリフのみ budget でカウント

### グリフコピー戦略

| ソース → ターゲット | 方式 |
|---|---|
| CFF → TrueType | `TransformPen` → `Cu2QuPen` → `TTGlyphPen` |
| TrueType → TrueType | `copy_glyph_tt` (composite 依存解決) |
| CFF → CFF | T2 CharString のプログラムを走査してオペランドをアフィン変換。`hstem`/`vstem`/`hintmask` などのヒント命令を保持したまま Private dict（`BlueValues`, `StdHW`/`StdVW`, `StemSnap*`）も同じ変換でコピー |
| TrueType → CFF | `TransformPen` → `ReverseContourPen` → `T2CharStringPen` |

出力書式は**常にベースフォントの書式に追従する** — ベースが TT なら TTF、CFF なら OTF。TT↔CFF のラウンドトリップは CFF ヒントの喪失(CFF→TT)か cu2qu によるアンカーポイント増加(TT→CFF)を招くため避ける。WOFF2 はラッパーなので自動的にベース書式を継承する。

TT→CFF グリフコピー時は `ReverseContourPen` を必ず挟む。TT は外周 CW/内穴 CCW、CFF は外周 CCW/内穴 CW と winding 規約が逆で、反転せずに描画すると non-zero fill で fill と穴が入れ替わり、Illustrator の縮小表示で交差部が白抜けに見える。

CFF のヒント保持: ヒント命令と Private dict（ブルーゾーン・ステム幅）はアウトラインと同じアフィン変換で再計算するので、マージ後もヒントがグリフ位置と整合する。

### 統合 UPM / スケール / ベースライン変換

`outputUpm`（UI で編集可能、デフォルト 1000）は JP 側のマージに対する単一
アフィン変換を駆動する。`jp_upm_ratio = outputUpm / jp_source_upm` を
`jp_scale_eff` / `jp_baseline_eff` に畳み込むことで、既存の JP 変換ブロックが
アウトライン・hmtx・CFF Private dict の blues/stems・(TT の)composite を
一度で処理する（二重丸めなし）。Latin は `final_lat_scale = lat_scale *
(outputUpm / lat_upm)` で直接 `outputUpm` にスケールする。

グリフ変換後、JP 由来のメトリクス（OS/2 sTypo*/usWin*/sxHeight/sCapHeight、
hhea ascent/descent/lineGap、post underline、head bbox）と JP GPOS ルックアップを
`jp_upm_ratio` で再スケールし、`head.unitsPerEm` を `outputUpm` に設定する。
その後 `reconcile_tables` は既にスケール済みの JP 値を参照するので、Latin との
エンベロープ比較は出力 UPM 単位で行われる。

### 欧文ペアカーニングの保持

Pan-CJK 書体（Noto Sans JP など）は Latin グリフを内蔵し、Latin 同士の
ペアカーニングまで定義していることが多い。cmap ベースのグリフ置換で
Latin 側のアウトラインに差し替えたあとも、JP 側の `kern` ルックアップは
同じグリフ名を参照し続けるため、Latin と JP 両方の PairPos が同時に発火し
`T+o` / `T+y` のような Latin ペアでカーニング値が積算されてしまう
（"Tokyo" や "Type" の T が極端に詰まる症状）。

`_strip_latin_first_from_pairpos` は JP ルックアップの分類後に走り、
JP 側 PairPos サブテーブルの先頭グリフ `Coverage`（および `ClassDef1`）
から Latin グリフを除去する。これにより Latin 始まりのペアでは JP の
PairPos が発火せず、Latin フォント側のカーニング値だけが反映される。
JP 始まりのクロススクリプト（CJK 約物 → Latin 文字など）は保持される。

これは後続グリフが JP フォントにしか無い場合でも意図的である。先頭が
Latin で始まる merged slot は、すでに Latin フォントのアウトラインと
字幅モデルに置き換わっているため、JP 由来の Latin-first カーニングは
一部だけ残さず従属データとしてまとめて捨てる。

### 欧文リガチャの保持

Pan-CJK ベース書体は `dlig` / `liga` の lookup に Latin 入力のリガチャ
を JP 専用リガチャと一緒に詰め込んでいることが多く、その出力が CJK 互換
の単位記号 — 例えば `n+s → ㎱` (U+33B1)、`S+v → ㎜`、`A+m → ㏟` —
になる。入力集合に Latin と非 Latin の両方が含まれるため
`_classify_lookup` は `mixed` と判定し、lookup は merge を生き残る。
Illustrator / InDesign で「任意の合字」(`dlig`) を ON にすると、
普通の Latin テキストにベース側の規則が発火して "Sans" が "Sa㎱" に化ける。

`_strip_latin_only_ligatures` は GSUB 側の `_strip_latin_first_from_pairpos`
相当の処理。生き残った JP-side lookup の Type 4 LigatureSubst サブテーブル
を歩き、先頭入力と Component グリフが **すべて** Latin フォントに含まれる
リガチャエントリを削除する。クロススクリプトのエントリ（入力鎖のどこかに
CJK グリフが含まれるもの）は保持されるので、JP 側の正規リガチャは生き残る。

### `ccmp` の重複タグ排除

kern を `latn` 配下で壊していた shadowing パターン（HarfBuzz は重複タグの
最初のレコードしか発火させない）は、GSUB 側の `ccmp` でも同じように起きる。
Pan-CJK 書体は独自の `ccmp` を `latn` 配下に持つので、マージ後の LangSys
には `ccmp` が 2 本ぶら下がり、HB は JP 側だけ走らせる。Latin フォントの
case-sensitive 結合マーク規則（`gravecomb → gravecomb.case` 等）が発火
しなくなり、`M̀` / `Ê̄` は大文字に対する `.case` フォームを失う。

`GSUB_LATN_DEDUPE_TAGS` は GPOS と同じ dedupe ルールを明示的 Latin script
で適用する GSUB タグの一覧。検証済みメンバー: `ccmp`。それ以外の GSUB
共有タグ（`aalt`, `liga`, `dlig` 等）は従来通り両方残す — JP 側の `aalt`
は CJK glyph 用に `latn` から到達可能である必要がある (Issue #2 #6)、
リガチャは `_strip_latin_only_ligatures` のエントリ単位の除去で対処済み。

### メトリクス

- `head.unitsPerEm` = `outputUpm`（ユーザー設定、デフォルト 1000）
- OS/2, hhea のアセンダー/ディセンダーは両フォントのエンベロープ（出力 UPM 単位）
- Latin のスケール/ベースラインはグローバルメトリクスに影響しない

### OFL メタデータ

- nameID 0 (Copyright): 両ソースの copyright を結合 + ユーザー追加
- nameID 7 (Trademark): 両ソースの trademark を結合 + ユーザー追加。3 つとも空のときだけレコードを残さない
- nameID 3 (Unique Font Identifier): `{version};{PostScript フルネーム}` を自動生成。派生フォントがベースフォントと同じ UniqueID を持たないようにして、OS のフォントキャッシュが別物として扱えるようにする。
- nameID 5 (Version String): `outputVersion`（デフォルト `1.000`）を使用。Python 側で `Version ` 接頭辞が無ければ自動で付与する。派生フォントがベースフォントのバージョンを引き継がないよう、フォントを読み込むたびにデフォルトへリセットされる。
- nameID 6 (PostScript Name): `outputPostScriptName` が設定されていればそれを使用、未設定なら `outputFamilyName` から printable ASCII 33-126 外 + `[]{}<>()/%` を除去したものを 63 バイトで打ち切って使用
- nameID 8 (Manufacturer): ユーザー設定値、空の場合はクリア
- nameID 9 (Designer): 常にクリア。元書体のデザイナーは nameID 10 の "by <source designer>" で明記する
- nameID 10 (Description): "Based on {fonts}. Built with OFL Font Baker."
- nameID 11 (Manufacturer URL): ユーザー設定値、空の場合はクリア
- nameID 12 (Designer URL): 常にクリア
- nameID 13/14 (License): OFL 1.1 テキスト + URL
- OS/2 `achVendID`: 常に半角スペース 4 つ（ベンダー不明）に固定。派生フォントがベースフォントの登録ベンダータグを引き継がないようにする。
- CFF TopDict `FullName` / `FamilyName` / `Notice`: nameID 4 / 1 / 0 と同じ値をセット。PDF 埋め込みや Adobe 系ツールが CFF を直接読む際にベースフォント名が残らないようにする。
- OS/2 `achVendID`: ユーザー設定の 4 文字タグ（短い場合は空白で右詰め）、空の場合は `"    "`（ベンダー不明）をセット

## 状態管理 (Zustand)

### Undo/Redo ヒストリー

全ての操作を単一タイムラインで管理:

- **⌘Z**: undo、**⌘⇧Z**: redo
- 最大 100 スナップショット
- 対象: フォント追加/削除、サンプルテキスト、メタデータ、スライダー値
- 除外: hoveredRole, mergeProgress, isMerging
- スライダー: mouseup/touchend 時に記録 (ドラッグ中は記録しない)
- テキスト入力（Family / Designer / Copyright / UPM / サンプルテキスト）: blur 時に記録（1 文字ごとには記録しない）
- Latin / Base の入力フォントを差し替えると `outputWeight` / `outputWidth` / `outputUpm` / `outputItalic` がデフォルト値（400 / 5 / 1000 / false）に戻る

### Persist

localStorage に永続化される状態:
- latinFont, baseFont
- sampleText
- outputFamilyName, outputPostScriptName, outputVersion, outputWeight, outputItalic, outputWidth
- outputManufacturer, outputManufacturerURL, outputCopyright, outputTrademark, outputUpm

## IPC チャンネル

Electron の renderer ↔ main プロセス間通信。renderer からファイルシステムやネイティブ UI にアクセスするための API。

| チャンネル | 方向 | 用途 |
|---|---|---|
| `dialog:pick-font` | renderer → main | ファイル選択ダイアログ |
| `dialog:pick-output` | renderer → main | ディレクトリ選択ダイアログ |
| `dialog:missing-font` | renderer → main | 欠落フォントダイアログ |
| `font:read-file` | renderer → main | フォントファイル読み込み |
| `font:check-exists` | renderer → main | ファイル存在確認 |
| `merge:start` | renderer → main | マージ実行 |
| `merge:progress` | main → renderer | 進捗通知 (JSON line) |

## テスト

```bash
npm test                                                # フル pytest スイート (~18分)
python3 -m pytest python/tests/ -k LargeCID -v         # 65535 グリフ CID テストのみ (~10分)
```

テストコードは `python/tests/` 以下の 4 ファイルに分かれています：

- `test_filter_subordinate_lookups.py` — `_reindex_table` /
  `_remap_lookup_references` / `_collect_lookup_glyphs` /
  `_rename_glyphs_in_ot_table` の helper-level カバレッジ
  (Issue #2 関連の helpers)
- `test_metadata.py` — name table、OFL テキスト、PostScript Name、
  Version / Manufacturer / Trademark、UINameID 衝突、Character
  Variant ラベル
- `test_glyph_data.py` — アウトライン、メトリクス、ヒント、GSUB/GPOS
  feature 保持、CFF hint / coincidence / FontBBox
- `test_pipeline.py` — CID Japanese、base-only、WOFF2、パッケージング、
  output dir、large-CID ストレステスト

| カテゴリ | テスト数 | 検証内容 |
|---|---|---|
| Filter subordinate lookups | 7 | helper-level: ScriptList & cross-lookup remap、Format 1 rule rename、Type 5 F3 collector |
| Variable instantiation | 4 | wght bake、JP weight、fvar 除去、デフォルト axes |
| Baseline offset | 4 | simple シフト、Latin & JP composite 二重シフト防止、JP 非影響 |
| Scale | 2 | グリフサイズ、advance width |
| UPM normalization | 3 | 2048→1000 変換、OS/2 metrics |
| Output UPM | 5 | hmtx / glyph / OS/2 への UPM スケーリング、base-only |
| GPOS scaling | 3 | kern scale、baseline 非影響、T+o ペアカーニング保持 |
| 欧文 kern 保持 | 60 | 32 ペア（UC-UC, UC-lc, lc-UC, lc-lc, 記号, 数字）+ 27 字幅 + JP PairPos の Latin 先頭除去確認 |
| 欧文 ligature 保持 | 27 | dlig で 12 系列（n+s/S+v/A+m の単位記号トラップ含む）+ 12 系列が Latin 単体と一致 + JP LigatureSubst の Latin-only 除去 + ccmp shape 一致（M̀ / Ê̄ 等）+ latn 配下 ccmp 1 本の構造確認 |
| Feature preservation | 9 | calt / case / frac / ss01 / liga、従属欧文除去、chaining リマップ |
| Same-tag features | 1 | Latin LangSys から JP 側 `aalt` への到達性 |
| Glyph names | 2 | post format 2.0、代替グリフ名 |
| Composite integrity | 2 | 参照完全性、hmtx 完全性 |
| Metrics preservation | 10 | UPM、OS/2、hhea、scale/baseline 非影響 |
| TT hinting preservation | 7 | prep / gasp / maxp、instructions クリア (scale 時) |
| Maxp recalc | 1 | merge 後の maxp サブフィールド再計算 |
| CFF hint preservation | 8 | hstem / vstem / BlueValues 保持 (CFF→CFF)、TopDict と nameID の整合 |
| CFF coincidence snap | 3 | スケール経由でも一致頂点を保持 |
| CFF FontBBox | 1 | TopDict.FontBBox が全 CharStrings を包含 |
| Latin cmap variant collision | 3 | 異なる cmap-target variant の生存 |
| Shared glyph collateral | 4 | U+2027 / U+30FB middle-dot の重複処理 |
| PostScript name (sanitize / validate) | 17 | nameID 6 のサニタイズ / バリデーション helper unit テスト |
| Metadata correctness | 39 | familyName / copyright / version / Manufacturer / Trademark / nameID hygiene |
| Metadata (base only) | 5 | familyName、OFL、copyright、designer、"Built with" |
| Output weight | 4 | usWeightClass、nameID 2 / 4 / 17 |
| UINameID collision | 1 | Inter `ss02` UINameID 257 と NotoSansJP nameID 257 の remap |
| Character variant labels | 2 | Charis `cv13` ラベル保持（sub / base 両方）|
| Build OFL text | 4 | source copyright 結合、ユーザー追記、フォールバック |
| Build settings text | 3 | サマリ行、sources 行、寸法 |
| CID Japanese font | 4 | CID-keyed CFF マージ、Latin / JP アウトライン、hmtx |
| ChainContext ClassDef rename | 1 | Inter Variable + Shippori `i.numr` no-crash |
| Base-only merge | 2 | Latin なしマージ、JP グリフ保持 |
| WOFF2 output | 2 | WOFF2 生成、base-only WOFF2 |
| Large CID font | 4 | 65535 グリフ、グリフ数制限、cmap 置換、post format 3.0 |
| Helpers (sfnt / style / outdir) | 8 | `detect_sfnt_ext`、`compute_style_name`、`prepare_output_dir` |
| Package output | 12 | manifest、font / woff2 / ofl / settings、overwrite、options |

`TestLatinKernPreservation` はコミット済み fixture
`python/tests/fonts/TikTok_Sans/static/TikTokSans-Regular.ttf` を前提にする。
このテストは上記の設計判断、すなわち「先頭グリフが Latin なら JP 由来の
PairPos は保持しない」ことも固定化している。

## コマンド

| コマンド | 用途 |
|---|---|
| `npm run dev` | 開発サーバー起動 |
| `npm run start` | ビルド + Electron 起動 |
| `npm run build` | JS/CSS ビルド |
| `npm test` | pytest テスト実行 |
| `npm run python:build` | PyInstaller バイナリ生成 |
| `npm run pack` | アプリパッケージ (unpacked) |
| `npm run dist` | arm64 dmg/zip 作成 (Apple Silicon) |

## 配布ビルド (macOS)

OFL Font Baker は **Apple Silicon (arm64) macOS のみ**を配布対象としています。
Intel Mac はサポートしていません。GitHub Actions の無料枠から `macos-13` Intel
runner が退役したことと、universal2 ビルドでは Electron Framework が .app 内で
二重化され ~530MB に膨らむのに対し arm64 単体は ~105MB で済むことが理由です。

### ローカルビルド

`npm run dist` で arm64 の dmg/zip を生成します。PyInstaller は PATH 上の
`python3` をそのまま使い、ネイティブ arm64 の `merge_fonts` を生成するので、
特別な Python のインストールは不要です。

### CI ビルド (GitHub Actions)

`.github/workflows/release.yml` は `macos-14` (arm64) で動作し、`actions/setup-python`
で Python をセットアップしてから `npm run dist` を実行、dmg/zip をアーティファクト
としてアップロードします。`v*` タグの push(または `workflow_dispatch` での手動
実行)でトリガーされ、後続の `release` ジョブがアーティファクトを集めて GitHub
Release のドラフトを作成します。

### バンドルサイズ最適化

- `electronLanguages: ["en", "ja"]` — 不要な ~50 言語の `.lproj` を除外
- `compression: "maximum"` — ビルドは遅くなるが dmg/zip が小さくなる
- `asar: true` — renderer/main の JS を 1つのアーカイブにパック

## 依存関係

### Node.js
- `electron` — デスクトップアプリフレームワーク
- `react`, `react-dom` — UI
- `zustand` — 状態管理 (persist middleware)
- `opentype.js` — フォント解析 (メタデータ取得)
- `harfbuzzjs` — HarfBuzz WASM (テキスト shaping)
- `tailwindcss`, `@tailwindcss/vite` — スタイリング
- `@radix-ui/react-dialog` — モーダルダイアログ
- `electron-builder` — 配布パッケージ作成

### Python
- `fonttools` (>= 4.47.0) — フォント解析・編集・instancer
- `brotli` — WOFF2 圧縮
- `pyinstaller` — バイナリ生成（配布用）
- `pytest` — テスト
