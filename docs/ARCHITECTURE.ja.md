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

### `subFont.excludeCodepoints`

呼び出し側が「この codepoint は `baseFont` を優先してほしい」と宣言する
ためのリスト。Latin + CJK マージで、`①` `◯` `※` `Ⅰ` `℃` などの
記号・囲み文字・ローマ数字を CJK 慣習の字形のまま残したい場合に使う。

```jsonc
{
  "subFont": {
    "path": "Inter-Regular.otf",
    "excludeCodepoints": ["U+2460-U+24FF", "U+25A0-U+25FF", "U+203B"]
  }
}
```

エントリは `"U+XXXX"` の単発、`"U+XXXX-U+YYYY"` の閉区間、生の整数の
いずれでも可（混在可）。マージ処理に入る前に sub-font の cmap から
これらの codepoint を取り除くだけのシンプルな仕組みなので、対象 codepoint
のベース字形はそのまま残る。font-baker 側にデフォルトの保護リストは
持たず、ポリシー判断は呼び出し側に委ねる。

Electron UI 側ではこのフィールドを表に出さない。プログラム的な用途で
`MergeConfig.subFont.excludeCodepoints` に値を入れた場合のみ、
`app/main/merge-engine.ts` の IPC ブリッジが Python に pass-through する
（`baseFont` 側に書かれたら無視）。`build_export_config` は
`ExportConfig.json`（`bundleInputFonts: true` で export したときのみ
書き出される）に同フィールドをそのまま残すので、保存した設定で再マージ
してもラウンドトリップする。

### グリフ名コリジョンの自動リネーム（cross-codepoint）

sub フォントと base フォントが同じグリフ名を別々の codepoint で参照
していることがある。代表例: Inter は U+0298 (`ʘ`, Latin bilabial click)
を `uni25CE` というグリフ名で持っているが、Noto Sans JP は同じ
`uni25CE` を U+25CE (`◎`, bullseye) に使っている。素朴に sub の
`uni25CE` を上書きすると、Noto の U+25CE がラテンクリックで描画される
というサイレントなバグになる（マージ後の TTF を視覚チェックしないと
気づかない）。

sub フォントの cmap codepoint 集合が base フォントの cmap codepoint
集合のスーパーセットでない場合、両者を別グリフとみなして sub 側を
`{元のグリフ名}.sub` にリネームする（衝突したら `.sub2` 等で重複回避）。
sub 側の codepoint (U+0298) はリネームされたグリフを指し、孤立していた
base 側の codepoint (U+25CE) は元の base 字形をそのまま保持する。
リネームが発生したグリフごとに stderr に warning を出力するので、
下流のツーリング側でログ可視化できる。

このリネームは無条件に行う（オプトアウト不可）。同じグリフ名で
codepoint 集合がずれているなら両者は別グリフ、という前提が成り立つ
ためで、無効化するとサイレント上書きが復活する。

### グリフリネームと縦組み情報

グリフ名そのものに縦組みの意味が含まれるわけではない。ただし
fontTools 上では、グリフ名が glyph-indexed table のキーになる。
そのため merge engine がグリフスロットをリネームまたは複製する
場合（`.sub`, `.lat`, `.orig`）、outline と `hmtx` だけでなく、
そのスロットを参照し続けるべき glyph-keyed table も同時に更新する
必要がある。

これは縦書きで特に問題になる。Noto Sans JP は U+2027
(hyphenation point) と U+30FB (katakana middle dot) を同じ base
glyph `uni2027` に割り当てている。Inter が U+2027 を置換する場合、
merge は元の base glyph を `uni2027.orig` に複製し、U+30FB をそこへ
向け直す。ここで outline と `hmtx` だけをコピーすると、後段の整合性
補完で `vmtx` がデフォルト値 `(advance=UPM, topSideBearing=0)` になり、
縦組み時に中黒が上に寄る。

同じ規則は置換側グリフをリネームした場合にも適用する。たとえば
cross-codepoint 保護によって Inter の U+2026 が `ellipsis.sub` に
リネームされることがあるが、base 側の Noto glyph `ellipsis` は
`vert` / `vrt2` で `ellipsis` → `uniFE19` の置換を持つ。この
SingleSubst を `ellipsis.sub` にもコピーしないと、codepoint は残って
いても縦組み shaping から外れる。

したがって、base 由来または base codepoint と重なるリネームでは
以下も追従させる。

- `vmtx` row
- `VORG` origin record（存在する場合）
- `vert` / `vrt2` の SingleSubst mapping（リネームされた入力 glyph 用）

リネーム戦略自体は引き続き必要である。共有 glyph slot を分割しないと、
ある codepoint だけを置換したつもりでも、同じ base glyph を共有していた
CJK 側の collateral codepoint を破壊してしまう。

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

### TrueType ヒンティング方針

TrueType の bytecode hinting はフォント全体で成立する仕組みで、各グリフのプログラムは `fpgm` / `prep` / `cvt ` / `maxp` カウンタが同一ソース由来であることを前提にしている。サブフォントのグリフ bytecode をベースフォントのヒント環境で実行すると、関数番号・ストレージスロット・CVT エントリが衝突し、結果として「どのソースの整合も取れていない」状態になる。

`normalize_truetype_hinting` は maxp 再計算の直後・保存直前に走り、以下を行う。

- 全グリフの `program.bytecode` をクリア
- `fpgm` / `prep` / `cvt ` テーブルを削除
- `maxp` v1 のヒント関連フィールド（`maxTwilightPoints` / `maxStorage` / `maxFunctionDefs` / `maxInstructionDefs` / `maxStackElements` / `maxSizeOfInstructions`）を 0 に正規化。`maxZones` は OpenType 仕様上 unhinted でも 1 が必要なので 1 に固定
- `gasp` はそのまま残す（スムージング戦略のテーブルで bytecode 実行とは独立）

オプションの後段処理として `output.hinting = "ttfautohint"`（エイリアス `"autohint"`）を指定すると、上記の strip 済み TTF を一度書き出した後で外部 `ttfautohint` バイナリをそのファイルに対してインプレースで実行する。ツールが見つからない場合は黙って fallback せずエラーを上げる。デフォルトの `"strip"`（`"unhinted"` / `"none"` も同義）は unhinted のまま出力し、小サイズはプラットフォームのオートヒンタに委ねる。CFF 出力は別系統のヒント保持パスを使う。

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

### Adobe 互換の `kern` feature 形状

merged GPOS の `kern` feature は、JP と Latin の feature record を分けて
残すのではなく、ベースフォントの元構造に寄せて 1 本化する。Noto Sans JP は
`DFLT` / `hani` / `kana` / `latn` の各 script から同じ `kern` feature record
を参照しており、Adobe アプリは日本語のメトリクスカーニングでこの形を前提に
しているように見える。merged font に重複した `kern` record が残ったり、
`latn` が Latin 側の kern lookup だけを指したりすると、Illustrator では
`palt` は効くのに `す。` のような CJK ペアカーニングだけ無視されることがある。

GPOS merge 時は、JP と Latin の `kern` feature record を 1 つの merged
feature record に畳み込む。JP/base の PairPos lookup は先頭に残し、事前に
Latin-first エントリを除去してあるため、CJK ペアはベースフォントの値を保ち、
Latin ペアは後続の Latin lookup に fall through して積算なしで適用される。
元々どちらかの `kern` を参照していた script/LangSys は、すべてこの 1 本の
merged record を参照する。

一度フォントを書き出したあと、`_save_with_adobe_kern_compat` は出力を読み戻し、
非 Latin の `kern` PairPos が GPOS ExtensionPos (`LookupType 9`) の背後に
隠れていないか確認する。該当する場合は fontTools の HarfBuzz repacker を
無効にして再保存し、CJK PairPos を direct `LookupType 2` として維持する。
これは Adobe が安定して処理できる元フォント側の構造に合わせるためである。

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

### Latin 1入力 GSUB 置換の保持 (Issue #23)

Pan-CJK ベース書体は Type 1 SingleSubst (`locl` / `fwid` / `hwid` /
`tnum`) や Type 3 AlternateSubst (`aalt`) でも Latin の数字・文字グリフを
ベース書体側の代替へ写すルールを持っている。#20 のクロスコードポイント
リネーム以降、これらの lookup は `latin` ではなく `mixed` に分類されて
merge を生き残るようになり（`ellipsis.sub` のように Latin 由来のリネーム
グリフが Latin 集合から外れるため）、Latin テキストにベース側ルールが発火する。
結果として `0123456789` を `latn/en` で組むと、Latin フォントの数字ではなく
ベース書体の全角／locl 代替に化ける。

`_strip_latin_owned_substitutions` は `_strip_latin_only_ligatures` の
Type 1 / Type 3 版。生き残ったベース側 lookup の SingleSubst (`mapping`)
／AlternateSubst (`alternates`) サブテーブルを歩き、source グリフが
Latin フォント所有のものは削除する。`Coverage` は fontTools が compile 時に
`mapping` / `alternates` のキーから再構築するので、辞書を更新するだけで足りる。

ストリップの保護セットは意図的に狭い：**クロスコードポイントの `.sub`
リネームだけ**を除外対象にする。Inter の `ellipsis` が Noto の U+22EF
にある `ellipsis` と名前衝突した場合、merge エンジンは Inter 側を
`ellipsis.sub` にリネームしてベース側の glyph を U+22EF に残す。
`_copy_single_substitutions_for_features` がベース側の `vert` / `vrt2`
マッピングを `ellipsis.sub` に複写するので、ストリップは `.sub` リネーム
対象だけは保護対象として除外する（`cross_codepoint_lat_renames` として
収集し `preserved_lat_names` で渡す）。これで U+2026 の縦書きも引き続き
機能する。

CID 系の cmap リネームは保護しない。Inter の `zero` が Noto Sans CJK で
`cid00017` に写るのは通常の cmap 駆動リネームであって、クロスコード
ポイントリネームではない — `cid00017 → cid63153` のようなエントリこそ
Issue #23 のバグなので必ず削除する。同名衝突回避の `.lat` リネーム
(`cedilla` → `cedilla.lat` 等) も保護セットに含めない：これらは cmap に
載らない位置に居住するため vert/vrt2 のクロスコピーが走ることもない。

65535 グリフ予算に当たる fallback 経路でもストリップが必要になる。
従来は `merge_feature_tables(None, ...)` を呼んで `lat_glyph_names` が
空のまま走らせていたため、ストリップが no-op になりベース側の Latin
入力ルールが残っていた。修正後は `append_lat_lookups=False` と
（budget loop と Step 4b のキャンセルを反映した *post-prune* な
`all_lat_glyphs` 由来の）`lat_glyph_names_override` を渡すので、
Latin GSUB の append が無理でも、実際にコピーされた Latin グリフ名に
対するベース側ルールはストリップされる。

### `ccmp` の重複タグ排除

kern を `latn` 配下で壊していた shadowing パターン（HarfBuzz は重複タグの
最初のレコードしか発火させない）は、GSUB 側の `ccmp` でも同じように起きる。
Pan-CJK 書体は独自の `ccmp` を `latn` 配下に持つので、マージ後の LangSys
には `ccmp` が 2 本ぶら下がり、HB は JP 側だけ走らせる。Latin フォントの
case-sensitive 結合マーク規則（`gravecomb → gravecomb.case` 等）が発火
しなくなり、`M̀` / `Ê̄` は大文字に対する `.case` フォームを失う。

`GSUB_LATN_DEDUPE_TAGS` は GPOS と同じ dedupe ルールを明示的 Latin script
で適用する GSUB タグの一覧。検証済みメンバー: `ccmp`（Latin case-sensitive
結合マーク）と `dlig`（Inter の chain context 形式 `f → f.i` / `r → f.1`
/ `t → t.1` 系 — エントリ単位の strip では JP の Latin 入力リガチャは
空になるが、JP `dlig` の *feature record* 自体は依然として `latn` の下で
Inter の lookup を shadowing する）。`aalt` その他の GSUB 共有タグは
従来通り両方残す — JP 側の `aalt` は CJK glyph 用に `latn` から到達可能
である必要がある (Issue #2 #6)。

dedupe は **LangSys 単位** で判定する。つまり Latin 側が *現在の* LangSys
に同じタグを実際に持っている場合だけ落とす。Latin font が当該 explicit
Latin script の LangSys を持たない場合（例: Latin サブが Greek 非対応
なのに base に grek LangSys がある場合）、JP 側 `ccmp` はそのまま残る
— shadowing する相手がいないため。

### メトリクス

- `head.unitsPerEm` = `outputUpm`（ユーザー設定、デフォルト 1000）
- OS/2, hhea のアセンダー/ディセンダーは両フォントのエンベロープ（出力 UPM 単位）
- Latin のスケール/ベースラインはグローバルメトリクスに影響しない

### 静的出力としての識別

ofl-font-baker は常に static インスタンスを出力する。base / sub は
マージ前にそれぞれの軸位置でインスタンス化され、ソースフォントが
持っていたファミリー階層情報は出力に持ち込まない:

- `STAT` は無条件で削除する。`fontTools.varLib.instancer` は STAT
  をインスタンス化位置だけ残して prune するため、軸レコードが残骸と
  して残ったり、軸上にない位置（例: `wght=465`）では部分的なテーブル
  になる。さらに `output.weight/italic/width` で上書きされると、継承
  された STAT が静的識別と矛盾する。Inter のような static TTF
  ファミリーは STAT を持たずに出荷されることが多く、`name` / `OS/2`
  を識別の唯一の真実とするためにも static 出力で STAT は不要 (Issue
  #16)。
- `OS/2.fsSelection` の REGULAR / BOLD / ITALIC、`head.macStyle` の
  bold / italic ビットは `(weight, italic, width)` から再計算する。
  `usWeightClass` / `usWidthClass` と italic フラグに矛盾しないように
  揃える。REGULAR は本当の Regular 面（weight 400・width 5・非
  italic）にだけ立てる。Light / Medium / SemiBold など RIBBI に入ら
  ないメンバーは REGULAR をクリアしないと、フォントマッチャがそれを
  ファミリーの Regular だと誤認する。

継承モードでは、`weight` / `italic` / `width` のいずれかが上書き
されたときだけビットを再計算する。何も指定しないピュアパススルー時
は継承元のビットをそのまま残す。

### OFL メタデータ

デフォルト（`output.metadataMode = "merge"` または未指定）では、出力を新しい
派生著作物として扱う。識別系のレコードは `output.*` の値からすべて作り直す:

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

### メタデータ継承モード（`output.metadataMode`）

`output.metadataMode` で識別レコードのポリシーを切り替えられる:

| 値 | 挙動 |
|---|---|
| 未指定 / `null` / `"merge"` | デフォルト。識別レコードを派生著作物として作り直す（上記）。 |
| `"inheritBase"` | base フォントの識別レコードをそのまま流用し、ユーザーが `output.*` で明示的に指定したフィールドだけ上書きする。 |
| `"inheritSub"` | 同様だが、識別を sub フォントから取る（`subFont` がない場合はエラー）。 |

中間生成物（さらに別パイプラインに渡すために、ベースに対してグリフだけ
焼き込みたい場合など）や、派生として再宣言したくないマージ（例: `Noto
Hentaigana` のグリフを `Noto Sans JP` に取り込みつつ、結果を Noto Sans JP
として識別させたい場合）に有用。

継承モードでは以下の処理を **行わない**:

- nameID 13 / 14 を OFL の正規テキストで上書きする
- nameID 9 / 12（designer）をクリアする
- `OS/2.achVendID` を半角スペース 4 つに固定する
- `head.created` / `head.modified` をマージ実行時刻で上書きする
- nameID 25（Variations PS Prefix）を削除する
- nameID 5 に `;ofl-font-baker {appVersion}` を追記する

`output.*` で値が指定された場合は、その項目だけ継承元を上書きする:

- `familyName` / `postScriptName` は nameID 1 / 4 / 6 / 16 を再合成する。style 部分は継承元の現値を使う。
- `weight` / `italic` / `width` は nameID 2 / 4 / 6 / 17 と `OS/2`、`head.macStyle` のビットを再計算する。指定されなかった項目は継承元の `OS/2` から拾い、`400 / 非イタリック / 標準幅` のデフォルトには戻さない。
- `version` は nameID 5 と `head.fontRevision` を上書き。
- `copyright` / `trademark` / `manufacturer` / `manufacturerURL` は対応する nameID を **完全に上書き**する（merge モードのような結合は行わない）。
- CFF TopDict `FullName` / `FamilyName` / `Notice` は、上書きで識別が変わったとき、または sub から継承するときに、最終的な name レコードに同期する。
- nameID 3（Unique Font Identifier）は、上記の識別系オーバーライド（`familyName` / `postScriptName` / `weight` / `italic` / `width` / `version`）が **指定されたとき**、新しい name 5 / 6 から `{version};{PostScript フルネーム}` で再生成する。何も指定しないピュアなパススルー時は継承元の UID をそのまま残す。

各上書きは `progress("info", ...)` で `[metadata] override
familyName='...'` のような 1 行をログに出すので、ビルドログから何が
書き換えられたか追跡できる。

`inheritBase` で出力したフォントは、グリフや feature が混ざっているにも
かかわらず name table 上ではベースフォントとして名乗ることになる。これを
そのまま「ベースフォント」として配布すると誤認を招くので、継承モードは
中間生成物・社内パイプライン・派生だと承知の上での拡張リリース、といった
用途を想定している（OFL §1 上は name table が何と書いていても派生著作物
であることに変わりはない）。

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
| Static style identity | 15 | merge / inheritBase / inheritSub での STAT 削除、fsSelection REGULAR/BOLD/ITALIC + macStyle bold/italic |
| Baseline offset | 4 | simple シフト、Latin & JP composite 二重シフト防止、JP 非影響 |
| Scale | 2 | グリフサイズ、advance width |
| UPM normalization | 3 | 2048→1000 変換、OS/2 metrics |
| Output UPM | 5 | hmtx / glyph / OS/2 への UPM スケーリング、base-only |
| GPOS scaling | 3 | kern scale、baseline 非影響、T+o ペアカーニング保持 |
| 欧文 kern 保持 | 60 | 32 ペア（UC-UC, UC-lc, lc-UC, lc-lc, 記号, 数字）+ 27 字幅 + JP PairPos の Latin 先頭除去確認 |
| 欧文 ligature 保持 | 28 | dlig で 12 系列（n+s/S+v/A+m の単位記号トラップ含む）+ 12 系列が Latin 単体と一致 + JP LigatureSubst の Latin-only 除去 + ccmp shape 一致（M̀ / Ê̄ 等）+ latn 配下 ccmp 1 本の構造確認 + grek の JP ccmp が LangSys 単位で温存される回帰確認 |
| Inter dlig chain context | 8 | Inter の fi/fl/ff/ffi/ffl/rf/tt chain-context dlig が merge 後も Inter 単体と一致 + latn 配下 dlig 1 本の構造確認 |
| Feature preservation | 9 | calt / case / frac / ss01 / liga、従属欧文除去、chaining リマップ |
| Same-tag features | 1 | Latin LangSys から JP 側 `aalt` への到達性 |
| Glyph names | 2 | post format 2.0、代替グリフ名 |
| Composite integrity | 2 | 参照完全性、hmtx 完全性 |
| Metrics preservation | 10 | UPM、OS/2、hhea、scale/baseline 非影響 |
| TT hinting normalization | 10 | fpgm / prep / cvt 削除、gasp 保持、glyph program クリア、maxp ヒントカウンタ 0、ヒント付きサブフォント regression、ttfautohint ポリシー配線 |
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
