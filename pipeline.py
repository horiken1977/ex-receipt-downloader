"""
決定論的なダウンロードパイプライン。

処理順は固定:
  login（手入力） → 会員メニューから一覧へ → From年月初日〜To年月末日で照会
  → 表示された領収書を1件ずつ取得 → PDF/ファイル保存（デスクトップ）。
えきねっとは Akamai 対策のため実Chrome(CDP)で別フロー（providers/ekinet.py）。
"""
from __future__ import annotations

from typing import List

import browser_manager
import config
from agents import discovery_agent, download_agent, login_agent


class Pipeline:
    def __init__(self, from_year: int, from_month: int,
                 to_year: int = None, to_month: int = None):
        self.from_year = from_year
        self.from_month = from_month
        # To 省略時は From と同じ（単月）
        self.to_year = to_year if to_year is not None else from_year
        self.to_month = to_month if to_month is not None else from_month
        self.service_cfg = config.get_service_config()
        self.downloaded: List[str] = []
        self.failed: List[str] = []

    async def run(self) -> dict:
        is_jr_central = config.SERVICE_TYPE in config.JR_CENTRAL_SERVICES

        # 利用可否/メンテ時間チェックは JR東海(RSV_P)系のみ適用（To年月で判定）。
        if is_jr_central:
            avail = config.check_month_available(self.to_year, self.to_month)
            if not avail.ok:
                print(f"[Pipeline] 中止: {avail.reason}")
                return self._result()
            if config.in_maintenance_window():
                print("[Pipeline] 警告: 23:30〜5:30 はメンテ時間帯で領収書表示が利用できない可能性があります。")

        # えきねっとは実Chromeに CDP 接続する専用フロー（browser_manager は使わない）。
        if config.SERVICE_TYPE == "eki-net":
            from providers import ekinet
            self.downloaded, self.failed = await ekinet.run_flow(
                self.from_year, self.from_month, self.to_year, self.to_month, config.RECIPIENT_NAME
            )
            return self._result()

        # JR東海系: ログインは手入力のため、常に画面を表示して実行する。
        await browser_manager.start(headless=False)
        try:
            page = await login_agent.ensure_session(self.service_cfg)
            await self._download_all(page)
        finally:
            await browser_manager.stop()
        return self._result()

    async def _download_all(self, page) -> None:
        await discovery_agent.open_and_filter(
            page, self.from_year, self.from_month, self.to_year, self.to_month
        )

        seq = 0
        page_no = 1
        while True:
            n = await discovery_agent.count_receipts(page)
            if n == 0:
                if page_no == 1:
                    print("[Pipeline] 対象期間の領収書が見つかりませんでした。")
                break
            print(f"[Pipeline] {page_no}ページ目: {n}件")

            for j in range(n):
                # この時点で一覧（page_no）が表示されている前提
                if not await discovery_agent.click_receipt(page, j):
                    self.failed.append(f"p{page_no}/{j}")
                    print(f"[Pipeline] {j}番目の領収書ボタンが見つかりません")
                    continue
                seq += 1
                try:
                    path = await download_agent.save_current_receipt(page, config.RECIPIENT_NAME, seq)
                    self.downloaded.append(str(path))
                except Exception as e:
                    self.failed.append(f"p{page_no}/{j}")
                    print(f"[Pipeline] 保存失敗 (p{page_no}/{j}): {e}")

                # 次の領収書のため一覧へ戻る
                if not await discovery_agent.return_to_list(
                    page, self.from_year, self.from_month, self.to_year, self.to_month
                ):
                    print("[Pipeline] 一覧へ戻れませんでした。処理を中断します。")
                    return

            if not await discovery_agent.go_to_next_page(page):
                break
            page_no += 1

    def _result(self) -> dict:
        print("\n" + "=" * 50)
        if (self.from_year, self.from_month) == (self.to_year, self.to_month):
            print(f"対象月: {self.from_year}年{self.from_month:02d}月")
        else:
            print(f"対象期間: {self.from_year}年{self.from_month:02d}月 〜 {self.to_year}年{self.to_month:02d}月")
        print(f"ダウンロード成功: {len(self.downloaded)}件")
        print(f"ダウンロード失敗: {len(self.failed)}件")
        if self.downloaded:
            print(f"\n保存先: {config.OUTPUT_DIR}")
            for f in self.downloaded:
                print(f"  {f}")
        print("=" * 50)
        return {"downloaded_files": self.downloaded, "failed": self.failed}
