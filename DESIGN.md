# 設計書 — 新幹線 領収書ダウンロードツール

最終更新: 2026-06 / 対象: スマートEX・エクスプレス予約（JR東海）, えきねっと（JR東日本）

## 1. 目的・前提

- 利用者本人のアカウントから、指定期間（From年月〜To年月）の新幹線領収書を**まとめてローカル保存**する。
- ブラウザ自動化（Playwright）でサイトを操作する。**ログインは手入力**（資格情報は保持しない）。
- 実行・保存は**必ず利用者のPC上**で行う（GitHub のサーバー上では実行不可）。GitHub はコード共有と
  画面（GitHub Pages）配信のみ。

## 2. 対応サービスと差異

| 項目 | スマートEX / エクスプレス予約（JR東海） | えきねっと（JR東日本） |
|---|---|---|
| 予約システム | RSV_P（`shinkansen2/1.jr-central.co.jp`） | `eki-net.com`（SPA） |
| ボット対策 | 弱い（Playwright Chromium で可） | **Akamai Bot Manager**（Playwright Chromium は遮断） |
| 起動ブラウザ | Playwright 同梱 Chromium | **実 Google Chrome**（CDP接続）|
| ログイン検知 | URL に `ClientService` ＋ `cfEXPY_doAction` 定義 ＋ メニュータイル | URL/パスワード欄/ログアウト表示で会員ページ判定 |
| 期間指定 | 照会期間プルダウン（From年月+日 / To年月+日） | 期間プルダウン（From年月 / To年月）|
| 領収書取得 | 行の「領収書表示」→ 別ウィンドウ → 宛名入力 → CDP printToPDF | 「ご利用票兼領収書を発行する」→ 宛名入力 → 「領収書を発行する」でファイルDL |
| 宛名 | 1欄 | 2欄（1行目=宛名、2行目=空欄化）|

## 3. アーキテクチャ / モジュール構成

```
[ 入口 ]                 [ 制御 ]               [ サービス実装 ]
main.py (CLI) ─┐
               ├─→ pipeline.Pipeline ─┬─ JR東海: agents/{login,discovery,download}_agent
webapp.py (Web)┘   (サービスで分岐)   └─ えきねっと: providers/ekinet

共通基盤: config.py（設定・セレクタ・利用可否） / browser_manager.py（Playwright管理）
          datetools.py（日本語日付） / docs/index.html（Web UI・GitHub Pages兼用）
```

| ファイル | 役割 |
|---|---|
| `main.py` | CLI。引数解釈（From/To・--service 等）→ `Pipeline` 実行 |
| `webapp.py` | ローカル Web サーバ（Flask）。フォーム受付→別スレッドで `Pipeline` 実行→進捗をJSONで返す。CORS/Private Network Access 対応（GitHub Pages からの呼び出し許可）|
| `docs/index.html` | 画面。GitHub Pages でも `webapp` でも同じものを配信。`HELPER` をオリジンで切替 |
| `pipeline.py` | サービス種別で分岐。JR東海系は browser_manager+agents、えきねっとは `providers.ekinet.run_flow` |
| `config.py` | サービス定義 `SERVICE_CONFIGS`、JR東海系セレクタ `SELECTORS`、利用可否・メンテ判定、各種設定 |
| `browser_manager.py` | 単一 Chromium コンテキスト管理。`window.print` 無効化 / 自動化痕跡マスク / デバッグ保存 |
| `agents/login_agent.py` | JR東海: 手入力ログイン→会員メニュー到達を自動検知 |
| `agents/discovery_agent.py` | JR東海: 会員メニュー→一覧、照会期間プルダウン設定、領収書ボタン操作、戻る、ページ送り |
| `agents/download_agent.py` | JR東海: 明細で宛名入力→印刷ポップアップを CDP printToPDF で保存 |
| `providers/ekinet.py` | えきねっと: 実Chrome起動→CDP接続→ログイン待ち→規約/JREID→履歴→絞込→発行→DL |
| `datetools.py` | 日本語日付の抽出・解析（全角対応、ファイル名用）|

## 4. 実行フロー（共通）

1. 入口（CLI/Web）が From/To年月・サービス・宛名・出力先・デバッグ等を決定し `config` に反映。
   - CLI は **サービス → From/To年月 → 宛名** の順に解決し、引数で与えられなかった項目だけを
     対話プロンプトで尋ねる（`--service` 等を付ければその項目は確認なし）。標準入力が
     非対話（TTYでない）の場合は既定値にフォールバックする。
2. `Pipeline.run()`:
   - JR東海系のみ利用可否（翌日〜15ヶ月）・メンテ時間（23:30〜5:30）を事前判定。
   - `SERVICE_TYPE == "eki-net"` → `providers.ekinet.run_flow(...)`。
   - それ以外 → `browser_manager.start(headless=False)` → `login_agent.ensure_session` → `_download_all`。
3. 結果（成功ファイル一覧・失敗件数）を返す。Web UI は `/status` ポーリングで進捗表示。

## 5. サービス別フロー詳細

### 5.1 JR東海（スマートEX / エクスプレス予約）
1. `login_url`（RSV_P）を開く → ユーザーがID/PW＋SMS認証を手入力。
2. 会員メニュー(ClientService)到達を自動検知（URL＋`cfEXPY_doAction`＋メニュータイル）。
3. メニュー「ご利用履歴・領収書の発行」→ 一覧。
4. 照会期間（From年月/1日 〜 To年月/末日）を4プルダウンで設定→「再検索」。
5. 各行「領収書表示」→ 別ウィンドウ（正式な領収書）→ 宛名入力 → **CDP `Page.printToPDF`** で PDF 化。
   - 「印刷」ボタンは押すが OS ダイアログは `window.print` 無効化で抑止し、ポップアップを直接PDF化。
6. 明細「戻る」で一覧へ戻り次へ。ページ送り対応。

### 5.2 えきねっと（JR東日本）
1. **実 Google Chrome** を `--remote-debugging-port=9222` ＋ 専用プロファイルで通常起動（automation痕跡なし）。
   既存のデバッグChromeは事前に終了（再接続不可のため）。
2. `connect_over_cdp` で接続。ユーザーがトップからログイン → 会員ページ到達を検知。
3. 規約合意ページ: 全チェック→「次へ」 / JREIDページ:「今は登録しない」（出る方を処理）。
4. 「JRきっぷ 確認・変更・払戻・領収書」(`data-action=TransitionToApplicationHistoryList`) → 申込履歴。
5. タブ「乗車／取消済の旅程」→ 表示内容「全て表示」＋ 期間 From/To年月プルダウン →「絞り込む」。
6. 各「ご利用票兼領収書を発行する」→ 宛名入力（1行目=宛名、2行目=空欄化）→「領収書を発行する」。
   PDF が**ファイルとしてダウンロード**される（保存先＝デスクトップ、重複はChromeが連番）。
7. 1件ごとに一覧へ戻る（ブラウザバック→失敗時は履歴再遷移＋再絞り込み）。

## 6. セレクタ管理・調整

- JR東海系のセレクタは `config.SELECTORS`、えきねっとは `providers/ekinet.py` の `SEL` に集約。
- すべて「候補リスト」で上から順に試す方針。サイト仕様変更時はここだけ直す。
- `--debug`（または Web UI のデバッグ）で各ステップの `output/debug_*.png|html` を保存し、実DOMに合わせて調整。

## 7. ログイン・ボット対策

- 資格情報は保存しない。ログインは常に手入力。
- JR東海: 会員メニュー到達をポーリング検知（最大5分）。`window.print` 無効化＋`navigator.webdriver` 等のマスク。
- えきねっと: Playwright Chromium だと Akamai に `Access Denied`。**実Chromeに CDP 接続**することで
  「普通のブラウザ」として通す。深いURLへの `goto` を避け、クリックで遷移。

## 8. 出力・データ

- 領収書PDF: `OUTPUT_DIR`（既定=デスクトップ）。JR東海は `領収書_<日付>_<連番>_<金額>円.pdf`、
  えきねっとはサイト提供のファイル名（重複はChrome連番）。
- セッションは保存しない（`.auth/` は基本未使用）。えきねっと用 Chrome プロファイルは
  `~/.ex-ekinet-chrome`（cookie保持で再ログインを軽減）。
- デバッグ成果物: `output/`（gitignore 済み）。

## 9. 主な設定（`.env` / 環境変数 / CLI）

`SERVICE_TYPE`（`smart-ex` / `expy` / `eki-net`）/ `RECIPIENT_NAME` / `OUTPUT_DIR` / `HEADLESS` /
`TIMEOUT` / `DEBUG` / `TRAVEL_DATE_INDEX`。

CLI 引数: `FROM [TO]` 位置引数・`--from/--to`（年月）・`--year/--month`・`--service`・`--recipient`・
`--output`・`--no-headless`・`--debug`・`--check`。

**引数なしで実行**すると、サービス → From/To年月 → 宛名 を順に対話選択する（`--service` などを
付けた項目はスキップ）。`--check` は照会期間・利用可否の表示のみでブラウザを起動しない。

## 10. 拡張ガイド（新サービス追加）

1. `config.SERVICE_CONFIGS` に定義を追加。RSV_P類似なら `JR_CENTRAL_SERVICES` に含める。
2. 既存と異なるフロー/ボット対策なら `providers/<name>.py` に `run_flow(from_y,from_m,to_y,to_m,recipient)` を実装し、
   `pipeline.run()` で分岐。
3. `main.py --service` の choices、`docs/index.html` のサービス選択肢、README/本書を更新。

## 11. 制約・既知の注意点

- サイト仕様変更でセレクタ/フローが変わると動かなくなる（`SELECTORS`/`SEL` で対応）。
- 実行ごとにログイン（必要に応じSMS/追加認証）が必要。
- えきねっとは **Google Chrome 必須**。Akamai 強化で将来通らなくなる可能性あり。
- GitHub Pages の画面から使う場合も、各PCでローカルヘルパー（`webapp.py`）の起動が必要。
- 非公式ツール。各サイトの利用規約を尊重し、過度なアクセスは避ける。無保証。
