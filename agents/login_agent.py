"""
セッション確立（手入力ログイン・ログイン自動検知）。

方針: 資格情報は保持しない。ログイン入口(login_url)を開き、会員メニュー(ClientService)
への到達を自動検知する。
  - 保存済み cookie(storage_state) が有効なら、入口から会員メニューへ自動遷移するので
    手入力なしで続行できる。
  - 無効なら、表示されたブラウザでユーザーがログインする（到達を自動検知）。

「到達」の判定は URL に ClientService を含み、かつページに cfEXPY_doAction（サイトの
画面遷移関数）が定義されていること。これにより、セッション失効時に出る簡易ページを
「ログイン済み」と誤判定しない。

ヘッドレス時は手入力できないため、短時間だけ自動遷移を待ち、ダメなら ManualLoginRequired
を投げる（呼び出し側が画面を表示して再試行する）。
"""
from __future__ import annotations

import asyncio

from playwright.async_api import Page

import browser_manager
import config


class LoginError(Exception):
    pass


class ManualLoginRequired(LoginError):
    """手入力ログインが必要だが、ブラウザが非表示(headless)で実行できない。"""


async def ensure_session(service_cfg: dict) -> Page:
    """会員メニューに到達したログイン済みページを返す。"""
    page = await browser_manager.new_page()
    try:
        await page.goto(service_cfg["login_url"], wait_until="domcontentloaded", timeout=config.TIMEOUT)
    except Exception:
        pass

    if browser_manager.is_headless():
        # 手入力不可。cookie が有効ならメニューへ自動遷移するはず。短時間だけ待つ。
        if await _wait_for_menu(page, timeout_sec=15, allow_enter=False):
            await browser_manager.save_state()
            return page
        await page.close()
        raise ManualLoginRequired()

    print("\n" + "=" * 60)
    print("ログイン: 表示されたブラウザで会員ID・パスワードを手入力してください。")
    print("会員メニューに到達すると自動検知して続行します（最大5分）。")
    print("※保存済みセッションが有効な場合は、自動でメニューに進みます。")
    print("=" * 60)
    if not await _wait_for_menu(page, timeout_sec=300, allow_enter=True):
        await browser_manager.dump_debug_html(page, "03_after_login")
        raise LoginError("会員メニューへの到達を検知できませんでした（タイムアウト）。")

    await browser_manager.dump_debug_html(page, "03_after_login")
    print(f"[Login] 会員メニューに到達しました（URL: {page.url}）")
    await browser_manager.save_state()
    return page


async def _wait_for_menu(page: Page, timeout_sec: int, allow_enter: bool) -> bool:
    """会員メニュー到達をポーリング検知。CLIでは Enter でも続行可。"""
    import sys
    import time

    enter_task = None
    if allow_enter and sys.stdin and sys.stdin.isatty():
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
    # セッション失効時の簡易ページには cfEXPY_doAction が無い。これで誤検知を防ぐ。
    try:
        return bool(await page.evaluate("typeof cfEXPY_doAction === 'function'"))
    except Exception:
        return False
