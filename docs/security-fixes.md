# 製品コード監査の修正

基点: main `60be2be`。それぞれ独立したブランチにコミットし、`fix/product-security` に統合した。

| ブランチ | 対応 |
| --- | --- |
| `fix/authorize-file-ipc` | main のトップレベル画面からのIPCのみ受理。ネイティブ選択／実ファイルのドロップで入力を認可し、mainのプロファイルに保存。読取り時にファイルの同一性とサイズを確認。出力先と上書き承認はmainで保持し、一度だけ利用可能。 |
| `fix/transactional-font-export` | パッケージ出力を同じファイルシステムの一時ディレクトリーで完成させてから置換。置換失敗時は旧出力を復元。入力を含む出力先、symlink、生成中に変化した出力先を拒否。 |
| `fix/restrict-external-links` | 子ウィンドウ作成を拒否。メタデータのリンクとopenExternal IPCはHTTP／HTTPSのみをOSブラウザーへ渡す。 |

## 利用上の変更

- 更新前のrenderer保存データは入力認可として信頼しないため、保存済みフォントは初回だけ選択し直す。以降の認可はmainのプロファイルに保存される。
- 256 MiBを超えるフォントは読み込まない。
- 出力に失敗した場合やキャンセル後の再実行では、保存先を再選択する。
- 生成途中で強制終了した場合、一時ディレクトリーが残ることがある。置換途中の強制終了では旧出力がその中のバックアップに残ることがある。電源断を含めた完全なトランザクションを保証するものではない。

## 検証コマンド

```sh
node --test scripts/tests/file-authority.cjs scripts/tests/external-links.cjs
.venv/bin/python -m pytest python/tests/test_export_safety.py -q
npx tsc --noEmit
npm run build
node_modules/.bin/electron scripts/tests/ipc-security.cjs
node_modules/.bin/electron scripts/tests/external-window-security.cjs
PATH="$PWD/.venv/bin:$PATH" npm run python:build
TEST_TRANSACTIONAL_EXPORT=1 node_modules/.bin/electron scripts/tests/ipc-security.cjs
```

統合テストは隔離プロファイル・一時ファイルを使い、ネイティブダイアログとOSの外部URL起動をスタブする。通常のファイル選択経路、未認可読取り、偽のFileオブジェクト、保存先未承認、別ウィンドウからのIPC、外部リンクの子ウィンドウ拒否を確認する。最後のコマンドは更新済みPython実行ファイルが必要で、失敗したexportが旧出力を保持することをElectronから確認する。

CSP、パーサーのfuzzing／実行時間制限、配布用entitlementsの最小化は今回の3件とは別の追加防御候補として残る。実機でのネイティブダイアログ操作・ドラッグ＆ドロップの目視確認、署名済み配布物での確認はこの自動テストに含まれない。

## 実行結果

- ファイル認可・URLのJavaScript回帰テスト: 7件成功。
- 最終コードの出力安全性テスト: 9件成功（実TTF／WOFF2と同梱設定ファイルを含む）。
- 初回の出力安全性8件と既存pipeline 33件: 計41件成功、562.42秒。以降の変更は出力設定の最終パスとバックアップ保護を追加し、上記9件で確認した。
- Electron IPC統合・外部ウィンドウ統合: 成功。更新済みPyInstaller実行ファイルを使った失敗exportの旧ファイル保持も成功。
- TypeScript型チェック、フロントエンド／main／preloadビルド、Python実行ファイルのビルド: 成功。Viteの既存チャンクサイズ警告あり。
