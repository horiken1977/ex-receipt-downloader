"""
Playwright のブラウザ/コンテキストを 1 つだけ管理する。

JR系サイトはサーバ側に画面遷移状態を持つため、単一コンテキストを逐次的に使う。

セッションの保存・再利用(storage_state)は行わない。古い cookie を読み込むと
ログイン時にサーバが「お取扱いできませんでした」エラーになるため、毎回まっさらな
コンテキストでログインする。
"""
from __future__ import annotations

from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

import config

_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_headless: bool = True

_CONTEXT_KWARGS = dict(
    viewport={"width": 1280, "height": 900},
    locale="ja-JP",
    timezone_id="Asia/Tokyo",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    accept_downloads=True,
)


async def start(headless: Optional[bool] = None) -> BrowserContext:
    """ブラウザを起動し、まっさらな単一コンテキストを返す（cookie再利用なし）。

    headless を省略すると config.HEADLESS に従う。ログイン時は呼び出し側が
    headless=False を指定する。
    """
    global _playwright, _browser, _context, _headless
    _headless = config.HEADLESS if headless is None else headless
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(
        headless=_headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    _context = await _browser.new_context(**_CONTEXT_KWARGS)
    _context.set_default_timeout(config.TIMEOUT)
    # 「印刷」操作で OS の印刷ダイアログが開くと自動化が固まるため無効化しておく。
    # 領収書PDFは Page.printToPDF で別途生成する。
    await _context.add_init_script("window.print = function () {};")
    return _context


def context() -> BrowserContext:
    assert _context is not None, "Browser not started. Call start() first."
    return _context


def is_headless() -> bool:
    return _headless


async def new_page() -> Page:
    return await context().new_page()


async def stop() -> None:
    global _playwright, _browser, _context
    if _context:
        await _context.close()
        _context = None
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


async def take_debug_screenshot(page: Page, name: str) -> None:
    if config.DEBUG:
        path = config.DEBUG_DIR / f"debug_{name}.png"
        try:
            await page.screenshot(path=str(path), full_page=True)
            print(f"[DEBUG] スクリーンショット保存: {path}")
        except Exception as e:  # ページが閉じている等
            print(f"[DEBUG] スクリーンショット失敗 ({name}): {e}")


async def dump_debug_html(page: Page, name: str) -> None:
    """セレクタ調整用に現在ページの HTML を保存する（--debug 時のみ）。"""
    if config.DEBUG:
        path = config.DEBUG_DIR / f"debug_{name}.html"
        try:
            html = await page.content()
            path.write_text(html, encoding="utf-8")
            print(f"[DEBUG] HTML保存: {path}")
        except Exception as e:
            print(f"[DEBUG] HTML保存失敗 ({name}): {e}")
