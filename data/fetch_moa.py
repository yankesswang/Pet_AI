#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_moa.py — VetLink AI 資料層 / 政府許可證底座擷取器

抓取農業部（動植物防疫檢疫署）「動物用藥資訊」開放資料集全量記錄。

資料集: https://data.moa.gov.tw/open_detail.aspx?id=023
API   : https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx

重點行為
--------
* API 單次回應被截斷在 9999 筆，必須用 OData 的 $skip / $top 分頁才能取全量。
* 每頁之間有禮貌性延遲（預設 1.5 秒），並對逾時 / 連線錯誤做退避重試。
* 可續傳（resumable）：分頁結果先寫入 raw/.pages/ 快取，重跑時直接沿用已完成的頁，
  只補抓缺的頁。加 --force 可忽略快取重抓。
* 冪等（idempotent）：最終輸出以 許可證字號 去重後依序寫出，重跑結果一致。

輸出
----
data/raw/moa_animal_drugs.json   完整原始記錄（未經任何欄位改寫）
data/raw/fetch_meta.json         擷取中繼資料（時間、頁數、總筆數、來源）

用法
----
    python3 fetch_moa.py                # 正常擷取（可續傳）
    python3 fetch_moa.py --force        # 清掉快取重抓
    python3 fetch_moa.py --page-size 2000 --delay 2.0
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# HTTP backend：優先用 requests，沒有就退回 urllib（純標準庫）
# ---------------------------------------------------------------------------
try:
    import requests  # type: ignore

    _HAS_REQUESTS = True
except ImportError:  # pragma: no cover - 環境相依
    requests = None  # type: ignore
    _HAS_REQUESTS = False

import urllib.error
import urllib.parse
import urllib.request


# ---------------------------------------------------------------------------
# 常數
# ---------------------------------------------------------------------------
SOURCE_URL = "https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx"
DATASET_PAGE = "https://data.moa.gov.tw/open_detail.aspx?id=023"
DATASET_ID = "moa-023-animal-drug"
SOURCE_AGENCY = "農業部動植物防疫檢疫署"

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "raw")
PAGE_CACHE_DIR = os.path.join(RAW_DIR, ".pages")
OUT_PATH = os.path.join(RAW_DIR, "moa_animal_drugs.json")
META_PATH = os.path.join(RAW_DIR, "fetch_meta.json")

DEFAULT_PAGE_SIZE = 2000
DEFAULT_DELAY = 1.5          # 秒；對公開 API 保持禮貌
DEFAULT_TIMEOUT = 60         # 秒
MAX_RETRIES = 4
MAX_PAGES = 200              # 安全上限，避免無限迴圈（200 * 2000 = 40 萬筆）

# 注意：HTTP header 只能是 latin-1，這裡不可放中文。
USER_AGENT = (
    "VetLinkAI-DataFetcher/1.0 "
    "(2026 competition prototype; open-data research use)"
)

# 主鍵：許可證字號在此資料集內唯一
PRIMARY_KEY = "許可證字號"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _http_get_json(url: str, timeout: int) -> Any:
    """單次 GET 並解析 JSON。requests 不存在時退回 urllib。"""
    if _HAS_REQUESTS:
        resp = requests.get(
            url, timeout=timeout, headers={"User-Agent": USER_AGENT}
        )
        resp.raise_for_status()
        # 該 API 偶爾回傳的 Content-Type 不是 application/json，直接吃 text
        return json.loads(resp.text)

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        charset = fh.headers.get_content_charset() or "utf-8"
        return json.loads(fh.read().decode(charset, errors="replace"))


def fetch_page(
    skip: int,
    top: int,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> List[Dict[str, Any]]:
    """抓取單一分頁，失敗時指數退避重試。"""
    params = urllib.parse.urlencode({"$skip": skip, "$top": top}, safe="$")
    url = f"{SOURCE_URL}?{params}"

    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            data = _http_get_json(url, timeout)
            if not isinstance(data, list):
                raise ValueError(
                    f"預期回傳 JSON array，實際為 {type(data).__name__}"
                )
            return data
        except Exception as exc:  # noqa: BLE001 - 網路層什麼都可能發生
            last_err = exc
            if attempt == max_retries:
                break
            backoff = 2.0 ** attempt
            print(
                f"    ! 第 {attempt}/{max_retries} 次失敗 ({exc.__class__.__name__}: {exc})"
                f"，{backoff:.0f}s 後重試",
                file=sys.stderr,
            )
            time.sleep(backoff)

    raise RuntimeError(f"分頁 skip={skip} top={top} 擷取失敗: {last_err}")


# ---------------------------------------------------------------------------
# 分頁快取（續傳用）
# ---------------------------------------------------------------------------
def _page_cache_path(skip: int, top: int) -> str:
    return os.path.join(PAGE_CACHE_DIR, f"page_{skip:07d}_{top}.json")


def _load_cached_page(skip: int, top: int) -> Optional[List[Dict[str, Any]]]:
    path = _page_cache_path(skip, top)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_cached_page(skip: int, top: int, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(PAGE_CACHE_DIR, exist_ok=True)
    path = _page_cache_path(skip, top)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def fetch_all(
    page_size: int = DEFAULT_PAGE_SIZE,
    delay: float = DEFAULT_DELAY,
    timeout: int = DEFAULT_TIMEOUT,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """分頁抓完整個資料集，回傳去重後的記錄清單。"""
    all_rows: List[Dict[str, Any]] = []
    skip = 0
    page_no = 0
    cache_hits = 0
    network_pages = 0

    while page_no < MAX_PAGES:
        page_no += 1

        rows = _load_cached_page(skip, page_size) if use_cache else None
        if rows is not None:
            cache_hits += 1
            print(f"  [{page_no:>3}] skip={skip:<6} 快取命中 {len(rows)} 筆")
        else:
            print(f"  [{page_no:>3}] skip={skip:<6} 擷取中 …", end="", flush=True)
            rows = fetch_page(skip, page_size, timeout=timeout)
            network_pages += 1
            _save_cached_page(skip, page_size, rows)
            print(f" 取得 {len(rows)} 筆")
            if rows:
                time.sleep(delay)  # 禮貌延遲，只在真的打了網路時才等

        all_rows.extend(rows)

        # 回傳筆數 < 請求筆數 => 已到資料尾端
        if len(rows) < page_size:
            break
        skip += page_size
    else:
        print(
            f"  ! 已達安全上限 {MAX_PAGES} 頁，提前停止",
            file=sys.stderr,
        )

    print(
        f"  分頁完成：{page_no} 頁（網路 {network_pages} / 快取 {cache_hits}），"
        f"原始 {len(all_rows)} 筆"
    )
    return dedupe(all_rows)


def dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """以 許可證字號 去重，保留首次出現順序（保證冪等）。"""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    dupes = 0
    for row in rows:
        key = (row.get(PRIMARY_KEY) or "").strip()
        if not key:
            # 沒有許可證字號的記錄：用整列內容當指紋，避免誤刪
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        out.append(row)
    if dupes:
        print(f"  去重：移除 {dupes} 筆重複（依 {PRIMARY_KEY}）")
    return out


def write_outputs(
    rows: List[Dict[str, Any]], page_size: int, fetched_at: str
) -> None:
    os.makedirs(RAW_DIR, exist_ok=True)

    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT_PATH)

    field_names = sorted({k for row in rows for k in row.keys()})
    meta = {
        "dataset_id": DATASET_ID,
        "dataset_page": DATASET_PAGE,
        "source_url": SOURCE_URL,
        "source_agency": SOURCE_AGENCY,
        "update_frequency": "每週（依官方標示）",
        "fetched_at": fetched_at,
        "record_count": len(rows),
        "page_size": page_size,
        "primary_key": PRIMARY_KEY,
        "fields": field_names,
        "notes": [
            "API 預設單次僅回傳 9999 筆，必須以 $skip/$top 分頁取得全量。",
            "本檔案為未經加工的原始回應，欄位改寫一律在 normalize.py 完成。",
        ],
    }
    with open(META_PATH, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="擷取農業部動物用藥開放資料（全量分頁）"
    )
    parser.add_argument(
        "--page-size", type=int, default=DEFAULT_PAGE_SIZE, help="每頁筆數"
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY, help="每頁之間的延遲秒數"
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT, help="單次請求逾時秒數"
    )
    parser.add_argument(
        "--force", action="store_true", help="忽略並清除分頁快取，重新擷取"
    )
    args = parser.parse_args()

    if args.force and os.path.isdir(PAGE_CACHE_DIR):
        shutil.rmtree(PAGE_CACHE_DIR)
        print("已清除分頁快取")

    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    print("=" * 68)
    print("VetLink AI — 農業部動物用藥開放資料擷取")
    print(f"來源: {SOURCE_URL}")
    print(f"HTTP: {'requests' if _HAS_REQUESTS else 'urllib (stdlib fallback)'}")
    print("=" * 68)

    try:
        rows = fetch_all(
            page_size=args.page_size,
            delay=args.delay,
            timeout=args.timeout,
            use_cache=not args.force,
        )
    except RuntimeError as exc:
        print(f"\n擷取失敗: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("\n未取得任何記錄，中止寫檔。", file=sys.stderr)
        return 1

    write_outputs(rows, args.page_size, fetched_at)

    print("-" * 68)
    print(f"總記錄數 : {len(rows)}")
    print(f"欄位數   : {len(rows[0])}")
    print(f"原始輸出 : {OUT_PATH}")
    print(f"中繼資料 : {META_PATH}")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
