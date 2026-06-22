#!/usr/bin/env python3
"""
EX予約 / スマートEX 領収書ダウンロードツール

指定した月の領収書を、照会期間に「その月の初日〜末日」を入力して全件 PDF で保存します。
PDF は既定でデスクトップに、ファイル名を個別（一意）にして保存します。

ログインは資格情報を保存せず、ブラウザを表示して手入力で行います。
初回ログイン後にセッションが保存され、次回以降は自動でスキップされます。

使い方:
    python3 main.py 2024/01                  # 初回は自動でブラウザが開く→手入力ログイン
    python3 main.py 2024 1
    python3 main.py --year 2024 --month 1
    python3 main.py 2024/01 --debug          # 各ステップのスクショ/HTMLを保存（セレクタ調整用）
    python3 main.py 2024/01 --check          # 設定と照会期間の確認のみ（ブラウザを起動しない）

設定は .env（.env.example をコピー）または環境変数で。主なもの:
    SERVICE_TYPE  smart-ex | expy
    RECIPIENT_NAME  宛名（既定: 日本IBM株式会社）
    OUTPUT_DIR（既定: デスクトップ）/ HEADLESS / DEBUG / TRAVEL_DATE_INDEX
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(
        description="EX予約 領収書ダウンロードツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("month_str", nargs="?", metavar="FROM", help="From年月 (例: 2024/01)")
    p.add_argument("to_month_str", nargs="?", metavar="TO", help="To年月 (省略時はFromと同じ)")
    p.add_argument("--from", dest="from_str", metavar="YYYY/MM", help="From年月")
    p.add_argument("--to", dest="to_str", metavar="YYYY/MM", help="To年月")
    p.add_argument("--year", type=int, help="From年 (4桁)")
    p.add_argument("--month", type=int, help="From月 (1-12)")
    p.add_argument("--service", choices=["smart-ex", "expy", "eki-net"], help="サービス種別")
    p.add_argument("--recipient", metavar="宛名", help="宛名")
    p.add_argument("--output", metavar="DIR", help="PDF出力ディレクトリ (既定: デスクトップ)")
    p.add_argument("--no-headless", action="store_true",
                   help="保存済みセッション利用時もブラウザを表示して実行（動作確認用）")
    p.add_argument("--debug", action="store_true", help="各ステップのスクショ/HTMLを保存")
    p.add_argument("--check", action="store_true",
                   help="設定・照会期間・利用可否の確認のみ（ブラウザを起動しない）")
    return p.parse_args()


def _parse_ym(s: str):
    m = re.match(r"(\d{4})[/\-年](\d{1,2})", s) or re.match(r"(\d{4})(\d{2})$", s)
    if not m:
        print(f"エラー: 年月の形式が不正です: {s!r} (例: 2024/01)")
        sys.exit(1)
    return int(m.group(1)), int(m.group(2))


def resolve_range(args) -> tuple[int, int, int, int]:
    """(from_year, from_month, to_year, to_month) を返す。To省略時はFromと同じ。"""
    from_s = args.from_str or args.month_str
    to_s = args.to_str or args.to_month_str

    if from_s:
        fy, fm = _parse_ym(from_s)
    elif args.year and args.month:
        fy, fm = args.year, args.month
    else:
        today = datetime.date.today()
        default = f"{today.year}/{today.month:02d}"
        raw = input(f"From年月を入力 (例: 2024/01) [{default}]: ").strip() or default
        fy, fm = _parse_ym(raw)
        raw_to = input(f"To年月を入力 (例: 2024/03) [{fy}/{fm:02d}]: ").strip()
        to_s = raw_to or None

    if to_s:
        ty, tm = _parse_ym(to_s)
    else:
        ty, tm = fy, fm
    return fy, fm, ty, tm


def apply_overrides(args) -> None:
    if args.service:
        config.SERVICE_TYPE = args.service
    if args.recipient:
        config.RECIPIENT_NAME = args.recipient
    if args.output:
        config.OUTPUT_DIR = Path(args.output).expanduser()
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.no_headless:
        config.HEADLESS = False
    if args.debug:
        config.DEBUG = True


def print_header(fy: int, fm: int, ty: int, tm: int) -> None:
    from agents.discovery_agent import date_range
    start, end = date_range(fy, fm, ty, tm)
    print("=" * 50)
    print("EX予約 領収書ダウンロードツール")
    print("=" * 50)
    if (fy, fm) == (ty, tm):
        print(f"対象月    : {fy}年{fm:02d}月")
    else:
        print(f"対象期間  : {fy}年{fm:02d}月 〜 {ty}年{tm:02d}月")
    print(f"照会期間  : {start} 〜 {end}")
    print(f"サービス  : {config.get_service_config()['name']}")
    print(f"宛名      : {config.RECIPIENT_NAME}")
    print(f"保存先    : {config.OUTPUT_DIR}")
    print(f"ヘッドレス: {config.HEADLESS}")
    # 利用可否/メンテ時間チェックは JR東海(RSV_P)系のみ
    if config.SERVICE_TYPE in config.JR_CENTRAL_SERVICES:
        avail = config.check_month_available(ty, tm)
        print(f"利用可否  : {'OK' if avail.ok else 'NG - ' + avail.reason}")
        if config.in_maintenance_window():
            print("注意      : 現在 23:30〜5:30 のメンテ時間帯の可能性")
    print("=" * 50)


async def main():
    args = parse_args()
    fy, fm, ty, tm = resolve_range(args)
    apply_overrides(args)

    print_header(fy, fm, ty, tm)

    if args.check:
        return

    from pipeline import Pipeline  # playwright 依存をここまで遅延
    result = await Pipeline(from_year=fy, from_month=fm, to_year=ty, to_month=tm).run()

    if result["downloaded_files"]:
        print(f"\n完了: {len(result['downloaded_files'])}件の領収書をダウンロードしました")
    else:
        print("\n領収書のダウンロードができませんでした")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
