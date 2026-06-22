"""
決定論的なダウンロードパイプライン。

処理順は固定:
  login（手入力/保存セッション） → 会員メニューから一覧へ → 対象月の初日〜末日で照会
  → 表示された領収書を1件ずつ 宛名入力 → PDF保存（デスクトップ） → 全件終わったら閉じる。
"""
from __future__ import annotations

from typing import List

import browser_manager
import config
from agents import discovery_agent, download_agent, login_agent


class Pipeline:
    def __init__(self, year: int, month: int):
        self.year = year
        self.month = month
        self.service_cfg = config.get_service_config()
        self.downloaded: List[str] = []
        self.failed: List[str] = []

    async def run(self) -> dict:
        is_jr_central = config.SERVICE_TYPE in config.JR_CENTRAL_SERVICES

        # 利用可否/メンテ時間チェックは JR東海(RSV_P)系のみ適用。
        if is_jr_central:
            avail = config.check_month_available(self.year, self.month)
            if not avail.ok:
                print(f"[Pipeline] 中止: {avail.reason}")
                return self._result()
            if config.in_maintenance_window():
                print("[Pipeline] 警告: 23:30〜5:30 はメンテ時間帯で領収書表示が利用できない可能性があります。")

        # ログインは手入力のため、常に画面を表示して実行する。
        await browser_manager.start(headless=False)
        try:
            if config.SERVICE_TYPE == "eki-net":
                from providers import ekinet
                self.downloaded, self.failed = await ekinet.run_flow(
                    self.year, self.month, config.RECIPIENT_NAME
                )
            else:
                page = await login_agent.ensure_session(self.service_cfg)
                await self._download_all(page)
        finally:
            await browser_manager.stop()
        return self._result()

    async def _download_all(self, page) -> None:
        await discovery_agent.open_and_filter(page, self.year, self.month)

        seq = 0
        page_no = 1
        while True:
            n = await discovery_agent.count_receipts(page)
            if n == 0:
                if page_no == 1:
                    print("[Pipeline] 対象月の領収書が見つかりませんでした。")
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
                if not await discovery_agent.return_to_list(page, self.year, self.month):
                    print("[Pipeline] 一覧へ戻れませんでした。処理を中断します。")
                    return

            if not await discovery_agent.go_to_next_page(page):
                break
            page_no += 1

    def _result(self) -> dict:
        print("\n" + "=" * 50)
        print(f"対象月: {self.year}年{self.month:02d}月")
        print(f"ダウンロード成功: {len(self.downloaded)}件")
        print(f"ダウンロード失敗: {len(self.failed)}件")
        if self.downloaded:
            print(f"\n保存先: {config.OUTPUT_DIR}")
            for f in self.downloaded:
                print(f"  {f}")
        print("=" * 50)
        return {"downloaded_files": self.downloaded, "failed": self.failed}
