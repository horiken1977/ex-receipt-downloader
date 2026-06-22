"""
えきねっと（JR東日本）から指定月の領収書をダウンロードするプロバイダ。

ユーザー指定のフロー:
  1. ログインページを開く
  2. ユーザーが ID/PW を手入力してログイン（必要なら追加認証も）
  3. 規約合意ページ（UserRuleAgreement）: 各「同意する」にチェック →「次へ」
  4. JREIDページ（JreidAnnounce）:「今は登録しない」
  5. 申込履歴一覧（ApplicationHistoryList）へ
  6. 「乗車/取消済の旅程」→「表示内容を絞り込む」をすべて表示、「期間」を対象月にして「絞り込む」
  7. 各行の「ご利用兼領収書を発行する」をクリック → 領収書ファイルが自動ダウンロード
     （同名はファイル名を変えて保存）。表示分すべてを繰り返す。

※ 実サイトの DOM は未検証。セレクタは下記 SEL に集約し、--debug の HTML/スクショで調整する。
"""
from __future__ import annotations

import asyncio
import calendar
import datetime
import re
from pathlib import Path
from typing import List, Optional

from playwright.async_api import Page

import browser_manager
import config

# --- えきねっと用セレクタ/URL（要・実DOM調整） ----------------------------
SEL = {
    "login_url": "https://www.eki-net.com/Personal/member/wb/Login/Login",
    "history_url": "https://www.eki-net.com/Personal/reserve/wb/ApplicationHistoryList/Index",

    # ページ判定（URL の部分一致）
    "url_login": "login",
    "url_agreement": "userruleagreement",
    "url_jreid": "jreid",
    "url_history": "applicationhistorylist",

    # 規約合意ページ
    "agreement_checkbox": "input[type='checkbox']",
    "agreement_next": ["次へ", "同意して次へ", "次へ進む", "同意する"],

    # JREID 案内ページ
    "jreid_skip": ["今は登録しない", "登録しない", "あとで登録", "スキップ"],

    # 履歴一覧: タブ・絞り込み
    "tab_used_cancelled": ["乗車/取消済の旅程", "乗車・取消済の旅程", "乗車/取消済", "乗車・取消済"],
    "filter_expand": ["表示内容を絞り込む", "絞り込み条件", "絞り込み"],
    "filter_show_all": ["すべて表示", "すべて", "全て表示", "全て"],
    "filter_apply": ["絞り込む", "絞込", "この条件で絞り込む", "検索"],
    # 期間の日付入力欄（name/id/placeholder 部分一致）
    "period_start_keys": ["from", "start", "開始", "fromDate", "startDate"],
    "period_end_keys": ["to", "end", "終了", "toDate", "endDate"],

    # 領収書発行ボタン
    "receipt_button": [
        "ご利用兼領収書を発行する",
        "ご利用兼領収書",
        "領収書を発行",
        "領収書発行",
        "領収書",
    ],
    # ページ送り
    "pager_next": ["次へ", "次の", ">"],
}


async def run_flow(year: int, month: int, recipient: str) -> tuple[List[str], List[str]]:
    """えきねっとから対象月の領収書を全件ダウンロードし、(成功パス, 失敗ラベル) を返す。"""
    downloaded: List[str] = []
    failed: List[str] = []

    page = await browser_manager.new_page()

    # 2) 手入力ログイン
    await _login(page)

    # 3-5) 規約合意 / JREID を捌いて履歴一覧へ
    if not await _reach_history(page):
        await _dump(page, "ek_05_history_not_reached")
        print("[えきねっと] 申込履歴一覧に到達できませんでした。--debug の HTML を確認してください。")
        return downloaded, failed

    # 6) 乗車/取消済タブ + 絞り込み（すべて表示 + 対象月）
    await _apply_filter(page, year, month)

    # 7) 領収書を順にダウンロード
    downloaded, failed = await _download_receipts(page)
    return downloaded, failed


# --- 2) ログイン ----------------------------------------------------------
async def _login(page: Page) -> None:
    print("\n" + "=" * 60)
    print("えきねっと ログイン: 表示されたブラウザで ID・パスワードを手入力してください。")
    print("ログイン後、画面が切り替われば自動で続行します（最大5分待機）。")
    print("=" * 60)

    # bot検知対策: まず eki-net トップに寄って保護用JS/cookieを通してからログインページへ。
    try:
        await page.goto("https://www.eki-net.com/", wait_until="domcontentloaded", timeout=config.TIMEOUT)
        await page.wait_for_timeout(2500)
    except Exception:
        pass
    try:
        await page.goto(SEL["login_url"], wait_until="domcontentloaded", timeout=config.TIMEOUT)
    except Exception:
        pass

    import time
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        url = (page.url or "").lower()
        if "error" in url:
            await _dump(page, "ek_03_after_login")
            raise RuntimeError(
                "えきねっとがエラーページ（ご確認ください）を表示しました。"
                "ボット検知の可能性があります（output/debug_ek_03_after_login.html を確認）。"
            )
        # ログインページを離れ、パスワード欄が無くなれば「ログイン済み」とみなす
        if SEL["url_login"] not in url and not await _has_password(page):
            await page.wait_for_timeout(800)
            if "error" in (page.url or "").lower():
                continue
            print(f"[えきねっと] ログインを検知しました（URL: {page.url}）")
            await _dump(page, "ek_03_after_login")
            return
        await asyncio.sleep(1.5)
    raise RuntimeError("えきねっと: ログインを検知できませんでした（タイムアウト）。")


# --- 3-5) 規約合意/JREIDを捌いて履歴一覧へ --------------------------------
async def _reach_history(page: Page) -> bool:
    for _ in range(6):
        url = (page.url or "").lower()

        if SEL["url_agreement"] in url or await _is_agreement_page(page):
            await _handle_agreement(page)
            continue
        if SEL["url_jreid"] in url or await _is_jreid_page(page):
            await _handle_jreid(page)
            continue
        if await _has_receipt_buttons(page) or SEL["url_history"] in url:
            return True

        # まだ履歴でなければ、履歴一覧URLへ移動を試す
        try:
            await page.goto(SEL["history_url"], wait_until="domcontentloaded", timeout=config.TIMEOUT)
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        # 移動先が規約/JREIDなら次ループで処理。履歴なら下で確定。
        url2 = (page.url or "").lower()
        if SEL["url_history"] in url2 and not await _is_agreement_page(page):
            return True

    return SEL["url_history"] in (page.url or "").lower()


async def _is_agreement_page(page: Page) -> bool:
    if SEL["url_agreement"] in (page.url or "").lower():
        return True
    try:
        return await page.locator(SEL["agreement_checkbox"]).count() > 0 and \
            await _has_text(page, ["規約", "同意"])
    except Exception:
        return False


async def _handle_agreement(page: Page) -> None:
    print("[えきねっと] 規約合意ページ: 同意にチェックして次へ進みます。")
    await _dump(page, "ek_04_agreement")
    # すべてのチェックボックスを ON
    try:
        boxes = page.locator(SEL["agreement_checkbox"])
        n = await boxes.count()
        for i in range(n):
            try:
                await boxes.nth(i).check(timeout=3000)
            except Exception:
                try:
                    await boxes.nth(i).click(timeout=3000)
                except Exception:
                    pass
    except Exception:
        pass
    await _click_text(page, SEL["agreement_next"])
    await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
    await page.wait_for_timeout(1500)


async def _is_jreid_page(page: Page) -> bool:
    if SEL["url_jreid"] in (page.url or "").lower():
        return True
    return await _has_text(page, ["JRE", "登録"]) and await _find_text_locator(page, SEL["jreid_skip"]) is not None


async def _handle_jreid(page: Page) -> None:
    print("[えきねっと] JREID案内ページ: 「今は登録しない」を選びます。")
    await _dump(page, "ek_04b_jreid")
    await _click_text(page, SEL["jreid_skip"])
    await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
    await page.wait_for_timeout(1500)


# --- 6) 絞り込み ----------------------------------------------------------
async def _apply_filter(page: Page, year: int, month: int) -> None:
    await _dump(page, "ek_06_history")
    # 「乗車/取消済の旅程」タブ
    await _click_text(page, SEL["tab_used_cancelled"])
    await page.wait_for_timeout(1200)

    # 「表示内容を絞り込む」を開く（折りたたみUIの場合）
    await _click_text(page, SEL["filter_expand"])
    await page.wait_for_timeout(800)

    # 「すべて表示」
    await _click_text(page, SEL["filter_show_all"])

    # 期間（対象月の初日〜末日）
    start, end = _month_range(year, month)
    print(f"[えきねっと] 期間: {start} 〜 {end}")
    await _fill_period(page, start, end)

    # 「絞り込む」
    await _click_text(page, SEL["filter_apply"])
    await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
    await page.wait_for_timeout(2000)
    await _dump(page, "ek_07_filtered")


async def _fill_period(page: Page, start_date: str, end_date: str) -> None:
    ok_s = await _fill_by_keys(page, start_date, SEL["period_start_keys"])
    ok_e = await _fill_by_keys(page, end_date, SEL["period_end_keys"])
    if not (ok_s and ok_e):
        # フォールバック: 可視テキスト入力欄を先頭から2つ
        try:
            inputs = page.locator("input[type='text'][name], input[type='date'][name]")
            cnt = await inputs.count()
            if cnt >= 2:
                if not ok_s:
                    await inputs.nth(0).fill(start_date)
                if not ok_e:
                    await inputs.nth(1).fill(end_date)
        except Exception:
            pass


# --- 7) 領収書ダウンロード ------------------------------------------------
async def _download_receipts(page: Page) -> tuple[List[str], List[str]]:
    downloaded: List[str] = []
    failed: List[str] = []
    seq = 0
    page_no = 1

    while True:
        sel = await _winning_receipt_selector(page)
        count = await page.locator(sel).count() if sel else 0
        print(f"[えきねっと] {page_no}ページ目: 領収書 {count} 件")
        if sel is None or count == 0:
            if page_no == 1:
                await _dump(page, "ek_08_no_receipts")
            break

        for i in range(count):
            seq += 1
            btn = page.locator(sel).nth(i)
            try:
                path = await _click_and_save(page, btn, seq)
                downloaded.append(str(path))
                print(f"[えきねっと #{seq:03d}] 保存: {Path(path).name}")
            except Exception as e:
                failed.append(f"p{page_no}/{i}")
                print(f"[えきねっと #{seq:03d}] 失敗 (p{page_no}/{i}): {e}")
            await page.wait_for_timeout(600)

        if not await _go_next_page(page):
            break
        page_no += 1
        await page.wait_for_timeout(1500)

    return downloaded, failed


async def _click_and_save(page: Page, button, seq: int) -> Path:
    """発行ボタンをクリックし、ダウンロード(添付) or 別タブPDF を保存する。"""
    # まず通常のファイルダウンロードを期待
    try:
        async with page.expect_download(timeout=15000) as di:
            await button.click()
        dl = await di.value
        name = dl.suggested_filename or f"領収書_{seq:03d}.pdf"
        path = _unique_path(config.OUTPUT_DIR / _sanitize(name))
        await dl.save_as(str(path))
        return path
    except Exception:
        pass

    # 別タブ(PDFビューア)で開くタイプ → そのページを printToPDF
    try:
        async with page.expect_popup(timeout=8000) as pi:
            await button.click()
        popup = await pi.value
        await popup.wait_for_load_state("load", timeout=config.TIMEOUT)
        await popup.wait_for_timeout(1500)
        path = _unique_path(config.OUTPUT_DIR / f"領収書_{seq:03d}.pdf")
        path.write_bytes(await _print_to_pdf(popup))
        try:
            await popup.close()
        except Exception:
            pass
        return path
    except Exception as e:
        raise RuntimeError(f"ダウンロードを検知できませんでした: {e}")


async def _print_to_pdf(page: Page) -> bytes:
    import base64
    client = await page.context.new_cdp_session(page)
    result = await client.send("Page.printToPDF", {
        "printBackground": True, "paperWidth": 8.27, "paperHeight": 11.69,
        "marginTop": 0.4, "marginBottom": 0.4, "marginLeft": 0.4, "marginRight": 0.4,
        "preferCSSPageSize": True,
    })
    return base64.b64decode(result["data"])


# --- helpers --------------------------------------------------------------
def _month_range(year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    start = datetime.date(year, month, 1)
    end = datetime.date(year, month, last)
    today = datetime.date.today()
    if end > today:
        end = today
    return start.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d")


async def _winning_receipt_selector(page: Page) -> Optional[str]:
    for text in SEL["receipt_button"]:
        for css in (
            f"a:has-text('{text}')",
            f"button:has-text('{text}')",
            f"input[type='submit'][value*='{text}']",
            f"input[type='button'][value*='{text}']",
        ):
            try:
                if await page.locator(css).count() > 0:
                    return css
            except Exception:
                continue
    return None


async def _has_receipt_buttons(page: Page) -> bool:
    return await _winning_receipt_selector(page) is not None


async def _go_next_page(page: Page) -> bool:
    for text in SEL["pager_next"]:
        try:
            el = page.locator(f"a:has-text('{text}'), button:has-text('{text}')").first
            if await el.count() > 0 and await el.is_enabled():
                await el.click()
                await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
                return True
        except Exception:
            continue
    return False


async def _click_text(page: Page, texts: List[str]) -> bool:
    loc = await _find_text_locator(page, texts)
    if loc is not None:
        try:
            await loc.click()
            return True
        except Exception:
            return False
    return False


async def _find_text_locator(page: Page, texts: List[str]):
    for text in texts:
        try:
            el = page.get_by_role("link", name=text)
            if await el.count() == 0:
                el = page.locator(
                    f"a:has-text('{text}'), button:has-text('{text}'), "
                    f"input[type='submit'][value*='{text}'], input[type='button'][value*='{text}']"
                )
            if await el.count() == 0:
                el = page.get_by_text(text, exact=False)
            if await el.count() > 0:
                return el.first
        except Exception:
            continue
    return None


async def _fill_by_keys(page: Page, value: str, keys: List[str]) -> bool:
    for kw in keys:
        for attr in ("name", "id", "placeholder"):
            try:
                el = page.locator(f"input[{attr}*='{kw}']").first
                if await el.count() > 0:
                    await el.fill(value)
                    return True
            except Exception:
                continue
    return False


async def _has_password(page: Page) -> bool:
    try:
        return await page.locator("input[type='password']").count() > 0
    except Exception:
        return False


async def _has_text(page: Page, words: List[str]) -> bool:
    try:
        body = await page.inner_text("body")
    except Exception:
        return False
    return any(w in body for w in words)


def _sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 2
    while (parent / f"{stem}_{i}{suffix}").exists():
        i += 1
    return parent / f"{stem}_{i}{suffix}"


async def _dump(page: Page, name: str) -> None:
    await browser_manager.take_debug_screenshot(page, name)
    await browser_manager.dump_debug_html(page, name)
