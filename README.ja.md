<div align="center">
  <img src="docs/assets/icon.png" alt="OFL Font Baker" width="200">
  <h1>OFL Font Baker</h1>
  <p><strong><a href="README.md">English</a></strong> | 日本語</p>
</div>

## Composite Font Builder

OFL Font Baker は、フォントの統合・書き出しを行う macOS アプリケーションです。  
2つの書体データを1つに合成し、静的な書体データ（OTF / TTF, WOFF2）として書き出すことができます。

和欧混植・かな書体の差し替えといった用途に加え、バリアブルフォントの静的な書き出しにも使用できます。

<img src="docs/assets/FontBaker.gif" alt="OFL Font Baker" width="100%">

## Features

- 2つのフォントのマージ
- 書体ごとのベースライン・サイズ調整
- バリアブルフォント対応（単体での書き出しにも対応）
- リアルタイムプレビュー
- OpenType 機能の保持
- ライセンス情報等のメタデータの自動的な統合
- 入力に対し最適な形式（OTF / TTF）で書き出し＋WOFF2 を同時生成

## OFL Fonts Only

**SIL Open Font License (OFL)** でライセンスされたフォントのみ読み込みが可能です。

OFL は、SIL International が策定したオープンソースライセンスです。フォントの自由な使用・改変・再配布を認めつつ、作者への帰属を保護する仕組みを持っています。
[Google Fonts](https://fonts.google.com/) や [Collletttivo](https://www.collletttivo.it/typefaces)、[Noto フォントファミリー](https://github.com/googlefonts/noto-fonts)など、多くの高品質な書体が OFL のもとで公開されています。

## Download

[Releases](https://github.com/yamatoiizuka/ofl-font-baker/releases) ページから `.dmg` ファイルをダウンロードできます。

## Support

もしこのプロジェクトが役に立ったら、開発の継続を応援していただけると嬉しいです。

<a href="https://www.buymeacoffee.com/yamatoiizuka" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="40"></a>

---

## フォントのライセンスについて

OFL Font Baker で扱えるフォントは OFL ライセンスのもとで公開されているものに限られます（[OFL Fonts Only ⇧](#ofl-fonts-only)）。  
ここでは、OFL のもとでフォントを使用・配布する際のルールを整理します。

### マージしたフォントを配布する場合

OFL でライセンスされたフォントを改変・マージして配布する場合、以下のルールが適用されます。

1. **著作権表示とライセンス文の保持** — 元フォントの著作権表示と OFL ライセンス文をすべて保持する必要があります。
2. **同一ライセンスでの配布** — 派生フォントも OFL のもとで配布しなければなりません。他のライセンスに変更することはできません。
3. **Reserved Font Name（予約済みフォント名）の使用禁止** — 元のフォントが Reserved Font Name を宣言している場合、派生フォントにその名前を使用できません。たとえば、元のフォントに `with Reserved Font Name 'Noto'` と記載されていれば、マージ後のフォント名に "Noto" を含めることはできません。
4. **フォント単体での販売禁止** — フォントファイルそのものを単体で販売することはできません。ただし、ソフトウェアにバンドルしての配布は許可されています。

OFL Font Baker は、上記の1・2 に準拠したメタデータ（著作権表示・ライセンス情報）を自動設定します。  
3 のフォント名や 4 の配布形態については、ソフトウェア使用者の確認が必要です。  
配布時には、著作権表示と OFL ライセンス全文を記載した OFL.txt の同梱を推奨します。

OFL の詳細については、[SIL Open Font License 公式サイト](https://openfontlicense.org) を参照してください。

### 自作フォントをマージする場合

自作フォントを OFL Font Baker で読み込むには、ソフトウェアの仕様上、そのフォントが OFL ライセンスのフォントとして判別できる必要があります。フォントの name テーブルに以下の情報を設定してください。

**License (nameID 13):**

```
This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is available with a FAQ at: https://openfontlicense.org
```

**License URL (nameID 14):**

```
https://openfontlicense.org
```

---

## 本ソフトウェアについて

### 対応環境

現在、開発者の検証環境の都合により、本アプリは **Apple Silicon 搭載の Mac (arm64)** のみ対応しています。

なお、本アプリは Electron ベースで開発しているため、将来的には Windows 版や Intel 搭載 Mac 向けの対応を行う可能性があります。これらの対応を後押ししていただける場合は、[Buy Me a Coffee￼](https://www.buymeacoffee.com/yamatoiizuka) や GitHub Sponsors からサポートしていただけると励みになります。

### ライセンス

このソフトウェアは [GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html) のもとで公開されています。

### 不具合の報告

不具合を見つけた場合は、Issues から報告をお願いします。報告の際、以下の情報を添えていただけると対応がスムーズです。

- 使用したフォント名とその入手元
- スケール・ベースラインなどの設定値
- 発生した問題の内容

### 免責事項

本ソフトウェアは現状のまま（AS IS）で提供されており、動作の完全性や特定目的への適合性を保証するものではありません。本ソフトウェアの使用により生じたいかなる損害についても、作者は責任を負いません。

---

## 謝辞

このアプリケーションは、[Claude Opus 4.6](https://www.anthropic.com/claude) との対話を通じて設計・開発されました。

フォントマージの中核には [fontTools](https://github.com/fonttools/fonttools)、リアルタイムプレビューには [HarfBuzz](https://github.com/nicolo-ribaudo/harfbuzzjs) を使用しています。
これらをはじめとする素晴らしいオープンソースソフトウェアの作者の皆さまに感謝します。

そしてなにより、SIL Open Font License のもとで素晴らしい書体を公開してくださっているタイプデザイナー・タイプファウンドリーの皆さまに、深く敬意を表します。
