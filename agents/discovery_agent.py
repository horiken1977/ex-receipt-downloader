"""
領収書一覧への到達と、各領収書の表示操作。

実サイト(スマートEX / RSV_P)の実装:
  - ログイン後の会員メニュー ClientService から「ご利用履歴・領収書の発行」
    (<a onclick="cfEXPY_doAction('RSWP120AIDP010')">) で一覧へ。
  - 一覧は対象月を <select> プルダウンで選び照会。
  - 各行の「領収書表示」は <input type=submit value=領収書表示
    onclick="jmpsel=i; cfEXPY_doAction('RSWP360AIDP043')"> で、押すと同一ページが
    明細へ遷移する（ポップアップではない）。そのため1件ごとに一覧へ戻る必要がある。

フレームセット対策: RSV_P は画面によってフレームセットを使い、一覧や照会プルダウンが
子フレーム内に置かれることがある。`page.locator` はメインフレームしか探さないため、
要素の探索・クリックは「メインフレーム→各子フレーム」の順に全フレームを横断する
（`_frames()`）。最初に見つかったフレーム上で操作する。

セレクタは config.SELECTORS に集約。
"""
from __future__ import annotations

import calendar
import datetime
from typing import List, Optional, Tuple

from playwright.async_api import Frame, Page

import browser_manager
import config
import datetools


def date_range(from_year: int, from_month: int, to_year: int, to_month: int) -> tuple[str, str]:
    """From年月の初日 〜 To年月の末日(YYYY/MM/DD)。当月は末日を今日でクランプ。"""
    last_day = calendar.monthrange(to_year, to_month)[1]
    start = datetime.date(from_year, from_month, 1)
    end = datetime.date(to_year, to_month, last_day)
    today = datetime.date.today()
    if end > today:
        end = today
    return start.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d")


async def open_and_filter(page: Page, from_year: int, from_month: int,
                          to_year: int, to_month: int) -> None:
    """会員メニュー→一覧へ到達し、From年月初日〜To年月末日をプルダウンで選んで照会する。"""
    reached = await _navigate_to_list(page)
    if not reached:
        await _log_frames(page, "一覧未到達")
        await browser_manager.take_debug_screenshot(page, "04b_list_not_reached", force=True)
        await browser_manager.dump_debug_html(page, "04b_list_not_reached", force=True)
        print("[Discovery] 一覧画面に到達できませんでした。output/debug_04b_list_not_reached*.html "
              "を確認し SELECTORS['menu_receipt_link'] を調整してください。")

    print(f"[Discovery] 照会対象: {from_year}年{from_month:02d}月 〜 {to_year}年{to_month:02d}月")
    await _set_date_filter(page, from_year, from_month, to_year, to_month)
    await browser_manager.take_debug_screenshot(page, "05_receipt_filtered")
    await browser_manager.dump_debug_html(page, "05_receipt_filtered")


async def count_receipts(page: Page) -> int:
    """現在の一覧ページにある「領収書表示」ボタン数。"""
    fr, sel = await _winning_button(page)
    if sel is None:
        return 0
    try:
        return await fr.locator(sel).count()
    except Exception:
        return 0


async def click_receipt(page: Page, index: int) -> bool:
    """一覧の index 番目の「領収書表示」を押して明細へ遷移する。"""
    fr, sel = await _winning_button(page)
    if sel is None:
        return False
    buttons = fr.locator(sel)
    if await buttons.count() <= index:
        return False
    await buttons.nth(index).click()
    await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
    await page.wait_for_timeout(1500)
    return True


async def return_to_list(page: Page, from_year: int, from_month: int,
                         to_year: int, to_month: int) -> bool:
    """明細ページから一覧へ戻る。戻るボタン→ブラウザバック→再照会の順で試す。"""
    # 1) 明細ページの「戻る」系ボタン
    for text in ["一覧へ戻る", "ご利用履歴に戻る", "ご利用履歴へ戻る", "戻る"]:
        if await _click_by_text(page, [text]):
            await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
            await page.wait_for_timeout(1200)
            if await _has_receipt_buttons(page):
                return True
            break
    # 2) ブラウザバック（POST結果のキャッシュ復帰を期待）
    try:
        await page.go_back(wait_until="domcontentloaded", timeout=config.TIMEOUT)
        await page.wait_for_timeout(1200)
        if await _has_receipt_buttons(page):
            return True
    except Exception:
        pass
    # 3) 最終手段: メニューから再照会（ページ位置は1ページ目に戻る点に注意）
    await open_and_filter(page, from_year, from_month, to_year, to_month)
    return await _has_receipt_buttons(page)


async def go_to_next_page(page: Page) -> bool:
    for fr in _frames(page):
        for sel in config.SELECTORS["pager_next"]:
            try:
                el = fr.locator(sel).first
                if await el.count() > 0 and await el.is_enabled():
                    await el.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
                    await page.wait_for_timeout(1200)
                    return True
            except Exception:
                continue
    return False


# --- フレーム横断ヘルパー --------------------------------------------------
def _frames(page: Page) -> List[Frame]:
    """探索対象フレームを「メインフレーム→子フレーム」の順で返す（フレームセット対応）。"""
    try:
        frames = list(page.frames)  # frames[0] がメインフレーム
        return frames if frames else [page.main_frame]
    except Exception:
        return [page.main_frame]


async def _log_frames(page: Page, label: str) -> None:
    """失敗診断用に、現在のフレーム構成（URL）を出力する。"""
    try:
        urls = [f.url for f in page.frames]
    except Exception:
        urls = []
    print(f"[Discovery] {label}: フレーム数={len(urls)} -> " + " | ".join(urls))


# --- 一覧への到達 ---------------------------------------------------------
async def _navigate_to_list(page: Page) -> bool:
    if await _is_list_page(page):
        return True

    await browser_manager.take_debug_screenshot(page, "03b_members_menu")
    await browser_manager.dump_debug_html(page, "03b_members_menu")

    # メニュー「ご利用履歴・領収書の発行」。テキストで押せなければ JS アクションで。
    clicked = await _click_by_text(page, config.SELECTORS["menu_receipt_link"])
    if not clicked:
        action = config.get_service_config().get("receipt_menu_action")
        if action:
            # cfEXPY_doAction が定義されているフレームで実行する。
            for fr in _frames(page):
                try:
                    if await fr.evaluate("typeof cfEXPY_doAction === 'function'"):
                        await fr.evaluate(f"cfEXPY_doAction('{action}')")
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                print(f"[Discovery] メニューJSアクションを実行できませんでした（cfEXPY_doAction 未検出）")
    if clicked:
        await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
        await page.wait_for_timeout(1800)
    await browser_manager.take_debug_screenshot(page, "04_after_menu")
    await browser_manager.dump_debug_html(page, "04_after_menu")

    # ガイド画面が挟まる場合のみ「進む」系
    for _ in range(3):
        if await _is_list_page(page):
            return True
        if not await _click_by_text(page, config.SELECTORS["proceed_to_list"]):
            break
        await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
        await page.wait_for_timeout(1500)

    return await _is_list_page(page)


async def _is_list_page(page: Page) -> bool:
    return (await _has_receipt_buttons(page)
            or await _has_month_pulldown(page)
            or await _has_date_filter(page))


async def _has_month_pulldown(page: Page) -> bool:
    import re as _re
    for fr in _frames(page):
        try:
            selects = fr.locator("select")
            n = await selects.count()
        except Exception:
            continue
        for i in range(n):
            for o in await _option_texts(selects.nth(i)):
                no = datetools.normalize(o)
                if _re.search(r"20\d{2}", no) or "年" in no or "月" in no:
                    return True
    return False


# --- 照会期間の入力（From/To 各 年月+日 の4プルダウン） -------------------
async def _set_date_filter(page: Page, from_year: int, from_month: int,
                           to_year: int, to_month: int) -> None:
    """照会期間を「From年月の初日 〜 To年月の末日」に設定して再検索する。

    実サイト: sel-1=From年月, sel-2=From日, sel-3=To年月, sel-4=To日。
    名前に依存せず、選択肢の内容で「年月select」「日select」を判別し、出現順に
    From→To として設定する。プルダウンが子フレームにある場合に備え、全フレームを
    横断して「年月select を持つフレーム」を採用する。
    """
    from_ym = f"{from_year}年{from_month}月"
    to_ym = f"{to_year}年{to_month}月"
    last = calendar.monthrange(to_year, to_month)[1]

    # 年月select を含むフレームを探す（無ければ最後に走査したフレームを使う）。
    target_fr: Optional[Frame] = None
    selects = None
    ym_idx: List[int] = []
    day_idx: List[int] = []
    for fr in _frames(page):
        try:
            s = fr.locator("select")
            n = await s.count()
        except Exception:
            continue
        yi: List[int] = []
        di: List[int] = []
        for i in range(n):
            joined = "".join(await _option_texts(s.nth(i)))
            if "年" in joined and "月" in joined:
                yi.append(i)
            elif "日" in joined:
                di.append(i)
        if yi:  # 年月プルダウンがあるフレームを採用して打ち切る
            target_fr, selects, ym_idx, day_idx = fr, s, yi, di
            break

    done = False
    if selects is not None and len(ym_idx) >= 2 and len(day_idx) >= 2:
        a = await _select_label(selects.nth(ym_idx[0]), from_ym)        # From 年月
        b = await _select_label(selects.nth(day_idx[0]), "1日")          # From 日
        c = await _select_label(selects.nth(ym_idx[1]), to_ym)          # To 年月
        d = await _select_label(selects.nth(day_idx[1]), f"{last}日")    # To 日
        done = a and b and c and d
        if done:
            print(f"[Discovery] 照会期間設定: {from_ym}1日 〜 {to_ym}{last}日")
    elif selects is not None and ym_idx:
        done = await _select_label(selects.nth(ym_idx[0]), from_ym)

    if not done:
        await _log_frames(page, "プルダウン未検出")
        await browser_manager.dump_debug_html(page, "05a_filter_not_found", force=True)
        await browser_manager.take_debug_screenshot(page, "05a_filter_not_found", force=True)
        print("[Discovery] 照会期間プルダウンを設定できませんでした。"
              "output/debug_05a_filter_not_found*.html を確認してください。")

    # 「再検索」は同じフレーム（無ければ全フレーム）で押す。
    await _click_first_text(target_fr or page, config.SELECTORS["filter_submit_texts"])
    await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
    await page.wait_for_timeout(2000)


async def _select_label(select, label: str) -> bool:
    """select の選択肢から label に一致（完全一致優先、無ければ部分一致）するものを選ぶ。"""
    opts = [datetools.normalize(o).strip() for o in await _option_texts(select)]
    for idx, o in enumerate(opts):
        if o == label:
            await select.select_option(index=idx)
            return True
    for idx, o in enumerate(opts):
        if label in o:
            await select.select_option(index=idx)
            return True
    return False


async def _option_texts(select) -> List[str]:
    try:
        return await select.locator("option").all_text_contents()
    except Exception:
        return []


# --- helpers --------------------------------------------------------------
async def _winning_button(page: Page) -> Tuple[Optional[Frame], Optional[str]]:
    """「領収書表示」ボタンを持つ (フレーム, セレクタ) を返す。無ければ (None, None)。"""
    for fr in _frames(page):
        for sel in config.SELECTORS["receipt_button"]:
            try:
                if await fr.locator(sel).count() > 0:
                    return fr, sel
            except Exception:
                continue
    return None, None


async def _has_receipt_buttons(page: Page) -> bool:
    _, sel = await _winning_button(page)
    return sel is not None


async def _has_date_filter(page: Page) -> bool:
    for fr in _frames(page):
        for kw in config.SELECTORS["filter_start_keywords"]:
            for attr in ("name", "id", "placeholder"):
                try:
                    if await fr.locator(f"input[{attr}*='{kw}']").count() > 0:
                        return True
                except Exception:
                    continue
    return False


async def _click_by_text(root, texts: List[str]) -> bool:
    """テキスト一致するリンク/ボタン/タイルを上から順に1つだけクリックする。

    root には Page または Frame を渡せる。Page の場合は全フレームを横断して探す。
    """
    roots = _frames(root) if isinstance(root, Page) else [root]
    for fr in roots:
        for text in texts:
            try:
                link = fr.get_by_role("link", name=text)
                if await link.count() == 0:
                    link = fr.locator(
                        f"a:has-text('{text}'), button:has-text('{text}'), "
                        f"input[type='submit'][value*='{text}'], input[type='button'][value*='{text}']"
                    )
                if await link.count() == 0:
                    link = fr.get_by_text(text, exact=False)
                if await link.count() > 0:
                    await link.first.click()
                    return True
            except Exception:
                continue
    return False


async def _click_first_text(root, texts: List[str]) -> bool:
    if await _click_by_text(root, texts):
        return True
    roots = _frames(root) if isinstance(root, Page) else [root]
    for fr in roots:
        try:
            el = fr.locator("input[type='submit'], button[type='submit']").first
            if await el.count() > 0:
                await el.click()
                return True
        except Exception:
            continue
    return False
