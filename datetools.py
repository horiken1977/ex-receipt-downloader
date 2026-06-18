"""日本語サイト向けの日付ユーティリティ。"""
from __future__ import annotations

import datetime
import re
from typing import List, Optional

# 全角数字 → 半角
_ZEN = str.maketrans("０１２３４５６７８９", "0123456789")

# 行テキストから日付トークンを拾う正規表現（年あり / 年なし）
_DATE_FULL = re.compile(r"(\d{4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})")
_DATE_MD = re.compile(r"(?<!\d)(\d{1,2})[/\-月](\d{1,2})日?")


def normalize(text: str) -> str:
    return text.translate(_ZEN)


def find_date_tokens(text: str) -> List[str]:
    """テキスト内の日付らしき部分文字列を出現順にすべて返す。"""
    text = normalize(text)

    full_spans = [(m.start(), m.end(), m.group(0)) for m in _DATE_FULL.finditer(text)]

    # 年なし MD（年付きと範囲が重複するものは除外）
    md_spans = [
        (m.start(), m.end(), m.group(0))
        for m in _DATE_MD.finditer(text)
        if not any(s <= m.start() < e for s, e, _ in full_spans)
    ]

    # 文中の出現位置でソートして順序を保つ（TRAVEL_DATE_INDEX が効くように）
    spans = sorted(full_spans + md_spans, key=lambda x: x[0])
    return [tok for _, _, tok in spans]


def parse_date(token: str, default_year: Optional[int] = None) -> Optional[datetime.date]:
    """日付トークンを date に変換。年がなければ default_year を補う。失敗時 None。"""
    if not token:
        return None
    token = normalize(token)

    m = _DATE_FULL.search(token)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_date(y, mo, d)

    m = _DATE_MD.search(token)
    if m and default_year is not None:
        mo, d = int(m.group(1)), int(m.group(2))
        return _safe_date(default_year, mo, d)

    return None


def _safe_date(y: int, mo: int, d: int) -> Optional[datetime.date]:
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None
