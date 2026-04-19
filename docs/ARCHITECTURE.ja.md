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
npm test                                                       # 標準テスト (~3分)
python3 -m pytest python/tests/test_merge.py -k LargeCID -v   # 65535 グリフテスト (~20分)
```

| カテゴリ | テスト数 | 検証内容 |
|---|---|---|
| Variable instantiation | 4 | wght bake、JP weight、fvar 除去、デフォルト axes |
| Baseline offset | 3 | simple シフト、composite 二重シフト防止、JP 非影響 |
| Scale | 2 | グリフサイズ、advance width |
| UPM normalization | 3 | 2048→1000 変換、OS/2 metrics |
| GPOS scaling | 3 | kern scale、baseline 非影響、T+o ペアカーニング保持 |
| Feature preservation | 8 | calt/case/frac/ss01、従属欧文除去、chaining リマップ |
| Metadata correctness | 12 | familyName、copyright 結合、designer、OFL license、description |
| Metadata (base only) | 5 | familyName、OFL、copyright、designer、"Built with" |
| Output weight | 4 | usWeightClass、nameID 2/4/17 |
| Glyph names | 2 | post format 2.0、代替グリフ名 |
| Composite integrity | 2 | 参照完全性、hmtx 完全性 |
| CID Japanese font | 4 | CID-keyed CFF マージ、Latin/JP アウトライン、hmtx |
| Metrics preservation | 10 | UPM、OS/2、hhea、scale/baseline 非影響 |
| Hinting preservation | 9 | prep/gasp/maxp、instructions クリア (scale 時) |
| Base-only merge | 2 | Latin なしマージ、JP グリフ保持 |
| WOFF2 output | 2 | WOFF2 生成、base-only WOFF2 |
| Large CID font | 4 | 65535 グリフ、グリフ数制限、cmap 置換、post format 3.0 |

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
