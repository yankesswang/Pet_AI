#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize.py — VetLink AI 資料層 / 產品證據卡正規化器

把 fetch_moa.py 取得的原始農業部記錄，轉成 Evidence Gate 可以直接判斷的
「產品證據卡」(product evidence card)。

輸入: data/raw/moa_animal_drugs.json
輸出: data/processed/drug_evidence.json
      data/processed/normalize_stats.json

處理的資料品質問題
------------------
1. 民國紀年轉西元
   有效期間: "至120年04月30日止" / "至82年01月01日止(已失效)"
   核發日期: "中華民國110年09月13日"（大量為空，另有少數格式錯誤）
   民國年 + 1911 = 西元年。

2. 成分欄位含原始 HTML（<div>、<sub>、&nbsp; 等）需清成純文字，
   但化學式的下標必須保留語義（C<sub>16</sub> -> C16）。

3. 效能(適應症) 是混合多物種的長段自由文字（"豬：…雞：…鰻形目：…"），
   需解析出物種清單。解析時必須排除疾病名稱造成的假陽性：
   「雞馬立克病」不代表馬、「假性狂犬病」不代表犬。

4. is_expired 同時採信兩種訊號：文字中的「(已失效)」標記，以及
   換算後的到期日與基準日（預設 2026-08-19）比較。

Answer Passport 欄位
--------------------
doc_id / version / source_url / fetched_at 讓每張證據卡都能被回答護照引用，
並支援 Impact Replay 在資料更新時比對版本。

用法
----
    python3 normalize.py
    python3 normalize.py --as-of 2026-08-19
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = os.path.join(HERE, "raw", "moa_animal_drugs.json")
META_PATH = os.path.join(HERE, "raw", "fetch_meta.json")
PROCESSED_DIR = os.path.join(HERE, "processed")
OUT_PATH = os.path.join(PROCESSED_DIR, "drug_evidence.json")
STATS_PATH = os.path.join(PROCESSED_DIR, "normalize_stats.json")

SOURCE_URL = "https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx"
SOURCE_AGENCY = "農業部動植物防疫檢疫署"

# Demo 的固定基準日；與提案 Demo 腳本一致，確保結果可重現。
DEFAULT_AS_OF = dt.date(2026, 8, 19)

ROC_OFFSET = 1911
SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# 1. HTML 清理
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_END_RE = re.compile(r"</\s*(div|p|br|li|tr)\s*/?>", re.IGNORECASE)
_BR_RE = re.compile(r"<\s*br\s*/?>", re.IGNORECASE)
_WS_RE = re.compile(r"[ \t　\xa0]+")
_MULTI_NL_RE = re.compile(r"\n{2,}")


def strip_html(text: Optional[str]) -> str:
    """把含 HTML 的欄位轉成乾淨純文字。

    化學式下標保留為一般字元（C<sub>16</sub>H<sub>19</sub> -> C16H19），
    區塊標籤轉為換行，實體字元（&nbsp; 等）解碼後正規化空白。
    """
    if not text:
        return ""

    s = str(text)
    # <sub>/<sup> 只脫標籤、不加換行，才不會把化學式拆行
    s = re.sub(r"</?\s*(sub|sup|span|b|i|strong|em|font)\b[^>]*>", "", s,
               flags=re.IGNORECASE)
    s = _BR_RE.sub("\n", s)
    s = _BLOCK_END_RE.sub("\n", s)
    s = _TAG_RE.sub("", s)          # 剩餘標籤一律移除
    s = html.unescape(s)            # &nbsp; &amp; &lt; …
    s = s.replace("\xa0", " ").replace("　", " ")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _WS_RE.sub(" ", s)
    s = "\n".join(line.strip() for line in s.split("\n"))
    s = _MULTI_NL_RE.sub("\n", s)
    return s.strip()


# ---------------------------------------------------------------------------
# 2. 民國紀年 -> ISO 日期
# ---------------------------------------------------------------------------
_EXPIRY_RE = re.compile(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_ISSUE_RE = re.compile(r"(?:中華民國)?\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
EXPIRED_MARKER = "已失效"


def _build_iso(roc_year: int, month: int, day: int) -> Optional[str]:
    """民國年月日 -> ISO 8601 字串，非法日期回傳 None。"""
    year = roc_year + ROC_OFFSET
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_roc_expiry(raw: Optional[str]) -> Tuple[Optional[str], bool]:
    """解析 有效期間。

    回傳 (expiry_date_iso, has_expired_marker)。
    範例:
        "至120年04月30日止"          -> ("2031-04-30", False)
        "至82年01月01日止(已失效)"    -> ("1993-01-01", True)
        ""                            -> (None, False)
    """
    if not raw:
        return None, False
    text = str(raw).strip()
    marker = EXPIRED_MARKER in text
    m = _EXPIRY_RE.search(text)
    if not m:
        return None, marker
    iso = _build_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return iso, marker


def parse_roc_issue(raw: Optional[str]) -> Optional[str]:
    """解析 核發日期（"中華民國110年09月13日"）。

    大量記錄為空字串，另有少數格式毀損（如 "中華民國0000301"），
    這些一律回傳 None，不做猜測。
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    m = _ISSUE_RE.search(text)
    if not m:
        return None
    roc_year = int(m.group(1))
    if roc_year <= 0:
        return None
    return _build_iso(roc_year, int(m.group(2)), int(m.group(3)))


# ---------------------------------------------------------------------------
# 3. 物種解析
# ---------------------------------------------------------------------------
# canonical -> 觸發關鍵字
SPECIES_PATTERNS: List[Tuple[str, List[str]]] = [
    ("犬", ["犬", "狗"]),
    ("貓", ["貓"]),
    ("豬", ["豬", "猪"]),
    ("雞", ["雞", "鶏"]),
    ("火雞", ["火雞"]),
    ("鴨", ["鴨"]),
    ("鵝", ["鵝"]),
    ("鴿", ["鴿"]),
    ("牛", ["牛"]),
    ("羊", ["羊"]),
    ("馬", ["馬"]),
    ("兔", ["兔"]),
    ("鹿", ["鹿"]),
    ("魚", ["魚", "鰻", "鮭", "鱒", "鱸", "鯛", "鱺", "石斑"]),
    ("蝦", ["蝦"]),
    ("蜂", ["蜂"]),
    ("猴", ["猴"]),
    ("鳥", ["鳥類", "禽鳥"]),
]

# 疾病 / 詞彙造成的假陽性。命中這些字串的位置不算物種出現。
# 例："雞馬立克病" 不代表馬；"假性狂犬病" 是豬的疾病，不代表犬。
FALSE_POSITIVE_TERMS: Dict[str, List[str]] = {
    "馬": ["馬立克", "馬上", "海馬", "馬克", "羅馬", "馬達", "馬鈴薯"],
    "犬": ["假性狂犬病", "偽狂犬病", "狂犬病"],
    "牛": ["牛蒡", "牛頓"],
    "羊": ["羊毛脂", "羊齒"],
    "魚": ["魚肝油", "魚精蛋白", "魚腥草"],
    "貓": ["貓爪草"],
    "雞": ["雞冠花", "雞內金"],
}

# 中文物種 -> 英文 slug，供前端 / 檢索標籤使用
SPECIES_SLUG = {
    "犬": "dog", "貓": "cat", "豬": "pig", "雞": "chicken",
    "火雞": "turkey", "鴨": "duck", "鵝": "goose", "鴿": "pigeon",
    "牛": "cattle", "羊": "sheep_goat", "馬": "horse", "兔": "rabbit",
    "鹿": "deer", "魚": "fish", "蝦": "shrimp", "蜂": "bee",
    "猴": "monkey", "鳥": "bird",
}

COMPANION_SPECIES = {"犬", "貓"}


def _mask_false_positives(text: str, species: str) -> str:
    """把會造成該物種假陽性的詞彙遮蔽掉，再做關鍵字比對。"""
    terms = FALSE_POSITIVE_TERMS.get(species)
    if not terms:
        return text
    masked = text
    for term in terms:
        masked = masked.replace(term, " " * len(term))
    return masked


def parse_species(indications: Optional[str], name_zh: str = "") -> List[str]:
    """從 效能(適應症) 自由文字解析出物種清單。

    適應症常見寫法為 "豬：…雞：…鰻形目：…"，多物種混在同一段。
    先遮蔽疾病名稱造成的假陽性，再逐一比對關鍵字。
    """
    text = f"{indications or ''}\n{name_zh or ''}"
    if not text.strip():
        return []

    found: List[str] = []
    for canonical, keywords in SPECIES_PATTERNS:
        masked = _mask_false_positives(text, canonical)
        if any(kw in masked for kw in keywords):
            found.append(canonical)

    # 火雞同時含「雞」；兩者皆保留（適應症通常真的兩種都涵蓋），
    # 但若只出現「火雞」而無獨立的「雞」，就移除誤加的「雞」。
    if "火雞" in found and "雞" in found:
        stripped = text.replace("火雞", "")
        if "雞" not in stripped and "鶏" not in stripped:
            found.remove("雞")

    return found


# ---------------------------------------------------------------------------
# 4. 單筆記錄正規化
# ---------------------------------------------------------------------------
def _clean(value: Any) -> str:
    if value is None:
        return ""
    return _WS_RE.sub(" ", str(value).replace("\xa0", " ")).strip()


def make_doc_id(licence_no: str) -> str:
    """穩定的文件 ID，供回答護照與 Impact Replay 引用。"""
    slug = re.sub(r"[^0-9A-Za-z]", "", licence_no) or "UNKNOWN"
    if not re.search(r"\d", slug):
        slug = hashlib.sha1(licence_no.encode("utf-8")).hexdigest()[:10].upper()
    return f"MOA-AD-{slug}"


def make_version(record: Dict[str, Any]) -> str:
    """內容指紋版本號。原始欄位有任何變動 -> 版本改變 -> 觸發 Impact Replay。"""
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return "v1." + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def normalize_record(
    record: Dict[str, Any], as_of: dt.date, fetched_at: str
) -> Dict[str, Any]:
    """把一筆原始記錄轉成產品證據卡。"""
    licence_no = _clean(record.get("許可證字號"))
    name_zh = _clean(record.get("動物用藥品中文名稱"))
    indications_raw = strip_html(record.get("效能(適應症)"))

    expiry_iso, expired_marker = parse_roc_expiry(record.get("有效期間"))
    issue_iso = parse_roc_issue(record.get("核發日期"))

    # 到期判定：文字標記 OR 日期已過基準日。兩者皆可獨立成立。
    expired_by_date = bool(expiry_iso and expiry_iso < as_of.isoformat())
    is_expired = bool(expired_marker or expired_by_date)

    species = parse_species(indications_raw, name_zh)
    is_companion = any(s in COMPANION_SPECIES for s in species)

    return {
        # --- 識別 ---
        "doc_id": make_doc_id(licence_no),
        "licence_no": licence_no,
        "name_zh": name_zh,
        "name_en": _clean(record.get("動物用藥品英文名稱")),

        # --- 業者與製造 ---
        "company": _clean(record.get("業者名稱")),
        "company_address": _clean(record.get("業者地址")),
        "manufacturer": _clean(record.get("製造廠名稱")),
        "manufacturer_address": _clean(record.get("製造廠地址")),

        # --- 產品規格 ---
        "dosage_form": _clean(record.get("劑型")),
        "packaging": _clean(record.get("包裝")),
        "ingredients_clean": strip_html(record.get("成分")),
        "ingredients_had_html": "<" in (record.get("成分") or ""),
        "indications_raw": indications_raw,

        # --- 適用範圍（回答護照的「適用範圍」欄位）---
        "species": species,
        "species_slugs": [SPECIES_SLUG[s] for s in species if s in SPECIES_SLUG],
        "is_companion_animal": is_companion,
        "export_only": _clean(record.get("外銷專用")) == "是",

        # --- 文件效期閘門 ---
        "issue_date_iso": issue_iso,
        "issue_date_raw": _clean(record.get("核發日期")) or None,
        "expiry_date_iso": expiry_iso,
        "expiry_date_raw": _clean(record.get("有效期間")) or None,
        "is_expired": is_expired,
        "expired_by_marker": expired_marker,
        "expired_by_date": expired_by_date,
        "expiry_unknown": expiry_iso is None and not expired_marker,

        # --- Answer Passport 溯源 ---
        "version": make_version(record),
        "schema_version": SCHEMA_VERSION,
        "source_url": SOURCE_URL,
        "source_agency": SOURCE_AGENCY,
        "source_type": "government_open_data",
        "fetched_at": fetched_at,
        "normalized_at": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "evaluated_as_of": as_of.isoformat(),
    }


# ---------------------------------------------------------------------------
# 5. 統計
# ---------------------------------------------------------------------------
def build_stats(cards: List[Dict[str, Any]], as_of: dt.date) -> Dict[str, Any]:
    total = len(cards)
    species_counts: Dict[str, int] = {}
    form_counts: Dict[str, int] = {}
    company_counts: Dict[str, int] = {}

    for card in cards:
        for sp in card["species"]:
            species_counts[sp] = species_counts.get(sp, 0) + 1
        form = card["dosage_form"] or "(未填)"
        form_counts[form] = form_counts.get(form, 0) + 1
        comp = card["company"] or "(未填)"
        company_counts[comp] = company_counts.get(comp, 0) + 1

    valid = [c for c in cards if not c["is_expired"]]
    companion = [c for c in cards if c["is_companion_animal"]]

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "evaluated_as_of": as_of.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "total_records": total,
        "expiry": {
            "expired_total": sum(1 for c in cards if c["is_expired"]),
            "expired_by_marker": sum(1 for c in cards if c["expired_by_marker"]),
            "expired_by_date_only": sum(
                1 for c in cards
                if c["expired_by_date"] and not c["expired_by_marker"]
            ),
            "valid_total": len(valid),
            "expiry_unknown": sum(1 for c in cards if c["expiry_unknown"]),
        },
        "dates": {
            "issue_date_parsed": sum(1 for c in cards if c["issue_date_iso"]),
            "issue_date_missing": sum(
                1 for c in cards if not c["issue_date_iso"]
            ),
            "expiry_date_parsed": sum(1 for c in cards if c["expiry_date_iso"]),
        },
        "content": {
            "ingredients_html_stripped": sum(
                1 for c in cards if c["ingredients_had_html"]
            ),
            "indications_empty": sum(
                1 for c in cards if not c["indications_raw"]
            ),
            "species_unparsed": sum(1 for c in cards if not c["species"]),
            "export_only": sum(1 for c in cards if c["export_only"]),
        },
        "companion_animal": {
            "total": len(companion),
            "valid": sum(1 for c in companion if not c["is_expired"]),
            "expired": sum(1 for c in companion if c["is_expired"]),
        },
        "species_counts": dict(
            sorted(species_counts.items(), key=lambda kv: -kv[1])
        ),
        "top_dosage_forms": dict(
            sorted(form_counts.items(), key=lambda kv: -kv[1])[:15]
        ),
        "top_companies": dict(
            sorted(company_counts.items(), key=lambda kv: -kv[1])[:15]
        ),
    }


# ---------------------------------------------------------------------------
# 6. 主流程
# ---------------------------------------------------------------------------
def load_fetched_at() -> str:
    try:
        with open(META_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh).get("fetched_at", "unknown")
    except (OSError, json.JSONDecodeError):
        return "unknown"


def normalize_all(as_of: dt.date) -> List[Dict[str, Any]]:
    if not os.path.exists(RAW_PATH):
        raise FileNotFoundError(
            f"找不到原始資料 {RAW_PATH}；請先執行 python3 fetch_moa.py"
        )
    with open(RAW_PATH, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    fetched_at = load_fetched_at()
    return [normalize_record(r, as_of, fetched_at) for r in raw]


def main() -> int:
    parser = argparse.ArgumentParser(description="正規化農業部動物用藥資料")
    parser.add_argument(
        "--as-of",
        default=DEFAULT_AS_OF.isoformat(),
        help="效期判定基準日 YYYY-MM-DD（預設 2026-08-19）",
    )
    args = parser.parse_args()
    as_of = dt.date.fromisoformat(args.as_of)

    print("=" * 68)
    print("VetLink AI — 產品證據卡正規化")
    print(f"效期基準日: {as_of.isoformat()}")
    print("=" * 68)

    try:
        cards = normalize_all(as_of)
    except FileNotFoundError as exc:
        print(f"錯誤: {exc}", file=sys.stderr)
        return 1

    stats = build_stats(cards, as_of)

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(cards, fh, ensure_ascii=False, indent=2)
    with open(STATS_PATH, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)

    e, d, c = stats["expiry"], stats["dates"], stats["content"]
    print(f"\n總記錄數           : {stats['total_records']}")
    print("\n[文件效期閘門]")
    print(f"  已失效           : {e['expired_total']}")
    print(f"    ├ (已失效) 標記 : {e['expired_by_marker']}")
    print(f"    └ 僅日期已過    : {e['expired_by_date_only']}")
    print(f"  仍有效           : {e['valid_total']}")
    print(f"  效期不明         : {e['expiry_unknown']}")
    print("\n[民國紀年轉換]")
    print(f"  核發日期成功解析 : {d['issue_date_parsed']}")
    print(f"  核發日期缺漏     : {d['issue_date_missing']}")
    print(f"  有效期間成功解析 : {d['expiry_date_parsed']}")
    print("\n[內容清理]")
    print(f"  成分 HTML 已剝除 : {c['ingredients_html_stripped']}")
    print(f"  適應症為空       : {c['indications_empty']}")
    print(f"  無法解析出物種   : {c['species_unparsed']}")
    print(f"  外銷專用         : {c['export_only']}")
    ca = stats["companion_animal"]
    print("\n[伴侶動物 (犬/貓)]")
    print(f"  總數 {ca['total']}（有效 {ca['valid']} / 失效 {ca['expired']}）")
    print("\n[物種分布]")
    for sp, n in list(stats["species_counts"].items())[:12]:
        print(f"  {sp:<4} {n}")
    print("\n輸出:")
    print(f"  {OUT_PATH}")
    print(f"  {STATS_PATH}")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
