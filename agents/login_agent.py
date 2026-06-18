"""
セッション確立（毎回まっさらで手入力ログイン）。

方針: cookie の保存・再利用は行わない（古いセッションを読み込むと JR 側で
「お取扱いできませんでした」エラーになるため）。実行ごとにログイン入口を開き、
ユーザーが手入力でログイン → 会員メニュー(ClientService)到達を自動検知して続行する。

「到達」の判定は URL に ClientService を含み、かつページに cfEXPY_doAction（サイトの
画面遷移関数）が定義されていること。これにより、セッション失効/エラー時に出る簡易
ページ（cfEXPY_doAction を持たない）を「ログイン済み」と誤判定しない。
"""
from __future__ import annotations

import asyncio

from playwright.async_api import Page

import browser_manager
import config


class LoginError(Exception):
    pass


async def ensure_session(service_cfg: dict) -> Page:
    """会員メニューに到達したログイン済みページを返す。"""
    page = await browser_manager.new_page()

    if browser_manager.is_headless():
        await page.close()
        raise LoginError("ログインには画面表示が必要です（ヘッドレス不可）。")

    try:
        await page.goto(service_cfg["login_url"], wait_until="domcontentloaded", timeout=config.TIMEOUT)
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("ログイン: 表示されたブラウザで会員ID・パスワードを手入力してください。")
    print("SMS認証（ワンタイムパスワード）が表示されたら、それも入力してください。")
    print("会員メニュー（「ご利用履歴・領収書の発行」が見える画面）に到達すると")
    print("自動検知して続行します（最大5分待機）。手動でEnterを押す必要はありません。")
    print("=" * 60)

    if not await _wait_for_menu(page, timeout_sec=300):
        await browser_manager.dump_debug_html(page, "03_after_login")
        raise LoginError(
            "会員メニューへの到達を検知できませんでした（タイムアウト）。"
            "ログイン後に会員メニュー（メインメニュー）まで進んでいるか確認してください。"
        )

    await browser_manager.dump_debug_html(page, "03_after_login")
    print(f"[Login] 会員メニューに到達しました（URL: {page.url}）")
    return page


async def _wait_for_menu(page: Page, timeout_sec: int) -> bool:
    """会員メニュー（領収書メニューのタイルが出る画面）への到達をポーリング検知する。

    過渡状態やエラー画面で先に進まないよう、Enter による強制続行は行わない。
    """
    import time

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if await _at_member_menu(page):
            return True
        await asyncio.sleep(1.5)
    return False


async def _at_member_menu(page: Page) -> bool:
    """会員メニューに居るか: ClientService の URL ＋ cfEXPY_doAction ＋ 領収書メニュータイル。"""
    try:
        url = (page.url or "").lower()
    except Exception:
        return False
    if "clientservice" not in url:
        return False
    # エラー/過渡ページには cfEXPY_doAction が無い。
    try:
        if not await page.evaluate("typeof cfEXPY_doAction === 'function'"):
            return False
    except Exception:
        return False
    # 「ご利用履歴・領収書の発行」等のメニュータイルが実際に表示されているか。
    for text in config.SELECTORS["menu_receipt_link"]:
        try:
            if await page.locator(f"a:has-text('{text}')").count() > 0:
                return True
        except Exception:
            continue
    return False
