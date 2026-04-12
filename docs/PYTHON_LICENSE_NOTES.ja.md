# Python サブディレクトリのライセンス表記メモ

この文書は、Claude Code や他の実装者が `python/README.md` や関連ドキュメントを書く際に、ライセンス表記を誤らないためのメモである。

## 前提

- リポジトリ全体の親プロジェクトは AGPL-3.0-or-later
- `python/` 配下には MIT ライセンスで再利用したい Python ソースコードがある
- ただし `python/` 配下には、MIT ではない第三者ライセンスのテストフォントや付随ファイルも含まれる

したがって、`python/` 全体を一括で MIT と言い切る表現は避けること。

## やってはいけない表現

以下のような文は、範囲を広く言いすぎるので避ける。

```md
This `python/` directory is independently licensed under MIT.
```

この書き方だと、`python/tests/fonts/` 配下のフォントやそのライセンス文書まで MIT であるかのように読めてしまう。

## 推奨する考え方

MIT であると明示したい対象は、`python/` ディレクトリそのものではなく、あくまでその中の「自分が著作権を持つ Python ソースコード」である。

つまり表現は以下に寄せる。

- `the source code in this directory`
- `unless otherwise noted`
- `test fonts and third-party assets are licensed separately`

## README に書く推奨文面

`python/README.md` には、例えば以下のように書く。

```md
## License

Unless otherwise noted, the source code in this directory is licensed under the MIT License. See [LICENSE](LICENSE) for details.

Test fonts and other third-party assets under `tests/fonts/` are licensed separately under their respective licenses.

Other parts of the parent repository are licensed under AGPL-3.0-or-later and are not covered by this MIT notice unless explicitly stated.
```

## この文面で守りたいこと

- `python/` 全体が MIT だと断定しない
- `tests/fonts/` 配下を MIT の対象に含めない
- 親リポジトリ全体まで MIT だと誤認させない
- `python/LICENSE` の適用範囲を「このディレクトリのコード」に限定して読めるようにする

## 実ファイル上の注意

第三者ライセンスが存在する実例:

- `python/tests/fonts/Inter-4.1/LICENSE.txt`
- `python/tests/fonts/Kaisei_Decol/OFL.txt`
- `python/tests/fonts/NotoSansCJKjp/LICENSE`
- `python/tests/fonts/Noto_Sans_JP/OFL.txt`
- `python/tests/fonts/Playwrite_IE/OFL.txt`

MIT ライセンス本文:

- `python/LICENSE`

## 追加でやるとよいこと

README の一文だけに頼らず、Python ソースファイル側にもライセンス識別子を入れるとよい。

例:

```py
# SPDX-License-Identifier: MIT
```

対象:

- `python/merge_fonts.py`
- 将来追加する `python/` 配下の自作 Python ソース

## Claude Code への指示

今後 Claude Code が `python/README.md` や `python/` 配下のドキュメントを作るときは、以下を守ること。

- `python/ directory is licensed under MIT` と断定しない
- `Unless otherwise noted, the source code in this directory...` のように範囲を限定して書く
- `tests/fonts/` 配下の別ライセンス資産を明示的に除外する
- 親リポジトリの AGPL ライセンスと混同しないように書く
- 必要なら SPDX ヘッダ追加も提案する

