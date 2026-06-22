# EX予約 / スマートEX 領収書ダウンロードツール

指定した月の領収書を**まとめて PDF 保存**するツールです。Playwright でブラウザを操作し、
スマートEX / エクスプレス予約の「ご利用履歴・領収書の発行」から対象月の領収書を1件ずつ
表示 → 宛名入力 → 正式な領収書を PDF 化して、**デスクトップ**に保存します。
**Web UI（フォーム）** と **CLI** の2通りで使えます。Windows / macOS / Linux 対応。

> ⚠️ **必ずお使いのPCで実行します。** ブラウザ操作とローカル保存を伴うため、GitHub の
> サーバー（Pages / Actions）上では実行できません。GitHub はコードの保管・共有用です。
> 画面を GitHub Pages の URL で開くこともできますが、その場合も実行は各自のPCで動きます。

ログイン情報は保存しません。実行のたびにブラウザでログイン（**会員ID・パスワード＋SMS認証**）が必要です。

---

## 1. 必要要件

- **Python 3.9 以上**
  - Windows: https://www.python.org/downloads/ から導入（インストール時に **「Add python.exe to PATH」にチェック**）
  - macOS: 標準の `python3`（または Homebrew 等）

### ファイルの入手と準備

1. このページ上部の**緑色の `< > Code` ボタン → `Download ZIP`** をクリックして全ファイルをダウンロードし、
   ZIP を解凍します（置き場所はどこでも構いません）。※ `git clone` でもOKです。
2. **ターミナル（Mac）／コマンドプロンプト（Windows）** を開き、解凍したフォルダへ移動します。
   - 移動は `cd ` と入力してから、解凍した**フォルダをウィンドウにドラッグ＆ドロップ**して Enter すると簡単です。
   - 例（Mac）: `cd ~/Downloads/ex-receipt-downloader-main`

## 2. セットアップ（初回のみ）

依存パッケージと Playwright 用 Chromium（各OS向け・約150MB）を入れます。

**かんたん（ダブルクリック）**
| OS | 実行するファイル |
|---|---|
| Windows | `scripts\setup.bat` |
| macOS | `scripts/setup.command`（初回は右クリック→「開く」） |
| Linux | `bash scripts/setup.sh` |

> **ダブルクリックでうまくいかない場合**は、上記ファイルを**ターミナル（またはコマンドプロンプト）に
> 直接ドラッグ＆ドロップして Enter** を押すと実行できます。
> これで依存パッケージと Playwright 用 Chromium（各OS向け・約150MB）がインストールされます。

**手動で行う場合**（上記でうまくいかないとき）
お使いのOSの行をコピペして実行してください。
```bash
# Windows:  py -3 -m pip install -r requirements.txt && py -3 -m playwright install chromium
# macOS  :  python3 -m pip install -r requirements.txt && python3 -m playwright install chromium
# Linux  :  python3 -m pip install -r requirements.txt && python3 -m playwright install --with-deps chromium
```

## 3. 使い方（Web UI）

1. **ヘルパーを起動**（下表のファイルをダブルクリック）。Webブラウザが起動し、
   `http://localhost:8765` の画面が自動で開きます。

   | OS | 実行するファイル |
   |---|---|
   | Windows | `scripts\start_helper.bat` |
   | macOS | `scripts/start_helper.command` |
   | Linux | `bash scripts/start_helper.sh` |

   > **ダブルクリックでうまくいかない場合**は、上記ファイルを**ターミナル（またはコマンドプロンプト）に
   > 直接ドラッグ＆ドロップして Enter** を押してください。Webブラウザが起動します。

2. 画面で **年・月・宛名・サービス** を選び、**「実行する」** を押す。
3. **別ウィンドウでブラウザが開く** → **会員ID・パスワード → SMS認証** を入力し、会員メニューまで進む。
4. 会員メニュー到達を自動検知 → 対象月の領収書をすべて取得し、**デスクトップに PDF 保存**。
   進捗とダウンロード結果は画面に表示されます。

> ヘルパーのウィンドウ（ターミナル）は実行中は開いたままにしてください。終了は Ctrl+C／ウィンドウを閉じる。

## 4. 使い方（CLI）

```bash
# 設定と照会期間・利用可否の確認のみ（ブラウザを起動しない）
python3 main.py 2026/05 --check

# 通常実行（単月）：ブラウザが開く → ログイン → 会員メニュー到達で自動継続
python3 main.py 2026/05

# 期間指定（From年月 〜 To年月）：From月初日〜To月末日が対象
python3 main.py 2026/03 2026/05
python3 main.py --from 2026/03 --to 2026/05

# 別指定・オプション
python3 main.py 2026/05 --service expy --recipient "株式会社○○"
python3 main.py 2026/05 --service eki-net --debug   # えきねっと
```
> Windows は `python` / `py -3`、macOS/Linux は `python3` を使ってください。

## 対応サービス

フォーム（または `--service`）で選びます。

- **スマートEX / エクスプレス予約（JR東海）**: 会員メニュー →「ご利用履歴・領収書の発行」→
  対象月で照会 → 明細で宛名を入力 →「印刷」で開く正式な領収書を PDF 化。
- **えきねっと（JR東日本）** (`--service eki-net`): ログイン → 規約同意（自動チェック→次へ）→
  JREID「今は登録しない」→ 申込履歴 →「乗車/取消済の旅程」を対象月で絞り込み →
  各「ご利用兼領収書を発行する」をクリックして**領収書ファイルをダウンロード**（重複は連番）。
  - ⚠️ えきねっとは **Akamai のボット対策**があり、Playwright のブラウザは遮断されます。
    そのため**お使いの実 Google Chrome を通常起動（デバッグポート付き）して CDP で操作**します
    （**Google Chrome のインストールが必要**）。実行すると専用プロファイルの Chrome ウィンドウが
    開くので、**ご自身でログイン**してください。以降は自動で進みます。
  - ログイン（ID/PW・追加認証）は手入力。**宛名入力は使いません**（えきねっと側で扱わないため）。
  - 保存先はデスクトップ。Chrome は実行後も開いたまま（次回は再ログイン不要で接続）。
  - セレクタは `providers/ekinet.py` の `SEL` に集約。うまく動かない場合は `--debug` で
    `output/debug_ek_*.html` を確認して `SEL` を調整してください。

## 5.（任意）GitHub Pages の URL で画面を開く

画面を `https://<ユーザー名>.github.io/ex-receipt-downloader/` で開けるようにできます
（実行は各自PCのヘルパーが担当）。

1. リポジトリを push 後、**Settings → Pages → Source: Deploy from a branch → `main` / `/docs`** を保存。
2. 各PCで **ヘルパーを起動**（手順3-1）。
3. 公開URLを **Chrome** で開く → 「✅ ローカルヘルパー稼働中」と出れば実行できます。

> ヘルパーは `127.0.0.1` のみで待ち受け、許可するのは自分の `*.github.io` と `localhost`
> だけです（CORS / Private Network Access で制限）。**Chrome 推奨**（Safari はローカル接続を
> ブロックする場合があります）。`localhost:8765` を直接開くだけなら GitHub の設定は不要です。

---

## 動作の仕組み

- 一覧の照会期間（From/To の「年月」「日」プルダウン）に **対象月の初日〜末日** を設定して
  「再検索」し、表示された領収書を全件取得します（当月指定時は末日を今日までにクランプ）。
- 各行の「領収書表示」→ 明細で宛名（上段）を入力 → 「印刷」を押すと**別ウィンドウに正式な
  領収書**が開きます。OSのネイティブ印刷ダイアログは自動操作できないため、その**別ウィンドウを
  CDP `Page.printToPDF` で PDF 化**します（印刷ダイアログで「PDFに保存」した場合と同じ内容。
  `window.print()` は固まり防止で無効化）。
- **1領収書＝1PDF**。ファイル名は `領収書_<乗車日YYYYMMDD>_<連番>_<金額>円.pdf`
  （日付/金額が取れない場合は連番のみ。同名は `_2`,`_3`… で一意化）。既定の保存先は**デスクトップ**。
- サイト制約: 予約完了日**当日は不可**、翌日〜**最大15ヶ月**、**23:30〜5:30はメンテで利用不可**
  （ツール側でも事前チェック／警告）。

## 設定（任意 / `.env` または環境変数）

`.env.example` をコピーして `.env` を作成すると既定値を変更できます（ID/PWの設定は不要）。

| 変数 | 既定 | 説明 |
|---|---|---|
| `SERVICE_TYPE` | `smart-ex` | `smart-ex`（スマートEX）/ `expy`（エクスプレス予約） |
| `RECIPIENT_NAME` | `上様` | 領収書の宛名（Web UI のフォームでも上書き可） |
| `OUTPUT_DIR` | デスクトップ | PDF の保存先 |
| `TRAVEL_DATE_INDEX` | `0` | 行内に複数日付がある場合にファイル名へ使う日付の番号 |
| `HEADLESS` | `true` | （CLI `--check` 等向け。実行時はログインのため自動で画面表示） |
| `TIMEOUT` | `30000` | ページ読み込みタイムアウト(ms) |
| `DEBUG` | `false` | 各ステップのスクショ/HTML を `output/` に保存 |

## うまく動かないとき

サイトの仕様変更などで止まる場合は `--debug` を付けて実行し、`output/debug_*.png` /
`output/debug_*.html` を確認して、`config.py` の `SELECTORS`（下表）を調整してください。

```bash
python3 main.py 2026/05 --debug
```

| キー | 用途 |
|---|---|
| `menu_receipt_link` | 会員メニュー →「ご利用履歴・領収書の発行」リンク文言 |
| `filter_start_keywords` / `filter_end_keywords` | 照会期間（From/To）プルダウン |
| `filter_submit_texts` | 照会ボタン（「再検索」など） |
| `receipt_button` | 一覧各行の「領収書表示」ボタン |
| `atena_input` | 明細の宛名入力欄（上段） |
| `print_button` | 明細の「印刷」ボタン |
| `pager_next` | 一覧のページ送り「次へ」 |

- 「ポート 8765 が使用中」: 既存ヘルパーが起動中です。起動スクリプトは自動で停止を試みます。
  手動なら macOS/Linux `lsof -ti:8765 | xargs kill`、Windows `netstat -ano | findstr :8765` → `taskkill /F /PID <番号>`。
- ログイン後に進まない: 会員メニュー（「ご利用履歴・領収書の発行」が見える画面）まで進むと自動検知します（最大5分待機）。

## 構成

```
webapp.py               ローカルWeb UI / API（フォーム→実行→進捗、CORS対応）
docs/index.html         GitHub Pages 用の画面（ローカルヘルパーを呼び出す静的UI）
scripts/setup.*         初回セットアップ（.bat=Win / .command=mac / .sh=Linux）
scripts/start_helper.*  ヘルパー起動（.bat=Win / .command=mac / .sh=Linux）
main.py                 CLI（引数解釈・設定上書き・--check）
pipeline.py             処理の全体フロー（サービスで分岐：JR東海系 / えきねっと）
providers/ekinet.py     えきねっと(JR東日本)のフロー（規約同意→履歴→絞込→領収書DL）
config.py               設定とセレクタ（SELECTORS）の集約／利用可否判定
browser_manager.py      ブラウザ/コンテキスト管理（window.print 無効化）
datetools.py            日本語日付の抽出・解析（ファイル名用）
agents/login_agent.py   手入力ログイン（会員メニュー到達を自動検知）
agents/discovery_agent.py  会員メニュー→一覧 到達・照会(From/To)・領収書表示・戻る
agents/download_agent.py   宛名入力→印刷ポップアップ(正式な領収書)を PDF 化
```

## 注意・免責

- `.env` は秘匿情報です。共有・コミットしないでください（`.gitignore` で除外済み）。
- 本ツールは**自分自身のアカウント**の領収書取得を自動化する目的のものです。
  サイトの利用規約を尊重し、過度なアクセスは避けてください。
- 非公式ツールです。JR東海・スマートEX・エクスプレス予約とは一切関係ありません。
  サイト仕様変更で動作しなくなる場合があります（セレクタは `config.py` に集約）。
- 本ソフトウェアは無保証です。利用は自己責任でお願いします。

## ライセンス

[MIT License](LICENSE)
