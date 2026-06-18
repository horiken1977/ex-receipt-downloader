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
    print("会員メニューに到達すると自動検知して続行します（最大5分）。")
    print("=" * 60)

    if not await _wait_for_menu(page, timeout_sec=300):
        await browser_manager.dump_debug_html(page, "03_after_login")
        raise LoginError("会員メニューへの到達を検知できませんでした（タイムアウト）。")

    await browser_manager.dump_debug_html(page, "03_after_login")
    print(f"[Login] 会員メニューに到達しました（URL: {page.url}）")
    return page


async def _wait_for_menu(page: Page, timeout_sec: int) -> bool:
    """会員メニュー到達をポーリング検知。CLIでは Enter でも続行可。"""
    import sys
    import time

    enter_task = None
    if sys.stdin and sys.stdin.isatty():
        print("（自動検知されない場合は、このターミナルで Enter を押すと続行します）")
        enter_task = asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if await _at_member_menu(page):
            return True
        if enter_task is not None and enter_task.done():
            return True
        await asyncio.sleep(1.5)
    return False


async def _at_member_menu(page: Page) -> bool:
    """会員メニュー(ClientService)に居り、画面遷移関数が使えるか。"""
    try:
        url = (page.url or "").lower()
    except Exception:
        return False
    if "clientservice" not in url:
        return False
    # エラー/失効ページには cfEXPY_doAction が無い。これで誤検知を防ぐ。
    try:
        return bool(await page.evaluate("typeof cfEXPY_doAction === 'function'"))
    except Exception:
        return False
