"""VetLink AI — 受控知識庫載入與檢索 (提案 §7.2 五層資料架構 / §7.1 文件效期閘門).

資料契約 (backend/app/data/demo_products.json，真實農業部開放資料)：
  licence_no, name_zh, name_en, company, dosage_form, packaging, ingredients_clean,
  indications_raw, species (中文), species_slugs (英文代碼), is_companion_animal,
  issue_date_iso, expiry_date_iso, expiry_date_raw, is_expired, expired_by_marker,
  expired_by_date, expiry_unknown, doc_id, version, source_url, fetched_at

**效期閘門的核心設計決定**：本模組不信任來源自帶的「(已失效)」標記，一律以
expiry_date_iso 與 as-of 日期重新計算。母體 13,738 筆中有 1,503 筆已逾效期卻
「沒有」失效標記，只能靠日期換算辨識；若信任標記欄位，這些過期文件會直接洩漏進回答。

檔案不存在時以內建 fallback fixture 降級，確保本模組可獨立測試。
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ..models import ProductCard, SourcePassage

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PRODUCTS_PATH = os.path.join(DATA_DIR, "demo_products.json")

# --------------------------------------------------------------------------
# Fallback fixture — 僅在真實資料檔缺席時使用，明確標示來源
# --------------------------------------------------------------------------
FALLBACK_PRODUCTS: List[Dict[str, Any]] = [
    {
        "licence_no": "動物藥入字第00001號",
        "name_zh": "示範用犬貓皮膚抗黴菌噴劑",
        "name_en": "DEMO Antifungal Spray for Dogs and Cats",
        "company": "示範藥廠（fallback fixture）",
        "dosage_form": "噴劑",
        "packaging": "50 mL/瓶",
        "ingredients_clean": "Miconazole nitrate 2%",
        "indications_raw": "犬貓皮膚真菌感染之輔助治療。",
        "species": ["dog", "cat"],
        "is_companion_animal": True,
        "issue_date_iso": "2023-01-15",
        "expiry_date_iso": "2028-01-14",
        "is_expired": False,
        "doc_id": "FALLBACK-DOC-0001",
        "version": "1.0",
        "source_url": "https://data.moa.gov.tw/open_detail.aspx?id=023",
        "fetched_at": "2026-07-01T00:00:00+00:00",
    },
    {
        "licence_no": "動物藥入字第00002號",
        "name_zh": "示範用犬貓腸胃道益生製劑",
        "name_en": "DEMO GI Support for Dogs and Cats",
        "company": "示範藥廠（fallback fixture）",
        "dosage_form": "口服液",
        "packaging": "100 mL/瓶",
        "ingredients_clean": "Lactobacillus spp., Electrolytes",
        "indications_raw": "犬貓消化道機能調整之營養補充。",
        "species": ["dog", "cat"],
        "is_companion_animal": True,
        "issue_date_iso": "2022-06-01",
        "expiry_date_iso": "2027-05-31",
        "is_expired": False,
        "doc_id": "FALLBACK-DOC-0002",
        "version": "1.0",
        "source_url": "https://data.moa.gov.tw/open_detail.aspx?id=023",
        "fetched_at": "2026-07-01T00:00:00+00:00",
    },
    {
        "licence_no": "動物藥入字第00003號",
        "name_zh": "示範用犬貓耳道清潔劑（已過期）",
        "name_en": "DEMO Ear Cleanser (EXPIRED)",
        "company": "示範藥廠（fallback fixture）",
        "dosage_form": "外用液劑",
        "packaging": "60 mL/瓶",
        "ingredients_clean": "Salicylic acid, Propylene glycol",
        "indications_raw": "犬貓外耳道清潔。",
        "species": ["dog", "cat"],
        "is_companion_animal": True,
        "issue_date_iso": "2015-03-01",
        "expiry_date_iso": "2020-02-29",
        "is_expired": True,
        "doc_id": "FALLBACK-DOC-0003",
        "version": "1.0",
        "source_url": "https://data.moa.gov.tw/open_detail.aspx?id=023",
        "fetched_at": "2026-07-01T00:00:00+00:00",
    },
    {
        "licence_no": "動物藥入字第00004號",
        "name_zh": "示範用犬專用外用除蚤滴劑",
        "name_en": "DEMO Spot-on for Dogs Only",
        "company": "示範藥廠（fallback fixture）",
        "dosage_form": "滴劑",
        "packaging": "1 mL x 3",
        "ingredients_clean": "Permethrin 45%",
        "indications_raw": "犬隻體外寄生蟲防治。本品不得使用於貓。",
        "species": ["dog"],
        "is_companion_animal": True,
        "issue_date_iso": "2021-09-01",
        "expiry_date_iso": "2026-08-31",
        "is_expired": False,
        "doc_id": "FALLBACK-DOC-0004",
        "version": "1.0",
        "source_url": "https://data.moa.gov.tw/open_detail.aspx?id=023",
        "fetched_at": "2026-07-01T00:00:00+00:00",
    },
    {
        "licence_no": "動物藥入字第00005號",
        "name_zh": "示範用犬貓眼部保健液",
        "name_en": "DEMO Ophthalmic Care Solution",
        "company": "示範藥廠（fallback fixture）",
        "dosage_form": "點眼液",
        "packaging": "10 mL/瓶",
        "ingredients_clean": "Hyaluronate sodium",
        "indications_raw": "犬貓眼部清潔與濕潤保健。",
        "species": ["dog", "cat"],
        "is_companion_animal": True,
        "issue_date_iso": "2024-02-01",
        "expiry_date_iso": "2029-01-31",
        "is_expired": False,
        "doc_id": "FALLBACK-DOC-0005",
        "version": "1.0",
        "source_url": "https://data.moa.gov.tw/open_detail.aspx?id=023",
        "fetched_at": "2026-07-01T00:00:00+00:00",
    },
]

# 衛教段落（獸醫審核內容層）— 綠色狀態主張的來源
EDUCATION_PASSAGES: List[Dict[str, Any]] = [
    {
        "passage_id": "EDU-URI-001",
        "doc_id": "EDU-URINARY-CARE",
        "version": "1.1",
        "text": "維持充足飲水與乾淨砂盆有助於降低下泌尿道問題的發生風險。建議每日記錄飲水量、排尿次數與尿量。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-01-10",
        "expiry_date_iso": "2027-01-09",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-URI-002",
        "doc_id": "EDU-URINARY-CARE",
        "version": "1.1",
        "text": "若出現用力排尿卻無尿液排出、反覆進出砂盆或精神明顯變差，屬需要立即就醫的危險徵兆。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-01-10",
        "expiry_date_iso": "2027-01-09",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-GI-001",
        "doc_id": "EDU-GI-CARE",
        "version": "1.0",
        "text": "單次軟便且精神食慾正常時，可先觀察並記錄排便次數與性狀，維持乾淨飲水，避免臨時更換飼料。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-02-01",
        "expiry_date_iso": "2027-01-31",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-GI-002",
        "doc_id": "EDU-GI-CARE",
        "version": "1.0",
        "text": "出現持續嘔吐、血便、精神變差或無法留住水分時，應立即就醫評估脫水與電解質狀況。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-02-01",
        "expiry_date_iso": "2027-01-31",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-DERM-001",
        "doc_id": "EDU-DERM-CARE",
        "version": "1.0",
        "text": "輕微搔癢可先記錄搔癢部位、頻率與是否有跳蚤痕跡，維持環境清潔，並避免自行使用人用藥膏。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-02-15",
        "expiry_date_iso": "2027-02-14",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-DERM-002",
        "doc_id": "EDU-DERM-CARE",
        "version": "1.0",
        "text": "耳道用藥前必須先由獸醫確認耳膜完整性，部分外用藥於耳膜破損時具風險。日常可觀察耳道異味、紅腫與分泌物變化。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-02-15",
        "expiry_date_iso": "2027-02-14",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-RES-001",
        "doc_id": "EDU-RESP-CARE",
        "version": "1.0",
        "text": "輕微上呼吸道症狀可保持環境通風與適當濕度，並記錄打噴嚏頻率、鼻分泌物性狀與食慾變化。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-03-01",
        "expiry_date_iso": "2027-02-28",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-RES-002",
        "doc_id": "EDU-RESP-CARE",
        "version": "1.0",
        "text": "呼吸費力、開口呼吸或黏膜顏色發紫發白屬立即危及生命的徵兆，應避免過度保定並儘速送醫。貓的開口呼吸尤其危險。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-03-01",
        "expiry_date_iso": "2027-02-28",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-POL-001",
        "doc_id": "EDU-REG-POLICY",
        "version": "1.0",
        "text": "依動物用藥品管理法及獸醫師（佐）處方藥品販賣及使用管理辦法，處方藥須由執業獸醫師診斷後開立處方，方得販賣及使用。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-01-01",
        "expiry_date_iso": "2028-12-31",
        "review_status": "approved",
        "source_url": "https://law.moa.gov.tw/LawContent.aspx?id=FL035300",
    },
    {
        "passage_id": "EDU-POL-002",
        "doc_id": "EDU-REG-POLICY",
        "version": "1.0",
        "text": "疾病確診需結合理學檢查與檢驗結果由獸醫師判斷，衛教資訊不得取代診斷。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-01-01",
        "expiry_date_iso": "2028-12-31",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-TOX-001",
        "doc_id": "EDU-TOXICOLOGY",
        "version": "1.0",
        "text": "乙醯胺酚（普拿疼）對貓具高度毒性，NSAIDs 類人用止痛藥可能造成犬貓腎損傷與消化道潰瘍，人用藥不得直接用於犬貓。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-01-05",
        "expiry_date_iso": "2028-01-04",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-TOX-002",
        "doc_id": "EDU-TOXICOLOGY",
        "version": "1.0",
        "text": "含 permethrin 之犬用體外寄生蟲產品對貓具嚴重神經毒性，可能致命，不得跨物種使用。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-01-05",
        "expiry_date_iso": "2028-01-04",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-EMG-001",
        "doc_id": "EDU-EMERGENCY",
        "version": "1.2",
        "text": "貓隻反覆進出砂盆且無尿液排出時，須高度懷疑尿道阻塞。此情況在公貓可於數小時內造成高血鉀與急性腎損傷而危及生命，需立即急診處置，居家用藥無法解除阻塞。",
        "species_scope": ["cat"],
        "issue_date_iso": "2026-01-08",
        "expiry_date_iso": "2027-01-07",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-EMG-002",
        "doc_id": "EDU-EMERGENCY",
        "version": "1.2",
        "text": "疑似中毒時不應自行催吐或給藥，請攜帶包裝或殘留物並記錄攝入時間與估計份量後立即就醫。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-01-08",
        "expiry_date_iso": "2027-01-07",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
    {
        "passage_id": "EDU-EMG-003",
        "doc_id": "EDU-EMERGENCY",
        "version": "1.2",
        "text": "抽搐發作時應移開周邊硬物、勿將手放入動物口中，記錄發作起訖時間；持續超過五分鐘或連續發作屬危及生命狀況。",
        "species_scope": ["cat", "dog"],
        "issue_date_iso": "2026-01-08",
        "expiry_date_iso": "2027-01-07",
        "review_status": "approved",
        "source_url": "internal://vet-reviewed-education",
    },
]


# Demo 基準日；資料集以此日期評估效期，支援 --as-of 時間平移展示
DEFAULT_AS_OF = date(2026, 8, 19)

_SPECIES_ZH_TO_SLUG: Dict[str, str] = {
    "犬": "dog", "狗": "dog", "貓": "cat", "豬": "pig", "牛": "cattle",
    "馬": "horse", "羊": "sheep_goat", "雞": "chicken", "火雞": "turkey",
    "兔": "rabbit", "鴿": "pigeon", "鴨": "duck", "鵝": "goose", "魚": "fish",
}

# 中化動藥（母公司：中國化學製藥股份有限公司）— 以公司名前綴比對，不用裸字串「中化」
CCPC_COMPANY_PREFIXES = ("中國化學製藥", "中化")


def _today() -> date:
    return datetime.now().date()


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def compute_expiry(
    expiry_date_iso: Optional[str], as_of: date
) -> tuple:
    """文件效期閘門的唯一判定依據 — 只看日期，不看來源的失效標記。

    回傳 (is_expired, expiry_unknown)。
    無效期日期者視為 unknown：不算過期，但在護照中標示待確認。
    """
    d = _parse_iso_date(expiry_date_iso)
    if d is None:
        return False, True
    return d < as_of, False


class KnowledgeBase:
    """受控知識庫：產品證據卡 + 獸醫審核衛教段落。"""

    def __init__(self, products_path: str = PRODUCTS_PATH, as_of: Optional[date] = None):
        self.products_path = products_path
        self.as_of: date = as_of or DEFAULT_AS_OF
        self.source: str = "fallback_fixture"
        self.products: List[ProductCard] = []
        self.passages: Dict[str, SourcePassage] = {}
        # 效期閘門稽核：來源標記與系統重算不一致的案例
        self.marker_disagreements: List[Dict[str, Any]] = []
        self._load_products()
        self._load_passages()

    # -- 載入 ------------------------------------------------------------
    def _load_products(self) -> None:
        raw_records: List[Dict[str, Any]]
        if os.path.exists(self.products_path):
            try:
                with open(self.products_path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                if isinstance(payload, dict):
                    raw_records = payload.get("records") or payload.get("products") or payload.get("data") or []
                elif isinstance(payload, list):
                    raw_records = payload
                else:
                    raw_records = []
                if raw_records:
                    self.source = f"file:{os.path.basename(self.products_path)}"
                else:
                    raw_records = FALLBACK_PRODUCTS
                    self.source = "fallback_fixture(empty_file)"
            except (json.JSONDecodeError, OSError):
                raw_records = FALLBACK_PRODUCTS
                self.source = "fallback_fixture(unreadable_file)"
        else:
            raw_records = FALLBACK_PRODUCTS
            self.source = "fallback_fixture(missing_file)"

        for rec in raw_records:
            card = self._to_card(rec)
            if card is not None:
                self.products.append(card)

    def _to_card(self, rec: Dict[str, Any]) -> Optional[ProductCard]:
        """寬鬆映射：容忍欄位缺漏，缺 licence_no 與 name_zh 才跳過。

        效期一律由 expiry_date_iso 重算，不採用來源的 (已失效) 標記。
        """
        licence_no = rec.get("licence_no") or rec.get("licenceNo") or ""
        name_zh = rec.get("name_zh") or rec.get("nameZh") or ""
        if not licence_no and not name_zh:
            return None

        # 優先使用正規化過的英文物種代碼；退回中文 species 欄位並轉譯
        species = rec.get("species_slugs")
        if not species:
            species = rec.get("species") or []
            if isinstance(species, str):
                species = [s.strip() for s in species.replace("、", ",").split(",") if s.strip()]
            species = [_SPECIES_ZH_TO_SLUG.get(s, s) for s in species]

        expiry = rec.get("expiry_date_iso")
        # === 文件效期閘門：系統自行重算，不信任來源標記 ===
        is_expired, expiry_unknown = compute_expiry(expiry, self.as_of)

        # 稽核：來源標記說沒過期、但日期換算已過期的案例 (母體共 1,503 筆)
        marker_says_expired = bool(rec.get("expired_by_marker"))
        if is_expired and not marker_says_expired:
            self.marker_disagreements.append(
                {
                    "licence_no": licence_no,
                    "name_zh": name_zh,
                    "expiry_date_raw": rec.get("expiry_date_raw"),
                    "expiry_date_iso": expiry,
                    "reason": "來源無失效標記，但依日期換算已逾效期",
                }
            )

        doc_id = rec.get("doc_id") or f"DOC-{licence_no or name_zh}"
        card = ProductCard(
            licence_no=licence_no or doc_id,
            name_zh=name_zh or licence_no,
            name_en=rec.get("name_en"),
            company=rec.get("company"),
            dosage_form=rec.get("dosage_form"),
            packaging=rec.get("packaging"),
            ingredients_clean=rec.get("ingredients_clean"),
            indications_raw=rec.get("indications_raw"),
            species=[str(s) for s in species],
            is_companion_animal=bool(rec.get("is_companion_animal", True)),
            issue_date_iso=rec.get("issue_date_iso"),
            expiry_date_iso=expiry,
            is_expired=bool(is_expired),
            doc_id=str(doc_id),
            version=str(rec.get("version", "1.0")),
            source_url=rec.get("source_url"),
            fetched_at=rec.get("fetched_at"),
        )
        card.expiry_unknown = expiry_unknown
        card.expiry_date_raw = rec.get("expiry_date_raw")
        card.expired_by_marker = marker_says_expired
        return card

    def _load_passages(self) -> None:
        for rec in EDUCATION_PASSAGES:
            p = SourcePassage(
                passage_id=rec["passage_id"],
                doc_id=rec["doc_id"],
                version=rec["version"],
                text=rec["text"],
                source_url=rec.get("source_url"),
                issue_date_iso=rec.get("issue_date_iso"),
                expiry_date_iso=rec.get("expiry_date_iso"),
                is_expired=self._passage_expired(rec.get("expiry_date_iso")),
                review_status=rec.get("review_status", "approved"),
                species_scope=list(rec.get("species_scope") or []),
            )
            self.passages[p.passage_id] = p

        # 每張產品證據卡也產生一段可引用的來源段落（適應症原文）
        for card in self.products:
            pid = f"PROD-{card.licence_no}"
            text_parts = [f"許可證字號：{card.licence_no}", f"品名：{card.name_zh}"]
            if card.ingredients_clean:
                text_parts.append(f"成分：{card.ingredients_clean}")
            if card.dosage_form:
                text_parts.append(f"劑型：{card.dosage_form}")
            if card.indications_raw:
                text_parts.append(f"核准適應症：{card.indications_raw}")
            self.passages[pid] = SourcePassage(
                passage_id=pid,
                doc_id=card.doc_id,
                version=card.version,
                text="；".join(text_parts),
                source_url=card.source_url,
                issue_date_iso=card.issue_date_iso,
                expiry_date_iso=card.expiry_date_iso,
                is_expired=card.is_expired,
                review_status="approved",
                species_scope=card.species,
                licence_no=card.licence_no,
                fetched_at=card.fetched_at,
            )

    def _passage_expired(self, expiry: Optional[str]) -> bool:
        is_expired, _ = compute_expiry(expiry, self.as_of)
        return is_expired

    # -- 查詢 ------------------------------------------------------------
    @property
    def stats(self) -> Dict[str, Any]:
        expired = sum(1 for p in self.products if p.is_expired)
        return {
            "source": self.source,
            "as_of": self.as_of.isoformat(),
            "product_count": len(self.products),
            "expired_product_count": expired,
            "valid_product_count": len(self.products) - expired,
            "passage_count": len(self.passages),
            "companion_animal_count": sum(1 for p in self.products if p.is_companion_animal),
            "expiry_unknown_count": sum(1 for p in self.products if p.expiry_unknown),
            # 只能靠日期換算才抓得到的過期文件 — Evidence Gate 的實證理由
            "date_only_expired_count": len(self.marker_disagreements),
            "ccpc_product_count": len(self.ccpc_products()),
            "ccpc_valid_count": sum(1 for p in self.ccpc_products() if not p.is_expired),
        }

    def ccpc_products(self, companion_only: bool = False) -> List[ProductCard]:
        """中化動藥（中國化學製藥集團）產品。以公司名前綴比對。"""
        out = [
            p for p in self.products
            if any((p.company or "").startswith(pre) for pre in CCPC_COMPANY_PREFIXES)
        ]
        if companion_only:
            out = [p for p in out if p.is_companion_animal]
        return out

    def get_passage(self, passage_id: str) -> Optional[SourcePassage]:
        return self.passages.get(passage_id)

    def valid_passages(self) -> List[SourcePassage]:
        """通過文件效期閘門的段落 (提案 §7.1)。"""
        return [p for p in self.passages.values() if not p.is_expired and p.review_status == "approved"]

    def search_passages(
        self, query: str, species: Optional[str] = None, limit: int = 5,
        include_expired: bool = False,
    ) -> List[SourcePassage]:
        """關鍵字檢索衛教/產品段落。確定性 scoring，無向量模型依賴。"""
        if not query:
            return []
        terms = [t for t in _tokenize(query) if t]
        scored: List[tuple] = []
        pool = self.passages.values() if include_expired else self.valid_passages()
        for p in pool:
            if species and p.species_scope and species not in p.species_scope:
                continue
            score = sum(1 for t in terms if t in p.text)
            if score:
                scored.append((score, p.passage_id, p))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [p for _, _, p in scored[:limit]]

    def search_products(
        self,
        query: str = "",
        species: Optional[str] = None,
        indication: Optional[str] = None,
        ingredient: Optional[str] = None,
        dosage_form: Optional[str] = None,
        limit: int = 10,
    ) -> tuple:
        """回傳 (有效產品清單, 被效期閘門排除的產品清單)。"""
        candidates: List[ProductCard] = []
        for p in self.products:
            if species and p.species and species not in p.species:
                continue
            if dosage_form and dosage_form not in (p.dosage_form or ""):
                continue
            if ingredient and ingredient.lower() not in (p.ingredients_clean or "").lower():
                continue
            if indication and indication not in (p.indications_raw or ""):
                continue
            if query:
                blob = " ".join(
                    filter(None, [p.name_zh, p.name_en, p.ingredients_clean, p.indications_raw, p.licence_no])
                )
                if not any(t in blob for t in _tokenize(query)):
                    continue
            candidates.append(p)

        expired = [p for p in candidates if p.is_expired]
        valid = [p for p in candidates if not p.is_expired]
        return valid[:limit], expired


def _tokenize(text: str) -> List[str]:
    """中英混合的簡易切詞：英數整段 + 中文 2-gram。"""
    import re as _re

    tokens: List[str] = []
    for chunk in _re.findall(r"[A-Za-z0-9]+|[一-鿿]+", text):
        if chunk[0].isascii():
            tokens.append(chunk.lower())
        else:
            tokens.append(chunk)
            for i in range(len(chunk) - 1):
                tokens.append(chunk[i: i + 2])
    return tokens


_KB: Optional[KnowledgeBase] = None


def get_kb(reload: bool = False, as_of: Optional[date] = None) -> KnowledgeBase:
    global _KB
    if _KB is None or reload or as_of is not None:
        _KB = KnowledgeBase(as_of=as_of)
    return _KB
