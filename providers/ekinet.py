"""
えきねっと（JR東日本）から指定月の領収書をダウンロードするプロバイダ。

えきねっとは Akamai のボット対策があり、Playwright が起動した Chromium は遮断される。
そこで「ユーザーの実 Google Chrome を通常起動（automation痕跡なし）」し、CDP で接続して
操作する。Chrome 側は普通のブラウザに見えるため検知を回避しやすい。

フロー（ユーザー指定）:
  1. 実Chromeを --remote-debugging-port 付きで起動し、eki-net トップを開く
  2. ユーザーが自分でログイン（ID/PW＋追加認証）。会員ページ到達を自動検知
  3. 規約合意ページ: 各「同意する」にチェック →「次へ」
  4. JREIDページ:「今は登録しない」
  5. 会員メニュー →「JR切符…確認・払戻・領収書」をクリックして申込履歴へ
  6. 「乗車/取消済の旅程」→ 対象月で絞り込み
  7. 各「ご利用兼領収書を発行する」をクリック → 領収書ファイルが自動ダウンロード（重複は連番）

※ ログイン後ページの DOM は未検証。セレクタは SEL に集約し、--debug で調整する。
"""
from __future__ import annotations

import asyncio
import calendar
import datetime
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from playwright.async_api import Page, async_playwright

import browser_manager
import config

CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
CHROME_PROFILE = Path.home() / ".ex-ekinet-chrome"   # OneDrive外の専用プロファイル
TOP_URL = "https://www.eki-net.com/"

SEL = {
    "url_login": "login",
    "url_agreement": "userruleagreement",
    "url_jreid": "jreid",
    "url_history": "applicationhistorylist",

    "agreement_checkbox": "input[type='checkbox']",
    "agreement_next": ["次へ", "同意して次へ", "次へ進む", "同意する"],
    "jreid_skip": ["今は登録しない", "登録しない", "あとで登録", "スキップ"],
    "history_menu": [
        "JRきっぷ 確認・変更・払戻・領収書",
        "JRきっぷ　確認・変更・払戻・領収書",
        "確認・変更・払戻・領収書",
        "確認・払戻・領収書",
        "申込履歴", "購入履歴", "ご利用履歴",
    ],
    "tab_used_cancelled": ["乗車/取消済の旅程", "乗車・取消済の旅程", "乗車/取消済", "乗車・取消済"],
    "filter_expand": ["表示内容を絞り込む", "絞り込み条件", "絞り込み"],
    "filter_show_all": ["すべて表示", "すべて", "全て表示", "全て"],
    "filter_apply": ["絞り込む", "絞込", "この条件で絞り込む", "検索"],
    "period_start_keys": ["from", "start", "開始", "fromDate", "startDate"],
    "period_end_keys": ["to", "end", "終了", "toDate", "endDate"],
    # 注意: 緩い「領収書」はマイページのメニュー文言に誤マッチするため入れない。
    "receipt_button": [
        "ご利用兼領収書を発行する", "ご利用兼領収書", "領収書を発行する", "領収書を発行", "領収書発行",
    ],
    "pager_next": ["次へ", "次の", ">"],
}


async def run_flow(from_year: int, from_month: int, to_year: int, to_month: int,
                   recipient: str) -> tuple[List[str], List[str]]:
    """実Chromeに CDP 接続し、From年月〜To年月の領収書を全件DLして (成功, 失敗) を返す。"""
    downloaded: List[str] = []
    failed: List[str] = []

    proc = _ensure_chrome_running()  # 残存デバッグChromeを終了し、毎回まっさらに起動
    pw = await async_playwright().start()
    try:
        browser = await _connect(pw)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await _ekinet_page(ctx)
        await _set_download_dir(page)

        await _login(page)
        if not await _reach_history(page):
            await _dump(page, "ek_05_history_not_reached")
            print("[えきねっと] 申込履歴一覧に到達できませんでした。--debug の HTML を確認してください。")
            return downloaded, failed

        await _apply_filter(page, from_year, from_month, to_year, to_month)
        downloaded, failed = await _download_receipts(page)
    finally:
        try:
            await pw.stop()
        except Exception:
            pass
        # 次回接続の競合を避けるため、起動したChromeを終了（プロファイルは残るのでcookieは保持）。
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
    return downloaded, failed


# --- 実Chrome起動 & CDP接続 ----------------------------------------------
def _find_chrome() -> Optional[str]:
    if sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    elif sys.platform == "win32":
        import os
        cands = []
        for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                cands.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    else:
        cands = []
        for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            p = shutil.which(n)
            if p:
                cands.append(p)
    for c in cands:
        if c and Path(c).exists():
            return c
    for n in ("google-chrome", "chrome", "chromium"):
        p = shutil.which(n)
        if p:
            return p
    return None


def _ensure_chrome_running() -> Optional[subprocess.Popen]:
    """残存デバッグChrome(ポート競合)を終了してから、実Chromeを通常起動する。

    既存インスタンスへの再接続は connect_over_cdp が失敗する（Browser context
    management is not supported）ため再利用しない。プロファイルは保持するので
    cookie/ログインは引き継がれる。
    """
    _kill_debug_chrome()

    chrome = _find_chrome()
    if not chrome:
        raise RuntimeError("Google Chrome が見つかりません。Chrome をインストールしてください。")
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={CHROME_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        TOP_URL,
    ]
    print("[えきねっと] 実Chromeを起動します（このウィンドウでログインしてください）。")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _kill_debug_chrome() -> None:
    """デバッグポート(CDP_PORT)を使っている残存Chromeを終了する。"""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                f'netstat -ano | findstr :{CDP_PORT}', shell=True,
                capture_output=True, text=True).stdout
            pids = {ln.split()[-1] for ln in out.splitlines() if "LISTENING" in ln}
            for pid in pids:
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
        else:
            out = subprocess.run(["lsof", "-ti", f"tcp:{CDP_PORT}"],
                                 capture_output=True, text=True).stdout
            for pid in out.split():
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except Exception:
                    pass
        time.sleep(1.2)
    except Exception:
        pass


async def _connect(pw):
    deadline = time.monotonic() + 30
    last = None
    while time.monotonic() < deadline:
        try:
            return await pw.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            last = e
            await asyncio.sleep(0.8)
    raise RuntimeError(f"Chromeのデバッグポートに接続できませんでした: {last}")


async def _ekinet_page(ctx) -> Page:
    for p in ctx.pages:
        try:
            if "eki-net.com" in (p.url or ""):
                return p
        except Exception:
            continue
    if ctx.pages:
        page = ctx.pages[0]
    else:
        page = await ctx.new_page()
    if "eki-net.com" not in (page.url or ""):
        try:
            await page.goto(TOP_URL, wait_until="domcontentloaded", timeout=config.TIMEOUT)
        except Exception:
            pass
    return page


async def _set_download_dir(page: Page) -> None:
    try:
        client = await page.context.new_cdp_session(page)
        await client.send("Browser.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(config.OUTPUT_DIR),
            "eventsEnabled": True,
        })
    except Exception as e:
        print(f"[えきねっと] ダウンロード先設定に失敗（デフォルト保存先になる可能性）: {e}")


# --- 2) ログイン待ち ------------------------------------------------------
async def _login(page: Page) -> None:
    print("\n" + "=" * 60)
    print("えきねっと: 開いた Chrome で、ご自身でログインしてください。")
    print("会員ページに入ると自動で続行します（最大5分待機）。")
    print("=" * 60)
    deadline = time.monotonic() + 300
    warned = False
    while time.monotonic() < deadline:
        if await _is_logged_in(page):
            await page.wait_for_timeout(800)
            print(f"[えきねっと] ログインを検知しました（URL: {page.url}）")
            await _dump(page, "ek_03_after_login")
            return
        if "error" in (page.url or "").lower() and not warned:
            warned = True
            print("[えきねっと] エラー/Access Denied が出た場合は、トップから入り直してください。")
        await asyncio.sleep(1.5)
    await _dump(page, "ek_03_after_login")
    raise RuntimeError("えきねっと: 会員ページ到達を検知できませんでした（タイムアウト）。")


async def _is_logged_in(page: Page) -> bool:
    url = (page.url or "").lower()
    if "login" in url or "error" in url or "denied" in url:
        return False
    if await _has_password(page):
        return False
    if any(k in url for k in ("userruleagreement", "jreid", "applicationhistory", "reserve/wb", "mypage")):
        return True
    if "/member/wb/" in url and "login" not in url:
        return True
    return await _has_text(page, ["ログアウト"])


# --- 3-5) 規約合意/JREID → 履歴 -------------------------------------------
async def _reach_history(page: Page) -> bool:
    last_url = None
    stuck = 0
    for _ in range(12):
        url = (page.url or "").lower()
        stuck = stuck + 1 if url == last_url else 0
        last_url = url

        if await _is_history_page(page):
            return True
        # JREID を先に判定（URLが確実）。規約合意の誤判定を避ける。
        if SEL["url_jreid"] in url or (stuck < 2 and await _is_jreid_page(page)):
            await _handle_jreid(page)
            continue
        if SEL["url_agreement"] in url or (stuck < 2 and await _is_agreement_page(page)):
            await _handle_agreement(page)
            continue
        # マイページ等 → 申込履歴へ（data-urlkey=HistoryList が確実）
        if stuck < 4 and await _click_history_menu(page):
            await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
            await page.wait_for_timeout(1800)
            continue
        break
    return await _is_history_page(page)


async def _click_history_menu(page: Page) -> bool:
    # 実サイト: 「JRきっぷ 確認・変更・払戻・領収書」= a[data-action=TransitionToApplicationHistoryList]
    # （data-urlkey=HistoryList は非表示の内部リンクなので使わない）。表示中のものをクリック。
    for css in ("a[data-action='TransitionToApplicationHistoryList']",
                "[data-action*='ApplicationHistoryList']",
                "a[data-urlkey='HistoryList']"):
        try:
            loc = page.locator(css)
            for i in range(await loc.count()):
                el = loc.nth(i)
                try:
                    if await el.is_visible():
                        await el.click()
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return await _click_text(page, SEL["history_menu"])


async def _is_history_page(page: Page) -> bool:
    # 申込履歴一覧の URL、または「ご利用兼領収書を発行する」等の具体ボタンがあれば履歴。
    if SEL["url_history"] in (page.url or "").lower():
        return True
    return await _has_receipt_buttons(page)


async def _is_agreement_page(page: Page) -> bool:
    if SEL["url_agreement"] in (page.url or "").lower():
        return True
    # 内容判定: チェックボックス＋「次へ」系ボタン＋「規約」が揃うときのみ規約合意とみなす
    # （JREID案内ページ等の誤判定を防ぐ）。
    try:
        if await page.locator(SEL["agreement_checkbox"]).count() == 0:
            return False
        if await _find_text_locator(page, SEL["agreement_next"]) is None:
            return False
        return await _has_text(page, ["規約"])
    except Exception:
        return False


async def _handle_agreement(page: Page) -> None:
    print("[えきねっと] 規約合意: 同意にチェックして次へ。")
    await _dump(page, "ek_04_agreement")
    try:
        boxes = page.locator(SEL["agreement_checkbox"])
        for i in range(await boxes.count()):
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
    print("[えきねっと] JREID案内:「今は登録しない」。")
    await _dump(page, "ek_04b_jreid")
    await _click_text(page, SEL["jreid_skip"])
    await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
    await page.wait_for_timeout(1500)


# --- 6) 絞り込み ----------------------------------------------------------
async def _apply_filter(page: Page, from_year: int, from_month: int,
                        to_year: int, to_month: int) -> None:
    # 履歴一覧がSPA描画されるのを待つ
    for _ in range(20):
        if await _has_receipt_buttons(page) or await _find_text_locator(page, SEL["tab_used_cancelled"]) is not None:
            break
        await page.wait_for_timeout(500)
    await _dump(page, "ek_06_history")

    await _click_text(page, SEL["tab_used_cancelled"])
    await page.wait_for_timeout(1200)
    await _click_text(page, SEL["filter_expand"])
    await page.wait_for_timeout(800)
    await _click_text(page, SEL["filter_show_all"])

    start, end = _date_range(from_year, from_month, to_year, to_month)
    print(f"[えきねっと] 期間: {start} 〜 {end}")
    await _fill_period(page, start, end)

    await _click_text(page, SEL["filter_apply"])
    await page.wait_for_load_state("domcontentloaded", timeout=config.TIMEOUT)
    await page.wait_for_timeout(2000)
    await _dump(page, "ek_07_filtered")


async def _fill_period(page: Page, start_date: str, end_date: str) -> None:
    ok_s = await _fill_by_keys(page, start_date, SEL["period_start_keys"])
    ok_e = await _fill_by_keys(page, end_date, SEL["period_end_keys"])
    if not (ok_s and ok_e):
        try:
            inputs = page.locator("input[type='text'][name], input[type='date'][name]")
            if await inputs.count() >= 2:
                if not ok_s:
                    await inputs.nth(0).fill(start_date)
                if not ok_e:
                    await inputs.nth(1).fill(end_date)
        except Exception:
            pass


# --- 7) 領収書ダウンロード（フォルダ監視方式） ----------------------------
async def _download_receipts(page: Page) -> tuple[List[str], List[str]]:
    downloaded: List[str] = []
    failed: List[str] = []
    seq = 0
    page_no = 1

    while True:
        sel = await _winning_receipt_selector(page)
        count = await page.locator(sel).count() if sel else 0
        print(f"[えきねっと] {page_no}ページ目: 領収書 {count} 件")
        if not sel or count == 0:
            if page_no == 1:
                await _dump(page, "ek_08_no_receipts")
            break

        for i in range(count):
            seq += 1
            try:
                path = await _click_and_capture(page, page.locator(sel).nth(i), seq)
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


async def _click_and_capture(page: Page, button, seq: int) -> Path:
    """発行ボタンをクリックし、(a)ダウンロードされたファイル or (b)別タブPDF を保存する。"""
    before = {p.name for p in config.OUTPUT_DIR.glob("*")}
    pages_before = set(page.context.pages)
    await button.click()

    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        newf = _newest_new_file(config.OUTPUT_DIR, before)
        if newf is not None:
            return newf
        new_pages = [p for p in page.context.pages if p not in pages_before]
        if new_pages:
            pop = new_pages[0]
            try:
                await pop.wait_for_load_state("load", timeout=8000)
            except Exception:
                pass
            await pop.wait_for_timeout(1000)
            # ダウンロードに転じるか待つ
            nf = _newest_new_file(config.OUTPUT_DIR, before)
            if nf is not None:
                try:
                    await pop.close()
                except Exception:
                    pass
                return nf
            path = _unique_path(config.OUTPUT_DIR / f"領収書_{seq:03d}.pdf")
            path.write_bytes(await _print_to_pdf(pop))
            try:
                await pop.close()
            except Exception:
                pass
            return path
        await asyncio.sleep(0.6)
    raise RuntimeError("ダウンロード/PDFを検知できませんでした")


def _newest_new_file(folder: Path, before: set) -> Optional[Path]:
    try:
        files = [p for p in folder.glob("*") if p.is_file()]
    except Exception:
        return None
    cand = [p for p in files if p.name not in before and not p.name.endswith(".crdownload")]
    if not cand:
        return None
    return max(cand, key=lambda p: p.stat().st_mtime)


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
def _date_range(from_year: int, from_month: int, to_year: int, to_month: int) -> tuple[str, str]:
    """From年月の初日 〜 To年月の末日（当月は今日でクランプ）。"""
    last = calendar.monthrange(to_year, to_month)[1]
    start = datetime.date(from_year, from_month, 1)
    end = datetime.date(to_year, to_month, last)
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
