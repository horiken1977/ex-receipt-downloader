"""
セッション確立（手入力ログイン方式）。

方針: 資格情報は保持しない。
  1. 保存済みセッション(storage_state)が有効なら、控えておいた会員トップURLを開いて再利用。
  2. 無効/未保存なら、表示されたブラウザでユーザーが手入力ログイン → 完了後に保存。

ensure_session() は「ログイン済みの会員ページ」を返す。呼び出し側はそのページから
メニューをたどって領収書一覧へ進む（公開ガイドページではなく会員メニューを使うため）。

ヘッドレスのまま手入力ログインはできないため、ログインが必要なのに画面が非表示の
場合は ManualLoginRequired を投げる（呼び出し側が画面を出して再試行する）。
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
    """ログイン済みの会員ページを返す。"""
    page = await browser_manager.new_page()

    # 1) 保存済みセッションの再利用（会員トップURLも控えてある場合のみ）
    if config.STATE_FILE.exists() and config.MEMBERS_URL_FILE.exists():
        if await _restore_session(page, service_cfg):
            print("[Login] 保存済みセッションが有効です。ログインをスキップします。")
            return page

    # 2) 手入力ログイン
    if browser_manager.is_headless():
        await page.close()
        raise ManualLoginRequired()

    await _manual_login(page, service_cfg)
    await browser_manager.save_state()
    _save_members_url(page.url)
    return page


async def _restore_session(page: Page, service_cfg: dict) -> bool:
    """控えておいた会員トップURL（無ければログイン入口）を開いてログイン状態を確認。"""
    url = _load_members_url() or service_cfg["login_url"]
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=config.TIMEOUT)
        await page.wait_for_timeout(1500)
    except Exception:
        return False
    return await _looks_logged_in(page)


async def _manual_login(page: Page, service_cfg: dict) -> None:
    print("\n" + "=" * 60)
    print("ログイン: 表示されたブラウザで会員ID・パスワードを手入力してください。")
    print("会員メニューに到達すると自動で検知して続行します（最大5分）。")
    print("=" * 60)
    try:
        await page.goto(service_cfg["login_url"], wait_until="domcontentloaded", timeout=config.TIMEOUT)
    except Exception:
        pass  # 入口URLが変わっていてもユーザーが手動で辿れるよう続行

    if not await _wait_for_login(page):
        raise LoginError("ログインを検知できませんでした（タイムアウト）。再度お試しください。")
    await browser_manager.dump_debug_html(page, "03_after_login")
    print(f"[Login] ログインを検知しました。続行します（URL: {page.url}）")


async def _wait_for_login(page: Page, timeout_sec: int = 300) -> bool:
    """会員メニュー(ClientService)到達をポーリングで検知。CLIでは Enter でも続行可。"""
    import sys
    import time

    enter_task = None
    if sys.stdin and sys.stdin.isatty():
        print("（自動検知されない場合は、このターミナルで Enter を押すと続行します）")
        enter_task = asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            url = (page.url or "").lower()
        except Exception:
            url = ""
        if "clientservice" in url:
            return True
        if enter_task is not None and enter_task.done():
            return True
        await asyncio.sleep(1.5)
    return False


async def _looks_logged_in(page: Page) -> bool:
    """保存セッション再利用時の緩い判定: ログインフォームが出ていなければ有効とみなす。"""
    if "login" in page.url.lower():
        return False
    return not await _has_password_field(page)


async def _has_password_field(page: Page) -> bool:
    try:
        return await page.locator("input[type='password']").count() > 0
    except Exception:
        return False


def _save_members_url(url: str) -> None:
    try:
        config.MEMBERS_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.MEMBERS_URL_FILE.write_text(url, encoding="utf-8")
    except Exception:
        pass


def _load_members_url() -> str:
    try:
        return config.MEMBERS_URL_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
