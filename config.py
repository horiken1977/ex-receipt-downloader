"""
設定とサイト固有情報の集約。

セレクタ類は実サイト未検証のため SELECTORS に集約してあります。
実アカウントで動かして合わない場合は、原則ここだけを直せば済むようにしています。
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# 完成した領収書PDFの保存先。既定はデスクトップ。
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(Path.home() / "Desktop"))).expanduser()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# デバッグ用スクショ/HTML の保存先（PDFと混ざらないよう分離）
DEBUG_DIR = BASE_DIR / "output"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# --- 基本設定 -------------------------------------------------------------
# ログインは常に「ブラウザを表示して手入力」。資格情報は保持しない。
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "smart-ex")
# 既定の宛名。自分用の既定は .env の RECIPIENT_NAME で設定（.env は公開されない）。
RECIPIENT_NAME = os.getenv("RECIPIENT_NAME", "上様")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
TIMEOUT = int(os.getenv("TIMEOUT", "30000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# 一覧の各行に複数の日付（利用日・購入日など）が出る場合、ファイル名に使う日付を
# どれにするかのインデックス。0=行の最初に出る日付。--debug でトークンをログ出力。
TRAVEL_DATE_INDEX = int(os.getenv("TRAVEL_DATE_INDEX", "0"))

# --- サービス定義 ---------------------------------------------------------
# login_url は予約システム(RSV_P)のログイン入口。ログイン後に会員メニュー
# (ClientService) へ遷移し、そこから「ご利用履歴・領収書の発行」を辿る。
SERVICE_CONFIGS = {
    "smart-ex": {
        "name": "スマートEX",
        "login_url": "https://shinkansen2.jr-central.co.jp/RSV_P/smart_index.htm",
        "base_url": "https://shinkansen2.jr-central.co.jp",
        # 会員メニュー「ご利用履歴・領収書の発行」の JS アクション（テキストクリックのフォールバック）
        "receipt_menu_action": "RSWP120AIDP010",
    },
    "expy": {
        "name": "エクスプレス予約",
        "login_url": "https://shinkansen1.jr-central.co.jp/RSV_P/index.htm",
        "base_url": "https://shinkansen1.jr-central.co.jp",
        "receipt_menu_action": "",
    },
    # えきねっと(JR東日本)。フローは providers/ekinet.py（JR東海とは別実装）。
    "eki-net": {
        "name": "えきねっと",
        "login_url": "https://www.eki-net.com/Personal/member/wb/Login/Login",
        "base_url": "https://www.eki-net.com",
    },
}

# JR東海(RSV_P)系のサービス。これ以外(eki-net等)は専用プロバイダで処理する。
JR_CENTRAL_SERVICES = ("smart-ex", "expy")


def get_service_config() -> dict:
    return SERVICE_CONFIGS.get(SERVICE_TYPE, SERVICE_CONFIGS["smart-ex"])


# --- セレクタ集約 ---------------------------------------------------------
# すべて「候補リスト」。上から順に試し、最初に一致したものを使う。
# 実サイトで動かして調整する想定。--debug で各ステップの HTML/スクショを出力する。
SELECTORS = {
    # ログイン済み（セッション有効）かどうかを body テキストで判定するキーワード
    "login_success_keywords": ["ログアウト", "マイページ", "ご利用状況", "メインメニュー", "ご利用履歴"],
    # 会員メニューから「ご利用履歴・領収書の発行」へ入るリンク文言
    "menu_receipt_link": [
        "ご利用履歴・領収書の発行",
        "ご利用履歴",
        "領収書の発行",
        "領収書",
    ],
    # ガイド/手順案内など、一覧に到達する前に押す「進む」系ボタン文言
    # （領収書ボタンやメニュー名を誤クリックしないよう、汎用的な進行語のみに限定）
    "proceed_to_list": [
        "同意して進む",
        "同意する",
        "次へ",
        "進む",
    ],
    # 照会期間の日付入力欄。name/id/placeholder を部分一致で探す。
    "filter_start_keywords": ["start", "from", "begin", "fromDate", "開始", "照会開始", "From"],
    "filter_end_keywords": ["end", "to", "finish", "toDate", "終了", "照会終了", "To"],
    # 照会/検索ボタン（実サイトは「再検索」）
    "filter_submit_texts": ["再検索", "照会", "検索", "表示", "絞り込み"],
    # 領収書一覧の各行に出る「領収書表示」ボタン/リンク
    # 注意: メニュータイル「ご利用履歴・領収書の発行」に誤マッチしないよう「領収書表示」に限定。
    "receipt_button": [
        "a:has-text('領収書表示')",
        "button:has-text('領収書表示')",
        "input[value*='領収書表示']",
        "input[type='button'][value*='領収書']",
        "input[type='submit'][value*='領収書']",
    ],
    # ページネーション「次へ」
    "pager_next": [
        "a:has-text('次へ')",
        "a:has-text('次の')",
        "button:has-text('次へ')",
        "a[rel='next']",
    ],
    # 領収書明細の宛名入力欄（実サイトは上段=i1 / 下段=i2。上段に入力する）
    "atena_input": [
        "input[name='i1']",
        "input[placeholder*='宛名']",
        "input[name*='atena']",
        "input[id*='atena']",
        "input[name*='ate']",
    ],
    # 明細の「印刷」ボタン（押すと別ウィンドウに正式な領収書が表示される）
    "print_button": [
        "input[value*='印刷']",
        "input[rel='but-p-1']",
        "button:has-text('印刷')",
        "a:has-text('印刷')",
    ],
}


# --- 利用可否チェック -----------------------------------------------------
class Availability:
    """対象月が照会可能か（サイト制約）を判定した結果。"""

    def __init__(self, ok: bool, reason: str = ""):
        self.ok = ok
        self.reason = reason


def check_month_available(year: int, month: int, today: Optional[datetime.date] = None) -> Availability:
    """
    領収書表示サービスは「予約完了日の翌日〜最大15ヶ月後」まで。
    未来月や15ヶ月超過は不可。
    """
    today = today or datetime.date.today()
    try:
        target_first = datetime.date(year, month, 1)
    except ValueError:
        return Availability(False, f"不正な年月です: {year}/{month}")

    if target_first > datetime.date(today.year, today.month, 1):
        return Availability(False, f"未来の月は照会できません: {year}/{month:02d}")

    months_ago = (today.year - year) * 12 + (today.month - month)
    if months_ago > 15:
        return Availability(False, f"15ヶ月より前のため表示できません: {year}/{month:02d}（{months_ago}ヶ月前）")

    return Availability(True)


def in_maintenance_window(now: Optional[datetime.datetime] = None) -> bool:
    """23:30〜翌5:30 はサイトメンテナンス時間帯で領収書表示が利用不可。"""
    now = now or datetime.datetime.now()
    t = now.time()
    return t >= datetime.time(23, 30) or t < datetime.time(5, 30)
