"""
領収書明細ページの保存。

実サイトの挙動:
  - 一覧で「領収書表示」→ 明細ページ(緑の画面 ⑤)に同一遷移（discovery.click_receipt が担当）。
  - 明細で宛名(上段=i1)を入力し「印刷」を押すと、別ウィンドウ(New_Screen)に
    印刷用の正式な領収書(⑥)が表示される。これを PDF 化するのが正解。

このモジュールは「明細ページ」を受け取り、宛名入力→印刷ボタン→開いたポップアップを
CDP Page.printToPDF で PDF 化し、デスクトップ(OUTPUT_DIR)へ一意名で保存する。
OSのネイティブ印刷ダイアログは自動操作できないため、ダイアログが印刷する対象である
そのポップアップ自体を PDF 化する（結果は同一）。window.print() は固まり防止で無効化済み。
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

import browser_manager
import config
import datetools


class DownloadError(Exception):
    pass

# A4 (インチ)
_A4_W, _A4_H = 8.27, 11.69


async def save_current_receipt(page: Page, recipient_name: str, seq: int) -> Path:
    """明細ページに宛名を入れ、印刷ポップアップ(正式な領収書)を PDF 保存する。"""
    await _fill_recipient(page, recipient_name, seq)
    date_str, amount = await _extract_meta(page)  # 明細から乗車日・金額
    await browser_manager.dump_debug_html(page, f"08b_receipt_{seq:03d}")
    await browser_manager.take_debug_screenshot(page, f"08_receipt_{seq:03d}")

    popup = await _open_print_popup(page)
    target = popup if popup is not None else page
    if popup is None:
        print(f"[Download #{seq:03d}] 警告: 印刷ポップアップが開かず、明細ページをPDF化します。")
    await browser_manager.take_debug_screenshot(target, f"09_print_{seq:03d}")

    file_path = _unique_path(config.OUTPUT_DIR / _build_filename(date_str, amount, seq))
    file_path.write_bytes(await _print_to_pdf(target))

    if popup is not None:
        try:
            await popup.close()
        except Exception:
            pass

    print(f"[Download #{seq:03d}] PDF保存: {file_path.name}")
    return file_path


async def _fill_recipient(page: Page, recipient_name: str, seq: int) -> None:
    for sel in config.SELECTORS["atena_input"]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.fill(recipient_name)
                try:
                    await el.evaluate("e => e.setAttribute('value', e.value)")
                except Exception:
                    pass
                print(f"[Download #{seq:03d}] 宛名入力: {recipient_name}")
                return
        except Exception:
            continue
    print(f"[Download #{seq:03d}] 宛名欄が見つからず（宛名なしで続行）")


async def _open_print_popup(page: Page) -> Optional[Page]:
    """「印刷」を押して開く別ウィンドウ(正式な領収書)を返す。開かなければ None。"""
    try:
        async with page.expect_popup(timeout=15000) as pinfo:
            await _click_print(page)
        popup = await pinfo.value
    except Exception:
        return None

    try:
        await popup.wait_for_load_state("load", timeout=config.TIMEOUT)
    except Exception:
        pass
    # 印刷ウィンドウは開いた後にフォーム送信で領収書本文が流し込まれる。本文待ち。
    try:
        await popup.wait_for_function(
            "() => document.body && "
            "(document.body.innerText.includes('領収書') || document.body.innerText.includes('RECEIPT'))",
            timeout=config.TIMEOUT,
        )
    except Exception:
        await popup.wait_for_timeout(3000)
    await popup.wait_for_timeout(800)
    return popup


async def _click_print(page: Page) -> bool:
    for sel in config.SELECTORS["print_button"]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                return True
        except Exception:
            continue
    raise DownloadError("「印刷」ボタンが見つかりません（SELECTORS['print_button'] を確認）")


async def _extract_meta(page: Page) -> tuple[str, str]:
    """明細ページから乗車日（ファイル名用）と金額を拾う。"""
    try:
        text = await page.inner_text("body")
    except Exception:
        text = ""
    norm = datetools.normalize(text)

    m = re.search(r"乗車日[^0-9]{0,8}(20\d{2}年\d{1,2}月\d{1,2}日)", norm)
    if m:
        date_str = m.group(1)
    else:
        dates = datetools.find_date_tokens(text)
        idx = config.TRAVEL_DATE_INDEX
        date_str = dates[idx] if 0 <= idx < len(dates) else (dates[0] if dates else "")

    a = re.search(r"[¥￥]\s*([\d,]{3,})", norm) or re.search(r"([\d,]{3,})\s*円", norm)
    amount = a.group(1).replace(",", "") if a else ""
    return date_str, amount


async def _print_to_pdf(page: Page) -> bytes:
    """CDP Page.printToPDF。ヘッドレス/ヘッドフルどちらでも動く。"""
    client = await page.context.new_cdp_session(page)
    result = await client.send("Page.printToPDF", {
        "printBackground": True,
        "paperWidth": _A4_W,
        "paperHeight": _A4_H,
        "marginTop": 0.4,
        "marginBottom": 0.4,
        "marginLeft": 0.4,
        "marginRight": 0.4,
        "preferCSSPageSize": True,
    })
    return base64.b64decode(result["data"])


def _build_filename(date_str: str, amount: str, seq: int) -> str:
    d = datetools.parse_date(date_str)
    date_part = d.strftime("%Y%m%d") if d else "日付不明"
    name = f"領収書_{date_part}_{seq:03d}"
    if amount:
        name += f"_{amount}円"
    return re.sub(r'[\\/:*?"<>|]', "_", name) + ".pdf"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 2
    while (parent / f"{stem}_{i}{suffix}").exists():
        i += 1
    return parent / f"{stem}_{i}{suffix}"
